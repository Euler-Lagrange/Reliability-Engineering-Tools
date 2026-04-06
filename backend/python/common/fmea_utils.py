#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FMEA Detection and Classification Utilities

Shared utilities for detecting FMEA file structure, classifying rows as
circuit_block or piece_part, and detecting RefDes columns.

These utilities are used by both BOM Compare (FMEA coverage validation)
and FMEA Generator (Fill Gaps mode).
"""
import re
import numbers
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

try:
    from common.refdes_utils import split_refdes_list, canonicalize_refdes, get_prefix, is_known_prefix
    from common.column_synonyms import get_synonyms
    from common.logger import get_tool_logger
except ImportError:
    from refdes_utils import split_refdes_list, canonicalize_refdes, get_prefix, is_known_prefix
    from column_synonyms import get_synonyms
    from logger import get_tool_logger

_logger = get_tool_logger("fmea_utils")

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

# FMEA Level column synonyms - narrow to avoid false matches like "Part Type"
# NOTE: 'level' and 'type' alone are TOO BROAD - they match unrelated columns
FMEA_LEVEL_SYNONYMS = ['fmea level', 'fmea_level', 'fmea type', 'row type', 'record type']

# Row type keywords for classification (used in cell value matching)
# Full phrases (substring match is safe - these are explicit and unambiguous)
CIRCUIT_BLOCK_PHRASES = ['circuit block', 'function block', 'circuit group', 'function group']
PIECE_PART_PHRASES = ['piece-part', 'piece part', 'piecepart']

# Short forms require word-boundary matching to avoid false positives
# e.g., "CB" matches but "CBT Capacitor" does not; "PP" matches but "PPM" does not
CB_SHORT_PATTERN = re.compile(r'\b(cb|fb)\b', re.IGNORECASE)
PP_SHORT_PATTERN = re.compile(r'\bpp\b', re.IGNORECASE)

# Legacy keyword lists for backwards compatibility (used in detect_fmea_level_column value sampling)
CIRCUIT_BLOCK_KEYWORDS = CIRCUIT_BLOCK_PHRASES + ['cb', 'fb']
PIECE_PART_KEYWORDS = PIECE_PART_PHRASES + ['pp']

# Filename pattern to detect FMEA files
FMEA_FILENAME_PATTERN = re.compile(r'fmea|fmeca|piece.?part', re.IGNORECASE)


# -----------------------------------------------------------------------------
# Data Structures
# -----------------------------------------------------------------------------

@dataclass
class RowClassification:
    """Classification of a single row in an FMEA file.

    Attributes:
        row_index: 1-based Excel row index (header is row 1, data starts at row 2)
        row_type: One of 'circuit_block', 'piece_part', or 'other'
        classification_source: 'fmea_level_column' if detected via column, 'row_scan' if via cell scan
        fmea_level_value: Cell value if column-based detection, else matched cell text
    """
    row_index: int
    row_type: str  # 'circuit_block', 'piece_part', or 'other'
    classification_source: str  # 'fmea_level_column' or 'row_scan'
    fmea_level_value: Optional[str] = None


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def is_circuit_block_text(text: str) -> bool:
    """Check if text indicates circuit/function block row.

    Uses substring matching for explicit phrases and word-boundary regex for short forms.

    Examples:
        >>> is_circuit_block_text("Circuit Block")
        True
        >>> is_circuit_block_text("CB")
        True
        >>> is_circuit_block_text("CBT Capacitor")  # Word boundary prevents false match
        False
    """
    text_lower = text.lower()
    return (any(phrase in text_lower for phrase in CIRCUIT_BLOCK_PHRASES) or
            bool(CB_SHORT_PATTERN.search(text)))


def is_piece_part_text(text: str) -> bool:
    """Check if text indicates piece-part row.

    Uses substring matching for explicit phrases and word-boundary regex for short forms.

    Examples:
        >>> is_piece_part_text("Piece-Part")
        True
        >>> is_piece_part_text("PP")
        True
        >>> is_piece_part_text("PPM")  # Word boundary prevents false match
        False
    """
    text_lower = text.lower()
    return (any(phrase in text_lower for phrase in PIECE_PART_PHRASES) or
            bool(PP_SHORT_PATTERN.search(text)))


def is_fmea_file(filename: str) -> bool:
    """Check if filename indicates FMEA file.

    Triggers FMEA validation when filename contains FMEA, FMECA,
    piecepart, or piece-part (case-insensitive).

    Args:
        filename: Filename to check (can include path)

    Returns:
        True if filename matches FMEA pattern
    """
    import os
    if not filename:
        return False
    # Extract just the filename if path is included
    basename = os.path.basename(filename)
    return bool(FMEA_FILENAME_PATTERN.search(basename))


# -----------------------------------------------------------------------------
# Column Detection Functions
# -----------------------------------------------------------------------------

def detect_fmea_level_column(df: pd.DataFrame, log_func: Optional[callable] = None) -> Optional[str]:
    """
    Detect FMEA Level column with value validation.

    1. Find candidate columns matching FMEA_LEVEL_SYNONYMS
    2. For each candidate, sample unique values
    3. Confirm column contains circuit_block OR piece_part keywords
    4. Return first validated column, or None if no valid match

    This prevents false positives like "Part Type" or "Level" columns
    that don't contain FMEA row type values.

    Args:
        df: DataFrame to search
        log_func: Optional logging callback

    Returns:
        Column name if found and validated, None otherwise
    """
    for col in df.columns:
        col_lower = str(col).lower().strip()
        if any(syn in col_lower for syn in FMEA_LEVEL_SYNONYMS):
            # Value sampling: check if column values match expected keywords
            unique_vals = df[col].dropna().astype(str).str.lower().unique()
            has_cb = any(kw in val for val in unique_vals for kw in CIRCUIT_BLOCK_KEYWORDS)
            has_pp = any(kw in val for val in unique_vals for kw in PIECE_PART_KEYWORDS)
            if has_cb or has_pp:
                if log_func:
                    log_func(f"FMEA Level column detected: '{col}' (validated by value sampling)")
                return col
            elif log_func:
                log_func(f"Column '{col}' matches synonym but values don't match expected keywords - skipped")
    return None  # No valid FMEA Level column found → use row scan fallback


def detect_refdes_column_for_fmea(df: pd.DataFrame, log_func: Optional[callable] = None) -> Optional[str]:
    """
    Detect RefDes column using synonyms.

    Uses the 'fmea_refdes' synonym list which includes common FMEA RefDes
    column names like 'Failure Mode Causes', 'Component RefDes', etc.

    Args:
        df: DataFrame to search
        log_func: Optional logging callback

    Returns:
        Column name if found, None otherwise
    """
    synonyms = get_synonyms('fmea_refdes')
    for col in df.columns:
        col_str = str(col).lower().strip()
        if any(syn.lower() in col_str for syn in synonyms):
            if log_func:
                log_func(f"RefDes column detected: '{col}'")
            return col
    return None


def find_best_token_cell(
    row: pd.Series,
    exclude_cols: List[str],
) -> Tuple[Optional[str], Optional[str]]:
    """
    Fallback: Find cell with most RefDes-like tokens in a row.

    For each cell (excluding level columns, row type columns):
    1. Attempt to extract tokens using split_refdes_list()
    2. Count tokens that look like RefDes (start with known prefix)
    3. Return (cell_value, column_name) with highest score

    Args:
        row: DataFrame row as Series
        exclude_cols: Column names to skip (e.g., FMEA Level column)

    Returns:
        (cell_value, column_name) with highest score, or (None, None) if no RefDes found
    """
    best_col = None
    best_cell = None
    best_score = 0

    for col in row.index:
        if col in exclude_cols:
            continue
        cell = str(row[col]) if pd.notna(row[col]) else ""
        if not cell or len(cell) < 2:
            continue
        try:
            tokens = split_refdes_list(cell)
            # Score = count of tokens with known IEEE 315 prefix
            # Use walrus operator to guard against None from get_prefix()
            score = sum(1 for t in tokens if t and (p := get_prefix(t)) and is_known_prefix(p))
            if score > best_score:
                best_score = score
                best_cell = cell
                best_col = col
        except Exception as e:
            _logger.debug(f"Error parsing token cell in column '{col}': {e}")
            continue

    return (best_cell, best_col) if best_score > 0 else (None, None)


# -----------------------------------------------------------------------------
# Row Classification Functions
# -----------------------------------------------------------------------------

def classify_fmea_rows(
    df: pd.DataFrame,
    log_func: Optional[callable] = None,
    cancel_token: Optional[Any] = None,
) -> Tuple[List[RowClassification], Optional[str], bool]:
    """
    Classify all rows in an FMEA file as circuit_block, piece_part, or other.

    Classification strategy (in order):
    1. Try to detect FMEA Level column with value sampling
    2. If column found: classify by cell value
    3. If no column: scan ALL cells in each row for keywords

    Args:
        df: FMEA DataFrame
        log_func: Optional logging callback
        cancel_token: Optional cancellation token with check() method for responsive cancel

    Returns:
        Tuple of:
        - List of RowClassification objects (one per row)
        - FMEA Level column name (if detected) or None
        - Whether column was validated by value sampling
    """
    classifications: List[RowClassification] = []

    def _count_refdes_like_tokens(value: Any) -> int:
        """Count RefDes-like tokens in a cell value."""
        if value is None or (hasattr(pd, "isna") and pd.isna(value)):
            return 0
        count = 0
        for token in split_refdes_list(value):
            canon = canonicalize_refdes(token)
            if not canon:
                continue
            prefix = get_prefix(canon)
            if prefix and is_known_prefix(prefix):
                count += 1
        return count

    def _detect_column_by_synonyms(columns: List[str], synonyms: List[str]) -> Optional[str]:
        """Return first column containing any synonym (case-insensitive)."""
        lowered_synonyms = [str(s).lower().strip() for s in synonyms if str(s).strip()]
        for col in columns:
            col_text = str(col).lower().strip()
            if any(syn in col_text for syn in lowered_synonyms):
                return col
        return None

    def _is_non_empty(value: Any) -> bool:
        return value is not None and pd.notna(value) and str(value).strip() != ""

    refdes_col = detect_refdes_column_for_fmea(df)
    usage_col = _detect_column_by_synonyms(list(df.columns), get_synonyms('part_usage'))
    fmr_col = _detect_column_by_synonyms(list(df.columns), get_synonyms('fmr_strict'))
    failure_mode_col = _detect_column_by_synonyms(list(df.columns), get_synonyms('failure_mode'))
    fmea_id_col = _detect_column_by_synonyms(
        list(df.columns),
        ['fmea id', 'fmea_id', 'fmeaid', 'fmeca id', 'fm id', 'failure mode id', 'mode id'],
    )

    def _infer_row_type_from_signals(
        row: pd.Series,
        last_known_type: str,
        *,
        allow_single_token_pp: bool,
        allow_last_known_fallback: bool,
    ) -> str:
        """Infer row type for blank/untyped rows using RefDes and PP signal columns."""
        token_count = _count_refdes_like_tokens(row.get(refdes_col)) if refdes_col else 0
        has_usage = _is_non_empty(row.get(usage_col)) if usage_col else False
        has_fmr = _is_non_empty(row.get(fmr_col)) if fmr_col else False
        has_failure_mode = _is_non_empty(row.get(failure_mode_col)) if failure_mode_col else False
        has_fmea_id = _is_non_empty(row.get(fmea_id_col)) if fmea_id_col else False

        # Strong PP signals win, including multi-token piece-part rows.
        if has_usage or has_fmr or has_failure_mode:
            return 'piece_part'
        if token_count >= 2:
            return 'circuit_block'
        if token_count == 1 and allow_single_token_pp:
            return 'piece_part'
        # FMEA ID alone is weak evidence; only use it when token count is not CB-like.
        if has_fmea_id and token_count <= 1 and (allow_single_token_pp or last_known_type == 'piece_part'):
            return 'piece_part'
        if allow_last_known_fallback and last_known_type in {'circuit_block', 'piece_part'}:
            return last_known_type
        return 'other'

    # Try to detect FMEA Level column
    level_col = detect_fmea_level_column(df, log_func)
    level_col_validated = level_col is not None

    if level_col:
        # Classify using FMEA Level column values
        last_known_type = 'other'
        for pos, (idx, row) in enumerate(df.iterrows(), start=2):
            # Check for cancellation every 100 rows
            if cancel_token and pos % 100 == 0:
                cancel_token.check()

            row_num = idx + 2 if isinstance(idx, numbers.Integral) else pos  # +2 for 1-based with header
            cell_val = str(row[level_col]).strip() if pd.notna(row[level_col]) else ""

            row_type = 'other'
            if is_circuit_block_text(cell_val):
                row_type = 'circuit_block'
            elif is_piece_part_text(cell_val):
                row_type = 'piece_part'
            elif not cell_val:
                row_type = _infer_row_type_from_signals(
                    row,
                    last_known_type,
                    allow_single_token_pp=True,
                    allow_last_known_fallback=True,
                )

            if row_type in {'circuit_block', 'piece_part'}:
                last_known_type = row_type

            classifications.append(RowClassification(
                row_index=row_num,
                row_type=row_type,
                classification_source='fmea_level_column',
                fmea_level_value=cell_val if cell_val else None,
            ))
    else:
        # Fallback: scan all cells in each row
        if log_func:
            log_func("No FMEA Level column found - using row scan fallback")

        last_known_type = 'other'
        for pos, (idx, row) in enumerate(df.iterrows(), start=2):
            # Check for cancellation every 100 rows (more frequent due to nested column loop)
            if cancel_token and pos % 100 == 0:
                cancel_token.check()

            row_num = idx + 2 if isinstance(idx, numbers.Integral) else pos  # +2 for 1-based with header
            row_type = 'other'
            matched_value = None

            # Scan all cells in row for keywords (uses word-boundary matching for short forms)
            for col in df.columns:
                cell_val = str(row[col]) if pd.notna(row[col]) else ""
                if is_circuit_block_text(cell_val):
                    row_type = 'circuit_block'
                    matched_value = cell_val
                    break
                elif is_piece_part_text(cell_val):
                    row_type = 'piece_part'
                    matched_value = cell_val
                    break

            if row_type == 'other':
                row_type = _infer_row_type_from_signals(
                    row,
                    last_known_type,
                    allow_single_token_pp=False,
                    allow_last_known_fallback=False,
                )

            if row_type in {'circuit_block', 'piece_part'}:
                last_known_type = row_type

            classifications.append(RowClassification(
                row_index=row_num,
                row_type=row_type,
                classification_source='row_scan',
                fmea_level_value=matched_value,
            ))

    return classifications, level_col, level_col_validated
