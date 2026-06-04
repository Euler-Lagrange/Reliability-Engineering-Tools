from __future__ import annotations

import logging
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from common.exceptions import ValidationError
from common import (
    atomic_write_path,
    atomic_finalize,
    validate_explicit_output_directory,
    verify_excel_readable,
)

from shared.pre_run_validation import (
    DO_NOT_MAP_SENTINEL,
    LabeledState,
    LabeledValue,
    validate_pre_run_state,
)
from shared.output_preview import build_preview_from_file
from fmea.fmea_generator_logic import FMEAProcessor, write_excel_report

_logger = logging.getLogger(__name__)

# Sentinel used by the frontend mapping table for "do not map this column".
# Mirrors frontend/src/app/types.ts DO_NOT_MAP_VALUE. Canonical definition now
# lives in shared/pre_run_validation.py and is imported above; this module
# re-exposes the name for backward compatibility so existing imports of
# ``fmea.runtime.DO_NOT_MAP_SENTINEL`` keep resolving.


# Fix D: map frontend canonical names (from FMEA_COLUMN_METADATA) to
# ``(HEADER_CONFIG file type, backend canonical key)`` tuples so explicit
# user mappings reach ``FMEAProcessor.map_columns()`` and override the
# heuristic column resolver, not just the A5 Part Usage gate.
#
# The frontend sends a single flat mapping table that spans all input
# files (e.g. "Failure Mode" → <column in FM file>, "Part Usage" → <column
# in BOM file>). The backend's ``process*()`` methods call ``map_columns``
# once per file type, passing ``col_overrides.get('BOM')`` /
# ``col_overrides.get('HDA')`` / etc. as the per-file overrides dict.
# Before Fix D, that lookup always returned ``None`` because the flat
# overrides dict was keyed by frontend canonical labels, not by file-type
# strings. Now we build BOTH shapes in ``_build_column_overrides`` so:
#
#   * The flat entries continue to feed the A5 Part Usage gate and any
#     future direct-canonical lookups (e.g. in ``_generate_component_rows``).
#   * The nested per-file entries feed ``map_columns`` so the heuristic
#     fallback is replaced by the user's explicit picks.
#
# Canonical labels not in this table are intentionally kept flat-only —
# the backend is still forward-compatible with new frontend canonicals
# that have not been wired into the HEADER_CONFIG plumbing yet.
#
# The FMD Commodity rows use dynamic labels on the frontend
# (``FMD-91 Commodity Type 1`` vs ``FMD-2016 Commodity Type 1``), so we
# register BOTH variants against the same backend key.
#
# Fix R2-M3: the overrides dict that ``_build_column_overrides`` returns
# carries BOTH flat canonical keys and nested per-file buckets at the
# same top level, so the file-type bucket names below are RESERVED: no
# future frontend canonical label may collide with any of the entries in
# ``_RESERVED_FILE_TYPE_KEYS``. If a new canonical clash is ever needed,
# restructure the return shape into ``{"flat": {...}, "nested": {...}}``
# instead of adding the clash to the flat dict.
_RESERVED_FILE_TYPE_KEYS: frozenset[str] = frozenset(
    {"BOM", "HDA", "FAILURE_MODES", "COMPONENT_GROUPING"}
)
FRONTEND_TO_BACKEND_MAPPING: dict[str, tuple[str, str]] = {
    # Grouping file
    "FMEA-ID": ("COMPONENT_GROUPING", "component_group"),
    "Failure Mode Causes": ("COMPONENT_GROUPING", "ref_des"),
    # BOM file
    "Component Part Description": ("BOM", "description"),
    "Part Usage": ("BOM", "part_usage"),
    # HDA file — BAE taxonomy
    "BAE HDA Commodity Level 1": ("HDA", "commodity_level1"),
    "BAE HDA Commodity Level 2": ("HDA", "commodity_level2"),
    # HDA file — FMD standard-specific commodity types.
    # Frontend sends the ACTIVE label (e.g. ``FMD-91 Commodity Type 1``);
    # both labels point at the same backend key so either standard works.
    "FMD-91 Commodity Type 1": ("HDA", "fmd_type1"),
    "FMD-2016 Commodity Type 1": ("HDA", "fmd_type1"),
    "FMD-91 Commodity Type 2": ("HDA", "fmd_type2"),
    "FMD-2016 Commodity Type 2": ("HDA", "fmd_type2"),
    # Failure Modes file
    "Failure Mode": ("FAILURE_MODES", "failure_mode"),
    "Failure Mode Ratio": ("FAILURE_MODES", "ratio"),
}


