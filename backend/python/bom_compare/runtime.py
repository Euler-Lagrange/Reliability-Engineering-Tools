"""BOM Compare runtime adapter for the Tauri sidecar."""
from __future__ import annotations

import threading
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from common import (
    try_read_table,
    get_tool_logger,
    CancellationToken,
    CancellationError,
    atomic_write_path,
    atomic_finalize,
    verify_excel_readable,
    validate_explicit_output_directory,
)
from common.exceptions import FileAccessError, ValidationError
from shared.pre_run_validation import (
    append_output_directory_warning,
    DO_NOT_MAP_SENTINEL,
    LabeledState,
    LabeledValue,
    validate_pre_run_state,
)
from shared.output_preview import build_preview_from_file

from bom_compare.bom_compare_logic import (
    ColumnMapping,
    AnalyzeOptions,
    AnalyzeResults,
    BomCompareResult,
    DEFAULT_DNP_REGEX,
    analyze,
    write_excel_report,
    compare_two_boms,
    write_bom_compare_excel,
)

_logger = get_tool_logger("bom_compare_runtime")

SUPPORTED_WORKFLOWS = {"bom_compare_group", "bom_compare_custom", "extraction_compare"}
LOG_LIMIT = 120

ROLE_LABELS = {
    "grouping": "Grouping workbook",
    "bom": "BOM workbook",
    "bomA": "File 1",
    "bomB": "File 2",
    "extractionA": "Extraction A (older)",
    "extractionB": "Extraction B (newer)",
}

# Human-readable labels for the canonical mapping tokens, so a blocked-run
# message reads "Missing required mappings: BOM: RefDes column." instead of the
# raw canonical ("bom_refdes_col"). These MUST mirror the frontend display
# labels in frontend/src/mocks/scenarios.ts (bomCompareGroupMappings /
# bomCompareCustomMappings). Unknown keys fall back to the raw canonical.
CANONICAL_DISPLAY_LABELS = {
    "grouping_group_col": "Grouping: group column",
    "grouping_refdes_col": "Grouping: RefDes column",
    "bom_refdes_col": "BOM: RefDes column",
    "bom_desc_col": "BOM: description column",
    "refdes_col_a": "File 1: RefDes column",
    "refdes_col_b": "File 2: RefDes column",
}


def _role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role)


def _mapping_label(canonical: str) -> str:
    return CANONICAL_DISPLAY_LABELS.get(canonical, canonical)


def _required_roles(workflow_id: str) -> list[str]:
    if workflow_id == "bom_compare_group":
        return ["grouping", "bom"]
    elif workflow_id == "bom_compare_custom":
        return ["bomA", "bomB"]
    elif workflow_id == "extraction_compare":
        return ["extractionA", "extractionB"]
    return []


def _required_mappings(workflow_id: str) -> list[str]:
    if workflow_id == "bom_compare_group":
        return ["grouping_group_col", "grouping_refdes_col", "bom_refdes_col"]
    elif workflow_id == "bom_compare_custom":
        return ["refdes_col_a", "refdes_col_b"]
    # extraction_compare: the extraction sheet has a fixed schema — no
    # column mapping is needed (or rendered by the frontend).
    return []


def _collect_inputs(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("role")): item
        for item in body.get("inputs", [])
        if isinstance(item, dict) and item.get("role")
    }


def _is_input_loaded(input_state: dict[str, Any]) -> bool:
    if not input_state:
        return False
    if input_state.get("resolutionError"):
        return False
    if not str(input_state.get("path", "")).strip():
        return False
    sheets = input_state.get("sheets") or []
    if sheets and not str(input_state.get("selectedSheet", "")).strip():
        return False
    return True


def _selected_sheet(inputs_by_role: dict[str, dict[str, Any]], role: str) -> str | None:
    value = str((inputs_by_role.get(role) or {}).get("selectedSheet", "")).strip()
    return value or None


