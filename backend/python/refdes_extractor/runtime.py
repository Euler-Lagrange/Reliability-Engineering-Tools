"""RefDes Extractor runtime adapter for the Tauri sidecar."""
from __future__ import annotations

import math
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
from common.excel_styles import StylePresets, style_header_only, style_worksheet
from common.exceptions import FileAccessError, ProcessingError, ValidationError
from refdes_extractor.validation_notes import annotate_results
from shared.pre_run_validation import (
    LabeledState,
    LabeledValue,
    append_output_directory_warning,
    validate_pre_run_state,
)
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
    # Opt-in: checkpoints write JSON artifacts into the user's chosen output
    # folder (_refdes_test_checkpoints/), so they must never be a default
    # side effect. Keep in lockstep with the frontend default.
    geometry_batch_checkpoint_enabled: bool = False
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

    def to_config_manager(self, out_folder: str = "") -> ConfigManager:
        """Create an in-memory ConfigManager for legacy engine compatibility.

        ``out_folder`` is the resolved run output directory. The engine's
        geometry-batch checkpoint writer early-returns without one, so
        omitting it silently disables the checkpoint feature the Advanced
        controls advertise.
        """
        cm = ConfigManager.__new__(ConfigManager)
        cm._lock = threading.Lock()
        cm.app_name = "refdes_extract_sidecar"
        cm.config_path = Path("/dev/null")
        cm.data = {f.name: getattr(self, f.name) for f in fields(self)}
        if out_folder:
            cm.data["out_folder"] = str(out_folder)
        return cm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _summarize_group_verification(results: list) -> tuple:
    """Count distinct logical groups and how many are genuinely verified.

    A group with a BOM is emitted as TWO rows ("X (Verified)" +
    "X (Unverified)"), and "GROUP NOT DETECTED" / _is_gap rows are
    placeholders for expected-but-missing groups. Count DISTINCT logical
    groups so the metrics aren't inflated by the split or by gap
    placeholders. Batch 5 (2026-07): a group counts as verified only when
    its "(Verified)" row actually CARRIES components — every regular group
    emits the row pair regardless of BOM state, so the label suffix alone
    said nothing (a no-BOM run reported every group "verified" while the
    notes said the opposite).
    """
    group_verified: dict = {}
    for r in results:
        g = str(r.get("group", ""))
        if r.get("_is_gap") or "GROUP NOT DETECTED" in g:
            continue
        base = g.replace(" (Verified)", "").replace(" (Unverified)", "")
        try:
            count = int(r.get("component count", 0) or 0)
        except (TypeError, ValueError):
            count = 0
        is_verified_row = "(Verified)" in g and count > 0
        group_verified[base] = group_verified.get(base, False) or is_verified_row
    total = len(group_verified)
    verified = sum(1 for v in group_verified.values() if v)
    return total, verified, total - verified


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
# Option validation (#5 Stage 2)
# ---------------------------------------------------------------------------
# All 16 engine parameters are now user-settable from the frontend and spread
# straight into the run payload's ``options`` dict. ``RefDesConfig.from_options``
# performs NO coercion — a wrong-typed or out-of-range value would flow verbatim
# into the extraction engine and fail late (or silently misbehave). Validate the
# type/range of every *present* option here so a bad value fails visibly at
# validate time with a clear, per-option message. Unknown keys are ignored, in
# lockstep with ``from_options``' silent-drop behavior.

_BOOL_OPTIONS = frozenset({
    "geometry_analysis_enabled",
    "adaptive_geometry_enabled",
    "geometry_subprocess_enabled",
    "geometry_batch_checkpoint_enabled",
    "pinlist_prefers_annotation_mode",
})

# Distances / sizes / timeout — must be a finite number strictly > 0.
_POSITIVE_NUMBER_OPTIONS = frozenset({
    "geometry_batch_timeout_seconds",
    "prov_distance",
    "pin_assignment_threshold",
    "refdes_search_radius",
})

# Counts / sizes / pages — must be a whole number >= 1.
_POSITIVE_INT_OPTIONS = frozenset({
    "geometry_batch_size",
    "max_pin_label_length",
    "adaptive_max_pages",
})

# Counts / thresholds that may legitimately be 0 (e.g. "trigger full geometry
# even with zero orphans"). Whole number >= 0. adaptive_orphan_threshold=0 is
# the integer analogue of adaptive_orphan_ratio=0.0, and the frontend control
# allows a minimum of 0 — validating it as >= 1 would hard-block a UI-permitted
# value.
_NON_NEGATIVE_INT_OPTIONS = frozenset({
    "adaptive_orphan_threshold",
})

