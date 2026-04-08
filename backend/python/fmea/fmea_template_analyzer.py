#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# Originally copied from src/apps/fmea_generator/fmea_template_analyzer.py.
# Freeze lifted 2026-04-08; this is now the maintained copy for the Tauri suite.
# ============================================================================
"""
FMEA Template Analyzer — Structural analysis of existing FMEA workbooks.

Loads an FMEA workbook via openpyxl, detects its structure (header row,
column mapping, function groups, row classifications), and returns a
TemplateMap that the template writer uses to merge generated data while
preserving the original formatting.
"""
from copy import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from openpyxl import load_workbook
from openpyxl.workbook import Workbook

from common import (
    detect_column,
    get_synonyms,
    get_tool_logger,
    try_read_table,
    CancellationError,
)
from common.refdes_utils import canonicalize_refdes
from common.fmea_utils import classify_fmea_rows, RowClassification
from fmea.fmea_generator_logic import (
    normalize_func_base_id,
    OUTPUT_HEADERS,
    output_headers_for,
)

_logger = get_tool_logger("fmea_template_analyzer")

# How often to check cancellation during row iteration
_CANCEL_CHECK_INTERVAL = 50

# Keys used for FMEA-related header scanning
_FMEA_SCAN_SYNONYM_KEYS = [
    'fmea_id', 'failure_mode', 'ref_des', 'part_usage',
    'fmr_strict', 'local_effect', 'part_number',
]

# Mapping from stable (FMD-standard-independent) OUTPUT_HEADERS names
# to synonym keys for column detection. Each entry is
# (output_header_name, synonym_key). The FMD commodity entries are
# keyed by stable names; the actual header text (FMD-91 vs FMD-2016)
# is built dynamically by `_build_output_header_synonym_map()` below.
_BASE_HEADER_SYNONYM_MAP: Dict[str, str] = {
    'FMEA-ID': 'fmea_id',
    'Function Description': 'function_description',
    'FMEA Level': 'circuit_block',
    'Failure Mode Causes': 'fmea_refdes',
    'Component Part Number': 'part_number',
    'Component Part Description': 'description',
    'Failure Mode': 'failure_mode',
    'Failure Mode Ratio': 'fmr_strict',
    'Part Usage': 'part_usage',
    'Local Effect': 'local_effect',
    'Next Higher Effect': 'next_higher_effect',
    'End Effect': 'end_effect',
    'Schematic Page': 'schematic_page',
    'BAE HDA Commodity I': 'commodity_level1',
    'BAE HDA Commodity II': 'commodity_level2',
}


def _build_output_header_synonym_map(standard: str) -> Dict[str, str]:
    """Build the full OUTPUT_HEADER → synonym-key map for a chosen FMD standard.

    Phase D: the FMD commodity columns are parametrized by failure modes
    standard (FMD-91 vs FMD-2016), so the synonym map must be built per-run
    rather than frozen at module load. The stable (non-FMD) entries come
    from _BASE_HEADER_SYNONYM_MAP; the FMD entries are synthesized from
    the standard string.
    """
    result: Dict[str, str] = dict(_BASE_HEADER_SYNONYM_MAP)
    result[f'{standard} Commodity Type 1'] = 'fmd_type1'
    result[f'{standard} Commodity Type 2'] = 'fmd_type2'
    return result


# Module-level default (FMD-2016) — kept for backwards compatibility with
# any legacy importer that expects the static map. New code should use
# `_build_output_header_synonym_map(standard)` instead.
_OUTPUT_HEADER_SYNONYM_MAP: Dict[str, str] = _build_output_header_synonym_map("FMD-2016")


# =============================================================================
# Data Structures
# =============================================================================

@dataclass(frozen=True)
class CellStyle:
    """Immutable snapshot of a cell's visual formatting."""
    font: Any       # openpyxl Font
    fill: Any       # openpyxl PatternFill
    alignment: Any  # openpyxl Alignment
    border: Any     # openpyxl Border
    number_format: str


@dataclass
class ColumnMap:
    """Mapping between original workbook columns and generator output columns."""
    original_headers: List[str]
    header_row: int                      # 1-based
    col_to_index: Dict[str, int]         # header_name -> 1-based col index
    canonical_map: Dict[str, str]        # OUTPUT_HEADER_name -> original_header_name
    extra_cols: List[str]                # OUTPUT_HEADERS not found in original


