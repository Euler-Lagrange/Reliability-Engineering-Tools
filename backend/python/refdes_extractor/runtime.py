"""RefDes Extractor runtime adapter for the Tauri sidecar."""
from __future__ import annotations

import threading
import tempfile
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from common import (
    get_tool_logger,
    write_df_to_sheet,
    CancellationToken,
    CancellationError,
    ConfigManager,
    atomic_write_path,
    atomic_finalize,
    verify_excel_readable,
    validate_explicit_output_directory,
)
from common.exceptions import ValidationError, ProcessingError
from shared.pre_run_validation import LabeledState, LabeledValue, validate_pre_run_state
from shared.output_preview import build_preview_from_file

_logger = get_tool_logger("refdes_extractor_runtime")

SUPPORTED_WORKFLOWS = {"refdes_extract"}
LOG_LIMIT = 120

ROLE_LABELS = {
    "pdf": "Schematic PDF",
    "bom": "BOM workbook",
    "pinlist": "Pinlist file",
}

# ---------------------------------------------------------------------------
# Typed config — explicit surface for the 25+ extraction parameters
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RefDesConfig:
    """Typed extraction configuration. Replaces scattered ConfigManager.get() calls."""
    extraction_mode: str = "functional"
    backend_mode: str = "auto"
    geometry_analysis_enabled: bool = True
    adaptive_geometry_enabled: bool = True
    geometry_batch_size: int = 10
    geometry_subprocess_enabled: bool = False
    geometry_batch_timeout_seconds: float = 240.0
    geometry_batch_checkpoint_enabled: bool = True
    max_pin_label_length: int = 4
    prov_distance: float = 15.0
    pin_assignment_threshold: float = 50.0
    refdes_search_radius: float = 100.0
    adaptive_orphan_threshold: int = 5
    adaptive_orphan_ratio: float = 0.30
    adaptive_max_pages: int = 10
    pinlist_prefers_annotation_mode: bool = True

    @classmethod
    def from_options(cls, options: dict[str, Any]) -> RefDesConfig:
        """Build from sidecar request body options dict."""
        field_names = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in options.items() if k in field_names}
        return cls(**filtered)

    def to_config_manager(self) -> ConfigManager:
        """Create an in-memory ConfigManager for legacy engine compatibility."""
        cm = ConfigManager.__new__(ConfigManager)
        cm._lock = threading.Lock()
        cm.app_name = "refdes_extract_sidecar"
        cm.config_path = Path("/dev/null")
        cm.data = {f.name: getattr(self, f.name) for f in fields(self)}
        return cm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role)


def _collect_inputs(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("role")): item
        for item in body.get("inputs", [])
        if isinstance(item, dict) and item.get("role")
    }


def _input_path(inputs_by_role: dict[str, dict[str, Any]], role: str) -> str | None:
    value = str((inputs_by_role.get(role) or {}).get("path", "")).strip()
    return value or None


def _selected_sheet(inputs_by_role: dict[str, dict[str, Any]], role: str) -> str | None:
    value = str((inputs_by_role.get(role) or {}).get("selectedSheet", "")).strip()
    return value or None


def _is_input_loaded(input_state: dict[str, Any], role: str) -> bool:
    if not input_state:
        return False
    if input_state.get("resolutionError"):
        return False
    if not str(input_state.get("path", "")).strip():
        return False
    # PDFs have no sheets — skip sheet check for pdf role
    if role == "pdf":
        return True
    sheets = input_state.get("sheets") or []
    if sheets and not str(input_state.get("selectedSheet", "")).strip():
        return False
    return True


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
    for role in ("pdf", "bom"):
        candidate = _input_path(inputs_by_role, role)
        if candidate:
            return Path(candidate).resolve().parent
    return Path(tempfile.gettempdir())


