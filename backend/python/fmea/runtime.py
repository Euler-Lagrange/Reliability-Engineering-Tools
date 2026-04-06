from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from common.exceptions import ValidationError

from shared.pre_run_validation import LabeledState, LabeledValue, validate_pre_run_state
from fmea.fmea_generator_logic import FMEAProcessor, write_excel_report

SUPPORTED_EXECUTION_WORKFLOWS = {"piece_part_generate", "bom_only", "fill_gaps"}
SUPPORTED_OUTPUT_STRATEGIES = {"new_workbook_standard", "existing_workbook_preserve_formatting"}
LOG_LIMIT = 120
PROGRESS_STAGE_WEIGHTS = {
    "Reading input files...": (5, 10, "Reading input files"),
    "Building indexes...": (15, 10, "Building indexes"),
    "Generating FMEA rows...": (25, 60, "Generating FMEA rows"),
    "Applying Piece-Part effect merge...": (85, 10, "Applying Piece-Part effect merge"),
    "Writing workbook...": (95, 5, "Writing workbook"),
}
FILL_GAPS_STAGE_WEIGHTS = {
    "Loading input files...": (5, 10, "Loading input files"),
    "Classifying FMEA rows...": (15, 15, "Classifying FMEA rows"),
    "Generating FMEA rows for missing RefDes...": (30, 55, "Generating gap-fill rows"),
    "Writing workbook...": (95, 5, "Writing workbook"),
}

ROLE_LABELS = {
    "grouping": "Grouping workbook",
    "bom": "BOM workbook",
    "hda": "HDA workbook",
    "failureModes": "Failure modes workbook",
    "functionalFmea": "Functional FMEA workbook",
    "piecePartFmea": "Piece-part source FMEA",
    "existingFmea": "Existing FMEA workbook",
    "targetWorkbook": "Target workbook",
}


def _role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role)


def _required_roles(
    workflow_id: str,
    output_strategy_id: str,
    enrichments: dict[str, bool],
) -> list[str]:
    roles: list[str]
    if workflow_id == "piece_part_generate":
        roles = ["grouping", "bom", "failureModes"]
    elif workflow_id == "bom_only":
        roles = ["bom", "failureModes"]
    elif workflow_id == "fill_gaps":
        roles = ["existingFmea", "bom", "failureModes"]
    else:
        roles = []

    if workflow_id != "fill_gaps" and enrichments.get("functional"):
        roles.append("functionalFmea")
    if workflow_id != "fill_gaps" and enrichments.get("piecePart"):
        roles.append("piecePartFmea")
    if output_strategy_id not in ("new_workbook_standard",):
        roles.append("targetWorkbook")
    return roles


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