@dataclass
class FunctionGroup:
    """One function group with its circuit-block and piece-part row ranges."""
    group_id: str                        # Normalized (via normalize_func_base_id)
    group_id_raw: str                    # Original cell value
    cb_start_row: int                    # 1-based first circuit-block row
    cb_end_row: int                      # 1-based last circuit-block row
    pp_start_row: int                    # 1-based first piece-part row (0 if none)
    pp_end_row: int                      # 1-based last piece-part row (0 if none)
    pp_index: Dict[Tuple[str, str], List[int]] = field(default_factory=dict)
    cb_style: Optional[CellStyle] = None
    pp_style: Optional[CellStyle] = None


@dataclass
class TemplateMap:
    """Complete structural analysis of an FMEA workbook."""
    fmea_sheet_name: str
    column_map: ColumnMap
    groups: List[FunctionGroup]
    group_by_id: Dict[str, FunctionGroup]
    total_data_rows: int


# =============================================================================
# Style Capture
# =============================================================================

def capture_cell_style(cell) -> CellStyle:
    """Create immutable copy of a cell's visual formatting.

    Uses copy() from stdlib to snapshot each style attribute so that
    later modifications to the source cell do not affect the captured style.

    Args:
        cell: An openpyxl Cell object.

    Returns:
        A frozen CellStyle dataclass with copies of font, fill, alignment,
        border, and number_format.
    """
    return CellStyle(
        font=copy(cell.font),
        fill=copy(cell.fill),
        alignment=copy(cell.alignment),
        border=copy(cell.border),
        number_format=cell.number_format or "General",
    )


# =============================================================================
# Sheet Detection
# =============================================================================

def _detect_fmea_sheet(wb: Workbook, preferred_name: Optional[str] = None) -> str:
    """Detect the FMEA sheet in a workbook.

    Priority:
    1. User-specified name (exact match, case-insensitive)
    2. Sheet named "FMEA" or "FMECA" (case-insensitive)
    3. Sheet with the most FMEA-like headers
    4. First visible sheet

    Args:
        wb: An openpyxl Workbook.
        preferred_name: Optional user-specified sheet name.

    Returns:
        The name of the detected FMEA sheet.

    Raises:
        ValueError: If preferred_name is given but not found.
    """
    sheet_names = wb.sheetnames

    # Priority 1: user-specified name
    if preferred_name:
        names_lower = {n.lower(): n for n in sheet_names}
        if preferred_name.lower() in names_lower:
            return names_lower[preferred_name.lower()]
        from common import ValidationError
        raise ValidationError(
            f"Sheet '{preferred_name}' not found in workbook. "
            f"Available sheets: {sheet_names}"
        )

    # Priority 2: "FMEA" or "FMECA" (case-insensitive)
    for name in sheet_names:
        if name.upper() in ("FMEA", "FMECA"):
            return name

    # Priority 3: sheet with most FMEA-like headers
    # Build a combined synonym list for scanning
    all_fmea_synonyms = []
    for key in _FMEA_SCAN_SYNONYM_KEYS:
        all_fmea_synonyms.extend(get_synonyms(key))
    all_fmea_synonyms_lower = [s.lower() for s in all_fmea_synonyms]

    best_sheet = None
    best_score = 0
    for name in sheet_names:
        ws = wb[name]
        if ws.sheet_state == "hidden":
            continue
        # Scan first row for header matches
        score = 0
        for cell in ws[1]:
            if cell.value and str(cell.value).strip().lower() in all_fmea_synonyms_lower:
                score += 1
        if score > best_score:
            best_score = score
            best_sheet = name

    if best_sheet and best_score >= 2:
        return best_sheet

    # Priority 4: first visible sheet
    for name in sheet_names:
        ws = wb[name]
        if ws.sheet_state != "hidden":
            return name

    # Absolute fallback
    return sheet_names[0]


# =============================================================================
# Header Row Detection
# =============================================================================

