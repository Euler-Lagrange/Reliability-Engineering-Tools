#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# Originally copied from src/apps/fmea_generator/fmea_template_writer.py.
# Freeze lifted 2026-04-08; this is now the maintained copy for the Tauri suite.
# ============================================================================
"""
FMEA Template Writer — Merge generated data into an existing FMEA workbook.

Preserves the original workbook's formatting, column order, merged cells,
and non-FMEA sheets while updating/inserting piece-part rows and appending
generator-specific columns.

Phase 2 of FMEA Template Preservation.  Works hand-in-hand with the
template analyzer (Phase 1) which produces the TemplateMap consumed here.
"""

import time
from copy import copy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import pandas as pd
from openpyxl.worksheet.cell_range import CellRange
from openpyxl.worksheet.worksheet import Worksheet

from common.cancellation import CancellationError, CancellationToken
from common.excel_styles import sanitize_for_excel
from common.exceptions import FileAccessError, ProcessingError
from common.logger import get_tool_logger
from common.refdes_utils import canonicalize_refdes
from fmea.fmea_generator_logic import (
    ROW_TYPE_COL,
    SUMMARY_SHEET_BANNERS,
    TOOL_SHEET_MARKER,
    build_summary_frames,
    normalize_func_base_id,
    output_headers_for,
    prepend_tool_sheet_banner,
)
from fmea.fmea_template_analyzer import (
    CellStyle,
    ColumnMap,
    FunctionGroup,
    TemplateMap,
    capture_cell_style,
    normalize_failure_mode_identity,
)

_logger = get_tool_logger("fmea_template_writer")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_CANCEL_CHECK_INTERVAL = 50      # Rows between cancellation checks
_GIL_YIELD_INTERVAL = 100       # Rows between GIL yields for UI repaint
_DIAGNOSTIC_COL = "Diagnostic"   # Generator diagnostic column name
_ISSUE_HEADERS = [
    "ReasonCode",
    "Source",
    "Excel Row",
    "Group ID",
    "RefDes",
    "Failure Mode",
    "Details",
]
_TEMPLATE_DIAGNOSTIC_SHEET_NAMES = (
    "Template_Merge_Summary",
    "Merge Changes",
    "Template_Merge_Issues",
)
_KNOWN_DIAGNOSTIC_SHEET_NAMES = (
    *SUMMARY_SHEET_BANNERS.keys(),
    *_TEMPLATE_DIAGNOSTIC_SHEET_NAMES,
)
_NOT_REBASED_FEATURE_ORDER = (
    "data validations",
    "conditional formatting",
    "tables",
    "formulas",
    "hyperlinks",
)


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class MergeChange:
    """One non-blank generated value that replaced user workbook content."""
    excel_row: int
    refdes: str
    fmea_id: str
    column: str
    previous_value: Any
    new_value: Any


@dataclass(frozen=True)
class CellUpdateResult:
    """Outcome of applying one generated value to an existing cell."""
    status: str
    previous_value: Any
    new_value: Any


@dataclass
class GroupMergeResult:
    """Result of merging piece-parts for one function group."""
    group_id: str
    pp_updated: int = 0
    pp_inserted: int = 0
    pp_flagged: int = 0
    insert_at: int = 0
    blanks_skipped: Dict[str, int] = field(default_factory=dict)
    merge_changes: List[MergeChange] = field(default_factory=list)
    issue_rows: List[Dict[str, Any]] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    not_rebased_features: Set[str] = field(default_factory=set)


@dataclass
class TemplateWriteResult:
    """Summary of the entire template-preserved write."""
    groups_matched: int = 0
    groups_unmatched: int = 0
    groups_new: int = 0
    pp_rows_updated: int = 0
    pp_rows_inserted: int = 0
    pp_rows_flagged: int = 0
    blanks_skipped: Dict[str, int] = field(default_factory=dict)
    merge_changes: List[MergeChange] = field(default_factory=list)
    issue_rows: List[Dict[str, Any]] = field(default_factory=list)
    extra_cols_appended: List[str] = field(default_factory=list)
    output_path: str = ""
    issues: List[str] = field(default_factory=list)
    not_rebased_features: Set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _noop_log(msg: str) -> None:
    """Fallback log function that does nothing."""


def _write_plain_cell(cell, value) -> None:
    """Write a value into an appended-row cell (no style source to copy).

    Same hygiene as ``_update_cell_preserving_format``: sanitize strings
    and never write NaN — a raw NaN float lands as a broken numeric cell
    in the saved workbook.
    """
    if isinstance(value, str):
        cell.value = sanitize_for_excel(value)
    elif pd.isna(value):
        cell.value = None
    else:
        cell.value = value


def _apply_cell_style(cell, style: CellStyle) -> None:
    """Apply a CellStyle snapshot to a worksheet cell.

    Uses copy() because openpyxl caches style objects; direct assignment
    of a shared object would mutate all cells sharing that style.
    """
    cell.font = copy(style.font)
    cell.fill = copy(style.fill)
    cell.alignment = copy(style.alignment)
    cell.border = copy(style.border)
    cell.number_format = style.number_format


def _range_reaches_row(reference: Any, row: int) -> bool:
    """Return whether a cell-range reference contains any row at/after *row*."""
    def reaches(cell_range: Any) -> bool:
        max_row = getattr(cell_range, "max_row", None)
        return max_row is None or max_row >= row

    ranges = getattr(reference, "ranges", None)
    if ranges is not None:
        return any(reaches(cell_range) for cell_range in ranges)
    try:
        return reaches(CellRange(str(reference)))
    except (TypeError, ValueError):
        return False