def _build_column_overrides(body_mappings: Any) -> dict[str, Any]:
    """Convert the frontend's mapping list into the backend column_overrides dict.

    The frontend sends ``body.mappings`` as a list of
    ``{canonical, mappedTo, status, ...}`` objects (see
    ``FmeaTool.tsx buildRunRequest``). The backend processor reads the
    result in two different shapes in two different places, so we build
    BOTH shapes into a single dict that carries them side-by-side:

    * **Flat entries** — keyed by the frontend canonical name
      (e.g. ``{"Part Usage": "Qty"}``). Used by direct lookups such as
      the A5 Part Usage discrepancy gate in
      ``_generate_component_rows``.
    * **Nested per-file entries** — keyed by the ``HEADER_CONFIG``
      file type (``BOM``, ``HDA``, ``FAILURE_MODES``,
      ``COMPONENT_GROUPING``) with inner dicts mapping the backend
      canonical key (e.g. ``part_usage``) to the user-picked column
      name. Used by ``FMEAProcessor.map_columns()`` to override the
      heuristic resolver.

    Example output for a run that mapped Failure Mode → ``fm_col`` and
    Part Usage → ``Qty``::

        {
            "Failure Mode": "fm_col",
            "Part Usage": "Qty",
            "FAILURE_MODES": {"failure_mode": "fm_col"},
            "BOM": {"part_usage": "Qty"},
        }

    Rows whose ``mappedTo`` is empty or set to the ``DO_NOT_MAP``
    sentinel are skipped so the heuristic column resolver can still run.
    """
    overrides: dict[str, Any] = {}
    if not body_mappings:
        return overrides
    for row in body_mappings:
        if not isinstance(row, Mapping):
            continue
        canonical = str(row.get("canonical", "")).strip()
        mapped_to = row.get("mappedTo")
        if not canonical:
            continue
        if mapped_to in (None, "", DO_NOT_MAP_SENTINEL):
            continue
        mapped_str = str(mapped_to).strip()
        # Fix R2-M3: defensively reject canonical labels that would
        # clash with the reserved file-type bucket keys we use for
        # nested shapes below. See ``_RESERVED_FILE_TYPE_KEYS`` above.
        if canonical in _RESERVED_FILE_TYPE_KEYS:
            raise ValidationError(
                f"Canonical column label {canonical!r} collides with a "
                f"reserved file-type bucket key. Rename the frontend "
                f"canonical to something else, or refactor "
                f"_build_column_overrides to use a nested return shape."
            )
        # Flat shape (used by direct-canonical lookups downstream).
        overrides[canonical] = mapped_str
        # Nested per-file shape (used by map_columns heuristic override).
        # Fix D: only entries whose canonical is in FRONTEND_TO_BACKEND_MAPPING
        # gain a nested entry. Unknown canonicals remain flat-only so the
        # backend is forward-compatible with new frontend labels.
        target = FRONTEND_TO_BACKEND_MAPPING.get(canonical)
        if target is not None:
            file_type, backend_key = target
            bucket = overrides.setdefault(file_type, {})
            if isinstance(bucket, dict):
                bucket[backend_key] = mapped_str
    return overrides

# Phase 4 / A6: CCA identifier (prefix) must be 1-8 chars of uppercase
# alphanumerics or hyphens, and must start with an alphanumeric. Frontend
# enforces this pattern too; backend re-validates defensively in case a
# stale client or integration test ships an unvalidated value.
CCA_PREFIX_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9\-]{0,7}$")