# Enum options — must be one of the allowed literal values.
_ENUM_OPTIONS: dict[str, tuple[str, ...]] = {
    "extraction_mode": ("functional", "piece_part"),
    "backend_mode": ("auto", "nextgen", "legacy"),
}

# adaptive_orphan_ratio is handled specially: a finite number in [0, 1].
_RATIO_OPTION = "adaptive_orphan_ratio"


def _coerce_number(value: Any) -> float:
    """Return ``value`` as a finite float, or raise ValueError.

    Booleans are rejected outright (``bool`` is an ``int`` subclass, so an
    unguarded numeric check would silently accept ``True``/``False`` as 1/0).
    Numeric strings (e.g. "10") parse for tolerance, and non-finite values
    (NaN / inf) are rejected so they can't slip past a ``> 0`` comparison.
    """
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        number = float(value.strip())  # may raise ValueError
    else:
        raise ValueError("not a number")
    if not math.isfinite(number):
        raise ValueError("not a finite number")
    return number


def _coerce_int(value: Any) -> int:
    """Return ``value`` as an integer, or raise ValueError.

    Accepts whole-valued floats (10.0 -> 10) but rejects fractional values.
    """
    number = _coerce_number(value)
    if number != int(number):
        raise ValueError("not a whole number")
    return int(number)