def _detect_not_rebased_features(ws: Worksheet, insert_at: int) -> Set[str]:
    """Identify worksheet features openpyxl will not move with inserted rows."""
    features: Set[str] = set()

    validations = getattr(ws.data_validations, "dataValidation", ())
    if any(
        _range_reaches_row(validation.sqref, insert_at)
        for validation in validations
    ):
        features.add("data validations")

    if any(
        _range_reaches_row(rule.sqref, insert_at)
        for rule in ws.conditional_formatting
    ):
        features.add("conditional formatting")

    if any(
        _range_reaches_row(table.ref, insert_at)
        for table in ws.tables.values()
    ):
        features.add("tables")

    materialized_cells = tuple(ws._cells.values())
    if any(
        cell.row >= insert_at and cell.data_type == "f"
        for cell in materialized_cells
    ):
        features.add("formulas")
    if any(
        cell.row >= insert_at and cell.hyperlink is not None
        for cell in materialized_cells
    ):
        features.add("hyperlinks")

    return features


def _prepare_merged_ranges_for_insert(
    ws: Worksheet,
    insert_at: int,
    amount: int,
) -> List[str]:
    """Unmerge affected ranges and return their post-insertion coordinates."""
    rebased_coordinates: List[str] = []
    affected: List[Tuple[str, str]] = []

    for merged_range in tuple(ws.merged_cells.ranges):
        if merged_range.max_row < insert_at:
            continue

        rebased = CellRange(str(merged_range))
        if rebased.min_row >= insert_at:
            rebased.shift(row_shift=amount)
        else:
            rebased.max_row += amount
        affected.append((str(merged_range), str(rebased)))

    for original, rebased in affected:
        ws.unmerge_cells(original)
        rebased_coordinates.append(rebased)

    return rebased_coordinates


def _move_row_dimensions_for_insert(
    ws: Worksheet,
    insert_at: int,
    amount: int,
) -> None:
    """Move explicit row metadata with rows shifted by an insertion."""
    source_rows = sorted(
        (
            row_index
            for row_index in tuple(ws.row_dimensions.keys())
            if row_index >= insert_at
        ),
        reverse=True,
    )
    for source_row in source_rows:
        dimension = ws.row_dimensions[source_row]
        del ws.row_dimensions[source_row]
        target_row = source_row + amount
        dimension.index = target_row
        ws.row_dimensions[target_row] = dimension


def _is_blank_value(value: Any) -> bool:
    """Return whether *value* is one of the decided merge blank values."""
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _merge_values_equal(previous_value: Any, generated_value: Any) -> bool:
    """Compare merge values without rewriting numerically equivalent cells.

    Excel may load a numeric user cell as ``1.0`` while generated tabular data
    supplies ``"1"``.  Numeric equality is checked first so that equivalent
    values retain the user's original cell type; non-numeric values keep the
    established stripped-string comparison.
    """
    try:
        if float(previous_value) == float(generated_value):
            return True
    except (TypeError, ValueError, OverflowError):
        pass
    return str(previous_value).strip() == str(generated_value).strip()


def _update_cell_preserving_format(ws: Worksheet, row: int, col: int,
                                    value: Any) -> CellUpdateResult:
    """Merge *value* into a cell without altering its existing formatting.

    Blank generated values never replace non-blank workbook content, and
    numerically equivalent values, then values equal after a stripped string
    comparison, are left untouched.
    The caller uses the returned status for summary counts and the audit.
    """
    cell = ws.cell(row=row, column=col)
    previous_value = cell.value

    if _is_blank_value(value):
        status = "blank_skipped" if not _is_blank_value(previous_value) else "unchanged"
        return CellUpdateResult(status, previous_value, previous_value)

    if (
        not _is_blank_value(previous_value)
        and _merge_values_equal(previous_value, value)
    ):
        return CellUpdateResult("unchanged", previous_value, previous_value)

    if isinstance(value, str):
        cell.value = sanitize_for_excel(value)
    else:
        cell.value = value
    status = "filled" if _is_blank_value(previous_value) else "changed"
    return CellUpdateResult(status, previous_value, cell.value)