def _detect_header_row(ws, max_scan: int = 10) -> int:
    """Detect the header row by finding the row with the most FMEA synonym matches.

    Scans the first N rows and scores each by counting cells that match
    known FMEA column synonyms.

    Args:
        ws: An openpyxl Worksheet.
        max_scan: Maximum number of rows to scan (default 10).

    Returns:
        1-based row number of the detected header row.
    """
    # Build combined synonym set for scoring
    all_synonyms_lower = set()
    for key in _FMEA_SCAN_SYNONYM_KEYS:
        for syn in get_synonyms(key):
            all_synonyms_lower.add(syn.lower())

    best_row = 1
    best_score = 0

    actual_max = min(max_scan, ws.max_row or 1)
    for row_num in range(1, actual_max + 1):
        score = 0
        for cell in ws[row_num]:
            if cell.value is not None:
                cell_text = str(cell.value).strip().lower()
                if cell_text in all_synonyms_lower:
                    score += 1
        if score > best_score:
            best_score = score
            best_row = row_num

    return best_row


# =============================================================================
# Column Mapping
# =============================================================================

def _build_column_map(
    ws,
    header_row: int,
    log_func: Optional[Any] = None,
    failure_modes_standard: str = "FMD-2016",
) -> ColumnMap:
    """Build a mapping between original workbook columns and OUTPUT_HEADERS.

    For each entry in `output_headers_for(failure_modes_standard)`, attempts
    to find a matching column in the original workbook headers:
    1. Exact match (case-insensitive)
    2. detect_column with appropriate synonyms

    Args:
        ws: An openpyxl Worksheet.
        header_row: 1-based row number containing headers.
        log_func: Optional logging callback.
        failure_modes_standard: "FMD-91" or "FMD-2016" — drives the FMD
            commodity column header names produced by the generator.

    Returns:
        A ColumnMap linking the selected-standard OUTPUT_HEADERS to
        original column names.
    """
    target_headers = output_headers_for(failure_modes_standard)
    synonym_map = _build_output_header_synonym_map(failure_modes_standard)

    # Read original headers from the worksheet
    original_headers = []
    col_to_index: Dict[str, int] = {}
    for cell in ws[header_row]:
        header_val = str(cell.value).strip() if cell.value is not None else ""
        original_headers.append(header_val)
        if header_val:
            col_to_index[header_val] = cell.column  # 1-based

    # Build case-insensitive lookup for exact matching
    headers_lower = {h.lower(): h for h in original_headers if h}

    canonical_map: Dict[str, str] = {}
    extra_cols: List[str] = []

    for output_header in target_headers:
        # Step 1: Exact case-insensitive match
        matched = headers_lower.get(output_header.lower())
        if matched:
            canonical_map[output_header] = matched
            continue

        # Step 2: detect_column with synonyms
        synonym_key = synonym_map.get(output_header)
        if synonym_key:
            try:
                synonyms = get_synonyms(synonym_key)
                found = detect_column(original_headers, synonyms, substring_match=True)
                if found:
                    canonical_map[output_header] = found
                    continue
            except KeyError:
                pass  # Unknown synonym key; fall through

        # Not found
        extra_cols.append(output_header)

    if log_func:
        mapped_count = len(canonical_map)
        total_count = len(target_headers)
        log_func(
            f"Column mapping ({failure_modes_standard}): {mapped_count}/{total_count} "
            f"output headers matched, {len(extra_cols)} unmapped"
        )
        if extra_cols:
            log_func(f"  Unmapped columns: {extra_cols}")

    return ColumnMap(
        original_headers=original_headers,
        header_row=header_row,
        col_to_index=col_to_index,
        canonical_map=canonical_map,
        extra_cols=extra_cols,
    )


# =============================================================================
# Function Group Building
# =============================================================================