def _build_validation_messages(
    result: Any,
    workflow_id: str,
    output_strategy_id: str,
    inputs_by_role: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []

    if workflow_id not in SUPPORTED_EXECUTION_WORKFLOWS:
        messages.append(
            {
                "id": "unsupported-workflow",
                "severity": "error",
                "area": "Workflow",
                "title": "This workflow is not migrated yet",
                "detail": "This workflow is not yet available in the migrated backend.",
            }
        )

    if output_strategy_id not in SUPPORTED_OUTPUT_STRATEGIES:
        messages.append(
            {
                "id": "unsupported-output-strategy",
                "severity": "error",
                "area": "Output Strategy",
                "title": "Only new workbook output is executable in this slice",
                "detail": "Existing workbook and preserve-formatting paths stay in analysis-only mode until the template-preserve migration lands.",
            }
        )

    for role, input_state in inputs_by_role.items():
        resolution_error = str(input_state.get("resolutionError", "")).strip()
        if resolution_error:
            messages.append(
                {
                    "id": f"input-error-{role}",
                    "severity": "error",
                    "area": _role_label(role),
                    "title": "Input requires review",
                    "detail": resolution_error,
                }
            )

    if result.ok:
        messages.insert(
            0,
            {
                "id": "ready-to-run",
                "severity": "info",
                "area": "Run State",
                "title": "Backend validation passed",
                "detail": "This workspace is ready for execution.",
            },
        )
    else:
        messages.insert(
            0,
            {
                "id": f"validation-{result.reason_code}",
                "severity": "error",
                "area": "Run State",
                "title": "Run is blocked",
                "detail": result.toast_text or "Resolve the highlighted setup issues before running.",
            },
        )

    return messages


def validate_run_request(body: dict[str, Any]) -> dict[str, Any]:
    workflow_id = str(body.get("workflowId", "")).strip()
    output_strategy_id = str(body.get("outputStrategyId", "")).strip()
    enrichments = body.get("enrichments") or {}
    inputs_by_role = _collect_inputs(body)

    required_roles = _required_roles(workflow_id, output_strategy_id, enrichments)
    required_files = [
        LabeledValue(_role_label(role), (inputs_by_role.get(role) or {}).get("path"))
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

    result = validate_pre_run_state(
        required_files=required_files,
        load_in_progress=load_in_progress,
        loaded_states=loaded_states,
        not_loaded_message="Load current files and sheets for: {labels}.",
    )

    if workflow_id not in SUPPORTED_EXECUTION_WORKFLOWS or output_strategy_id not in SUPPORTED_OUTPUT_STRATEGIES:
        result = type(result)(
            ok=False,
            reason_code="unsupported_execution_path",
            toast_text="This execution path is not yet available in the migrated backend.",
            affected_labels=result.affected_labels,
        )

    return {
        "ok": result.ok,
        "reason_code": result.reason_code,
        "toast_text": result.toast_text,
        "validations": _build_validation_messages(result, workflow_id, output_strategy_id, inputs_by_role),
        "mode": "desktop-bridge",
    }


def _selected_sheet(inputs_by_role: dict[str, dict[str, Any]], role: str) -> str | None:
    value = str((inputs_by_role.get(role) or {}).get("selectedSheet", "")).strip()
    return value or None


def _resolve_output_directory(inputs_by_role: dict[str, dict[str, Any]]) -> Path:
    for role in ("targetWorkbook", "bom", "grouping", "existingFmea"):
        candidate = str((inputs_by_role.get(role) or {}).get("path", "")).strip()
        if candidate:
            return Path(candidate).resolve().parent
    return Path(tempfile.gettempdir())


def _build_output_name(workflow_id: str) -> str:
    suffixes = {"bom_only": "BomOnly", "fill_gaps": "FillGaps"}
    suffix = suffixes.get(workflow_id, "Standard")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"DarkStarFMEA_{suffix}_{timestamp}.xlsx"


def _emit_status(
    callback: Callable[[str, str, str], None] | None,
    *,
    status: str,
    stage: str,
    message: str,
) -> None:
    if callback:
        callback(status, stage, message)


def _emit_progress(
    callback: Callable[[str, str, int, int | None, int | None], None] | None,
    *,
    stage: str,
    message: str,
    percent: int,
    current: int | None = None,
    total: int | None = None,
) -> None:
    if callback:
        callback(stage, message, percent, current, total)


def _progress_percent(
    stage_message: str,
    current: int,
    total: int,
    weights: dict[str, tuple[int, int, str]] | None = None,
) -> tuple[str, int]:
    table = weights or PROGRESS_STAGE_WEIGHTS
    start, span, stage = table.get(stage_message, (10, 70, stage_message))
    if total <= 0:
        return stage, start

    percent = start + round((current / total) * span)
    return stage, min(99, max(start, percent))


def execute_run_request(
    body: dict[str, Any],
    *,
    log_callback: Callable[[str], None] | None = None,
    status_callback: Callable[[str, str, str], None] | None = None,
    progress_callback: Callable[[str, str, int, int | None, int | None], None] | None = None,
    processor_ready_callback: Callable[[FMEAProcessor], None] | None = None,
) -> dict[str, Any]:
    validation = validate_run_request(body)
    if not validation["ok"]:
        raise ValidationError(validation["toast_text"] or "Run validation failed.")

    workflow_id = str(body.get("workflowId", "")).strip()
    enrichments = body.get("enrichments") or {}
    inputs_by_role = _collect_inputs(body)
    output_directory = _resolve_output_directory(inputs_by_role)
    output_path = output_directory / _build_output_name(workflow_id)

    logs: list[str] = []
    current_stage_message = "Preparing migrated backend run..."

    def stream_log_callback(message: str) -> None:
        logs.append(message)
        if log_callback:
            log_callback(message)

    def runtime_status_callback(message: str) -> None:
        nonlocal current_stage_message
        current_stage_message = message
        _, _, stage_label = PROGRESS_STAGE_WEIGHTS.get(message, (10, 70, message))
        _emit_status(
            status_callback,
            status="running",
            stage=stage_label,
            message=message,
        )
        default_percent = PROGRESS_STAGE_WEIGHTS.get(message, (10, 70, stage_label))[0]
        _emit_progress(
            progress_callback,
            stage=stage_label,
            message=message,
            percent=default_percent,
        )

    def runtime_progress_callback(current: int, total: int) -> None:
        stage_label, percent = _progress_percent(current_stage_message, current, total)
        _emit_progress(
            progress_callback,
            stage=stage_label,
            message=current_stage_message,
            percent=percent,
            current=current,
            total=total,
        )

    _emit_status(
        status_callback,
        status="starting",
        stage="Run accepted",
        message="Preparing migrated backend run...",
    )
    _emit_progress(
        progress_callback,
        stage="Run accepted",
        message="Preparing migrated backend run...",
        percent=1,
    )

    processor = FMEAProcessor(log_callback=stream_log_callback)
    if processor_ready_callback:
        processor_ready_callback(processor)

    if workflow_id == "fill_gaps":
        run_inputs = {
            "fmea": str((inputs_by_role.get("existingFmea") or {}).get("path", "")).strip() or None,
            "bom": str((inputs_by_role.get("bom") or {}).get("path", "")).strip() or None,
            "fm": str((inputs_by_role.get("failureModes") or {}).get("path", "")).strip() or None,
            "hda": str((inputs_by_role.get("hda") or {}).get("path", "")).strip() or None,
            "group": str((inputs_by_role.get("grouping") or {}).get("path", "")).strip() or None,
            "verbose": False,
            "column_overrides": {},
            "fmea_sheet": _selected_sheet(inputs_by_role, "existingFmea"),
            "bom_sheet": _selected_sheet(inputs_by_role, "bom"),
            "fm_sheet": _selected_sheet(inputs_by_role, "failureModes"),
            "hda_sheet": _selected_sheet(inputs_by_role, "hda"),
            "group_sheet": _selected_sheet(inputs_by_role, "grouping"),
        }

        def fill_gaps_progress_adapter(current: int, total: int) -> None:
            stage_label, percent = _progress_percent(
                "Generating FMEA rows for missing RefDes...", current, total,
                weights=FILL_GAPS_STAGE_WEIGHTS,
            )
            _emit_progress(
                progress_callback,
                stage=stage_label,
                message=f"Generating gap-fill rows ({current}/{total})...",
                percent=percent,
                current=current,
                total=total,
            )

        dataframe = processor.process_gaps(
            run_inputs,
            progress_callback=fill_gaps_progress_adapter,
        )
    else:
        run_inputs = {
            "group": str((inputs_by_role.get("grouping") or {}).get("path", "")).strip() or None,
            "bom": str((inputs_by_role.get("bom") or {}).get("path", "")).strip() or None,
            "hda": str((inputs_by_role.get("hda") or {}).get("path", "")).strip() or None,
            "fm": str((inputs_by_role.get("failureModes") or {}).get("path", "")).strip() or None,
            "func": str((inputs_by_role.get("functionalFmea") or {}).get("path", "")).strip() or None,
            "piecepart_fmea": str((inputs_by_role.get("piecePartFmea") or {}).get("path", "")).strip() or None,
            "out_folder": str(output_directory),
            "out_name": output_path.stem,
            "bom_only_mode": workflow_id == "bom_only",
            "use_func": bool(enrichments.get("functional")),
            "use_piecepart_merge": bool(enrichments.get("piecePart")),
            "verbose": False,
            "column_overrides": {},
            "template_preserve": False,
            "group_sheet": _selected_sheet(inputs_by_role, "grouping"),
            "bom_sheet": _selected_sheet(inputs_by_role, "bom"),
            "hda_sheet": _selected_sheet(inputs_by_role, "hda"),
            "fm_sheet": _selected_sheet(inputs_by_role, "failureModes"),
            "func_sheet": _selected_sheet(inputs_by_role, "functionalFmea"),
            "piecepart_fmea_sheet": _selected_sheet(inputs_by_role, "piecePartFmea"),
        }

        dataframe = processor.process(
            run_inputs,
            progress_callback=runtime_progress_callback,
            status_callback=runtime_status_callback,
        )

    output_strategy_id = str(body.get("outputStrategyId", "")).strip()
    use_template_preserve = output_strategy_id == "existing_workbook_preserve_formatting"

    _emit_status(
        status_callback,
        status="running",
        stage="Writing workbook",
        message="Writing workbook...",
    )
    _emit_progress(
        progress_callback,
        stage="Writing workbook",
        message="Writing workbook...",
        percent=95,
    )

    if use_template_preserve:
        from fmea.fmea_template_analyzer import analyze_template as _analyze_template
        from fmea.fmea_template_writer import (
            write_template_preserved,
            build_template_output_path,
        )

        target_path = str((inputs_by_role.get("targetWorkbook") or {}).get("path", "")).strip()
        target_sheet = _selected_sheet(inputs_by_role, "targetWorkbook")
        output_path = Path(build_template_output_path(target_path, mode="DarkStar"))

        template_map, wb = _analyze_template(
            target_path,
            sheet_name=target_sheet,
            cancel_token=processor.cancel,
            log_func=stream_log_callback,
        )
        try:
            write_template_preserved(
                wb, template_map, dataframe, processor,
                str(output_path),
                cancel_token=processor.cancel,
                log_func=stream_log_callback,
            )
        finally:
            wb.close()
    else:
        write_excel_report(dataframe, output_path, processor)

    _emit_progress(
        progress_callback,
        stage="Writing workbook",
        message="Workbook written successfully.",
        percent=100,
    )

    fmr_count = len(processor.fmr_warnings)
    usage_count = len(processor.usage_warnings)
    no_match_count = len(processor.no_matches)
    warning_count = fmr_count + usage_count + no_match_count

    notes = []
    if workflow_id == "fill_gaps":
        notes.append("Fill-gaps mode: generated rows for RefDes in BOM but missing from existing FMEA.")
    elif use_template_preserve:
        notes.append("Template-preserved mode: merged generated data into existing workbook.")
    else:
        notes.append("New-workbook generation path.")
    if warning_count == 0:
        notes.append("No processor warnings were recorded during this run.")
    else:
        notes.append(f"{warning_count} warning or unmatched condition(s) were captured in the workbook summary sheets.")

    return {
        "status": "success",
        "title": "FMEA generated",
        "summary": f"{len(dataframe)} rows were written through the migrated backend.",
        "output_file": str(output_path),
        "primary_metric": f"{len(dataframe)} rows",
        "secondary_metric": f"{warning_count} warnings",
        "notes": notes,
        "log_lines": logs[-LOG_LIMIT:],
        "row_count": len(dataframe),
        "warning_count": warning_count,
        "no_match_count": no_match_count,
        "mode": "desktop-bridge",
    }
