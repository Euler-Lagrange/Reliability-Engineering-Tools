#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOM Compare - FMEA Coverage Module

FMEA piece-part coverage validation: classify circuit block and piece-part rows,
extract RefDes tokens, and validate that each circuit block token has matching
piece-part rows.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

import pandas as pd

from common import (
    get_tool_logger,
    CancellationError,
)
from common.refdes_utils import (
    canonicalize_refdes,
    get_prefix,
    is_known_prefix,
    split_refdes_list,
)
from common.fmea_utils import (
    RowClassification,
    is_fmea_file,
    detect_fmea_level_column,
    detect_refdes_column_for_fmea,
    find_best_token_cell,
    classify_fmea_rows,
)

_logger = get_tool_logger("bom_compare")

# -----------------------------------------------------------------------------
# FMEA Piece-Part Coverage Validation Data Structures
# -----------------------------------------------------------------------------
# NOTE: RowClassification is now imported from common.fmea_utils

@dataclass
class TokenCoverage:
    """Coverage status for a single RefDes token."""
    token: str                          # Canonicalized RefDes token
    original_cell: str                  # Raw cell value it came from
    source_column: str                  # Column name where found
    has_piece_part: bool                # Covered?
    piece_part_row_count: int           # How many PP rows match
    piece_part_row_indexes: List[int] = field(default_factory=list)  # 1-based row indexes
    first_piece_part_row_data: Optional[Dict[str, Any]] = None  # First matching PP row data


@dataclass
class CircuitBlockCoverage:
    """Coverage details for a single circuit block row."""
    row_index: int                      # 1-based
    classification_source: str          # 'fmea_level_column' or 'row_scan'
    fmea_level_value: Optional[str]     # If column-based
    block_label: Optional[str]          # Function/Circuit Block name if detected
    tokens: List[TokenCoverage] = field(default_factory=list)
    original_row_data: Dict[str, Any] = field(default_factory=dict)  # All columns from CB row


@dataclass
class CoverageSummary:
    """Summary statistics for FMEA coverage validation."""
    total_tokens: int = 0
    covered_tokens: int = 0
    missing_tokens: int = 0
    coverage_pct: float = 0.0
    missing_list: List[str] = field(default_factory=list)  # For quick display


@dataclass
class FmeaCoverageResult:
    """Complete result of FMEA piece-part coverage validation."""
    source_file: str
    detected_by_filename: bool
    fmea_level_column: Optional[str] = None  # Column name or None if row_scan
    fmea_level_validated_by_values: bool = False  # Value sampling confirmation
    refdes_column_detected: Optional[str] = None  # Column name or None if per-row fallback
    refdes_detection_method: str = 'none'  # 'column_synonym' or 'per_row_best_cell'
    circuit_blocks: List[CircuitBlockCoverage] = field(default_factory=list)
    piece_part_rows: List[RowClassification] = field(default_factory=list)
    piece_part_row_data: Dict[int, Dict[str, Any]] = field(default_factory=dict)  # row_index -> row data
    summary: CoverageSummary = field(default_factory=CoverageSummary)
    classified_by_level_col_count: int = 0
    classified_by_row_scan_count: int = 0



# -----------------------------------------------------------------------------
# FMEA Piece-Part Coverage Validation Functions
# -----------------------------------------------------------------------------
# NOTE: Core detection functions (detect_fmea_level_column, detect_refdes_column_for_fmea,
# find_best_token_cell, classify_fmea_rows) are now imported from common.fmea_utils