def _build_function_groups(
    ws,
    classifications: List[RowClassification],
    column_map: ColumnMap,
    cancel_token=None,
    log_func: Optional[Any] = None,
) -> List[FunctionGroup]:
    """Build function groups from classified rows.

    Walks classified rows to identify circuit-block boundaries, piece-part
    ranges, and builds a lookup index for piece-part rows keyed by
    (canonicalized_refdes, normalized_failure_mode).

    Args:
        ws: An openpyxl Worksheet.
        classifications: List of RowClassification from classify_fmea_rows.
        column_map: The ColumnMap built from the worksheet.
        cancel_token: Optional CancellationToken for cooperative cancellation.
        log_func: Optional logging callback.

    Returns:
        List of FunctionGroup objects.
    """
    groups: List[FunctionGroup] = []
    current_group: Optional[FunctionGroup] = None

    # Resolve column indices for FMEA-ID, RefDes, and Failure Mode
    fmea_id_original = column_map.canonical_map.get('FMEA-ID')
    fmea_id_col_idx = column_map.col_to_index.get(fmea_id_original, 0) if fmea_id_original else 0

    refdes_original = column_map.canonical_map.get('Failure Mode Causes')
    refdes_col_idx = column_map.col_to_index.get(refdes_original, 0) if refdes_original else 0

    fm_original = column_map.canonical_map.get('Failure Mode')
    fm_col_idx = column_map.col_to_index.get(fm_original, 0) if fm_original else 0

    pp_row_count = 0

    for idx, clf in enumerate(classifications):
        # Cancellation check every _CANCEL_CHECK_INTERVAL rows
        if cancel_token and idx % _CANCEL_CHECK_INTERVAL == 0:
            cancel_token.check()

        row_num = clf.row_index  # 1-based Excel row

        if clf.row_type == 'circuit_block':
            # Finalize previous group
            if current_group is not None:
                groups.append(current_group)

            # Extract group_id from FMEA-ID column
            group_id_raw = ""
            if fmea_id_col_idx > 0:
                cell = ws.cell(row=row_num, column=fmea_id_col_idx)
                if cell.value is not None and pd.notna(cell.value):
                    group_id_raw = str(cell.value).strip()

            group_id = normalize_func_base_id(group_id_raw) if group_id_raw else ""

            # Capture CB style from first cell in this row
            cb_style = capture_cell_style(ws.cell(row=row_num, column=1))

            current_group = FunctionGroup(
                group_id=group_id,
                group_id_raw=group_id_raw,
                cb_start_row=row_num,
                cb_end_row=row_num,
                pp_start_row=0,
                pp_end_row=0,
                pp_index={},
                cb_style=cb_style,
                pp_style=None,
            )

        elif clf.row_type == 'piece_part':
            if current_group is None:
                # Piece-part before any circuit-block; skip
                continue

            # Update CB end row (CB rows can span multiple rows before PP starts)
            # and track PP range
            if current_group.pp_start_row == 0:
                current_group.pp_start_row = row_num
                # Capture PP style from first piece-part row
                current_group.pp_style = capture_cell_style(
                    ws.cell(row=row_num, column=1)
                )
            current_group.pp_end_row = row_num
            pp_row_count += 1

            # Build pp_index keyed by (canonicalized_refdes, normalized_failure_mode)
            refdes_val = ""
            if refdes_col_idx > 0:
                cell_val = ws.cell(row=row_num, column=refdes_col_idx).value
                if cell_val is not None and pd.notna(cell_val):
                    refdes_val = canonicalize_refdes(str(cell_val).strip())

            fm_val = ""
            if fm_col_idx > 0:
                cell_val = ws.cell(row=row_num, column=fm_col_idx).value
                if cell_val is not None and pd.notna(cell_val):
                    fm_val = str(cell_val).strip().upper()

            key = (refdes_val, fm_val)
            if key not in current_group.pp_index:
                current_group.pp_index[key] = []
            current_group.pp_index[key].append(row_num)

        else:
            # 'other' row — if inside a group, extend CB end row
            if current_group is not None and current_group.pp_start_row == 0:
                current_group.cb_end_row = row_num

    # Finalize last group
    if current_group is not None:
        groups.append(current_group)

    if log_func:
        log_func(
            f"Analyzing template: {len(groups)} groups found, "
            f"{pp_row_count} piece-part rows indexed"
        )

    return groups


# =============================================================================
# Main Entry Point
# =============================================================================

