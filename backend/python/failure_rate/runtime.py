"""Failure Rate runtime adapter for the Tauri sidecar."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Callable

from common import (
    get_tool_logger,
    CancellationToken,
    atomic_write_path,
    atomic_finalize,
    verify_excel_readable,
    build_output_filename,
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

from failure_rate.failure_rate_logic import FMEALinkerLogic, note_is_informational_only

_logger = get_tool_logger("failure_rate_runtime")

SUPPORTED_WORKFLOWS = {"failure_rate_link"}
LOG_LIMIT = 120

ROLE_LABELS = {
    "prediction": "Prediction workbook",
    "fmea": "FMEA workbook",
}

# Human-readable labels for the canonical mapping tokens, so a blocked-run
# message reads "Missing required mappings: FMEA: failure mode ratio." instead
# of the raw canonical ("fmea_ratio"). These MUST mirror the frontend display
# labels in frontend/src/mocks/scenarios.ts (failureRateMappings). Unknown keys
# fall back to the raw canonical.
CANONICAL_DISPLAY_LABELS = {
    "pred_ref": "Prediction: RefDes column",
    "pred_fr": "Prediction: failure rate column",
    "fmea_cause": "FMEA: failure mode causes",
    "fmea_ratio": "FMEA: failure mode ratio",
    "fmea_usage": "FMEA: part usage",
    "fmea_func": "FMEA: function column",
}


def _role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role)


def _mapping_label(canonical: str) -> str:
    return CANONICAL_DISPLAY_LABELS.get(canonical, canonical)


def _required_roles(workflow_id: str) -> list[str]:
    if workflow_id == "failure_rate_link":
        return ["prediction", "fmea"]
    return []


def _required_mappings(workflow_id: str) -> list[str]:
    if workflow_id == "failure_rate_link":
        return ["pred_ref", "pred_fr", "fmea_cause", "fmea_ratio", "fmea_usage"]
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
    for role in ("fmea", "prediction"):
        candidate = _input_path(inputs_by_role, role)
        if candidate:
            return Path(candidate).resolve().parent
    return Path(tempfile.gettempdir())


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
            toast_text="This Failure Rate workflow is not supported.",
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
        preview = _build_failure_rate_output_preview(inputs_by_role)
        if preview is not None:
            response["output_preview"] = preview
    return response


def _build_failure_rate_output_preview(
    inputs_by_role: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Sample the prediction workbook so the Review drawer can show the
    source failure-rate rows about to be merged into the FMEA.
    """
    input_state = inputs_by_role.get("prediction") or {}
    path = str(input_state.get("path", "")).strip() or None
    sheet = str(input_state.get("selectedSheet", "")).strip() or None
    if not path:
        return None
    return build_preview_from_file(
        path,
        sheet,
        [
            ("RefDes", ("Reference Designator", "RefDes", "Ref Des", "Reference")),
            ("Failure Rate", ("Failure Rate", "FIT", "FR", "Lambda", "Failure Rate (FIT)")),
            ("Description", ("Description", "Component Description", "Part Description")),
        ],
    )