def _input_path(inputs_by_role: dict[str, dict[str, Any]], role: str) -> str | None:
    value = str((inputs_by_role.get(role) or {}).get("path", "")).strip()
    return value or None


def _get_mapping(
    body: dict[str, Any],
    canonical: str,
    *,
    required: bool = False,
) -> str | None:
    """Return the column a canonical is mapped to, or None.

    Bug 2 (belt-and-suspenders): when ``required`` is True, the Do-Not-Map
    sentinel ("__do_not_map__") is treated as None so a stale client that
    pins a REQUIRED mapping to "do not map" can't inject the sentinel string
    as a real column name into the execute path (which would otherwise crash
    with a ColumnMappingError about a column literally named "__do_not_map__").
    """
    for m in body.get("mappings", []):
        if isinstance(m, dict) and m.get("canonical") == canonical:
            value = str(m.get("mappedTo", "")).strip()
            if required and value == DO_NOT_MAP_SENTINEL:
                return None
            return value or None
    return None


def _raw_mapping(body: dict[str, Any], canonical: str) -> str | None:
    """Return the mapped value verbatim (sentinel preserved), for validation."""
    for m in body.get("mappings", []):
        if isinstance(m, dict) and m.get("canonical") == canonical:
            value = str(m.get("mappedTo", "")).strip()
            return value or None
    return None


def _resolve_output_directory(
    inputs_by_role: dict[str, dict[str, Any]],
    explicit_directory: str | None = None,
    log_callback: Callable[[str], None] | None = None,
) -> Path:
    resolved = validate_explicit_output_directory(
        explicit_directory,
        log_func=log_callback,
    )
    if resolved is not None:
        return resolved
    for role in ("bom", "grouping", "bomA", "bomB", "extractionA", "extractionB"):
        candidate = _input_path(inputs_by_role, role)
        if candidate:
            return Path(candidate).resolve().parent
    return Path(tempfile.gettempdir())


