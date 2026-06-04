#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOM Compare Tool - Core Logic
"""
import os
import re
import json
import datetime
import numbers
import threading
from pathlib import Path
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Any

import pandas as pd

# Tauri backend copy — source: src/apps/bom_compare/bom_compare_logic.py
from common import (
    make_run_id,
    ensure_file_available,
    try_read_table,
    normalize_df_columns,
    detect_column,
    ensure_columns_exist,
    sha256_of_path,
    get_tool_logger,
    style_worksheet,
    write_df_to_sheet,
    check_cancelled,
    CancellationError,
    FMR_TOLERANCE,
    get_synonyms,
    parse_usage,
    to_reason_code_label,
    to_user_facing_text,
)
from common.exceptions import ColumnMappingError
from common.refdes_utils import (
    canonicalize_refdes,
    get_base_refdes,
    get_usage_base_refdes,
    get_prefix,
    is_known_prefix,
    expand_refdes_range,
    split_refdes_list,
    TOKEN_SPLIT_REGEX,
    CONTROL_CHARS_PATTERN,
)
from common.validation_utils import (
    USAGE_TOLERANCE,
    validate_part_usage,
    validate_usage_format,
    validate_fmr_usage_product,
)
from common.fmea_utils import (
    FMEA_LEVEL_SYNONYMS,
    CIRCUIT_BLOCK_PHRASES,
    PIECE_PART_PHRASES,
    CIRCUIT_BLOCK_KEYWORDS,
    PIECE_PART_KEYWORDS,
    RowClassification,
    is_circuit_block_text,
    is_piece_part_text,
    is_fmea_file,
    detect_fmea_level_column,
    detect_refdes_column_for_fmea,
    find_best_token_cell,
    classify_fmea_rows,
)

# Initialize module logger
_logger = get_tool_logger("bom_compare")

# -----------------------------------------------------------------------------
# Global Constants
# -----------------------------------------------------------------------------

# Column synonyms from centralized definitions (common.column_synonyms)
# Exposed here for GUI auto-detection with semantic names
# Note: GROUPING_REF and BOM_REF both use 'ref_des' - kept separate for clarity
REF_SYNONYMS = get_synonyms('ref_des')
GROUPING_REF_SYNONYMS = REF_SYNONYMS  # Alias for backward compatibility
BOM_REF_SYNONYMS = REF_SYNONYMS       # Alias for backward compatibility
GROUPING_GROUP_SYNONYMS = get_synonyms('component_group')
BOM_DESC_SYNONYMS = get_synonyms('description')

DEFAULT_DNP_REGEX = r"(?:\bDNP\b|\bNF\b|NOT\s*FITTED|NO[-\s]?LOAD|DO\s*NOT\s*POPULATE)"
# TOKEN_SPLIT_REGEX is imported from common.refdes_utils
RANGE_SEPS = ["-", "\u2013", "\u2014", ".."]


# -----------------------------------------------------------------------------
# Data Structures
# -----------------------------------------------------------------------------
@dataclass
class ColumnMapping:
    grouping_group_col: Optional[str] = None
    grouping_refdes_col: Optional[str] = None
    bom_refdes_col: Optional[str] = None
    bom_desc_col: Optional[str] = None

@dataclass
class AnalyzeOptions:
    # NOTE: there is intentionally no ``base_match`` field. The frontend "base
    # match" checkbox is wired to ``loose_base_match`` in runtime.py (the wire
    # key stays ``base_match`` for stability, but it maps to loose/prefix base
    # matching). A previously-dead ``base_match`` field was removed so no
    # checkbox can silently no-op against a field nothing reads.
    exact_match: bool = False
    treat_prov_as_covered: bool = True
    ignore_dnp: bool = True
    dnp_regex: str = DEFAULT_DNP_REGEX
    run_warning_checks: bool = True
    run_duplicate_checks: bool = True
    loose_base_match: bool = False
    ignore_refdes_pattern: Optional[str] = None
    ignore_desc_pattern: Optional[str] = None
    check_fmr: bool = False
    check_part_usage: bool = True  # Validate part usage values match 1/instance_count

@dataclass
class AnalyzeResults:
    summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    missing_in_bom: pd.DataFrame = field(default_factory=pd.DataFrame)
    bom_not_in_groups: pd.DataFrame = field(default_factory=pd.DataFrame)
    description_warnings: pd.DataFrame = field(default_factory=pd.DataFrame)
    duplicates: pd.DataFrame = field(default_factory=pd.DataFrame)
    fmr_warnings: pd.DataFrame = field(default_factory=pd.DataFrame)
    part_usage_warnings: pd.DataFrame = field(default_factory=pd.DataFrame)
    log: str = ""



# -----------------------------------------------------------------------------
# BOM vs BOM Comparison
# -----------------------------------------------------------------------------

@dataclass
class BomCompareResult:
    """Results from comparing two BOMs."""
    only_in_a: List[Dict[str, Any]] = field(default_factory=list)
    only_in_b: List[Dict[str, Any]] = field(default_factory=list)
    differences: List[Dict[str, Any]] = field(default_factory=list)
    in_both_count: int = 0
    summary: Dict[str, Any] = field(default_factory=dict)
    duplicates_a: List[Dict[str, Any]] = field(default_factory=list)  # Duplicate RefDes in BOM A
    duplicates_b: List[Dict[str, Any]] = field(default_factory=list)  # Duplicate RefDes in BOM B
    part_usage_warnings: List[Dict[str, Any]] = field(default_factory=list)  # Part Usage validation warnings
    scope_warnings: List[Dict[str, Any]] = field(default_factory=list)  # CB vs PP scope warnings for FMEA-like files
    fmr_warnings: List[Dict[str, Any]] = field(default_factory=list)  # Failure Mode Ratio sum warnings (check_fmr)


# -----------------------------------------------------------------------------
# Re-exports (must be after dataclass definitions to avoid circular imports)
# -----------------------------------------------------------------------------
from .custom_compare import (  # noqa: E402
    compare_two_boms,
    detect_circuit_block_column,
    CIRCUIT_BLOCK_SYNONYMS,
    FAILURE_MODE_SYNONYMS,
    FMEA_ID_SYNONYMS,
)
from .group_analysis import (  # noqa: E402
    # Constants
    MULTIPLIERS,
    RE_PINCOUNT,
    RE_ARRAY,
    CONNECTOR_WORDS,
    IGNORE_NUMBER_CONTEXT,
    MAX_RANGE_EXPANSION,
    # Backward-compat aliases
    expand_range_token,
    canonicalize_token,
    base_of_token,
    # Token parsing
    infer_expected_count,
    explode_grouping,
    explode_bom,
    # Analysis helpers
    _compile_patterns,
    _find_missing_in_bom,
    _find_extra_in_bom,
    _check_warnings,
    _check_duplicates,
    _check_fmr,
    _check_part_usage,
    # Orchestrator
    analyze,
    # Excel report
    write_excel_report,
)
from .fmea_coverage import (  # noqa: E402
    TokenCoverage,
    CircuitBlockCoverage,
    CoverageSummary,
    FmeaCoverageResult,
    validate_fmea_coverage,
)
from .excel_export import (  # noqa: E402
    sanitize_sheet_name,
    write_bom_compare_excel,
    EXCEL_INVALID_SHEET_CHARS,
    EXCEL_MAX_SHEET_NAME_LEN,
)