def _build_output_name(output_directory: Path | None = None) -> str:
    return build_output_filename(
        "FailureRate",
        "Link",
        output_directory=output_directory,
    )


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
    output_path = output_directory / _build_output_name(output_directory)

    def emit_status(status: str, stage: str, message: str) -> None:
        if status_callback:
            status_callback(status, stage, message)

    def emit_progress(stage: str, message: str, percent: int) -> None:
        if progress_callback:
            progress_callback(stage, message, percent, None, None)

    def logic_progress(fraction: float) -> None:
        # Convert 0.0-1.0 to 10-85% range (loading is 0-10, writing is 85-100)
        percent = 10 + round(fraction * 75)
        emit_progress("Processing", f"Linking failure rates ({percent}%)...", min(85, percent))

    emit_status("starting", "Run accepted", "Preparing Failure Rate run...")
    emit_progress("Run accepted", "Preparing...", 1)

    logic = FMEALinkerLogic(log_func=stream_log, progress_func=logic_progress)
    if processor_ready_callback:
        processor_ready_callback(logic)

    # Load files
    pred_path = _input_path(inputs_by_role, "prediction")
    fmea_path = _input_path(inputs_by_role, "fmea")
    pred_sheet = _selected_sheet(inputs_by_role, "prediction")
    fmea_sheet = _selected_sheet(inputs_by_role, "fmea")

    emit_status("running", "Loading prediction", "Loading prediction workbook...")
    emit_progress("Loading prediction", "Loading...", 3)
    logic.load_prediction(pred_path, sheet_name=pred_sheet)
    # Close each stage with a completed-phrase message: the frontend
    # timeline keeps a stage's LAST message, so without this the step
    # reads "Loading..." forever next to a completed chip.
    emit_progress("Loading prediction", "Prediction workbook loaded.", 5)

    emit_status("running", "Loading FMEA", "Loading FMEA workbook...")
    emit_progress("Loading FMEA", "Loading...", 7)
    logic.load_fmea(fmea_path, sheet_name=fmea_sheet)
    emit_progress("Loading FMEA", "FMEA workbook loaded.", 9)

    # Build column map from mappings
    col_map = {
        "pred_ref": _get_mapping(body, "pred_ref", required=True) or "",
        "pred_fr": _get_mapping(body, "pred_fr", required=True) or "",
        "unit_mode": str(options.get("unit_mode", "per_hour")),
        "fmea_cause": _get_mapping(body, "fmea_cause", required=True) or "",
        "fmea_ratio": _get_mapping(body, "fmea_ratio", required=True) or "",
        "fmea_usage": _get_mapping(body, "fmea_usage", required=True) or "",
        "fmea_func": _get_mapping(body, "fmea_func") or "",
    }
    check_fmr = bool(options.get("validate_fmr", False))

    emit_status("running", "Processing", "Linking failure rates...")
    emit_progress("Processing", "Linking...", 10)

    result_df = logic.process(col_map=col_map, check_fmr=check_fmr)
    emit_progress("Processing", "Failure rates linked.", 88)

    emit_status("running", "Writing workbook", "Writing Excel report...")
    emit_progress("Writing workbook", "Writing...", 90)
    tmp_output = atomic_write_path(output_path)
    try:
        logic.save_results(str(tmp_output))
        logic.cancel.check("Cancelled before finalizing output")
        output_is_readable = verify_excel_readable(tmp_output)
        logic.cancel.check("Cancelled before finalizing output")
        if not output_is_readable:
            raise FileAccessError(
                f"Post-write verification failed for {tmp_output}; workbook did not open.",
                file_path=str(tmp_output),
                operation="write",
            )
        logic.cancel.check("Cancelled before finalizing output")
        atomic_finalize(tmp_output, output_path, log_func=stream_log)
    except Exception:
        try:
            if tmp_output.exists():
                tmp_output.unlink()
        except OSError:
            pass
        raise
    emit_progress("Writing workbook", "Workbook written.", 98)
    emit_progress("Complete", "Failure rate linking complete.", 100)

    # Count warnings from Validation_Notes column. Pure roll-up annotations
    # are informational and excluded — counting them overstated the toast's
    # warning total on every block-structured FMEA.
    warning_count = 0
    no_match_count = 0
    if "Validation_Notes" in result_df.columns:
        notes_series = result_df["Validation_Notes"].fillna("")
        warning_count = int(sum(
            1
            for note in notes_series
            if str(note).strip() != "" and not note_is_informational_only(note)
        ))
        no_match_count = int(notes_series.str.contains("not in Prediction", case=False, na=False).sum())

    return {
        "status": "success",
        "title": "Failure rate linking complete",
        "summary": f"{len(result_df)} FMEA rows linked with prediction failure rates.",
        "output_file": str(output_path),
        "primary_metric": f"{len(result_df)} rows",
        "secondary_metric": f"{warning_count} warnings",
        "notes": [
            "Failure rate linking mode: matched prediction rates to FMEA failure modes.",
        ],
        "log_lines": logs[-LOG_LIMIT:],
        "row_count": len(result_df),
        "warning_count": warning_count,
        "no_match_count": no_match_count,
        "mode": "desktop-bridge",
    }