def _validate_options(options: Any) -> list[tuple[str, str]]:
    """Type/range-check every present option; return (name, detail) for each
    invalid one (empty list when all present options are valid)."""
    if not isinstance(options, dict):
        return []

    errors: list[tuple[str, str]] = []
    for name, value in options.items():
        if name in _BOOL_OPTIONS:
            if not isinstance(value, bool):
                errors.append((name, f"must be true or false (got {value!r})"))
        elif name in _ENUM_OPTIONS:
            allowed = _ENUM_OPTIONS[name]
            if not (isinstance(value, str) and value in allowed):
                errors.append((name, f"must be one of {', '.join(allowed)} (got {value!r})"))
        elif name in _POSITIVE_INT_OPTIONS:
            try:
                number = _coerce_int(value)
            except (TypeError, ValueError):
                errors.append((name, f"must be a whole number >= 1 (got {value!r})"))
            else:
                if number < 1:
                    errors.append((name, f"must be >= 1 (got {value!r})"))
        elif name in _NON_NEGATIVE_INT_OPTIONS:
            try:
                number = _coerce_int(value)
            except (TypeError, ValueError):
                errors.append((name, f"must be a whole number >= 0 (got {value!r})"))
            else:
                if number < 0:
                    errors.append((name, f"must be >= 0 (got {value!r})"))
        elif name in _POSITIVE_NUMBER_OPTIONS:
            try:
                number = _coerce_number(value)
            except (TypeError, ValueError):
                errors.append((name, f"must be a number > 0 (got {value!r})"))
            else:
                if number <= 0:
                    errors.append((name, f"must be > 0 (got {value!r})"))
        elif name == _RATIO_OPTION:
            try:
                number = _coerce_number(value)
            except (TypeError, ValueError):
                errors.append((name, f"must be a number between 0 and 1 (got {value!r})"))
            else:
                if not (0.0 <= number <= 1.0):
                    errors.append((name, f"must be between 0 and 1 (got {value!r})"))
        # else: unknown key — silently ignored, mirroring from_options.
    return errors


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

    # #5 Stage 2: type/range-check the engine options so a wrong-typed or
    # out-of-range value fails visibly here instead of flowing into the engine.
    # Only run once the setup (files / workflow / dependency) is otherwise
    # green, so those more fundamental blockers take precedence.
    option_errors: list[tuple[str, str]] = []
    if result.ok:
        option_errors = _validate_options(body.get("options") or {})
        if option_errors:
            result = type(result)(
                ok=False,
                reason_code="invalid_option",
                toast_text=(
                    "Invalid extraction option(s): "
                    + "; ".join(f"{name} {detail}" for name, detail in option_errors)
                ),
                affected_labels=tuple(name for name, _ in option_errors),
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
        # Surface each offending option as its own entry so the user sees
        # exactly which control is invalid, not just a concatenated toast.
        for name, detail in option_errors:
            messages.append({
                "id": f"invalid-option-{name}",
                "severity": "error",
                "area": "Options",
                "title": f"Invalid option: {name}",
                "detail": f"'{name}' {detail}.",
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

# User-facing header text for the extraction sheet. The engines emit
# lowercase keys; the sheet headers are Title Case (matches the empty-results
# branch and the coverage sheets).
_DISPLAY_COLUMNS = {
    "group": "Group",
    "failure mode causes": "Failure Mode Causes",
    "component count": "Component Count",
    "pages": "Pages",
    "validation notes": "Validation Notes",
}

_EMPTY_SHEET_HEADERS = list(_DISPLAY_COLUMNS.values())


def _results_dataframe(results) -> pd.DataFrame:
    """Build the output DataFrame from engine result rows.

    Drops internal bookkeeping columns and renames the engine's lowercase
    keys to the user-facing Title Case headers.

    Gap-detection rows carry an ``_is_gap`` styling marker, and
    ``annotate_results`` adds a ``_row_style`` marker for the Excel styler.
    Drop any ``_``-prefixed column so no internal key ever reaches the
    workbook.
    """
    df = pd.DataFrame(results)
    internal_cols = [col for col in df.columns if str(col).startswith("_")]
    if internal_cols:
        df = df.drop(columns=internal_cols)
    return df.rename(columns=_DISPLAY_COLUMNS)


# Extractor-scoped presets: Aptos Narrow (user choice) without touching the
# suite-wide "Aptos" default other tools inherit from the global PRESETS.
_EXTRACTOR_FONT = "Aptos Narrow"
_extractor_presets_cache: StylePresets | None = None


def _extractor_presets() -> StylePresets:
    global _extractor_presets_cache
    if _extractor_presets_cache is None:
        _extractor_presets_cache = StylePresets(font_name=_EXTRACTOR_FONT)
    return _extractor_presets_cache


_COMPONENT_DETAIL_SHEET = "Component Detail"
_ORPHAN_PINS_SHEET = "Orphan Pins"


def _ambiguity_flag(candidates) -> str:
    try:
        count = int(candidates or 0)
    except (TypeError, ValueError):
        return ""
    return f"ambiguous ({count} candidates)" if count > 1 else ""


def _write_component_detail_sheet(wb, details: dict | None) -> None:
    """One row per extracted component: pages, confidence, source, flags.

    NextGen-only diagnostics — when the accumulator is empty (legacy
    fallback, or no diagnostics), the sheet is skipped entirely.
    """
    token_diags = (details or {}).get("token_diagnostics") or {}
    if not token_diags:
        return
    from refdes_extractor.extraction_engine import natural_key

    rows = [
        {
            "Component": token,
            "Group": info.get("group", ""),
            "Pages": ", ".join(str(p) for p in info.get("pages", [])),
            "Confidence": info.get("confidence", ""),
            "Source": info.get("source", ""),
            "Flags": _ambiguity_flag(info.get("candidates")),
        }
        for token, info in token_diags.items()
    ]
    rows.sort(key=lambda row: (natural_key(row["Group"]), natural_key(row["Component"])))
    df = pd.DataFrame(rows, columns=["Component", "Group", "Pages", "Confidence", "Source", "Flags"])
    ws = wb.create_sheet(_COMPONENT_DETAIL_SHEET)
    write_df_to_sheet(ws, df)
    style_worksheet(ws, df, presets=_extractor_presets(), alternate_rows=True)


def _write_orphan_pins_sheet(wb, details: dict | None) -> None:
    """One row per pin dropped before the output rows (skipped when none)."""
    orphans = (details or {}).get("orphan_pins") or []
    if not orphans:
        return
    rows = [
        {
            "Pin": o.get("pin_text", ""),
            "Page": o.get("page", ""),
            "Group": o.get("group", ""),
            "Disposition": o.get("disposition", ""),
            "Detail": o.get("detail", ""),
        }
        for o in orphans
    ]
    rows.sort(key=lambda row: (row["Page"] if isinstance(row["Page"], int) else 0, str(row["Pin"])))
    df = pd.DataFrame(rows, columns=["Pin", "Page", "Group", "Disposition", "Detail"])
    ws = wb.create_sheet(_ORPHAN_PINS_SHEET)
    write_df_to_sheet(ws, df)
    style_worksheet(ws, df, presets=_extractor_presets(), alternate_rows=True)


def _write_extraction_sheet(ws, results) -> pd.DataFrame:
    """Write + style the main extraction sheet from annotated result rows.

    ``results`` rows may carry a ``_row_style`` semantic-style marker from
    ``annotate_results``; it drives per-row highlighting (duplicates = amber,
    gap placeholders = yellow, populated Unverified rows = grey) and is
    dropped from the sheet itself by ``_results_dataframe``.
    """
    df = _results_dataframe(results)
    row_styles = [str(row.get("_row_style", "default")) for row in results]

    def _row_style(_row: pd.Series, idx: int) -> str:
        return row_styles[idx] if 0 <= idx < len(row_styles) else "default"

    write_df_to_sheet(ws, df)
    style_worksheet(
        ws,
        df,
        presets=_extractor_presets(),
        row_style_func=_row_style,
        alternate_rows=True,
        max_width=60,  # component lists run long; still capped for sanity
    )
    return df


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
    # Built AFTER output resolution so geometry-batch checkpoints have a
    # destination (they early-return without out_folder).
    config_cm = config.to_config_manager(out_folder=str(output_directory))

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
        load_pinlist,
    )
    from refdes_extractor.bom_loader import BASE_MODE, load_bom_data
    from refdes_extractor.coverage_report import build_coverage, write_coverage_sheets
    from refdes_extractor.extraction_engine import cleanup_words_extraction_threads

    # --- Load BOM (1-5%) ---
    bom_set: set[str] = set()
    bom_page_map: dict[str, set[int]] | None = None
    bom_meta: dict[str, dict[str, str]] = {}
    bom_load_error: str | None = None
    if bom_path:
        emit_status("running", "Loading BOM", "Loading BOM workbook...")
        emit_progress("Loading BOM", "Loading BOM...", 2)
        try:
            _bom_result = load_bom_data(
                Path(bom_path), log_func=stream_log, sheet_name=bom_sheet,
                include_page_metadata=True, include_component_metadata=True,
                mode=BASE_MODE,
            )
            bom_set = _bom_result.refdes
            bom_page_map = _bom_result.page_map
            bom_meta = _bom_result.meta
            stream_log(f"Loaded {len(bom_set)} RefDes from BOM.")
        except (InterruptedError, CancellationError):
            raise
        except Exception as exc:
            # The user supplied a BOM for cross-check; a load failure must NOT
            # masquerade as a completed verification. Continue (per design) but
            # surface it prominently in the result, not just one log line, since
            # an empty bom_set marks EVERY component "NOT IN BOM" (Tier-1 #4).
            bom_load_error = f"the supplied BOM could not be loaded ({exc})"
            stream_log(
                f"WARNING: A BOM was supplied for cross-check but it failed to "
                f"load ({exc}). Extraction will continue, but EVERY component is "
                f"reported NOT IN BOM because no BOM data is available. Fix the "
                f"BOM (sheet selection / file lock / RefDes column) and re-run to "
                f"actually verify."
            )
            bom_set = set()
        # An empty-but-successful load (wrong sheet, blank RefDes column, all
        # values failing the RefDes regex) reproduces the same silent "looks
        # complete" report: bom_set is empty so every component is NOT IN BOM.
        # Treat it as a soft failure and surface it just as prominently.
        if bom_load_error is None and not bom_set:
            bom_load_error = (
                "the BOM loaded but contained 0 recognizable RefDes "
                "(check the selected sheet and the RefDes column)"
            )
            stream_log(
                "WARNING: the supplied BOM loaded but yielded 0 RefDes, so every "
                "component will be reported NOT IN BOM. Check the sheet selection "
                "and the RefDes column, then re-run to actually verify."
            )
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
        # Close each stage with a completed-phrase message: the frontend
        # timeline keeps a stage's LAST message, so without this the step
        # reads "Opening PDF..." forever next to a completed chip.
        emit_progress("Opening PDF", "PDF opened.", 10)

        emit_status("running", "Extracting annotations", "Extracting annotations from PDF...")
        emit_progress("Extracting annotations", "Extracting annotations...", 10)
        annotations = extract_annotations_from_doc(
            doc, stop_event=bridge.stop_event, log_func=stream_log,
        )
        stream_log(f"Found {len(annotations)} annotations.")
        emit_progress("Extracting annotations", "Annotations extracted.", 13)

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

    # --- Validation notes (runtime-side annotation; engines untouched) ---
    # Adds the "validation notes" column (cross-group duplicate ordinals,
    # ambiguous-assignment flags from the diagnostics accumulator,
    # not-in-BOM reasons, gap explanations) and the internal _row_style
    # marker that drives row highlighting in the workbook.
    _token_diags = (details or {}).get("token_diagnostics") or {}
    ambiguous_tokens = {}
    for _token, _info in _token_diags.items():
        try:
            _count = int(_info.get("candidates") or 0)
        except (TypeError, ValueError):
            _count = 0
        if _count > 1:
            ambiguous_tokens[_token] = _count
    results = annotate_results(
        results,
        bom_provided=bool(bom_set) and not bom_load_error,
        ambiguous_tokens=ambiguous_tokens,
    )

    # --- Compute BOM coverage reverse-diff (only meaningful with a real BOM) ---
    # Gated on a non-empty, successfully-loaded BOM: with no BOM the diff is
    # degenerate (everything "unverified"), and a failed load already emits the
    # prominent BOM-CROSS-CHECK-FAILED notice below.
    coverage = None
    if bom_set and not bom_load_error:
        # Coverage is a SECONDARY, additive report computed after the expensive
        # extraction has finished. A defect here must never sink the primary
        # result, so swallow any failure and continue without coverage sheets.
        try:
            coverage = build_coverage(
                bom_set, results, bom_meta=bom_meta, bom_page_map=bom_page_map,
            )
        except (InterruptedError, CancellationError):
            raise
        except Exception as exc:
            coverage = None
            stream_log(
                f"WARNING: the BOM coverage report could not be computed ({exc}); "
                f"the extraction output is unaffected."
            )

    def _safe_write_coverage(workbook) -> None:
        """Append coverage sheets, never letting a failure abort the main save."""
        if coverage is None:
            return
        try:
            write_coverage_sheets(workbook, coverage, presets=_extractor_presets())
        except (InterruptedError, CancellationError):
            raise
        except Exception as exc:
            stream_log(
                f"WARNING: coverage sheets could not be written ({exc}); the main "
                f"extraction sheet is unaffected."
            )

    # --- Write Excel (90-98%) ---
    emit_status("running", "Writing workbook", "Writing extraction results...")
    emit_progress("Writing workbook", "Writing...", 92)

    tmp_output = atomic_write_path(output_path)
    try:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "RefDes Extraction"
        if results:
            _write_extraction_sheet(ws, results)
        else:
            ws.append(_EMPTY_SHEET_HEADERS)
            ws.append(["(No groups extracted)", "", 0, "", ""])
            style_header_only(ws, len(_EMPTY_SHEET_HEADERS), _extractor_presets())
        # Diagnostics sheets are additive (NextGen-only data) — like the
        # coverage sheets, a failure here must never sink the main save.
        try:
            _write_component_detail_sheet(wb, details)
            _write_orphan_pins_sheet(wb, details)
        except (InterruptedError, CancellationError):
            raise
        except Exception as exc:
            stream_log(
                f"WARNING: diagnostics sheets could not be written ({exc}); the "
                f"main extraction sheet is unaffected."
            )
        _safe_write_coverage(wb)
        wb.save(str(tmp_output))
        wb.close()
        if not verify_excel_readable(tmp_output):
            raise FileAccessError(
                f"Post-write verification failed for {tmp_output}; workbook did not open.",
                file_path=str(tmp_output),
                operation="write",
            )
        atomic_finalize(tmp_output, output_path, log_func=stream_log)
    except Exception:
        try:
            if tmp_output.exists():
                tmp_output.unlink()
        except OSError:
            pass
        raise
    # Close the write stage before the terminal step (see "Opening PDF" note).
    emit_progress("Writing workbook", "Workbook written.", 98)

    emit_progress("Complete", "Extraction complete.", 100)

    # --- Compute statistics ---
    total_groups, verified, unverified = _summarize_group_verification(results)
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
    elif bom_load_error:
        notes.insert(0, (
            f"BOM CROSS-CHECK FAILED: {bom_load_error}. Every component is marked "
            f"NOT IN BOM, so this report does NOT reflect a real BOM comparison. "
            f"Re-run with a usable BOM to verify."
        ))

    if coverage is not None:
        cs = coverage.summary
        notes.append(
            f"BOM coverage: {cs['bom_not_grouped_count']} BOM component(s) not grouped "
            f"({cs['not_extracted_count']} never extracted), "
            f"{cs['extracted_not_in_bom_count']} extracted not in BOM — see the "
            f"'Coverage Summary', 'BOM Not Grouped', and 'Extracted Not In BOM' sheets."
        )

    _orphan_count = len((details or {}).get("orphan_pins") or [])
    if _orphan_count:
        notes.append(
            f"{_orphan_count} pin{'s' if _orphan_count != 1 else ''} dropped before "
            f"output — see the 'Orphan Pins' sheet."
        )
    if ambiguous_tokens:
        notes.append(
            f"{len(ambiguous_tokens)} component{'s' if len(ambiguous_tokens) != 1 else ''} "
            f"assigned ambiguously — see the 'Component Detail' sheet."
        )

    return {
        "status": "success",
        "title": (
            "RefDes extraction complete - BOM cross-check FAILED"
            if bom_load_error else "RefDes extraction complete"
        ),
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