class _CancelBridge:
    """Bridges CancellationToken to threading.Event for the RefDes extraction engine.

    The token and the threading.Event share the same underlying ``threading.Event``
    so that ``self.cancel.cancel()`` (called by the sidecar's
    ``ActiveRun.request_cancel``) sets the same event that the extraction engine
    checks via ``stop_event.is_set()``.
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


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_run_request(body: dict[str, Any]) -> dict[str, Any]:
    workflow_id = str(body.get("workflowId", "")).strip()
    inputs_by_role = _collect_inputs(body)

    # PDF is always required
    required_roles = ["pdf"]
    required_files = [
        LabeledValue(_role_label(role), _input_path(inputs_by_role, role))
        for role in required_roles
    ]
    loaded_states = [
        LabeledState(_role_label(role), _is_input_loaded(inputs_by_role.get(role) or {}, role))
        for role in required_roles
    ]

    # BOM and pinlist are optional — check load-in-progress only if provided
    optional_roles = ["bom", "pinlist"]
    load_in_progress = any(
        bool((inputs_by_role.get(role) or {}).get("isResolvingSheets"))
        for role in required_roles + optional_roles
        if _input_path(inputs_by_role, role)
    )

    result = validate_pre_run_state(
        required_files=required_files,
        load_in_progress=load_in_progress,
        loaded_states=loaded_states,
        not_loaded_message="Load required files: {labels}.",
    )

    if workflow_id not in SUPPORTED_WORKFLOWS:
        result = type(result)(
            ok=False,
            reason_code="unsupported_workflow",
            toast_text="This RefDes Extractor workflow is not supported.",
            affected_labels=result.affected_labels,
        )

    # Check fitz availability
    if result.ok:
        try:
            import fitz  # noqa: F401
        except ImportError:
            result = type(result)(
                ok=False,
                reason_code="missing_dependency",
                toast_text="PyMuPDF (fitz) is not installed. PDF extraction requires this dependency.",
                affected_labels=(),
            )

    messages: list[dict[str, str]] = []
    if result.ok:
        messages.append({
            "id": "ready-to-run",
            "severity": "info",
            "area": "Run State",
            "title": "Backend validation passed",
            "detail": "This workspace is ready for extraction.",
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
    if result.ok:
        preview = _build_refdes_output_preview(inputs_by_role)
        if preview is not None:
            response["output_preview"] = preview
    return response


def _build_refdes_output_preview(
    inputs_by_role: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Sample the optional BOM workbook so the Review drawer can show the
    reference designators that the extracted PDF results will be
    validated against. No preview is emitted when the user hasn't
    provided a BOM — the PDF itself isn't cheap to preview via
    ``try_read_table``, and the extracted-designator head is only
    meaningful after the real extraction runs.
    """
    bom_state = inputs_by_role.get("bom") or {}
    path = str(bom_state.get("path", "")).strip() or None
    sheet = str(bom_state.get("selectedSheet", "")).strip() or None
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


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def execute_run_request(
    body: dict[str, Any],
    *,
    log_callback: Callable[[str], None] | None = None,
    status_callback: Callable[[str, str, str], None] | None = None,
    progress_callback: Callable[[str, str, int, int | None, int | None], None] | None = None,
    processor_ready_callback: Callable[[Any], None] | None = None,
) -> dict[str, Any]:
    import fitz  # noqa: F811

    validation = validate_run_request(body)
    if not validation["ok"]:
        raise ValidationError(validation["toast_text"] or "Run validation failed.")

    inputs_by_role = _collect_inputs(body)
    options = body.get("options") or {}
    config = RefDesConfig.from_options(options)
    config_cm = config.to_config_manager()

    pdf_path = _input_path(inputs_by_role, "pdf")
    bom_path = _input_path(inputs_by_role, "bom")
    pinlist_path = _input_path(inputs_by_role, "pinlist")
    bom_sheet = _selected_sheet(inputs_by_role, "bom")
    pinlist_sheet = _selected_sheet(inputs_by_role, "pinlist")

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
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_directory / f"RefDesExtract_{timestamp}.xlsx"

    def emit_status(status: str, stage: str, message: str) -> None:
        if status_callback:
            status_callback(status, stage, message)

    def emit_progress(stage: str, message: str, percent: int) -> None:
        if progress_callback:
            progress_callback(stage, message, percent, None, None)

    bridge = _CancelBridge()
    if processor_ready_callback:
        processor_ready_callback(bridge)

    emit_status("starting", "Run accepted", "Preparing RefDes extraction...")
    emit_progress("Run accepted", "Preparing...", 1)

    # Lazy imports — keeps module loadable even without fitz at import time
    from refdes_test.refdes_test_logic import (
        extract_with_geometry_analysis_detailed,
        extract_annotations_from_doc,
        detect_groups_with_fallback,
        load_bom_with_metadata,
        load_pinlist,
    )
    from refdes_extractor.extraction_engine import cleanup_words_extraction_threads

    # --- Load BOM (1-5%) ---
    bom_set: set[str] = set()
    bom_page_map: dict[str, set[int]] | None = None
    if bom_path:
        emit_status("running", "Loading BOM", "Loading BOM workbook...")
        emit_progress("Loading BOM", "Loading BOM...", 2)
        try:
            bom_set, bom_page_map = load_bom_with_metadata(
                Path(bom_path), log_func=stream_log, sheet_name=bom_sheet,
            )
            stream_log(f"Loaded {len(bom_set)} RefDes from BOM.")
        except (InterruptedError, CancellationError):
            raise
        except Exception as exc:
            stream_log(f"WARNING: BOM load failed ({exc}). Proceeding without BOM verification.")
            bom_set = set()
    emit_progress("Loading BOM", "BOM loaded.", 5)

    # --- Load Pinlist (5-8%) ---
    pinlist_set: set[str] | None = None
    if pinlist_path and config.extraction_mode == "piece_part":
        emit_status("running", "Loading pinlist", "Loading pinlist file...")
        emit_progress("Loading pinlist", "Loading pinlist...", 6)
        try:
            pinlist_set = load_pinlist(Path(pinlist_path), log_func=stream_log)
            stream_log(f"Loaded {len(pinlist_set)} pin identifiers from pinlist.")
        except (InterruptedError, CancellationError):
            raise
        except Exception as exc:
            stream_log(f"WARNING: Pinlist load failed ({exc}). Proceeding without pinlist.")
    emit_progress("Loading pinlist", "Pinlist loaded.", 8)

    # --- Open PDF + Extract Annotations (8-18%) ---
    emit_status("running", "Opening PDF", "Opening schematic PDF...")
    emit_progress("Opening PDF", "Opening PDF...", 9)

    doc = fitz.open(str(pdf_path))
    try:
        stream_log(f"Opened PDF: {Path(pdf_path).name} ({len(doc)} pages)")

        emit_status("running", "Extracting annotations", "Extracting annotations from PDF...")
        emit_progress("Extracting annotations", "Extracting annotations...", 10)
        annotations = extract_annotations_from_doc(
            doc, stop_event=bridge.stop_event, log_func=stream_log,
        )
        stream_log(f"Found {len(annotations)} annotations.")

        bridge.cancel.check()

        # Detect groups from annotations
        emit_progress("Detecting groups", "Detecting component groups...", 14)
        groups, _used_fallback, _provenance = detect_groups_with_fallback(doc, annotations, log_func=stream_log)
        stream_log(f"Detected {len(groups)} component groups.")
        emit_progress("Groups detected", "Groups detected.", 18)

        if not groups:
            stream_log("WARNING: No component groups found in PDF annotations.")

        # --- Extract with Geometry Analysis (18-90%) ---
        def engine_progress(fraction: float) -> None:
            percent = 18 + round(fraction * 72)
            emit_progress("Extracting", f"Extraction progress ({percent}%)...", min(90, percent))

        def engine_status(message: str) -> None:
            emit_status("running", "Extracting", message)

        emit_status("running", "Extracting", "Running extraction engine...")

        results, details = extract_with_geometry_analysis_detailed(
            pdf_path=Path(pdf_path),
            groups=groups,
            bom_set=bom_set,
            config=config_cm,
            pinlist_set=pinlist_set,
            log_func=stream_log,
            progress_func=engine_progress,
            status_func=engine_status,
            stop_event=bridge.stop_event,
            bom_page_map=bom_page_map,
            backend_override=config.backend_mode,
            doc=doc,
        )
    finally:
        cleanup_words_extraction_threads()
        doc.close()

    # --- Write Excel (90-98%) ---
    emit_status("running", "Writing workbook", "Writing extraction results...")
    emit_progress("Writing workbook", "Writing...", 92)

    tmp_output = atomic_write_path(output_path)
    try:
        if results:
            df = pd.DataFrame(results)
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "RefDes Extraction"
            write_df_to_sheet(ws, df)
            wb.save(str(tmp_output))
            wb.close()
        else:
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "RefDes Extraction"
            ws.append(["Group", "Failure Mode Causes", "Component Count", "Pages"])
            ws.append(["(No groups extracted)", "", 0, ""])
            wb.save(str(tmp_output))
            wb.close()
        if not verify_excel_readable(tmp_output):
            raise IOError(
                f"Post-write verification failed for {tmp_output}; workbook did not open."
            )
        atomic_finalize(tmp_output, output_path, log_func=stream_log)
    except Exception:
        try:
            if tmp_output.exists():
                tmp_output.unlink()
        except OSError:
            pass
        raise

    emit_progress("Complete", "Extraction complete.", 100)

    # --- Compute statistics ---
    # A group with a BOM is emitted as TWO rows ("X (Verified)" + "X (Unverified)"),
    # and "GROUP NOT DETECTED" / _is_gap rows are placeholders for expected-but-missing
    # groups. Count DISTINCT logical groups so the metrics aren't inflated by the split
    # or by gap placeholders, and so verified/unverified don't overlap. A logical group
    # counts as "verified" if any of its rows is a (Verified) row.
    _group_verified = {}
    for r in results:
        _g = str(r.get("group", ""))
        if r.get("_is_gap") or "GROUP NOT DETECTED" in _g:
            continue
        _base = _g.replace(" (Verified)", "").replace(" (Unverified)", "")
        _group_verified[_base] = _group_verified.get(_base, False) or ("(Verified)" in _g)
    total_groups = len(_group_verified)
    verified = sum(1 for v in _group_verified.values() if v)
    unverified = total_groups - verified
    # Each component appears in exactly one row (verified xor unverified set), so
    # summing all rows still counts every extracted component once.
    total_refdes = sum(r.get("component count", 0) for r in results)

    backend_used = details.get("backend_used", "unknown")
    notes = [
        f"Backend: {backend_used}.",
        f"Extraction mode: {config.extraction_mode}.",
    ]
    if details.get("fallback_reason"):
        notes.append(f"Fallback reason: {details['fallback_reason']}")
    if not bom_path:
        notes.append("No BOM provided — all groups marked as unverified.")

    return {
        "status": "success",
        "title": "RefDes extraction complete",
        "summary": f"{total_refdes} components extracted from {total_groups} groups.",
        "output_file": str(output_path),
        "primary_metric": f"{verified} verified groups",
        "secondary_metric": f"{unverified} unverified, {total_refdes} total components",
        "notes": notes,
        "log_lines": logs[-LOG_LIMIT:],
        "row_count": total_groups,
        "warning_count": unverified,
        "no_match_count": unverified,
        "mode": "desktop-bridge",
    }
