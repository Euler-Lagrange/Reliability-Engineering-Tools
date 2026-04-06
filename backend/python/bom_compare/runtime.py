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
)
from common.exceptions import ValidationError
from shared.pre_run_validation import LabeledState, LabeledValue, validate_pre_run_state

from bom_compare.bom_compare_logic import (
    ColumnMapping,
    AnalyzeOptions,
    AnalyzeResults,
    BomCompareResult,
    analyze,
    write_excel_report,
    compare_two_boms,
    write_bom_compare_excel,
)

_logger = get_tool_logger("bom_compare_runtime")

SUPPORTED_WORKFLOWS = {"bom_compare_group", "bom_compare_custom"}
LOG_LIMIT = 120

ROLE_LABELS = {
    "grouping": "Grouping workbook",
    "bom": "BOM workbook",
    "bomA": "File 1",
    "bomB": "File 2",
}


def _role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role)


def _required_roles(workflow_id: str) -> list[str]:
    if workflow_id == "bom_compare_group":
        return ["grouping", "bom"]
    elif workflow_id == "bom_compare_custom":
        return ["bomA", "bomB"]
    return []


def _required_mappings(workflow_id: str) -> list[str]:
    if workflow_id == "bom_compare_group":
        return ["grouping_group_col", "grouping_refdes_col", "bom_refdes_col"]
    elif workflow_id == "bom_compare_custom":
        return ["refdes_col_a", "refdes_col_b"]
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


def _get_mapping(body: dict[str, Any], canonical: str) -> str | None:
    for m in body.get("mappings", []):
        if isinstance(m, dict) and m.get("canonical") == canonical:
            value = str(m.get("mappedTo", "")).strip()
            return value or None
    return None


def _resolve_output_directory(inputs_by_role: dict[str, dict[str, Any]]) -> Path:
    for role in ("bom", "grouping", "bomA", "bomB"):
        candidate = _input_path(inputs_by_role, role)
        if candidate:
            return Path(candidate).resolve().parent
    return Path(tempfile.gettempdir())


def _build_output_name(workflow_id: str) -> str:
    suffix = "Group" if workflow_id == "bom_compare_group" else "Custom"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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
    required_mapping_values = [
        LabeledValue(name, _get_mapping(body, name))
        for name in req_mapping_names
    ]

    result = validate_pre_run_state(
        required_files=required_files,
        load_in_progress=load_in_progress,
        loaded_states=loaded_states,
        not_loaded_message="Load current files and sheets for: {labels}.",
        required_mappings=required_mapping_values,
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

    return {
        "ok": result.ok,
        "reason_code": result.reason_code,
        "toast_text": result.toast_text,
        "validations": messages,
        "mode": "desktop-bridge",
    }


class _CancelBridge:
    """Bridges CancellationToken to threading.Event for BOM Compare functions."""

    def __init__(self) -> None:
        self.cancel = CancellationToken()
        self._event = threading.Event()

    @property
    def stop_event(self) -> threading.Event:
        return self._event

    def request_cancel(self) -> None:
        self.cancel.cancel()
        self._event.set()


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
    output_directory = _resolve_output_directory(inputs_by_role)
    output_path = output_directory / _build_output_name(workflow_id)

    logs: list[str] = []

    def stream_log(message: str) -> None:
        logs.append(message)
        if log_callback:
            log_callback(message)

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

    group_df = try_read_table(group_path, sheet_name=group_sheet, log_func=log)
    bom_df = try_read_table(bom_path, sheet_name=bom_sheet, log_func=log)

    emit_progress("Reading input files", "Files loaded.", 15)

    mapping = ColumnMapping(
        grouping_group_col=_get_mapping(body, "grouping_group_col"),
        grouping_refdes_col=_get_mapping(body, "grouping_refdes_col"),
        bom_refdes_col=_get_mapping(body, "bom_refdes_col"),
        bom_desc_col=_get_mapping(body, "bom_desc_col"),
    )
    analyze_options = AnalyzeOptions(
        base_match=options.get("base_match", True),
        exact_match=options.get("exact_match", False),
        treat_prov_as_covered=options.get("treat_prov_as_covered", True),
        ignore_dnp=options.get("ignore_dnp", True),
        dnp_regex=options.get("dnp_regex", ""),
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

    emit_status("running", "Writing workbook", "Writing Excel report...")
    emit_progress("Writing workbook", "Writing...", 85)
    write_excel_report(results, str(output_path))
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

    bom_a_df = try_read_table(path_a, sheet_name=sheet_a, log_func=log)
    bom_b_df = try_read_table(path_b, sheet_name=sheet_b, log_func=log)

    emit_progress("Reading input files", "Files loaded.", 15)

    refdes_col_a = _get_mapping(body, "refdes_col_a")
    refdes_col_b = _get_mapping(body, "refdes_col_b")

    compare_columns_raw = options.get("compare_columns") or []
    compare_columns = [
        (entry.get("col_a", ""), entry.get("col_b", ""), entry.get("rule", "Text (exact)"))
        for entry in compare_columns_raw
        if isinstance(entry, dict) and entry.get("col_a") and entry.get("col_b")
    ]

    name_a = options.get("display_name_a") or Path(path_a).stem if path_a else "File 1"
    name_b = options.get("display_name_b") or Path(path_b).stem if path_b else "File 2"

    emit_status("running", "Comparing entries", "Comparing entries between files...")
    emit_progress("Comparing entries", "Comparing...", 30)

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
    )

    emit_status("running", "Writing workbook", "Writing Excel report...")
    emit_progress("Writing workbook", "Writing...", 85)
    write_bom_compare_excel(result, str(output_path), bom_a_name=name_a, bom_b_name=name_b)
    emit_progress("Complete", "Custom comparison complete.", 100)

    only_a = len(result.only_in_a)
    only_b = len(result.only_in_b)
    diff_count = len(result.differences)
    warning_count = len(result.part_usage_warnings) + len(result.scope_warnings)

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