SUPPORTED_EXECUTION_WORKFLOWS = {
    "piece_part_generate",
    "bom_only",
    "fill_gaps",
    "functional_to_piecepart",
}
SUPPORTED_OUTPUT_STRATEGIES = {
    "new_workbook_standard",
    "existing_workbook_preserve_formatting",
}
SUPPORTED_FAILURE_MODES_STANDARDS = {"FMD-91", "FMD-2016"}
LOG_LIMIT = 120
PROGRESS_STAGE_WEIGHTS = {
    "Reading input files...": (5, 10, "Reading input files"),
    "Building indexes...": (15, 10, "Building indexes"),
    "Generating FMEA rows...": (25, 60, "Generating FMEA rows"),
    "Writing workbook...": (95, 5, "Writing workbook"),
}
FILL_GAPS_STAGE_WEIGHTS = {
    "Loading input files...": (5, 10, "Loading input files"),
    "Classifying FMEA rows...": (15, 15, "Classifying FMEA rows"),
    "Generating FMEA rows for missing RefDes...": (30, 55, "Generating gap-fill rows"),
    "Writing workbook...": (95, 5, "Writing workbook"),
}
FUNCTIONAL_TO_PP_STAGE_WEIGHTS = {
    "Reading input files...": (5, 10, "Reading input files"),
    "Building indexes...": (15, 10, "Building indexes"),
    "Parsing functional FMEA blocks...": (25, 15, "Parsing functional blocks"),
    "Generating piece-part rows under blocks...": (40, 50, "Generating piece-part rows"),
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
) -> list[str]:
    """Required input roles for a workflow.

    Phase C/D: enrichment toggles were removed from the UI; functional FMEA
    is now its own primary workflow (`functional_to_piecepart`) instead of
    a bolt-on enrichment. The legacy `piecePartFmea` enrichment is dropped
    entirely.
    """
    roles: list[str]
    if workflow_id == "piece_part_generate":
        roles = ["grouping", "bom", "failureModes"]
    elif workflow_id == "bom_only":
        roles = ["bom", "failureModes"]
    elif workflow_id == "functional_to_piecepart":
        roles = ["functionalFmea", "bom", "failureModes"]
    elif workflow_id == "fill_gaps":
        roles = ["existingFmea", "bom", "failureModes"]
    else:
        roles = []

    if output_strategy_id == "existing_workbook_preserve_formatting":
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
    failure_modes_standard: str | None,
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
                "title": "Output strategy is not supported",
                "detail": "Choose 'New Workbook' or 'Existing Workbook (Preserve Formatting)'.",
            }
        )

    if failure_modes_standard not in SUPPORTED_FAILURE_MODES_STANDARDS:
        messages.append(
            {
                "id": "missing-failure-modes-standard",
                "severity": "error",
                "area": "Failure Modes",
                "title": "Failure Modes standard is required",
                "detail": "Select either FMD-91 or FMD-2016 to drive failure-mode column headers.",
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
    options = body.get("options") or {}
    failure_modes_standard = (
        str(options.get("failureModesStandard", "")).strip() or None
    )
    inputs_by_role = _collect_inputs(body)

    # Fix C2: merge modes parse "Failure Mode Causes" as a comma-separated
    # list of reference designators to derive each group's component set.
    # Without an explicit mapping for that column, the backend runs but
    # silently produces empty component lists — the generated FMEA is
    # effectively blank. Block that upfront.
    if workflow_id in ("fill_gaps", "functional_to_piecepart"):
        body_mappings = body.get("mappings") or []
        mapped_canonicals: dict[str, Any] = {}
        for row in body_mappings:
            if isinstance(row, Mapping):
                # Fix R2-H3: strip canonical to match the normalization in
                # ``_build_column_overrides`` so a padded/case-different
                # canonical can't bypass the validator while still landing
                # in the overrides dict under the stripped key.
                mapped_canonicals[str(row.get("canonical", "")).strip()] = row.get(
                    "mappedTo"
                )
        fmc_mapped_to = mapped_canonicals.get("Failure Mode Causes")
        if not fmc_mapped_to or fmc_mapped_to == DO_NOT_MAP_SENTINEL:
            return {
                "ok": False,
                "reason_code": "missing_failure_mode_causes_mapping",
                "toast_text": (
                    "Map the 'Failure Mode Causes' column before running a "
                    "merge. The backend parses it to identify components in "
                    "each function group."
                ),
                "validations": [],
                "mode": "desktop-bridge",
            }

    required_roles = _required_roles(workflow_id, output_strategy_id)
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
    elif failure_modes_standard not in SUPPORTED_FAILURE_MODES_STANDARDS:
        result = type(result)(
            ok=False,
            reason_code="missing_failure_modes_standard",
            toast_text="Select FMD-91 or FMD-2016 before running.",
            affected_labels=result.affected_labels,
        )
    elif workflow_id == "bom_only":
        # Phase 4 / A6: BOM-Only mode requires a CCA identifier — it
        # replaces the default "BOM" group label in generated FMEA-IDs.
        # Frontend validates but we re-check here so an unvalidated
        # client (e.g., integration test) can't slip an invalid value
        # through and silently produce "-C200-A" or "bom-c200-A" output.
        cca_prefix_raw = options.get("ccaPrefix")
        cca_prefix = str(cca_prefix_raw).strip() if cca_prefix_raw is not None else ""
        if not cca_prefix:
            result = type(result)(
                ok=False,
                reason_code="missing_cca_prefix",
                toast_text=(
                    "Enter a CCA identifier in the Workflow card before "
                    "running BOM-Only mode."
                ),
                affected_labels=result.affected_labels,
            )
        elif not CCA_PREFIX_PATTERN.match(cca_prefix):
            result = type(result)(
                ok=False,
                reason_code="invalid_cca_prefix",
                toast_text=(
                    "CCA identifier must be 1-8 uppercase alphanumerics "
                    "or hyphens."
                ),
                affected_labels=result.affected_labels,
            )

    # Contract fix: honor the ``hdaSource`` flag. When the user explicitly
    # selected "Separate HDA file" but no usable HDA workbook is loaded, the
    # old backend silently fell back to inline detection. Block that here so
    # the explicit choice is respected. ``inline`` and the legacy absent case
    # never require an HDA file. Checked only after the prior gates pass so the
    # narrowest blocking message still wins (matches the elif chain above).
    if result.ok:
        hda_source = _hda_source(options)
        if hda_source == "separate" and not _is_input_loaded(
            inputs_by_role.get("hda") or {}
        ):
            result = type(result)(
                ok=False,
                reason_code="missing_separate_hda",
                toast_text=(
                    "Separate HDA file selected but no HDA workbook is loaded. "
                    "Attach the HDA workbook or switch HDA source to inline."
                ),
                affected_labels=(_role_label("hda"),) + result.affected_labels,
            )

    response: dict[str, Any] = {
        "ok": result.ok,
        "reason_code": result.reason_code,
        "toast_text": result.toast_text,
        "validations": _build_validation_messages(
            result, workflow_id, output_strategy_id, inputs_by_role, failure_modes_standard
        ),
        "mode": "desktop-bridge",
    }
    # Attach output_preview on success only (design handoff principle D /
    # phase 4a). Preview failures never fail validation — the helper
    # swallows exceptions and returns None.
    if result.ok:
        preview = _build_fmea_output_preview(workflow_id, inputs_by_role)
        if preview is not None:
            response["output_preview"] = preview
    return response


def _build_fmea_output_preview(
    workflow_id: str, inputs_by_role: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """Sample the primary BOM / functional FMEA so the Review drawer can show
    the source rows that will feed the generated workbook.

    The preview is a head of the user's input mapped to the canonical
    columns most users care about (RefDes, Part Number, Description) —
    not a faithful simulation of the eventual FMEA row expansion, which
    would require running the processor. It still answers the question
    "did the tool see my parts?".
    """
    # functional_to_piecepart reads from the functional FMEA first; every
    # other workflow anchors on the BOM.
    primary_role = "functionalFmea" if workflow_id == "functional_to_piecepart" else "bom"
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


def _selected_sheet(inputs_by_role: dict[str, dict[str, Any]], role: str) -> str | None:
    value = str((inputs_by_role.get(role) or {}).get("selectedSheet", "")).strip()
    return value or None


# Contract fix: the frontend sends ``options.hdaSource`` ("inline" | "separate")
# to declare whether HDA commodity data comes from a dedicated workbook or is
# detected inline from BOM columns. The backend now honors the flag in BOTH
# directions instead of guessing from path presence (see
# ``_hda_source`` / ``_resolve_hda_path`` and the ``missing_separate_hda``
# validation gate).
#
# ``None`` (flag absent) preserves legacy behavior for older/other clients that
# don't send it: path presence decides inline vs. separate downstream.
def _hda_source(options: Mapping[str, Any]) -> str | None:
    """Read the normalized ``hdaSource`` flag, or ``None`` when absent.

    Returns ``"inline"`` or ``"separate"`` for recognized values; ``None`` when
    the key is missing or blank (legacy client) so callers fall back to the
    historical path-presence behavior.
    """
    raw = options.get("hdaSource")
    if raw is None:
        return None
    value = str(raw).strip().lower()
    return value or None


def _resolve_hda_path(
    inputs_by_role: dict[str, dict[str, Any]],
    hda_source: str | None,
) -> str | None:
    """Resolve the effective dedicated-HDA path, honoring ``hdaSource``.

    This is the single seam where the flag becomes authoritative for the
    execute path, keeping ``fmea_generator_logic.py`` flag-free:

    * ``hda_source == "inline"`` → return ``None`` so the logic layer ignores
      any stray hda input (a hidden hda role can persist with a path after the
      user toggles back to inline) and runs inline detection instead.
    * Otherwise (``"separate"`` or ``None`` for legacy clients) → return the
      attached hda path, or ``None`` when none is attached.
    """
    if hda_source == "inline":
        return None
    return str((inputs_by_role.get("hda") or {}).get("path", "")).strip() or None


def _resolve_hda_sheet(
    inputs_by_role: dict[str, dict[str, Any]],
    hda_source: str | None,
) -> str | None:
    """Resolve the effective HDA sheet, suppressed when the source is inline."""
    if hda_source == "inline":
        return None
    return _selected_sheet(inputs_by_role, "hda")


def _resolve_output_directory(
    inputs_by_role: dict[str, dict[str, Any]],
    explicit_directory: str | None = None,
    log_callback: Callable[[str], None] | None = None,
) -> Path:
    """Resolve the output directory for the generated FMEA workbook.

    Phase 4 / A7: when the frontend sends a top-level ``outputDirectory``
    field on the run request body, honor it. If the provided path is
    invalid (missing, not a directory, or unwriteable), fall back to the
    existing "first input file parent" heuristic.

    Fix B3: the invalid-path fallback used to be silent, so the user saw
    their workbook land in an unexpected location with no indication of
    why. We now emit a WARNING log on every fallback path so the run
    log surfaces the reason.
    """
    resolved = validate_explicit_output_directory(
        explicit_directory,
        log_func=log_callback,
    )
    if resolved is not None:
        return resolved
    for role in ("targetWorkbook", "bom", "grouping", "existingFmea"):
        candidate = str((inputs_by_role.get(role) or {}).get("path", "")).strip()
        if candidate:
            return Path(candidate).resolve().parent
    return Path(tempfile.gettempdir())


def _build_output_name(workflow_id: str) -> str:
    suffixes = {
        "bom_only": "BomOnly",
        "fill_gaps": "FillGaps",
        "functional_to_piecepart": "FromFunctional",
    }
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

    # Phase D: hard-fail on legacy enrichment payloads. The Enrichments UI
    # was removed in Phase C; functional FMEA is now its own primary
    # workflow (`functional_to_piecepart`) and piece-part enrichment was
    # deprecated entirely. A stale client that still sends
    # enrichments.functional=true would otherwise be silently misrun in
    # the new primary workflow mode, producing output without the merge
    # the user requested. Fail loudly so the client knows to migrate.
    legacy_enrichments = body.get("enrichments") or {}
    if legacy_enrichments.get("functional") or legacy_enrichments.get("piecePart"):
        raise ValidationError(
            "Functional / Piece-Part enrichment toggles have been removed. "
            "Use workflowId='functional_to_piecepart' for the new functional path."
        )

    workflow_id = str(body.get("workflowId", "")).strip()
    options = body.get("options") or {}
    failure_modes_standard = str(options.get("failureModesStandard", "FMD-2016")).strip() or "FMD-2016"
    column_selection_raw = options.get("columnSelection") or {}
    column_selection = {
        "mode": str(column_selection_raw.get("mode", "all")).strip() or "all",
        "columns": [str(c) for c in (column_selection_raw.get("columns") or [])],
    }
    # Phase 4 / A6: CCA identifier (BOM-Only only). Already validated above.
    cca_prefix_raw = options.get("ccaPrefix")
    cca_prefix = (
        str(cca_prefix_raw).strip()
        if workflow_id == "bom_only" and cca_prefix_raw is not None
        else None
    ) or None
    inputs_by_role = _collect_inputs(body)
    # Contract fix: resolve the effective HDA source ONCE so the flag is
    # authoritative for every workflow branch below. When the source is
    # "inline" the helpers return None, so a stray hda input (e.g. a hidden
    # role that kept its path after the user toggled back to inline) is
    # ignored and the logic layer runs inline detection. "separate" / legacy
    # absent keep using the attached path. fmea_generator_logic.py stays
    # flag-free — it still branches only on whether it received an hda path.
    hda_source = _hda_source(options)
    effective_hda_path = _resolve_hda_path(inputs_by_role, hda_source)
    effective_hda_sheet = _resolve_hda_sheet(inputs_by_role, hda_source)
    # Fix A2: plumb the frontend's column mapping rows through to the
    # processor as column_overrides. Previously we hardcoded {} and the
    # user's explicit column picks were silently discarded, forcing the
    # backend to fall back to heuristic column detection.
    body_mappings = body.get("mappings") or []
    column_overrides = _build_column_overrides(body_mappings)

    logs: list[str] = []
    current_stage_message = "Preparing migrated backend run..."

    def stream_log_callback(message: str) -> None:
        logs.append(message)
        if log_callback:
            log_callback(message)

    # Phase 4 / A7: honor explicit outputDirectory when the frontend sends one.
    # Fix B3: pass stream_log_callback so fallback warnings reach the run log.
    explicit_output_directory = body.get("outputDirectory")
    if explicit_output_directory is not None:
        explicit_output_directory = str(explicit_output_directory).strip() or None
    output_directory = _resolve_output_directory(
        inputs_by_role,
        explicit_directory=explicit_output_directory,
        log_callback=stream_log_callback,
    )
    output_path = output_directory / _build_output_name(workflow_id)

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
    # Phase 4 / A6: set CCA prefix BEFORE process*() runs so _format_fmea_id
    # sees it. _reset_state() deliberately preserves this field.
    processor.cca_prefix = cca_prefix
    if processor_ready_callback:
        processor_ready_callback(processor)

    if workflow_id == "fill_gaps":
        run_inputs = {
            "fmea": str((inputs_by_role.get("existingFmea") or {}).get("path", "")).strip() or None,
            "bom": str((inputs_by_role.get("bom") or {}).get("path", "")).strip() or None,
            "fm": str((inputs_by_role.get("failureModes") or {}).get("path", "")).strip() or None,
            "hda": effective_hda_path,
            "group": str((inputs_by_role.get("grouping") or {}).get("path", "")).strip() or None,
            "verbose": False,
            "column_overrides": column_overrides,
            "failure_modes_standard": failure_modes_standard,
            "fmea_sheet": _selected_sheet(inputs_by_role, "existingFmea"),
            "bom_sheet": _selected_sheet(inputs_by_role, "bom"),
            "fm_sheet": _selected_sheet(inputs_by_role, "failureModes"),
            "hda_sheet": effective_hda_sheet,
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
    elif workflow_id == "functional_to_piecepart":
        run_inputs = {
            "func": str((inputs_by_role.get("functionalFmea") or {}).get("path", "")).strip() or None,
            "bom": str((inputs_by_role.get("bom") or {}).get("path", "")).strip() or None,
            "hda": effective_hda_path,
            "fm": str((inputs_by_role.get("failureModes") or {}).get("path", "")).strip() or None,
            "group": str((inputs_by_role.get("grouping") or {}).get("path", "")).strip() or None,
            "out_folder": str(output_directory),
            "out_name": output_path.stem,
            "verbose": False,
            "column_overrides": column_overrides,
            "failure_modes_standard": failure_modes_standard,
            "func_sheet": _selected_sheet(inputs_by_role, "functionalFmea"),
            "bom_sheet": _selected_sheet(inputs_by_role, "bom"),
            "hda_sheet": effective_hda_sheet,
            "fm_sheet": _selected_sheet(inputs_by_role, "failureModes"),
            "group_sheet": _selected_sheet(inputs_by_role, "grouping"),
        }

        def functional_progress_adapter(current: int, total: int) -> None:
            stage_label, percent = _progress_percent(
                "Generating piece-part rows under blocks...", current, total,
                weights=FUNCTIONAL_TO_PP_STAGE_WEIGHTS,
            )
            _emit_progress(
                progress_callback,
                stage=stage_label,
                message=f"Generating piece-part rows ({current}/{total})...",
                percent=percent,
                current=current,
                total=total,
            )

        dataframe = processor.process_functional_to_piecepart(
            run_inputs,
            progress_callback=functional_progress_adapter,
            status_callback=runtime_status_callback,
        )
    else:
        run_inputs = {
            "group": str((inputs_by_role.get("grouping") or {}).get("path", "")).strip() or None,
            "bom": str((inputs_by_role.get("bom") or {}).get("path", "")).strip() or None,
            "hda": effective_hda_path,
            "fm": str((inputs_by_role.get("failureModes") or {}).get("path", "")).strip() or None,
            "func": None,
            "piecepart_fmea": None,
            "out_folder": str(output_directory),
            "out_name": output_path.stem,
            "bom_only_mode": workflow_id == "bom_only",
            "use_func": False,
            "use_piecepart_merge": False,
            "verbose": False,
            "column_overrides": column_overrides,
            "template_preserve": False,
            "failure_modes_standard": failure_modes_standard,
            "group_sheet": _selected_sheet(inputs_by_role, "grouping"),
            "bom_sheet": _selected_sheet(inputs_by_role, "bom"),
            "hda_sheet": effective_hda_sheet,
            "fm_sheet": _selected_sheet(inputs_by_role, "failureModes"),
            "func_sheet": None,
            "piecepart_fmea_sheet": None,
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

    # Apply column subset filtering if requested. ROW_TYPE_COL is always
    # retained because the writer uses it to drive insert/update decisions.
    # Phase D safety: if NONE of the user-requested columns actually exist
    # in the generated DataFrame (e.g., stale UI state after a column
    # inspection), fall back to keeping all columns rather than silently
    # shipping an empty workbook. The user gets a WARNING log so they
    # notice.
    if column_selection["mode"] == "subset" and column_selection["columns"]:
        from fmea.fmea_generator_logic import ROW_TYPE_COL
        keep = set(column_selection["columns"])
        keep.add(ROW_TYPE_COL)
        filtered_cols = [c for c in dataframe.columns if c in keep]
        user_matches = [c for c in filtered_cols if c != ROW_TYPE_COL]
        if user_matches:
            dataframe = dataframe[filtered_cols]
        else:
            stream_log_callback(
                f"WARNING: column subset filter matched none of the requested columns "
                f"{column_selection['columns']!r}. Keeping all columns as a safe fallback. "
                f"Available columns: {list(dataframe.columns)[:10]}{'...' if len(dataframe.columns) > 10 else ''}"
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

        # Phase D: thread the selected FMD standard through to the template
        # analyzer + writer so the column map, synonym lookups, and appended
        # headers all use the user's selected standard. Without this, picking
        # FMD-91 with preserve-formatting silently dropped the FMD commodity
        # columns because the writer was looking up FMD-2016 header names.
        template_map, wb = _analyze_template(
            target_path,
            sheet_name=target_sheet,
            cancel_token=processor.cancel,
            log_func=stream_log_callback,
            failure_modes_standard=failure_modes_standard,
        )
        tmp_output = atomic_write_path(output_path)
        try:
            try:
                write_template_preserved(
                    wb, template_map, dataframe, processor,
                    str(tmp_output),
                    cancel_token=processor.cancel,
                    log_func=stream_log_callback,
                    failure_modes_standard=failure_modes_standard,
                )
            finally:
                wb.close()
            if not verify_excel_readable(tmp_output):
                raise IOError(
                    f"Post-write verification failed for {tmp_output}; workbook did not open."
                )
            atomic_finalize(tmp_output, output_path, log_func=stream_log_callback)
        except Exception:
            try:
                if tmp_output.exists():
                    tmp_output.unlink()
            except OSError:
                pass
            raise
    else:
        tmp_output = atomic_write_path(output_path)
        try:
            write_excel_report(dataframe, tmp_output, processor)
            if not verify_excel_readable(tmp_output):
                raise IOError(
                    f"Post-write verification failed for {tmp_output}; workbook did not open."
                )
            atomic_finalize(tmp_output, output_path, log_func=stream_log_callback)
        except Exception:
            try:
                if tmp_output.exists():
                    tmp_output.unlink()
            except OSError:
                pass
            raise

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