def analyze_template(
    workbook_path: str,
    sheet_name: Optional[str] = None,
    cancel_token=None,
    log_func: Optional[Any] = None,
    failure_modes_standard: str = "FMD-2016",
) -> Tuple[TemplateMap, Workbook]:
    """Analyze an existing FMEA workbook and return its structural map.

    This is the main entry point for template analysis. It:
    1. Loads the workbook via openpyxl (preserving formulas and VBA)
    2. Detects the FMEA sheet
    3. Detects the header row
    4. Builds the column mapping
    5. Reads data into a DataFrame for row classification
    6. Classifies rows as circuit-block / piece-part / other
    7. Builds function groups with row ranges and style prototypes

    Args:
        workbook_path: Path to the FMEA workbook (.xlsx or .xlsm).
        sheet_name: Optional user-specified sheet name.
        cancel_token: Optional CancellationToken for cooperative cancellation.
        log_func: Optional logging callback.

    Returns:
        Tuple of (TemplateMap, Workbook) where the Workbook is the loaded
        openpyxl workbook (caller owns it and must handle saving/closing).

    Raises:
        CancellationError: If cancel_token is triggered during analysis.
        FileAccessError: If the workbook cannot be loaded.
        ValidationError: If the specified sheet_name is not found.
    """
    _log = log_func or (lambda msg: None)

    _log(f"Loading workbook: {workbook_path}")

    # Determine load options based on file extension
    path_lower = str(workbook_path).lower()
    load_kwargs: Dict[str, Any] = {"data_only": False}
    if path_lower.endswith(".xlsm"):
        load_kwargs["keep_vba"] = True

    try:
        wb = load_workbook(workbook_path, **load_kwargs)
    except (InterruptedError, CancellationError):
        raise
    except Exception as exc:
        from common import FileAccessError
        raise FileAccessError(
            f"Cannot load workbook: {exc}",
            file_path=str(workbook_path),
            operation="read",
        ) from exc

    if cancel_token:
        cancel_token.check()

    # Step 2: Detect FMEA sheet
    fmea_sheet_name = _detect_fmea_sheet(wb, preferred_name=sheet_name)
    ws = wb[fmea_sheet_name]
    _log(f"FMEA sheet detected: '{fmea_sheet_name}'")

    if cancel_token:
        cancel_token.check()

    # Step 3: Detect header row
    header_row = _detect_header_row(ws)
    _log(f"Header row detected: row {header_row}")

    # Step 4: Build column map (Phase D: parametrized by FMD standard)
    column_map = _build_column_map(
        ws, header_row,
        log_func=_log,
        failure_modes_standard=failure_modes_standard,
    )

    if cancel_token:
        cancel_token.check()

    # Step 5: Read data into DataFrame for classification
    # try_read_table uses 0-based header_row, so subtract 1
    df = try_read_table(
        str(workbook_path),
        header_row=header_row - 1,
        sheet_name=fmea_sheet_name,
        log_func=_log,
    )
    _log(f"Read {len(df)} data rows from '{fmea_sheet_name}'")

    if cancel_token:
        cancel_token.check()

    # Step 6: Classify rows
    classifications, _level_col, _level_validated = classify_fmea_rows(
        df, log_func=_log, cancel_token=cancel_token,
    )

    # classify_fmea_rows assumes header at row 1 (row_index = idx + 2).
    # When the actual header is at row N, data starts at row N+1, so we
    # need to shift all row_index values by (header_row - 1).
    row_offset = header_row - 1
    if row_offset != 0:
        adjusted = []
        for clf in classifications:
            adjusted.append(RowClassification(
                row_index=clf.row_index + row_offset,
                row_type=clf.row_type,
                classification_source=clf.classification_source,
                fmea_level_value=clf.fmea_level_value,
            ))
        classifications = adjusted
        _log(f"Adjusted row indices by +{row_offset} for header at row {header_row}")

    if cancel_token:
        cancel_token.check()

    # Step 7: Build function groups
    groups = _build_function_groups(
        ws, classifications, column_map,
        cancel_token=cancel_token, log_func=_log,
    )

    # Build ID lookup — use first occurrence; warn on duplicates
    group_by_id: Dict[str, FunctionGroup] = {}
    for grp in groups:
        if grp.group_id:
            if grp.group_id in group_by_id:
                _log(f"WARNING: Duplicate normalized group ID '{grp.group_id}' "
                     f"(raw: '{grp.group_id_raw}' at row {grp.cb_start_row}, "
                     f"first seen at row {group_by_id[grp.group_id].cb_start_row}). "
                     f"Each instance will be processed independently.")
            else:
                group_by_id[grp.group_id] = grp

    total_data_rows = len(classifications)

    template_map = TemplateMap(
        fmea_sheet_name=fmea_sheet_name,
        column_map=column_map,
        groups=groups,
        group_by_id=group_by_id,
        total_data_rows=total_data_rows,
    )

    _log(
        f"Template analysis complete: {len(groups)} function groups, "
        f"{total_data_rows} data rows, "
        f"{len(column_map.canonical_map)} columns mapped"
    )

    return template_map, wb