def _build_generated_index(
    df: pd.DataFrame,
    log_func: Optional[Callable[[str], None]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Index the generator DataFrame by normalized group (function) ID.

    Walks the DataFrame row-by-row.  When ``_row_type == 'circuit_block'``,
    extracts the ``FMEA-ID`` column and applies ``normalize_func_base_id``
    to establish the current group.  When ``_row_type == 'piece_part'``,
    the row dict is appended to the current group's list.

    Returns:
        ``{normalized_group_id: [row_dict, ...]}``
    """
    log = log_func or _noop_log
    index: Dict[str, List[Dict[str, Any]]] = {}
    current_group_id: Optional[str] = None

    for idx, row_series in df.iterrows():
        row_dict = row_series.to_dict()
        row_type = row_dict.get(ROW_TYPE_COL, "")

        if row_type == "circuit_block":
            fmea_id = ""
            raw_id = row_dict.get("FMEA-ID", "")
            if pd.notna(raw_id):
                fmea_id = str(raw_id).strip()
            current_group_id = normalize_func_base_id(fmea_id)
            if current_group_id and current_group_id not in index:
                index[current_group_id] = []

        elif row_type == "piece_part" and current_group_id:
            index.setdefault(current_group_id, []).append(row_dict)

    log(f"Built generated index: {len(index)} groups, "
        f"{sum(len(v) for v in index.values())} piece-part rows")
    return index


def _build_generated_identity_map(
    rows: List[Dict[str, Any]],
) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    """Index generated piece-part rows by the merge identity key."""
    rows_by_identity: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for row_dict in rows:
        refdes_raw = row_dict.get("Failure Mode Causes", "")
        refdes = (
            canonicalize_refdes(str(refdes_raw)) if pd.notna(refdes_raw) else ""
        )
        fm_raw = row_dict.get("Failure Mode", "")
        failure_mode = (
            normalize_failure_mode_identity(fm_raw) if pd.notna(fm_raw) else ""
        )
        rows_by_identity.setdefault((refdes, failure_mode), []).append(row_dict)
    return rows_by_identity


def _issue_text(value: Any) -> str:
    """Render a generated identity field without exposing pandas NaN text."""
    return "" if _is_blank_value(value) else str(value)


def _remove_ambiguous_identities(
    template_rows: Dict[Tuple[str, str], List[int]],
    generated_rows: Dict[Tuple[str, str], List[Dict[str, Any]]],
    *,
    group_id: str,
    result: Any,
) -> None:
    """Remove non-1:1 duplicate keys and record every affected row."""
    ambiguous_keys = sorted(
        key
        for key in set(template_rows) | set(generated_rows)
        if len(template_rows.get(key, [])) > 1
        or len(generated_rows.get(key, [])) > 1
    )
    for refdes, failure_mode in ambiguous_keys:
        template_matches = template_rows.pop((refdes, failure_mode), [])
        generated_matches = generated_rows.pop((refdes, failure_mode), [])
        counts = (
            f"Identity matches {len(template_matches)} template row(s) and "
            f"{len(generated_matches)} generated row(s); pairing is not exactly 1:1."
        )
        for excel_row in template_matches:
            result.issue_rows.append({
                "ReasonCode": "AMBIGUOUS_IDENTITY",
                "Source": "Template",
                "Excel Row": excel_row,
                "Group ID": group_id,
                "RefDes": refdes,
                "Failure Mode": failure_mode,
                "Details": f"Template row left completely untouched. {counts}",
            })
        for row_dict in generated_matches:
            fmea_id = _issue_text(row_dict.get("FMEA-ID", ""))
            part_number = _issue_text(
                row_dict.get("Component Part Number", "")
            )
            result.issue_rows.append({
                "ReasonCode": "AMBIGUOUS_IDENTITY",
                "Source": "Generated",
                "Excel Row": None,
                "Group ID": group_id,
                "RefDes": refdes,
                "Failure Mode": failure_mode,
                "Details": (
                    f"Generated row was not inserted (FMEA-ID '{fmea_id}', "
                    f"part number '{part_number}'). {counts}"
                ),
            })


def _resolve_col_index(
    col_name: str,
    column_map: ColumnMap,
    extra_col_indices: Dict[str, int],
) -> Optional[int]:
    """Map a generator column name to a 1-based worksheet column index.

    Lookup order:
    1. ``column_map.canonical_map`` -> ``column_map.col_to_index``
    2. ``extra_col_indices`` (for columns appended by the writer)

    Returns ``None`` if the column is not mapped anywhere.
    """
    # Check canonical map first
    canonical = column_map.canonical_map.get(col_name)
    if canonical and canonical in column_map.col_to_index:
        return column_map.col_to_index[canonical]

    # Check extra (appended) columns
    if col_name in extra_col_indices:
        return extra_col_indices[col_name]

    return None


def _append_extra_columns(
    ws: Worksheet,
    column_map: ColumnMap,
    header_row: int,
    failure_modes_standard: str = "FMD-2016",
) -> Dict[str, int]:
    """Append generator-specific columns that do not exist in the template.

    Walks `output_headers_for(failure_modes_standard)` and writes any
    unmapped header at the first available column after the current max.
    Applies a minimal bold style so the header is visually distinguishable.

    Phase D: must be parametrized by FMD standard so that picking FMD-91
    appends `FMD-91 Commodity Type 1/2` rather than the module-default
    FMD-2016 headers. Without this, preserve-formatting runs with
    FMD-91 would silently drop the FMD commodity columns because the
    column-index resolver would look for headers that were never written.

    Returns:
        ``{col_name: 1_based_index}`` for every appended column.
    """
    from openpyxl.styles import Font

    existing_canonical = set(column_map.canonical_map.keys())
    existing_originals = set(column_map.col_to_index.keys())
    next_col = ws.max_column + 1
    appended: Dict[str, int] = {}

    target_headers = output_headers_for(failure_modes_standard)

    for col_name in target_headers:
        if col_name == ROW_TYPE_COL:
            continue
        # Already present in the template
        if col_name in existing_canonical or col_name in existing_originals:
            continue
        # Also skip if canonical_map maps this name already
        if column_map.canonical_map.get(col_name) in existing_originals:
            continue

        cell = ws.cell(row=header_row, column=next_col)
        cell.value = col_name
        cell.font = Font(bold=True)
        appended[col_name] = next_col
        next_col += 1

    # Always ensure a Diagnostic column exists
    if _DIAGNOSTIC_COL not in appended and _DIAGNOSTIC_COL not in existing_canonical:
        if not column_map.canonical_map.get(_DIAGNOSTIC_COL):
            cell = ws.cell(row=header_row, column=next_col)
            cell.value = _DIAGNOSTIC_COL
            cell.font = Font(bold=True)
            appended[_DIAGNOSTIC_COL] = next_col

    return appended


def _merge_group_piece_parts(
    ws: Worksheet,
    group: FunctionGroup,
    gen_pp_rows: List[Dict[str, Any]],
    column_map: ColumnMap,
    extra_col_indices: Dict[str, int],
    log_func: Optional[Callable[[str], None]] = None,
    flag_missing_template_rows: bool = True,
) -> GroupMergeResult:
    """Merge generated piece-part rows into a single template function group.

    Algorithm:
    1. Build match index from template PP rows using (canon_refdes, norm_fm).
    2. Match generated rows to template rows.
    3. Update matched rows in-place (preserving format).
    4. Flag unmatched template rows ("NOT IN BOM - Review").
    5. Insert brand-new rows below the group's PP region.

    Returns:
        :class:`GroupMergeResult` summarising the merge outcome.
    """
    log = log_func or _noop_log
    result = GroupMergeResult(group_id=group.group_id)

    # ------------------------------------------------------------------
    # 1. BUILD MATCH INDEX from template piece-part rows
    # ------------------------------------------------------------------
    # pp_index is already Dict[(canon_refdes, norm_fm) -> [row_numbers]]
    # from the analyzer, so we can use it directly.
    template_rows: Dict[Tuple[str, str], List[int]] = dict(group.pp_index)

    # Build match index from generated piece-part rows
    # Use list-of-dicts to preserve ALL rows for duplicate (RefDes, FM) keys
    # (e.g., dual op-amps with same RefDes in different circuit blocks).
    gen_rows_map = _build_generated_identity_map(gen_pp_rows)

    # A duplicate identity on either side is unsafe to pair positionally.
    # Remove the entire key before matching so template rows are untouched
    # and generated rows cannot fall through to the insertion path.
    _remove_ambiguous_identities(
        template_rows,
        gen_rows_map,
        group_id=group.group_id,
        result=result,
    )

    # ------------------------------------------------------------------
    # 2. MATCH template rows to generated rows
    # ------------------------------------------------------------------
    matched: List[Tuple[int, Dict[str, Any]]] = []
    missing: List[int] = []

    for key, excel_rows in template_rows.items():
        gen_list = gen_rows_map.pop(key, [])
        if not gen_list and not flag_missing_template_rows:
            continue
        # Pair template rows 1:1 with generated rows
        for i, excel_row in enumerate(excel_rows):
            if i < len(gen_list):
                matched.append((excel_row, gen_list[i]))
            else:
                missing.append(excel_row)
        # Excess generated rows (more generated than template) become new rows
        gen_rows_map.setdefault(key, []).extend(gen_list[len(excel_rows):])

    new_rows = [row for rows in gen_rows_map.values() for row in rows]

    # ------------------------------------------------------------------
    # 3. UPDATE MATCHED — no row position changes
    # ------------------------------------------------------------------
    refdes_col = _resolve_col_index(
        "Failure Mode Causes", column_map, extra_col_indices
    )
    fmea_id_col = _resolve_col_index("FMEA-ID", column_map, extra_col_indices)
    for excel_row, gen_dict in matched:
        row_refdes = (
            ws.cell(row=excel_row, column=refdes_col).value if refdes_col else ""
        )
        row_fmea_id = (
            ws.cell(row=excel_row, column=fmea_id_col).value if fmea_id_col else ""
        )
        for col_name, value in gen_dict.items():
            if col_name == ROW_TYPE_COL:
                continue
            col_idx = _resolve_col_index(col_name, column_map, extra_col_indices)
            if col_idx:
                update = _update_cell_preserving_format(
                    ws, excel_row, col_idx, value
                )
                if update.status == "blank_skipped":
                    result.blanks_skipped[col_name] = (
                        result.blanks_skipped.get(col_name, 0) + 1
                    )
                elif update.status == "changed":
                    result.merge_changes.append(MergeChange(
                        excel_row=excel_row,
                        refdes=str(row_refdes or ""),
                        fmea_id=str(row_fmea_id or ""),
                        column=col_name,
                        previous_value=update.previous_value,
                        new_value=update.new_value,
                    ))
    result.pp_updated = len(matched)

    # ------------------------------------------------------------------
    # 4. FLAG MISSING — template rows not in generated data
    # ------------------------------------------------------------------
    diag_col = (extra_col_indices.get(_DIAGNOSTIC_COL)
                or _resolve_col_index(_DIAGNOSTIC_COL, column_map, extra_col_indices))
    for excel_row in missing:
        if diag_col:
            ws.cell(row=excel_row, column=diag_col).value = "NOT IN BOM - Review"
    result.pp_flagged = len(missing)

    # ------------------------------------------------------------------
    # 5. INSERT NEW ROWS
    # ------------------------------------------------------------------
    if new_rows:
        if group.pp_end_row > 0:
            insert_at = group.pp_end_row + 1
        else:
            insert_at = group.cb_end_row + 1

        result.not_rebased_features.update(
            _detect_not_rebased_features(ws, insert_at)
        )
        rebased_merges = _prepare_merged_ranges_for_insert(
            ws, insert_at, len(new_rows)
        )
        ws.insert_rows(insert_at, amount=len(new_rows))
        _move_row_dimensions_for_insert(ws, insert_at, len(new_rows))
        for merged_coordinate in rebased_merges:
            ws.merge_cells(merged_coordinate)

        for offset, row_dict in enumerate(new_rows):
            target_row = insert_at + offset

            # Clone style from prototype
            if group.pp_style:
                for col in range(1, ws.max_column + 1):
                    _apply_cell_style(
                        ws.cell(row=target_row, column=col), group.pp_style
                    )

            # Write data
            for col_name, value in row_dict.items():
                if col_name == ROW_TYPE_COL:
                    continue
                col_idx = _resolve_col_index(col_name, column_map, extra_col_indices)
                if col_idx:
                    _update_cell_preserving_format(ws, target_row, col_idx, value)

            # Mark as new in diagnostic column
            if diag_col:
                ws.cell(row=target_row, column=diag_col).value = (
                    "NEW - Added by generator"
                )

        result.pp_inserted = len(new_rows)
        result.insert_at = insert_at

    if missing:
        result.issues.append(
            f"{len(missing)} template row(s) not found in generated data"
        )
    if new_rows:
        result.issues.append(
            f"{len(new_rows)} new row(s) inserted"
        )

    log(f"Group '{group.group_id}': "
        f"updated={result.pp_updated}, inserted={result.pp_inserted}, "
        f"flagged={result.pp_flagged}")
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_template_preserved(
    wb,
    template_map: TemplateMap,
    generated_df: pd.DataFrame,
    processor,
    output_path: str,
    cancel_token: Optional[CancellationToken] = None,
    log_func: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[float], None]] = None,
    failure_modes_standard: str = "FMD-2016",
) -> TemplateWriteResult:
    """Merge generated FMEA data into a template workbook and save.

    This is the main entry point for Phase 2 template preservation.

    Parameters
    ----------
    wb : openpyxl.Workbook
        The opened template workbook (may have ``keep_vba=True`` for .xlsm).
    template_map : TemplateMap
        Structural map produced by the Phase 1 analyzer.
    generated_df : pd.DataFrame
        The full generator output DataFrame (includes ``_row_type``).
    processor : FMEAProcessor
        The generator processor instance (used for summary data).
    output_path : str
        Destination file path.
    cancel_token : CancellationToken, optional
        Cooperative cancellation token.
    log_func : callable, optional
        GUI log callback ``(str) -> None``.
    progress_callback : callable, optional
        Progress callback ``(float) -> None``; values 0.0 – 1.0.

    Returns
    -------
    TemplateWriteResult
        Summary of everything the writer did.

    Raises
    ------
    CancellationError
        If the user cancels via *cancel_token*.
    FileAccessError
        If the workbook cannot be saved.
    ProcessingError
        If the FMEA sheet is missing or other structural errors occur.
    """
    log = log_func or _noop_log
    cancel = cancel_token or CancellationToken()
    result = TemplateWriteResult(
        output_path=output_path,
        issue_rows=[
            dict(issue) for issue in template_map.column_map.analysis_issue_rows
        ],
    )

    # ------------------------------------------------------------------
    # 1. Get the FMEA worksheet
    # ------------------------------------------------------------------
    if template_map.fmea_sheet_name not in wb.sheetnames:
        raise ProcessingError(
            f"FMEA sheet '{template_map.fmea_sheet_name}' not found in workbook",
            context="template_write",
        )
    ws = wb[template_map.fmea_sheet_name]

    log(f"Writing to sheet '{template_map.fmea_sheet_name}' "
        f"({template_map.total_data_rows} template data rows)")

    # ------------------------------------------------------------------
    # 2. Append generator-specific columns (Phase D: FMD-standard-aware)
    # ------------------------------------------------------------------
    extra_col_indices = _append_extra_columns(
        ws, template_map.column_map, template_map.column_map.header_row,
        failure_modes_standard=failure_modes_standard,
    )
    result.extra_cols_appended = list(extra_col_indices.keys())
    if extra_col_indices:
        log(f"Appended {len(extra_col_indices)} extra column(s) "
            f"({failure_modes_standard}): {', '.join(extra_col_indices.keys())}")

    # ------------------------------------------------------------------
    # 3. Build generated data index
    # ------------------------------------------------------------------
    cancel.check()
    gen_index = _build_generated_index(generated_df, log_func=log)
    total_generated_groups = len(gen_index)

    # ------------------------------------------------------------------
    # 4. Sort groups by cb_start_row DESCENDING (bottom-to-top)
    #    so that row insertions don't shift unprocessed groups.
    # ------------------------------------------------------------------
    sorted_groups = sorted(
        template_map.groups,
        key=lambda g: g.cb_start_row,
        reverse=True,
    )

    total_groups = len(sorted_groups)
    log(f"Processing {total_groups} template group(s) bottom-to-top")

    # ------------------------------------------------------------------
    # 5. Merge each group
    # ------------------------------------------------------------------
    row_counter = 0
    for g_idx, group in enumerate(sorted_groups):
        cancel.check()

        # Consume matched groups so only truly new groups remain for the
        # append-at-end pass.
        gen_pp_rows = gen_index.pop(group.group_id, [])
        has_template_duplicates = any(
            len(excel_rows) > 1 for excel_rows in group.pp_index.values()
        )

        if gen_pp_rows or has_template_duplicates:
            merge_result = _merge_group_piece_parts(
                ws, group, gen_pp_rows,
                template_map.column_map, extra_col_indices,
                log_func=log,
                flag_missing_template_rows=bool(gen_pp_rows),
            )
            if gen_pp_rows:
                result.groups_matched += 1
            else:
                result.groups_unmatched += 1
            result.pp_rows_updated += merge_result.pp_updated
            result.pp_rows_inserted += merge_result.pp_inserted
            result.pp_rows_flagged += merge_result.pp_flagged
            if merge_result.insert_at:
                for change in result.merge_changes:
                    if change.excel_row >= merge_result.insert_at:
                        change.excel_row += merge_result.pp_inserted
                for issue in result.issue_rows:
                    excel_row = issue.get("Excel Row")
                    if (
                        isinstance(excel_row, int)
                        and excel_row >= merge_result.insert_at
                    ):
                        issue["Excel Row"] = excel_row + merge_result.pp_inserted
            for column, count in merge_result.blanks_skipped.items():
                result.blanks_skipped[column] = (
                    result.blanks_skipped.get(column, 0) + count
                )
            result.merge_changes.extend(merge_result.merge_changes)
            result.issue_rows.extend(merge_result.issue_rows)
            result.issues.extend(merge_result.issues)
            result.not_rebased_features.update(
                merge_result.not_rebased_features
            )
        else:
            result.groups_unmatched += 1
            log(f"Unmatched group kept as-is: {group.group_id}")

        row_counter += 1
        if row_counter % _GIL_YIELD_INTERVAL == 0:
            time.sleep(0)  # Yield GIL so UI thread can repaint

        if progress_callback and total_groups > 0:
            progress_callback((g_idx + 1) / (total_groups + total_generated_groups + 1))

    # ------------------------------------------------------------------
    # 6. Append remaining generated groups (not in template)
    # ------------------------------------------------------------------
    if gen_index:
        log(f"Appending {len(gen_index)} new group(s) not found in template")
        # Find last data row in the sheet
        append_row = ws.max_row + 2  # leave a blank row before new groups

        for group_id, pp_rows in gen_index.items():
            cancel.check()

            generated_rows = _build_generated_identity_map(pp_rows)
            _remove_ambiguous_identities(
                {}, generated_rows, group_id=group_id, result=result
            )
            pp_rows = [
                row for rows in generated_rows.values() for row in rows
            ]
            if not pp_rows:
                log(
                    f"Skipped new group '{group_id}': all generated rows "
                    "had ambiguous identities"
                )
                continue

            # Write a circuit-block header row for the new group
            # Find the first circuit_block row in generated_df for this group
            cb_row_dict = _find_circuit_block_row(generated_df, group_id)
            if cb_row_dict:
                for col_name, value in cb_row_dict.items():
                    if col_name == ROW_TYPE_COL:
                        continue
                    col_idx = _resolve_col_index(
                        col_name, template_map.column_map, extra_col_indices
                    )
                    if col_idx:
                        _write_plain_cell(ws.cell(row=append_row, column=col_idx), value)
                append_row += 1

            # Write piece-part rows
            for offset, row_dict in enumerate(pp_rows):
                target_row = append_row + offset
                for col_name, value in row_dict.items():
                    if col_name == ROW_TYPE_COL:
                        continue
                    col_idx = _resolve_col_index(
                        col_name, template_map.column_map, extra_col_indices
                    )
                    if col_idx:
                        _write_plain_cell(ws.cell(row=target_row, column=col_idx), value)

                # Mark as new
                diag_col = (extra_col_indices.get(_DIAGNOSTIC_COL)
                            or _resolve_col_index(
                                _DIAGNOSTIC_COL, template_map.column_map,
                                extra_col_indices))
                if diag_col:
                    ws.cell(row=target_row, column=diag_col).value = (
                        "NEW - Added by generator"
                    )

                if (offset + 1) % _CANCEL_CHECK_INTERVAL == 0:
                    cancel.check()
                if (offset + 1) % _GIL_YIELD_INTERVAL == 0:
                    time.sleep(0)

            append_row += len(pp_rows) + 1  # +1 for spacing
            result.groups_new += 1

    if result.not_rebased_features:
        ordered_features = [
            feature
            for feature in _NOT_REBASED_FEATURE_ORDER
            if feature in result.not_rebased_features
        ]
        feature_list = ", ".join(ordered_features)
        details = (
            "Rows were inserted without rebasing these workbook features: "
            f"{feature_list}. Review them in the merged output."
        )
        result.issue_rows.append({
            "ReasonCode": "NOT_REBASED_FEATURES",
            "Source": "Template",
            "Excel Row": None,
            "Group ID": "",
            "RefDes": "",
            "Failure Mode": "",
            "Details": details,
        })
        log(f"Template merge WARNING: NOT_REBASED_FEATURES: {details}")

    # ------------------------------------------------------------------
    # 7. Write summary sheets (matching existing write_excel_report pattern)
    # ------------------------------------------------------------------
    _write_summary_sheets(
        wb,
        processor,
        result,
        log,
        protected_sheet_name=template_map.fmea_sheet_name,
    )

    # ------------------------------------------------------------------
    # 8. Save workbook
    # ------------------------------------------------------------------
    cancel.check()
    try:
        wb.save(output_path)
        log(f"Saved workbook to {output_path}")
    except PermissionError as exc:
        raise FileAccessError(
            f"Cannot save workbook — file may be open in another application: {exc}",
            file_path=output_path,
            operation="write",
        ) from exc
    except (InterruptedError, CancellationError):
        raise
    except Exception as exc:
        raise FileAccessError(
            f"Failed to save workbook: {exc}",
            file_path=output_path,
            operation="write",
        ) from exc

    if progress_callback:
        progress_callback(1.0)

    log(f"Template write complete: "
        f"matched={result.groups_matched}, "
        f"unmatched={result.groups_unmatched}, "
        f"new={result.groups_new}, "
        f"rows updated={result.pp_rows_updated}, "
        f"inserted={result.pp_rows_inserted}, "
        f"flagged={result.pp_rows_flagged}")

    return result


def _find_circuit_block_row(
    df: pd.DataFrame, group_id: str
) -> Optional[Dict[str, Any]]:
    """Find the circuit-block row dict in *df* that matches *group_id*."""
    for _, row_series in df.iterrows():
        row_dict = row_series.to_dict()
        if row_dict.get(ROW_TYPE_COL) != "circuit_block":
            continue
        raw_id = row_dict.get("FMEA-ID", "")
        if pd.notna(raw_id):
            fid = normalize_func_base_id(str(raw_id).strip())
            if fid == group_id:
                return row_dict
    return None


def _generated_sheet_name(base_name: str, index: int = 1) -> str:
    """Build a capped generated-sheet alias using the shared sanitizer."""
    from bom_compare.bom_compare_logic import sanitize_sheet_name

    suffix = " (Generated)" if index == 1 else f" (Generated {index})"
    safe_base = sanitize_sheet_name(base_name, max_len=31 - len(suffix))
    return f"{safe_base}{suffix}"


def _find_sheet_name(wb, candidate: str) -> Optional[str]:
    """Find an existing title using Excel's case-insensitive semantics."""
    candidate_key = candidate.casefold()
    return next(
        (name for name in wb.sheetnames if name.casefold() == candidate_key),
        None,
    )


def _is_tool_owned_sheet(wb, sheet_name: str) -> bool:
    value = wb[sheet_name].cell(row=1, column=1).value
    return isinstance(value, str) and value.startswith(TOOL_SHEET_MARKER)


def _is_protected_sheet(sheet_name: str, protected_sheet_name: str) -> bool:
    return sheet_name.casefold() == protected_sheet_name.casefold()


def _preclean_owned_diagnostic_sheets(
    wb,
    protected_sheet_name: str,
) -> None:
    """Remove only known, marker-owned diagnostics from a previous run."""
    known_titles = {
        title.casefold()
        for base_name in _KNOWN_DIAGNOSTIC_SHEET_NAMES
        for title in (
            base_name,
            *(_generated_sheet_name(base_name, index) for index in range(1, 100)),
        )
    }
    for sheet_name in list(wb.sheetnames):
        if (
            sheet_name.casefold() in known_titles
            and not _is_protected_sheet(sheet_name, protected_sheet_name)
            and _is_tool_owned_sheet(wb, sheet_name)
        ):
            del wb[sheet_name]


def _resolve_tool_sheet_name(
    wb,
    requested_name: str,
    result: TemplateWriteResult,
    log_func: Callable[[str], None],
    protected_sheet_name: str,
) -> str:
    """Resolve a diagnostic title without ever deleting a user-owned sheet."""
    existing_name = _find_sheet_name(wb, requested_name)
    if existing_name is None:
        return requested_name
    if (
        not _is_protected_sheet(existing_name, protected_sheet_name)
        and _is_tool_owned_sheet(wb, existing_name)
    ):
        del wb[existing_name]
        return requested_name

    generated_name = ""
    for index in range(1, 100):
        candidate = _generated_sheet_name(requested_name, index)
        existing_candidate = _find_sheet_name(wb, candidate)
        if existing_candidate is None:
            generated_name = candidate
            break
        if (
            not _is_protected_sheet(existing_candidate, protected_sheet_name)
            and _is_tool_owned_sheet(wb, existing_candidate)
        ):
            del wb[existing_candidate]
            generated_name = candidate
            break
    if not generated_name:
        raise ProcessingError(
            f"Could not create a generated sheet name for '{requested_name}' "
            "without replacing an existing user sheet.",
            context="template_write",
        )

    detail = (
        f"Preserved user-owned sheet '{existing_name}'; wrote generated "
        f"diagnostics to '{generated_name}'."
    )
    log_func(f"Template merge WARNING: {detail}")
    result.issue_rows.append({
        "ReasonCode": "SHEET_NAME_CONFLICT",
        "Source": "Workbook",
        "Excel Row": None,
        "Group ID": "",
        "RefDes": "",
        "Failure Mode": "",
        "Details": detail,
    })
    return generated_name


def _write_summary_sheets(wb, processor, result: TemplateWriteResult,
                          log_func: Callable[[str], None], *,
                          protected_sheet_name: str) -> None:
    """Add diagnostic summary sheets to the workbook.

    Mirrors the pattern in ``write_excel_report`` — adds sheets only when
    there is data to report.
    """
    from openpyxl.styles import Font

    _preclean_owned_diagnostic_sheets(wb, protected_sheet_name)

    # Template merge summary. The last two rows are a legend for the values
    # the writer puts in the Diagnostic column — without them the flags read
    # as bare tokens in the merged workbook.
    summary_data = [
        ("Groups matched", result.groups_matched),
        ("Groups unmatched (kept as-is)", result.groups_unmatched),
        ("Groups new (appended)", result.groups_new),
        ("Piece-part rows updated", result.pp_rows_updated),
        ("Piece-part rows inserted", result.pp_rows_inserted),
        ("Piece-part rows flagged 'NOT IN BOM - Review'", result.pp_rows_flagged),
        ("Extra columns appended", ", ".join(result.extra_cols_appended) or "None"),
    ]
    summary_data.extend(
        (f"Blank generated values skipped: {column}", count)
        for column, count in sorted(result.blanks_skipped.items())
    )
    summary_data.extend([
        (
            "Diagnostic flag 'NOT IN BOM - Review'",
            "This template row has no matching generated piece-part row — its "
            "RefDes is absent from the current BOM. Verify the component and "
            "either update the BOM or remove the stale row.",
        ),
        (
            "Diagnostic flag 'NEW - Added by generator'",
            "This row was inserted by the generator for a RefDes present in "
            "the BOM/grouping data but missing from the template workbook.",
        ),
    ])

    sheet_name = _resolve_tool_sheet_name(
        wb, "Template_Merge_Summary", result, log_func, protected_sheet_name
    )
    ws_summary = wb.create_sheet(sheet_name)
    ws_summary.cell(row=1, column=1, value="Metric").font = Font(bold=True)
    ws_summary.cell(row=1, column=2, value="Value").font = Font(bold=True)
    for row_idx, (metric, value) in enumerate(summary_data, start=2):
        ws_summary.cell(row=row_idx, column=1, value=metric)
        ws_summary.cell(row=row_idx, column=2, value=value)
    prepend_tool_sheet_banner(
        ws_summary,
        f"{TOOL_SHEET_MARKER} - Summary of preserve-formatting merge activity "
        "and diagnostic flags.",
        2,
    )

    if result.merge_changes:
        changes_name = _resolve_tool_sheet_name(
            wb, "Merge Changes", result, log_func, protected_sheet_name
        )
        ws_changes = wb.create_sheet(changes_name)
        banner = (
            f"{TOOL_SHEET_MARKER} - non-blank generated values "
            "that replaced existing workbook values."
        )
        ws_changes.cell(row=1, column=1, value=banner).font = Font(bold=True)
        ws_changes.merge_cells(start_row=1, start_column=1, end_row=1, end_column=6)
        headers = [
            "Excel Row",
            "RefDes",
            "FMEA-ID",
            "Column",
            "Previous Value",
            "New Value",
        ]
        for col_idx, header in enumerate(headers, start=1):
            ws_changes.cell(row=2, column=col_idx, value=header).font = Font(bold=True)
        for row_idx, change in enumerate(
            sorted(result.merge_changes, key=lambda item: (item.excel_row, item.column)),
            start=3,
        ):
            values = [
                change.excel_row,
                change.refdes,
                change.fmea_id,
                change.column,
                change.previous_value,
                change.new_value,
            ]
            for col_idx, value in enumerate(values, start=1):
                cell = ws_changes.cell(row=row_idx, column=col_idx)
                _write_plain_cell(cell, value)
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    cell.data_type = "s"
        ws_changes.freeze_panes = "A3"

    # Processor sheets can add SHEET_NAME_CONFLICT rows, so render them
    # before the issues sheet and render issues last.
    _write_processor_summaries(
        wb, processor, result, log_func, protected_sheet_name
    )

    # Issues sheet (if any). Structured issue rows carry stable reason codes;
    # legacy merge notes remain visible in the Details column.
    if result.issues or result.issue_rows:
        issues_name = _resolve_tool_sheet_name(
            wb, "Template_Merge_Issues", result, log_func, protected_sheet_name
        )
        ws_issues = wb.create_sheet(issues_name)
        for col_idx, header in enumerate(_ISSUE_HEADERS, start=1):
            ws_issues.cell(row=1, column=col_idx, value=header).font = Font(bold=True)
        issue_rows = [
            {
                "ReasonCode": "",
                "Source": "Merge",
                "Excel Row": None,
                "Group ID": "",
                "RefDes": "",
                "Failure Mode": "",
                "Details": issue,
            }
            for issue in result.issues
        ] + result.issue_rows
        for row_idx, issue in enumerate(issue_rows, start=2):
            for col_idx, header in enumerate(_ISSUE_HEADERS, start=1):
                _write_plain_cell(
                    ws_issues.cell(row=row_idx, column=col_idx),
                    issue.get(header),
                )
        prepend_tool_sheet_banner(
            ws_issues,
            f"{TOOL_SHEET_MARKER} - Rows and workbook conditions requiring review.",
            len(_ISSUE_HEADERS),
        )


def _write_processor_summaries(
    wb,
    processor,
    result: TemplateWriteResult,
    log_func: Callable[[str], None],
    protected_sheet_name: str,
) -> None:
    """Write the processor diagnostic sheets to the workbook.

    Consumes ``build_summary_frames`` — the single source of truth shared
    with ``write_excel_report`` — so the preserve-formatting path emits the
    SAME diagnostic sheets as the new-workbook path (Validation_Warnings,
    FMEA Gen New RefDes, Part Usage Diagnostics, and the five legacy
    sheets). These sheets were silently dropped in preserve mode before.
    """
    from openpyxl.styles import Font

    frames = build_summary_frames(processor)

    written = 0
    for requested_name, frame in frames.items():
        if frame.empty:
            continue
        sheet_name = _resolve_tool_sheet_name(
            wb, requested_name, result, log_func, protected_sheet_name
        )
        ws = wb.create_sheet(sheet_name)
        for col_idx, header in enumerate(frame.columns, start=1):
            ws.cell(row=1, column=col_idx, value=str(header)).font = Font(bold=True)
        for row_idx, row_values in enumerate(frame.itertuples(index=False), start=2):
            for col_idx, val in enumerate(row_values, start=1):
                cell = ws.cell(row=row_idx, column=col_idx)
                if isinstance(val, str):
                    cell.value = sanitize_for_excel(val)
                elif pd.isna(val):
                    cell.value = None
                else:
                    cell.value = val
        # Same explanation banners the new-workbook writer prepends.
        banner = SUMMARY_SHEET_BANNERS.get(requested_name)
        if banner and len(frame.columns) > 0:
            prepend_tool_sheet_banner(ws, banner, len(frame.columns))
        written += 1

    if written:
        log_func(f"Wrote {written} processor summary sheet(s)")


def build_template_output_path(
    original_path: str, mode: str = "Generated", output_directory=None
) -> str:
    """Auto-suffix an output path: ``FMEA_v3.xlsx`` -> ``FMEA_v3_Generated_20260325.xlsx``.

    Parameters
    ----------
    original_path : str
        The original template file path.
    mode : str
        A label to include in the suffix (default ``"Generated"``).
    output_directory : str | os.PathLike | None
        Directory to write the suffixed file into. When provided, it overrides
        the template's own folder — Tier-2 #18: preserve-formatting mode must
        honor the user's chosen output folder instead of silently landing the
        merged workbook next to the template. When ``None`` the file stays in
        the template's parent (the historical default, which is also what the
        FMEA resolver falls back to via the target workbook).

    Returns
    -------
    str
        The suffixed output path, preserving the original extension.
    """
    p = Path(original_path)
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    new_name = f"{p.stem}_{mode}_{date_str}{p.suffix}"
    parent = Path(output_directory) if output_directory else p.parent
    return str(parent / new_name)