def _build_output_name(workflow_id: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if workflow_id == "extraction_compare":
        return f"ExtractionCompare_{timestamp}.xlsx"
    suffix = "Group" if workflow_id == "bom_compare_group" else "Custom"
    return f"BomCompare_{suffix}_{timestamp}.xlsx"


def validate_run_request(body: dict[str, Any]) -> dict[str, Any]:
    workflow_id = str(body.get("workflowId", "")).strip()
    inputs_by_role = _collect_inputs(body)

    required_roles = _required_roles(workflow_id)
    required_files = [
        LabeledValue(_role_label(role), _input_path(inputs_by_role, role))
        for role in required_roles
    ]
    loaded_states = [
        LabeledState(_role_label(role), _is_input_loaded(inputs_by_role.get(role) or {}))
        for role in required_roles
    ]
    load_in_progress = any(
        bool((inputs_by_role.get(role) or {}).get("isResolvingSheets"))
        or bool((inputs_by_role.get(role) or {}).get("isAnalyzing"))
        for role in required_roles
    )

    req_mapping_names = _required_mappings(workflow_id)
    # Bug 2: a required mapping pinned to the Do-Not-Map sentinel is a
    # non-empty string, so without special handling _has_value would treat
    # it as a present mapping — it would pass validate_run and then crash
    # execute with ColumnMappingError("column '__do_not_map__' not found").
    # Funnel sentinel-pinned required canonicals through invalid_mappings so
    # validate_pre_run_state surfaces the precise invalid_do_not_map message.
    # required_mappings reports the RAW value (sentinel preserved) so the
    # sentinel is seen as present and is NOT short-circuited by the
    # missing_mappings branch — letting the more precise invalid_do_not_map
    # branch fire instead. A genuinely empty/absent mapping is raw None, so it
    # still triggers missing_mappings as before.
    required_mapping_values = [
        LabeledValue(_mapping_label(name), _raw_mapping(body, name))
        for name in req_mapping_names
    ]
    invalid_mapping_values = [
        LabeledValue(_mapping_label(name), _raw_mapping(body, name))
        for name in req_mapping_names
        if _raw_mapping(body, name) == DO_NOT_MAP_SENTINEL
    ]

    result = validate_pre_run_state(
        required_files=required_files,
        load_in_progress=load_in_progress,
        loaded_states=loaded_states,
        not_loaded_message="Load current files and sheets for: {labels}.",
        required_mappings=required_mapping_values,
        invalid_mappings=invalid_mapping_values,
    )

    if workflow_id not in SUPPORTED_WORKFLOWS:
        result = type(result)(
            ok=False,
            reason_code="unsupported_workflow",
            toast_text="This BOM Compare workflow is not supported.",
            affected_labels=result.affected_labels,
        )

    messages: list[dict[str, str]] = []
    if result.ok:
        messages.append({
            "id": "ready-to-run",
            "severity": "info",
            "area": "Run State",
            "title": "Backend validation passed",
            "detail": "This workspace is ready for execution.",
        })
    else:
        messages.append({
            "id": f"validation-{result.reason_code}",
            "severity": "error",
            "area": "Run State",
            "title": "Run is blocked",
            "detail": result.toast_text or "Resolve the highlighted setup issues before running.",
        })

    response: dict[str, Any] = {
        "ok": result.ok,
        "reason_code": result.reason_code,
        "toast_text": result.toast_text,
        "validations": messages,
        "mode": "desktop-bridge",
    }
    # Tier-2 #19: surface an unusable explicit output folder at validate time.
    append_output_directory_warning(response, body.get("outputDirectory"))
    if result.ok:
        preview = _build_bom_compare_output_preview(workflow_id, inputs_by_role)
        if preview is not None:
            response["output_preview"] = preview
    return response


def _build_bom_compare_output_preview(
    workflow_id: str,
    inputs_by_role: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Sample the primary BOM so the Review drawer can show the source rows
    that will be compared. The eventual diff output is richer (matched /
    missing / extra annotations), but previewing it requires running the
    full compare — this sample answers "these are the parts I'm comparing".
    """
    primary_role = "bomA" if workflow_id == "bom_compare_custom" else "bom"
    input_state = inputs_by_role.get(primary_role) or {}
    path = str(input_state.get("path", "")).strip() or None
    sheet = str(input_state.get("selectedSheet", "")).strip() or None
    if not path:
        return None
    return build_preview_from_file(
        path,
        sheet,
        [
            ("RefDes", ("Reference Designator", "RefDes", "Ref Des", "Reference")),
            ("Part Number", ("Part Number", "Manufacturer Part Number", "PartNumber", "Mfg PN", "MPN")),
            ("Description", ("Description", "Component Description", "Part Description")),
        ],
    )


class _CancelBridge:
    """Bridges CancellationToken to threading.Event for BOM Compare functions.

    The token and the threading.Event share the same underlying ``threading.Event``
    so that ``self.cancel.cancel()`` (called by the sidecar's
    ``ActiveRun.request_cancel``) sets the same event that BOM Compare's inner
    helpers check via ``stop_event.is_set()``.
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self.cancel = CancellationToken(event=self._event)

    @property
    def stop_event(self) -> threading.Event:
        return self._event

    def request_cancel(self) -> None:
        # Kept for backward compatibility; ``self.cancel.cancel()`` alone is
        # now sufficient because the underlying Event is shared.
        self.cancel.cancel()


def execute_run_request(
    body: dict[str, Any],
    *,
    log_callback: Callable[[str], None] | None = None,
    status_callback: Callable[[str, str, str], None] | None = None,
    progress_callback: Callable[[str, str, int, int | None, int | None], None] | None = None,
    processor_ready_callback: Callable[[Any], None] | None = None,
) -> dict[str, Any]:
    validation = validate_run_request(body)
    if not validation["ok"]:
        raise ValidationError(validation["toast_text"] or "Run validation failed.")

    workflow_id = str(body.get("workflowId", "")).strip()
    inputs_by_role = _collect_inputs(body)
    options = body.get("options") or {}

    logs: list[str] = []

    def stream_log(message: str) -> None:
        logs.append(message)
        if log_callback:
            log_callback(message)

    output_directory = _resolve_output_directory(
        inputs_by_role,
        explicit_directory=body.get("outputDirectory"),
        log_callback=stream_log,
    )
    output_path = output_directory / _build_output_name(workflow_id)

    def emit_status(status: str, stage: str, message: str) -> None:
        if status_callback:
            status_callback(status, stage, message)

    def emit_progress(stage: str, message: str, percent: int) -> None:
        if progress_callback:
            progress_callback(stage, message, percent, None, None)

    bridge = _CancelBridge()
    if processor_ready_callback:
        processor_ready_callback(bridge)

    emit_status("starting", "Run accepted", "Preparing BOM Compare run...")
    emit_progress("Run accepted", "Preparing BOM Compare run...", 1)

    if workflow_id == "bom_compare_group":
        result_data = _run_group_compare(
            body, inputs_by_role, options, output_path,
            bridge, stream_log, emit_status, emit_progress,
        )
    elif workflow_id == "extraction_compare":
        result_data = _run_extraction_compare(
            body, inputs_by_role, options, output_path,
            bridge, stream_log, emit_status, emit_progress,
        )
    else:
        result_data = _run_custom_compare(
            body, inputs_by_role, options, output_path,
            bridge, stream_log, emit_status, emit_progress,
        )

    result_data["log_lines"] = logs[-LOG_LIMIT:]
    result_data["mode"] = "desktop-bridge"
    return result_data


def _run_group_compare(
    body: dict[str, Any],
    inputs_by_role: dict[str, dict[str, Any]],
    options: dict[str, Any],
    output_path: Path,
    bridge: _CancelBridge,
    log: Callable[[str], None],
    emit_status: Callable,
    emit_progress: Callable,
) -> dict[str, Any]:
    emit_status("running", "Reading input files", "Loading grouping and BOM workbooks...")
    emit_progress("Reading input files", "Loading workbooks...", 5)

    group_path = _input_path(inputs_by_role, "grouping")
    bom_path = _input_path(inputs_by_role, "bom")
    group_sheet = _selected_sheet(inputs_by_role, "grouping")
    bom_sheet = _selected_sheet(inputs_by_role, "bom")

    # Pass cancel_check so a click on Cancel during a large OneDrive
    # download / retry loop stops promptly instead of blocking until the
    # read completes.
    group_df = try_read_table(
        group_path,
        sheet_name=group_sheet,
        log_func=log,
        cancel_check=bridge.stop_event.is_set,
    )
    bom_df = try_read_table(
        bom_path,
        sheet_name=bom_sheet,
        log_func=log,
        cancel_check=bridge.stop_event.is_set,
    )

    emit_progress("Reading input files", "Files loaded.", 15)

    mapping = ColumnMapping(
        grouping_group_col=_get_mapping(body, "grouping_group_col", required=True),
        grouping_refdes_col=_get_mapping(body, "grouping_refdes_col", required=True),
        bom_refdes_col=_get_mapping(body, "bom_refdes_col", required=True),
        bom_desc_col=_get_mapping(body, "bom_desc_col"),
    )
    analyze_options = AnalyzeOptions(
        # The frontend "base match" checkbox maps to loose/prefix base matching.
        # The wire key stays ``base_match`` (frontend stability), but it drives
        # ``loose_base_match`` here — the only base-matching control the group
        # analyzer actually reads. The frontend default for this option is now
        # FALSE, so a default run keeps loose matching OFF (byte-identical to the
        # pre-wiring behavior). The dead AnalyzeOptions.base_match field was
        # removed; nothing in the analyzer ever read it.
        loose_base_match=options.get("base_match", False),
        exact_match=options.get("exact_match", False),
        treat_prov_as_covered=options.get("treat_prov_as_covered", True),
        ignore_dnp=options.get("ignore_dnp", True),
        # Bug 1: the frontend never sends a dnp_regex key, and an empty
        # string compiles to a match-everything pattern (re.compile('')
        # succeeds, so the re.error fallback in _compile_patterns never
        # fires) — which makes explode_bom skip EVERY BOM row and report
        # the whole BOM as DNP. A falsy value (omitted/empty/None) must
        # fall back to the canonical default so DNP filtering only removes
        # genuine Do-Not-Populate rows.
        dnp_regex=options.get("dnp_regex") or DEFAULT_DNP_REGEX,
        check_fmr=options.get("check_fmr", False),
        check_part_usage=options.get("check_part_usage", True),
    )

    emit_status("running", "Running comparison", "Comparing grouping against BOM...")
    emit_progress("Running comparison", "Comparing...", 30)

    results = analyze(
        group_df, bom_df, mapping, analyze_options,
        (group_path or "", bom_path or ""),
        stop_event=bridge.stop_event,
    )
    # Close each stage with a completed-phrase message: the frontend
    # timeline keeps a stage's LAST message, so without this the step
    # reads "Comparing..." forever next to a completed chip.
    emit_progress("Running comparison", "Comparison finished.", 80)

    emit_status("running", "Writing workbook", "Writing Excel report...")
    emit_progress("Writing workbook", "Writing...", 85)
    # Atomic write: stage the workbook in a sibling .part file, verify it
    # opens, then replace the target so a crash mid-write can't leave a
    # half-written .xlsx in the user's output folder.
    tmp_output = atomic_write_path(output_path)
    try:
        write_excel_report(results, str(tmp_output))
        if not verify_excel_readable(tmp_output):
            raise FileAccessError(
                f"Post-write verification failed for {tmp_output}; workbook did not open.",
                file_path=str(tmp_output),
                operation="write",
            )
        atomic_finalize(tmp_output, output_path, log_func=log)
    except Exception:
        try:
            if tmp_output.exists():
                tmp_output.unlink()
        except OSError:
            pass
        raise
    emit_progress("Writing workbook", "Workbook written.", 98)
    emit_progress("Complete", "BOM comparison complete.", 100)

    missing_count = len(results.missing_in_bom)
    extra_count = len(results.bom_not_in_groups)
    warning_count = len(results.description_warnings) + len(results.fmr_warnings) + len(results.part_usage_warnings)

    return {
        "status": "success",
        "title": "BOM comparison complete",
        "summary": f"Group vs BOM: {missing_count} missing, {extra_count} extra.",
        "output_file": str(output_path),
        "primary_metric": f"{missing_count} missing in BOM",
        "secondary_metric": f"{warning_count} warnings",
        "notes": [
            "Group vs BOM mode: compared grouping file against BOM.",
        ],
        "row_count": missing_count + extra_count,
        "warning_count": warning_count,
        "no_match_count": missing_count,
    }


def _run_extraction_compare(
    body: dict[str, Any],
    inputs_by_role: dict[str, dict[str, Any]],
    options: dict[str, Any],
    output_path: Path,
    bridge: _CancelBridge,
    log: Callable[[str], None],
    emit_status: Callable,
    emit_progress: Callable,
) -> dict[str, Any]:
    """Diff two RefDes-extraction workbooks: appeared / disappeared / moved."""
    from bom_compare.extraction_compare import (
        compare_extractions,
        write_extraction_compare_excel,
    )

    emit_status("running", "Reading input files", "Loading both extraction workbooks...")
    emit_progress("Reading input files", "Loading workbooks...", 5)

    path_a = _input_path(inputs_by_role, "extractionA")
    path_b = _input_path(inputs_by_role, "extractionB")
    df_a = try_read_table(
        path_a,
        sheet_name=_selected_sheet(inputs_by_role, "extractionA"),
        log_func=log,
        cancel_check=bridge.stop_event.is_set,
    )
    df_b = try_read_table(
        path_b,
        sheet_name=_selected_sheet(inputs_by_role, "extractionB"),
        log_func=log,
        cancel_check=bridge.stop_event.is_set,
    )
    emit_progress("Reading input files", "Files loaded.", 15)

    name_a = options.get("display_name_a") or (Path(path_a).stem if path_a else "Extraction A")
    name_b = options.get("display_name_b") or (Path(path_b).stem if path_b else "Extraction B")

    emit_status("running", "Comparing extractions", "Diffing component groups between revisions...")
    emit_progress("Comparing extractions", "Comparing...", 30)
    result = compare_extractions(df_a, df_b)
    emit_progress("Comparing extractions", "Comparison finished.", 80)

    emit_status("running", "Writing workbook", "Writing Excel report...")
    emit_progress("Writing workbook", "Writing...", 85)
    tmp_output = atomic_write_path(output_path)
    try:
        from openpyxl import Workbook
        wb = Workbook()
        write_extraction_compare_excel(result, wb, name_a=name_a, name_b=name_b)
        wb.save(str(tmp_output))
        wb.close()
        if not verify_excel_readable(tmp_output):
            raise FileAccessError(
                f"Post-write verification failed for {tmp_output}; workbook did not open.",
                file_path=str(tmp_output),
                operation="write",
            )
        atomic_finalize(tmp_output, output_path, log_func=log)
    except Exception:
        try:
            if tmp_output.exists():
                tmp_output.unlink()
        except OSError:
            pass
        raise
    emit_progress("Writing workbook", "Workbook written.", 98)
    emit_progress("Complete", "Extraction comparison complete.", 100)

    appeared = len(result.appeared)
    disappeared = len(result.disappeared)
    moved = len(result.moved)

    return {
        "status": "success",
        "title": "Extraction comparison complete",
        "summary": (
            f"{appeared} appeared, {disappeared} disappeared, {moved} moved groups "
            f"({result.in_both_count} unchanged)."
        ),
        "output_file": str(output_path),
        "primary_metric": f"{appeared + disappeared + moved} changes",
        "secondary_metric": f"{moved} moved groups, {result.in_both_count} in both",
        "notes": [
            f"Compared {name_a} (rev A) against {name_b} (rev B).",
            "Group identity ignores the (Verified)/(Unverified) split; gap rows are skipped.",
        ],
        "row_count": result.in_both_count + appeared + disappeared,
        "warning_count": moved,
        "no_match_count": appeared + disappeared,
    }


def _run_custom_compare(
    body: dict[str, Any],
    inputs_by_role: dict[str, dict[str, Any]],
    options: dict[str, Any],
    output_path: Path,
    bridge: _CancelBridge,
    log: Callable[[str], None],
    emit_status: Callable,
    emit_progress: Callable,
) -> dict[str, Any]:
    emit_status("running", "Reading input files", "Loading File 1 and File 2 workbooks...")
    emit_progress("Reading input files", "Loading workbooks...", 5)

    path_a = _input_path(inputs_by_role, "bomA")
    path_b = _input_path(inputs_by_role, "bomB")
    sheet_a = _selected_sheet(inputs_by_role, "bomA")
    sheet_b = _selected_sheet(inputs_by_role, "bomB")

    bom_a_df = try_read_table(
        path_a,
        sheet_name=sheet_a,
        log_func=log,
        cancel_check=bridge.stop_event.is_set,
    )
    bom_b_df = try_read_table(
        path_b,
        sheet_name=sheet_b,
        log_func=log,
        cancel_check=bridge.stop_event.is_set,
    )

    emit_progress("Reading input files", "Files loaded.", 15)

    refdes_col_a = _get_mapping(body, "refdes_col_a", required=True)
    refdes_col_b = _get_mapping(body, "refdes_col_b", required=True)

    compare_columns_raw = options.get("compare_columns") or []
    compare_columns = [
        # Default rule matches custom_compare.parse_compare_columns and the
        # frontend picker default ("Text (ignore case)"); the frontend always
        # sends an explicit rule, so this is only the rule-less-entry fallback.
        (entry.get("col_a", ""), entry.get("col_b", ""), entry.get("rule", "Text (ignore case)"))
        for entry in compare_columns_raw
        if isinstance(entry, dict) and entry.get("col_a") and entry.get("col_b")
    ]

    name_a = options.get("display_name_a") or (Path(path_a).stem if path_a else "File 1")
    name_b = options.get("display_name_b") or (Path(path_b).stem if path_b else "File 2")

    emit_status("running", "Comparing entries", "Comparing entries between files...")
    emit_progress("Comparing entries", "Comparing...", 30)

    # Forward the shared comparison options so the custom (BOM-vs-BOM) path
    # honors the same checkboxes as the group path:
    #   - base_match  -> loose_base_match (frontend default FALSE; see group path)
    #   - exact_match -> full-token vs base-RefDes matching
    #   - ignore_dnp  -> skip Do-Not-Populate rows before comparison
    #   - check_fmr   -> per-RefDes Failure Mode Ratio sum validation
    # NOTE: ``treat_prov_as_covered`` is intentionally NOT forwarded here. On the
    # group path it drops grouping tokens whose GROUP-NAME column contains
    # "PROV". The custom path compares two BOMs by RefDes and has no group-name
    # column, so there is no provisional-group signal to act on — the option is
    # genuinely inapplicable to a two-BOM compare (not merely unimplemented).
    result = compare_two_boms(
        bom_a_df, bom_b_df,
        refdes_col_a=refdes_col_a,
        refdes_col_b=refdes_col_b,
        compare_columns=compare_columns if compare_columns else None,
        key_mode=options.get("key_mode", "refdes_list"),
        log_callback=log,
        stop_event=bridge.stop_event,
        check_part_usage=options.get("check_part_usage", True),
        source_name_a=path_a,
        source_name_b=path_b,
        exact_match=options.get("exact_match", False),
        loose_base_match=options.get("base_match", False),
        ignore_dnp=options.get("ignore_dnp", True),
        check_fmr=options.get("check_fmr", False),
    )
    # Close the comparison stage (see the group path's note above).
    emit_progress("Comparing entries", "Comparison finished.", 80)

    emit_status("running", "Writing workbook", "Writing Excel report...")
    emit_progress("Writing workbook", "Writing...", 85)
    tmp_output = atomic_write_path(output_path)
    try:
        write_bom_compare_excel(result, str(tmp_output), bom_a_name=name_a, bom_b_name=name_b)
        if not verify_excel_readable(tmp_output):
            raise FileAccessError(
                f"Post-write verification failed for {tmp_output}; workbook did not open.",
                file_path=str(tmp_output),
                operation="write",
            )
        atomic_finalize(tmp_output, output_path, log_func=log)
    except Exception:
        try:
            if tmp_output.exists():
                tmp_output.unlink()
        except OSError:
            pass
        raise
    emit_progress("Writing workbook", "Workbook written.", 98)
    emit_progress("Complete", "Custom comparison complete.", 100)

    only_a = len(result.only_in_a)
    only_b = len(result.only_in_b)
    diff_count = len(result.differences)
    warning_count = (
        len(result.part_usage_warnings)
        + len(result.scope_warnings)
        + len(result.fmr_warnings)
    )

    return {
        "status": "success",
        "title": "Custom comparison complete",
        "summary": f"Only in {name_a}: {only_a}, only in {name_b}: {only_b}, {diff_count} differences.",
        "output_file": str(output_path),
        "primary_metric": f"{only_a + only_b} unique entries",
        "secondary_metric": f"{diff_count} differences, {warning_count} warnings",
        "notes": [
            f"Custom Compare mode: compared {name_a} against {name_b}.",
        ],
        "row_count": result.in_both_count + only_a + only_b,
        "warning_count": warning_count,
        "no_match_count": only_a + only_b,
    }