def validate_fmea_coverage(
    df: pd.DataFrame,
    filename: str,
    refdes_col: Optional[str] = None,
    cancel_token: Optional[Any] = None,
    progress_func: Optional[callable] = None,
    log_func: Optional[callable] = None,
) -> FmeaCoverageResult:
    """
    Validate FMEA piece-part coverage for a single file.

    RefDes extraction strategy (in order):
    1. Use provided refdes_col if given
    2. Auto-detect via column synonyms (detect_refdes_column_for_fmea)
    3. Per-row fallback: find_best_token_cell() for each CB row

    Uses exact token matching:
    1. Expand CB RefDes using split_refdes_list()
    2. Canonicalize each token (uppercase, strip control chars)
    3. Match against PP row tokens (exact match, no base reduction)

    Args:
        df: FMEA DataFrame
        filename: Source filename (for result)
        refdes_col: Optional RefDes column name (will auto-detect if None)
        cancel_token: Optional cancellation token with check() method
        progress_func: Optional callback for progress updates (0.0 to 1.0)
        log_func: Optional logging callback

    Returns:
        FmeaCoverageResult with complete validation results
    """
    from common.refdes_utils import is_known_prefix, get_prefix

    def log(msg: str):
        if log_func:
            log_func(msg)
        _logger.info(msg)

    result = FmeaCoverageResult(
        source_file=filename,
        detected_by_filename=is_fmea_file(filename),
    )

    # Step 1: Classify all rows
    log("Classifying FMEA rows...")
    classifications, level_col, level_validated = classify_fmea_rows(df, log, cancel_token)
    result.fmea_level_column = level_col
    result.fmea_level_validated_by_values = level_validated

    # Count classifications by source
    result.classified_by_level_col_count = sum(
        1 for c in classifications if c.classification_source == 'fmea_level_column'
    )
    result.classified_by_row_scan_count = sum(
        1 for c in classifications if c.classification_source == 'row_scan'
    )

    # Separate circuit block and piece-part rows
    cb_rows = [c for c in classifications if c.row_type == 'circuit_block']
    pp_rows = [c for c in classifications if c.row_type == 'piece_part']
    result.piece_part_rows = pp_rows

    log(f"Found {len(cb_rows)} circuit block rows, {len(pp_rows)} piece-part rows")

    if not cb_rows:
        log("No circuit block rows found - nothing to validate")
        return result

    # Step 2: Detect RefDes column
    detected_refdes_col = refdes_col

    # Validate provided column has RefDes-like content (fallback if zero tokens)
    if detected_refdes_col and detected_refdes_col in df.columns:
        # Sample 50 cells to handle files with metadata/headers in first rows
        sample_cells = df[detected_refdes_col].dropna().head(50).astype(str)
        token_count = sum(
            1 for cell in sample_cells
            for t in split_refdes_list(cell)
            if t and (p := get_prefix(t)) and is_known_prefix(p)
        )
        if token_count == 0:
            log(f"Provided column '{detected_refdes_col}' has no RefDes tokens - falling back to auto-detect")
            detected_refdes_col = None  # Trigger fallback

    if not detected_refdes_col:
        detected_refdes_col = detect_refdes_column_for_fmea(df, log)
        if detected_refdes_col:
            result.refdes_column_detected = detected_refdes_col
            result.refdes_detection_method = 'column_synonym'
        else:
            result.refdes_detection_method = 'per_row_best_cell'
            log("RefDes column not detected - will use per-row best cell fallback")
    else:
        result.refdes_column_detected = detected_refdes_col
        result.refdes_detection_method = 'column_synonym'

    # Step 3: Build piece-part token lookup
    log("Building piece-part token lookup...")
    pp_token_lookup: Dict[str, List[int]] = {}  # token -> [row_indexes]
    pp_row_data_lookup: Dict[int, Dict[str, Any]] = {}  # row_index -> row data (for export)
    exclude_cols = [level_col] if level_col else []

    for pp_class in pp_rows:
        if cancel_token:
            try:
                cancel_token.check()
            except CancellationError:
                log("Validation cancelled")
                return result

        row_idx = pp_class.row_index - 2  # Convert back to 0-based DataFrame index
        if row_idx < 0 or row_idx >= len(df):
            continue

        row = df.iloc[row_idx]
        # Store row data for export (keyed by 1-based row index)
        pp_row_data_lookup[pp_class.row_index] = {str(col): row[col] for col in df.columns}

        # Get RefDes tokens from piece-part row
        if detected_refdes_col and detected_refdes_col in df.columns:
            refdes_cell = str(row[detected_refdes_col]) if pd.notna(row[detected_refdes_col]) else ""
        else:
            refdes_cell, _ = find_best_token_cell(row, exclude_cols)
            refdes_cell = refdes_cell or ""

        tokens = split_refdes_list(refdes_cell)
        for token in tokens:
            if token:
                canonical = canonicalize_refdes(token)
                if canonical:
                    if canonical not in pp_token_lookup:
                        pp_token_lookup[canonical] = []
                    pp_token_lookup[canonical].append(pp_class.row_index)

    log(f"Built lookup with {len(pp_token_lookup)} unique piece-part tokens")

    # Step 4: Validate circuit block coverage
    log("Validating circuit block coverage...")
    total_tokens = 0
    covered_tokens = 0
    missing_list: List[str] = []

    for i, cb_class in enumerate(cb_rows):
        if cancel_token and i % 10 == 0:
            try:
                cancel_token.check()
            except CancellationError:
                log("Validation cancelled")
                return result

        if progress_func:
            progress_func(i / len(cb_rows))

        row_idx = cb_class.row_index - 2  # Convert back to 0-based DataFrame index
        if row_idx < 0 or row_idx >= len(df):
            continue

        row = df.iloc[row_idx]

        # Get RefDes tokens from circuit block row
        if detected_refdes_col and detected_refdes_col in df.columns:
            refdes_cell = str(row[detected_refdes_col]) if pd.notna(row[detected_refdes_col]) else ""
            source_column = detected_refdes_col
        else:
            refdes_cell, source_column = find_best_token_cell(row, exclude_cols)
            refdes_cell = refdes_cell or ""
            source_column = source_column or "unknown"

        tokens = split_refdes_list(refdes_cell)
        token_coverages: List[TokenCoverage] = []

        for token in tokens:
            if not token:
                continue
            total_tokens += 1
            canonical = canonicalize_refdes(token)
            pp_matches = pp_token_lookup.get(canonical, [])

            has_pp = len(pp_matches) > 0
            if has_pp:
                covered_tokens += 1
            else:
                missing_list.append(canonical)

            # Get first piece-part row data for export (if available)
            first_pp_row_data = None
            if pp_matches:
                first_pp_idx = pp_matches[0]
                first_pp_row_data = pp_row_data_lookup.get(first_pp_idx)

            token_coverages.append(TokenCoverage(
                token=canonical,
                original_cell=refdes_cell,
                source_column=source_column,
                has_piece_part=has_pp,
                piece_part_row_count=len(pp_matches),
                piece_part_row_indexes=pp_matches,
                first_piece_part_row_data=first_pp_row_data,
            ))

        # Build original row data dict
        original_row_data = {str(col): row[col] for col in df.columns}

        result.circuit_blocks.append(CircuitBlockCoverage(
            row_index=cb_class.row_index,
            classification_source=cb_class.classification_source,
            fmea_level_value=cb_class.fmea_level_value,
            block_label=None,  # Could detect block name from another column if needed
            tokens=token_coverages,
            original_row_data=original_row_data,
        ))

    # Step 5: Calculate summary
    missing_tokens = total_tokens - covered_tokens
    coverage_pct = (covered_tokens / total_tokens * 100) if total_tokens > 0 else 0.0

    result.summary = CoverageSummary(
        total_tokens=total_tokens,
        covered_tokens=covered_tokens,
        missing_tokens=missing_tokens,
        coverage_pct=coverage_pct,
        missing_list=missing_list,
    )

    # Store piece-part row data for Sheet 4 export
    result.piece_part_row_data = pp_row_data_lookup

    log(f"Coverage: {covered_tokens}/{total_tokens} ({coverage_pct:.1f}%) - {missing_tokens} missing")

    if progress_func:
        progress_func(1.0)

    return result

