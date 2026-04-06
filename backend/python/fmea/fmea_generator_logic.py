#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# FROZEN -- Do not modify this file.
# This module is part of a legacy tool whose development is on hold.
# All changes, bug fixes, and refactors are suspended until the freeze is lifted.
# See CLAUDE.md "Frozen Tools" section for details.
# ============================================================================
"""
FMEA Generator - Core Logic
"""
import os
import re
import time
import threading
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import pandas as pd

# Import shared utilities from the local common package (Tauri-self-contained copy)
from common import (
    make_run_id,
    try_read_table,
    ensure_columns_exist,
    write_snapshot,
    get_tool_logger,
    style_worksheet,
    write_df_to_sheet,
    PRESETS,
    clean_string,
    canonical_pn,
    parse_usage,
    CancellationToken,
    HEADER_CONFIG as COMMON_HEADER_CONFIG,
    get_synonyms,
    ColumnMappingError,
    ValidationError,
    to_reason_code_label,
    to_user_facing_text,
)
from common.refdes_utils import (
    split_refdes_list,
    is_pin_notation,
    canonicalize_refdes,
    get_usage_base_refdes,
)
from common.partition_id import parse_partition_id
from common.validation_utils import USAGE_TOLERANCE, FMR_TOLERANCE

# Initialize module logger
_logger = get_tool_logger("fmea_generator")

# ==================== CONFIGURATION & CONSTANTS ====================

# HEADER_CONFIG now uses centralized synonyms from common.column_synonyms
# This ensures consistent column detection across all tools
HEADER_CONFIG = {
    'BOM': {
        'ref_des': get_synonyms('ref_des'),
        'part_number': get_synonyms('part_number'),
        'description': get_synonyms('description'),
        'hda_level1': get_synonyms('commodity_level1'),
        'hda_level2': get_synonyms('commodity_level2'),
        'part_usage': get_synonyms('part_usage'),
    },
    'HDA': {
        'part_number': get_synonyms('part_number'),
        'commodity_level1': get_synonyms('commodity_level1'),
        'commodity_level2': get_synonyms('commodity_level2'),
        'description': get_synonyms('description'),
        'fmd_type1': get_synonyms('fmd_type1'),
        'fmd_type2': get_synonyms('fmd_type2'),
    },
    'FAILURE_MODES': {
        'commodity_level1': get_synonyms('fmd_type1'),  # FM file uses FMD types
        'commodity_level2': get_synonyms('fmd_type2'),
        'failure_mode': get_synonyms('failure_mode'),
        'ratio': get_synonyms('ratio'),
    },
    'COMPONENT_GROUPING': {
        'component_group': get_synonyms('component_group'),
        'description': get_synonyms('function_description'),
        'ref_des': get_synonyms('ref_des'),
        'schematic_page': get_synonyms('schematic_page'),
    },
    'FUNCTIONAL': {
        'function_id': get_synonyms('function_id'),
        'failure_mode': get_synonyms('failure_mode'),
        'local_effect': get_synonyms('local_effect'),
        'next_higher_effect': get_synonyms('next_higher_effect'),
        'end_effect': get_synonyms('end_effect'),
    },
    'FUNCTIONAL_MERGE_SOURCE': {
        'function_id': get_synonyms('function_id'),
        'failure_mode': get_synonyms('failure_mode'),
        'local_effect': get_synonyms('local_effect'),
        'next_higher_effect': get_synonyms('next_higher_effect'),
        'end_effect': get_synonyms('end_effect'),
    },
    'PIECEPART_MERGE_SOURCE': {
        'ref_des': get_synonyms('ref_des'),
        'fmea_id': get_synonyms('fmea_id'),
        'part_number': get_synonyms('part_number'),
        'part_usage': get_synonyms('part_usage'),
        'failure_mode': get_synonyms('failure_mode'),
        'local_effect': get_synonyms('local_effect'),
        'next_higher_effect': get_synonyms('next_higher_effect'),
        'end_effect': get_synonyms('end_effect'),
    },
}

REQUIRED_COLS = {
    'COMPONENT_GROUPING': ['component_group', 'ref_des'],
    'BOM': ['ref_des', 'part_number'],
    'HDA': ['part_number'],
    'FAILURE_MODES': ['commodity_level1', 'failure_mode', 'ratio'],
    'FUNCTIONAL': ['function_id', 'failure_mode'],
    'FUNCTIONAL_MERGE_SOURCE': ['function_id', 'failure_mode'],
    'PIECEPART_MERGE_SOURCE': ['ref_des', 'failure_mode'],
}

OUTPUT_HEADERS = [
    'Schematic Page', 'FMEA-ID', 'Function Description', 'FMEA Level',
    'Failure Mode Causes', 'Component Part Number', 'Component Part Description',
    'BAE HDA Commodity I', 'BAE HDA Commodity II', 'FMD-2016 Commodity Type 1',
    'FMD-2016 Commodity Type 2', 'Failure Mode', 'Failure Mode Ratio',
    'Part Usage', 'Diagnostic',
    'Local Effect', 'Next Higher Effect', 'End Effect',
    'FuncFM Source Row', 'FuncFM Key', 'FuncFM Hash'
]

ROW_TYPE_COL = '_row_type'
ALPHABET_LENGTH = 26  # Length of uppercase alphabet for suffix generation
INDEX_CANCEL_CHECK_INTERVAL = 50  # Rows between cancellation checks during index build
MERGE_CANCEL_CHECK_INTERVAL = 25  # RefDes/rows between cancellation checks during merge work
MAX_MERGE_DETAIL_LOGS = 25  # Cap live log spam; full detail still goes to workbook sheets
MERGE_FUNCTIONAL = 'functional'
MERGE_PIECEPART = 'piecepart'
MERGE_EFFECT_FIELDS = ('local_effect', 'next_higher_effect', 'end_effect')
MERGE_EFFECT_OUTPUT_MAP = {
    'local_effect': 'Local Effect',
    'next_higher_effect': 'Next Higher Effect',
    'end_effect': 'End Effect',
}
ROW_STYLE_PRIORITY = {
    'default': 0,
    'neutral': 1,
    'warning': 2,
    'validation_warning': 2,
    'merge_warning': 2,
    'error': 3,
    'piece_part_no_match': 3,
    'merge_error': 3,
}


@dataclass(frozen=True)
class MergeSourceSpec:
    merge_type: str
    file_key: str
    enable_key: str
    config_key: str
    source_name: str
    required_fields: Tuple[str, ...]
    optional_fields: Tuple[str, ...]
    target_row_type: str


@dataclass
class MergeIssue:
    merge_type: str
    severity: str
    kind: str
    entity_key: str
    field: str = ''
    new_value: str = ''
    old_value: str = ''
    message: str = ''
    action: str = ''
    source_row: str = ''
    target_row: str = ''


@dataclass
class MergeResult:
    merge_type: str
    copied_count: int = 0
    skipped_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    issue_rows: List[MergeIssue] = field(default_factory=list)


FUNCTIONAL_MERGE_SPEC = MergeSourceSpec(
    merge_type=MERGE_FUNCTIONAL,
    file_key='func',
    enable_key='use_func',
    config_key='FUNCTIONAL_MERGE_SOURCE',
    source_name='Functional FMEA merge source',
    required_fields=('function_id', 'failure_mode'),
    optional_fields=('local_effect', 'next_higher_effect', 'end_effect'),
    target_row_type='circuit_block',
)

PIECEPART_MERGE_SPEC = MergeSourceSpec(
    merge_type=MERGE_PIECEPART,
    file_key='piecepart_fmea',
    enable_key='use_piecepart_merge',
    config_key='PIECEPART_MERGE_SOURCE',
    source_name='Piece-Part FMEA merge source',
    required_fields=('ref_des', 'failure_mode'),
    optional_fields=('fmea_id', 'part_number', 'part_usage', 'local_effect', 'next_higher_effect', 'end_effect'),
    target_row_type='piece_part',
)

# ==================== UTILITY FUNCTIONS (FMEA-specific) ====================
# Shared utilities (try_read_table, make_run_id, clean_string, canonical_pn, etc.)
# are imported from common module. RefDes utilities from common.refdes_utils.

def resolve_column(df: pd.DataFrame, possible_names: List[str]) -> Optional[str]:
    """Find matching column name from list of possible names.

    M16: Uses minimum match length (4 chars) to avoid false positives.
    """
    MIN_SUBSTRING_MATCH_LEN = 4  # Prevent "Ref" matching "Reference Designator"
    cols_lower = {c.lower().strip(): c for c in df.columns}
    # First pass: exact match (case-insensitive)
    for name in possible_names:
        if name.lower().strip() in cols_lower:
            return cols_lower[name.lower().strip()]
    # Second pass: substring match with minimum length requirement
    for c in df.columns:
        c_low = c.lower().strip()
        for name in possible_names:
            name_low = name.lower().strip()
            if len(name_low) >= MIN_SUBSTRING_MATCH_LEN and name_low in c_low:
                return c
    return None

# split_ref_designators is now imported from common.refdes_utils as split_refdes_list
# Create alias for backward compatibility within this module
split_ref_designators = split_refdes_list

def normalize_func_base_id(fid: Optional[str]) -> str:
    """Normalize a function ID by removing letter or FM# suffixes."""
    if not fid:
        return ""
    fid = parse_partition_id(fid).comparison_key
    m = re.match(r"^(.*?)-([A-Z])$", fid)
    if m:
        return m.group(1)
    m = re.match(r"^(.*?)-(FM\d+)$", fid)
    if m:
        return m.group(1)
    return fid


def _index_to_suffix(idx: int) -> str:
    """Convert 0-based index to letter suffix for auto-generated circuit block IDs.

    Used when multiple functional FMEA failure modes share the same function_id.
    Generates unique suffixes: A, B, C, ... Z, AA, AB, AC, ...

    Args:
        idx: 0-based index (0 → A, 1 → B, ..., 25 → Z, 26 → AA, ...)

    Returns:
        Letter suffix string
    """
    # Base-26 bijective numeration: A-Z, AA-AZ, BA-BZ, ..., ZZ, AAA-...
    result = []
    n = idx + 1  # Convert 0-based to 1-based
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result.append(chr(ord('A') + remainder))
    return ''.join(reversed(result))


# ensure_columns_exist, write_snapshot are imported from common

# ==================== LOGIC CLASS ====================

class FMEAProcessor:
    """Core processor for generating FMEA reports from BOM and component data."""

    def __init__(self, log_callback: Optional[Callable[[str], None]] = None) -> None:
        self._lock = threading.Lock()  # Thread safety for shared state
        self.log_callback: Optional[Callable[[str], None]] = log_callback
        self.cancel: CancellationToken = CancellationToken()
        self.verbose: bool = False
        self.bom_only_mode: bool = False
        self.successful_matches: List[Tuple[str, str]] = []
        self.no_matches: List[Tuple[str, str]] = []
        self.no_match_details: List[Tuple[str, str, str]] = []
        self.unmatched_hda: List[Tuple[str, str]] = []
        self.group_missing_in_bom: List[Tuple[str, str]] = []
        self.bom_missing_ref_rows: List[Tuple[int, str]] = []
        self.bom_duplicate_refdes: List[Tuple[str, int]] = []
        self.fm_index: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        self.functional_rows_by_base: Dict[str, List[Dict[str, Any]]] = {}
        self.functional_total_rows: int = 0
        self.merge_results: Dict[str, MergeResult] = {}
        # Internal indexes (populated by _build_indexes)
        self.bom_index: Dict[str, Dict[str, Any]] = {}
        self.hda_index: Dict[str, Dict[str, Any]] = {}
        self.fm_c1_set: set = set()
        self.fm_c1_to_c2: Dict[str, set] = defaultdict(set)
        # Usage validation: count of instances per usage base (for 1/n validation)
        self.usage_base_counts: Dict[str, int] = {}
        # Validation warnings tracking (for FMR sum and Part Usage validation)
        self.fmr_warnings: List[Dict[str, Any]] = []
        self.usage_warnings: List[Dict[str, Any]] = []

    def _reset_state(self) -> None:
        """Reset all mutable state for a new processing run.

        Thread Safety: This method assumes the caller holds self._lock.
        The lock is NOT acquired here to avoid double-acquisition when called
        from process() which already holds the lock.
        """
        # Verify we're called under lock (debug assertion - no runtime cost in production)
        assert self._lock.locked(), "_reset_state must be called with _lock held"
        self.successful_matches = []
        self.no_matches = []
        self.no_match_details = []
        self.unmatched_hda = []
        self.group_missing_in_bom = []
        self.bom_missing_ref_rows = []
        self.bom_duplicate_refdes = []
        self.fm_index = defaultdict(list)
        self.functional_rows_by_base = {}
        self.functional_total_rows = 0
        self.merge_results = {}
        self.bom_index = {}
        self.hda_index = {}
        self.fm_c1_set = set()
        self.fm_c1_to_c2 = defaultdict(set)
        self.usage_base_counts = {}
        self.fmr_warnings = []
        self.usage_warnings = []

    def log(self, message: str, level: str = 'INFO') -> None:
        """Log a message with timestamp and level."""
        if level == 'DEBUG' and not self.verbose: return
        timestamp = datetime.now().strftime("%H:%M:%S")
        msg = f"[{timestamp}] {level}: {message}"
        if self.log_callback:
            self.log_callback(msg)
        # Always log to file logger (primary logging destination)
        if level == 'DEBUG': _logger.debug(message)
        elif level == 'WARNING': _logger.warning(message)
        elif level == 'ERROR': _logger.error(message)
        else: _logger.info(message)

    def read_excel_safe(self, file_path: Union[str, Path], sheet_name=None) -> pd.DataFrame:
        """Read Excel file with error handling.

        Args:
            file_path: Path to the file.
            sheet_name: Excel sheet name (None = first sheet).
        """
        return try_read_table(file_path, header_row=0, sheet_name=sheet_name, log_func=self.log)

    def map_columns(
        self,
        df: pd.DataFrame,
        config_section: Dict[str, List[str]],
        required_list: Optional[List[str]] = None,
        source_name: str = "file",
        overrides: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """Map DataFrame columns to standard names using config synonyms.

        Args:
            df: DataFrame to map columns for
            config_section: Dict mapping standard names to synonym lists
            required_list: List of required standard column names
            source_name: Name of source file for error messages
            overrides: Optional dict of standard_name -> actual_column_name overrides
        """
        mapped = {}
        missing = []
        overrides = overrides or {}
        for std, candidates in config_section.items():
            # Check for manual override first
            if std in overrides and overrides[std] in df.columns:
                mapped[std] = overrides[std]
            else:
                found = resolve_column(df, candidates)
                if found: mapped[std] = found
                elif required_list and std in required_list: missing.append(std)
        if missing:
            raise ColumnMappingError(missing[0], source_name, tried_synonyms=missing)
        return mapped

    def _get_merge_result(self, merge_type: str) -> MergeResult:
        result = self.merge_results.get(merge_type)
        if result is None:
            result = MergeResult(merge_type=merge_type)
            self.merge_results[merge_type] = result
        return result

    def _normalize_merge_text(self, value: Any) -> str:
        return re.sub(r'\s+', ' ', clean_string(value)).strip().lower()

    def _parse_usage_value_for_merge(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)) and not pd.isna(value):
            return float(value)
        raw = clean_string(value)
        if not raw:
            return None
        if raw.startswith('='):
            raw = raw[1:].strip()
        parsed, _ = parse_usage(raw)
        if parsed is not None:
            return float(parsed)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _apply_row_style(self, row: Dict[str, Any], style: str) -> None:
        current = row.get(ROW_TYPE_COL, 'default')
        current_rank = ROW_STYLE_PRIORITY.get(current, 0)
        next_rank = ROW_STYLE_PRIORITY.get(style, 0)
        if next_rank >= current_rank:
            row[ROW_TYPE_COL] = style

    def _append_merge_diagnostic(self, target_row: Dict[str, Any], message: str) -> None:
        message = clean_string(message)
        if not message:
            return
        existing = clean_string(target_row.get('Diagnostic'))
        if not existing:
            target_row['Diagnostic'] = message
        elif message not in existing:
            target_row['Diagnostic'] = f"{existing}; {message}"

    def _copy_effect_fields(self, target_row: Dict[str, Any], source_row: Dict[str, Any]) -> List[str]:
        copied_fields = []
        for source_key, output_key in MERGE_EFFECT_OUTPUT_MAP.items():
            effect_value = clean_string(source_row.get(source_key))
            if effect_value:
                target_row[output_key] = effect_value
                copied_fields.append(output_key)
        return copied_fields

    def _record_merge_issue(self, kind: str, severity: str, merge_type: str, details: Dict[str, Any]) -> None:
        result = self._get_merge_result(merge_type)
        issue = MergeIssue(
            merge_type=merge_type,
            severity=severity,
            kind=kind,
            entity_key=clean_string(details.get('entity_key')) or clean_string(details.get('ref_des')) or clean_string(details.get('group')),
            field=clean_string(details.get('field')),
            new_value=clean_string(details.get('new_value')),
            old_value=clean_string(details.get('old_value')),
            message=clean_string(details.get('message')),
            action=clean_string(details.get('action')),
            source_row=clean_string(details.get('source_row')),
            target_row=clean_string(details.get('target_row')),
        )
        result.issue_rows.append(issue)
        if severity == 'warning':
            result.warning_count += 1
        elif severity == 'error':
            result.error_count += 1

        target_row_ref = details.get('target_row_ref')
        if isinstance(target_row_ref, dict):
            if severity == 'error':
                self._apply_row_style(target_row_ref, 'merge_error')
            elif severity == 'warning':
                self._apply_row_style(target_row_ref, 'merge_warning')
            if issue.message:
                self._append_merge_diagnostic(target_row_ref, issue.message)

    def _load_merge_source_df(
        self,
        spec: MergeSourceSpec,
        inputs: Dict[str, Any],
        col_overrides: Optional[Dict[str, str]],
    ) -> Optional[pd.DataFrame]:
        if not inputs.get(spec.enable_key):
            return None
        source_path = inputs.get(spec.file_key)
        if not source_path:
            return None
        if spec.merge_type == MERGE_FUNCTIONAL and self.bom_only_mode:
            return None

        # Resolve sheet name from inputs (e.g. 'func_sheet', 'piecepart_sheet')
        sheet_key = spec.file_key + '_sheet'
        sheet_name = inputs.get(sheet_key)

        self.log(f"Loading {spec.source_name}...")
        raw_df = self.read_excel_safe(source_path, sheet_name=sheet_name)
        return self._map_merge_source_columns(raw_df, spec, col_overrides)

    def _map_merge_source_columns(
        self,
        df: pd.DataFrame,
        spec: MergeSourceSpec,
        overrides: Optional[Dict[str, str]],
    ) -> pd.DataFrame:
        mapped = self.map_columns(
            df,
            HEADER_CONFIG[spec.config_key],
            list(spec.required_fields),
            source_name=spec.source_name,
            overrides=overrides,
        )
        renamed = df.rename(columns={v: k for k, v in mapped.items()})
        ensure_columns_exist(renamed, list(spec.required_fields), spec.source_name)

        mapped_effects = [field_name for field_name in MERGE_EFFECT_FIELDS if field_name in mapped]
        if not mapped_effects:
            raise ValidationError(
                f"{spec.source_name} is missing all effect columns. Map at least one of: "
                "Local Effect, Next Higher Effect, End Effect."
            )

        for field_name in spec.optional_fields:
            if field_name not in renamed.columns:
                renamed[field_name] = ''
        return renamed

    def _normalize_merge_source_rows(
        self,
        df: pd.DataFrame,
        spec: MergeSourceSpec,
    ) -> Dict[str, List[Dict[str, Any]]]:
        if spec.merge_type == MERGE_FUNCTIONAL:
            return self._normalize_functional_merge_rows(df)
        if spec.merge_type == MERGE_PIECEPART:
            return self._normalize_piecepart_merge_rows(df)
        return {}

    def _normalize_functional_merge_rows(self, df: pd.DataFrame) -> Dict[str, List[Dict[str, Any]]]:
        rows_by_base: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for idx, row in enumerate(df.itertuples()):
            if idx % INDEX_CANCEL_CHECK_INTERVAL == 0:
                self.cancel.check()

            fid = clean_string(getattr(row, 'function_id', ''))
            fm = clean_string(getattr(row, 'failure_mode', ''))
            if not fid or not fm:
                continue

            base = normalize_func_base_id(fid)
            source_row_num = idx + 2
            item = {
                'src_idx': source_row_num,
                'function_id': fid,
                'failure_mode': fm,
                'failure_mode_norm': self._normalize_merge_text(fm),
                'local_effect': clean_string(getattr(row, 'local_effect', '')),
                'next_higher_effect': clean_string(getattr(row, 'next_higher_effect', '')),
                'end_effect': clean_string(getattr(row, 'end_effect', '')),
                'source_key': f"{fid}|{fm}",
            }
            rows_by_base[base].append(item)
            self.functional_total_rows += 1

        return rows_by_base

    def _normalize_piecepart_merge_rows(self, df: pd.DataFrame) -> Dict[str, List[Dict[str, Any]]]:
        from common.fmea_utils import classify_fmea_rows

        rows_by_refdes: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        raw_values_by_refdes: Dict[str, set] = defaultdict(set)

        classifications, _, _ = classify_fmea_rows(df, self.log, self.cancel)
        for pos, (df_idx, row) in enumerate(df.iterrows()):
            if pos >= len(classifications) or classifications[pos].row_type != 'piece_part':
                continue

            source_row_num = pos + 2
            refs = split_ref_designators(row.get('ref_des', ''))
            if len(refs) != 1:
                if len(refs) > 1:
                    self._record_merge_issue(
                        'multi_refdes_source_row',
                        'error',
                        MERGE_PIECEPART,
                        {
                            'entity_key': ', '.join(refs),
                            'field': 'Reference Designator',
                            'message': (
                                f"Piece-Part merge source row {source_row_num} contains multiple reference designators "
                                f"({', '.join(refs)}), so it cannot be matched safely."
                            ),
                            'action': 'Skipped copying effects from this source row.',
                            'source_row': str(source_row_num),
                        },
                    )
                continue

            ref_raw = clean_string(refs[0])
            ref_canon = canonicalize_refdes(ref_raw)
            raw_values_by_refdes[ref_canon].add(ref_raw)
            failure_mode = clean_string(row.get('failure_mode', ''))
            if not failure_mode:
                self._get_merge_result(MERGE_PIECEPART).skipped_count += 1
                self._record_merge_issue(
                    'missing_failure_mode',
                    'error',
                    MERGE_PIECEPART,
                    {
                        'entity_key': ref_raw,
                        'field': 'Failure Mode',
                        'message': (
                            f"Piece-Part merge source row {source_row_num} for '{ref_raw}' is missing a failure mode, "
                            "so it cannot be matched safely."
                        ),
                        'action': 'Skipped this source row because Failure Mode is required for piece-part merge.',
                        'source_row': str(source_row_num),
                    },
                )
                continue
            item = {
                'ref_des': ref_raw,
                'ref_des_canon': ref_canon,
                'failure_mode': failure_mode,
                'failure_mode_norm': self._normalize_merge_text(failure_mode),
                'fmea_id': clean_string(row.get('fmea_id', '')),
                'part_number': clean_string(row.get('part_number', '')),
                'part_number_canon': canonical_pn(row.get('part_number', '')),
                'part_usage': row.get('part_usage', ''),
                'part_usage_value': self._parse_usage_value_for_merge(row.get('part_usage', '')),
                'local_effect': clean_string(row.get('local_effect', '')),
                'next_higher_effect': clean_string(row.get('next_higher_effect', '')),
                'end_effect': clean_string(row.get('end_effect', '')),
                'source_order': len(rows_by_refdes[ref_canon]),
                'source_row': source_row_num,
            }
            rows_by_refdes[ref_canon].append(item)

        for ref_canon, raw_values in raw_values_by_refdes.items():
            if len(raw_values) > 1:
                self._record_merge_issue(
                    'ambiguous_source_match',
                    'warning',
                    MERGE_PIECEPART,
                    {
                        'entity_key': ref_canon,
                        'field': 'Reference Designator',
                        'message': (
                            f"Piece-Part merge source contains multiple raw reference designators ({', '.join(sorted(raw_values))}) "
                            f"that normalize to '{ref_canon}'."
                        ),
                        'action': 'Merge continues using normalized matching.',
                    },
                )

        return rows_by_refdes

    def _build_indexes(
        self,
        bom_df: pd.DataFrame,
        hda_df: pd.DataFrame,
        fm_df: pd.DataFrame,
        func_df: Optional[pd.DataFrame] = None,
    ) -> None:
        self._build_base_indexes(bom_df, hda_df, fm_df)
        self.functional_rows_by_base = {}
        self.functional_total_rows = 0
        if func_df is not None:
            self.functional_rows_by_base = self._normalize_functional_merge_rows(func_df)

    def _build_base_indexes(
        self,
        bom_df: pd.DataFrame,
        hda_df: pd.DataFrame,
        fm_df: pd.DataFrame,
    ) -> None:
        # Type guards for required DataFrames
        if bom_df is None or bom_df.empty:
            raise ValidationError("BOM DataFrame cannot be None or empty")
        if hda_df is None:
            raise ValidationError("HDA DataFrame cannot be None")
        if fm_df is None or fm_df.empty:
            raise ValidationError("Failure Modes DataFrame cannot be None or empty")

        self.bom_index = {}
        all_bom_refs = []
        if 'part_number' in bom_df.columns:
            bom_df['canon_pn'] = bom_df['part_number'].apply(canonical_pn)
        # C4: Use enumerate for reliable row counting (Excel row 1 = header, data starts at row 2)
        bom_dupe_warnings = []  # Track duplicates for logging
        for excel_row, row in enumerate(bom_df.itertuples(), start=2):
            # Check cancellation frequently to keep UI responsive on large datasets.
            if excel_row % INDEX_CANCEL_CHECK_INTERVAL == 0:
                self.cancel.check()

            ref_des_val = getattr(row, 'ref_des', '') if hasattr(row, 'ref_des') else ''
            refs = split_ref_designators(ref_des_val)
            if not refs:
                self.bom_missing_ref_rows.append((excel_row, ref_des_val))
            for r in refs:
                # Normalize RefDes for consistent matching (case-insensitive, strip whitespace)
                r_canon = canonicalize_refdes(r)
                all_bom_refs.append(r_canon)
                if r_canon not in self.bom_index:
                    self.bom_index[r_canon] = row._asdict()
                else:
                    # Log first few duplicate warnings (avoid log spam)
                    if len(bom_dupe_warnings) < 10:
                        first_row = self.bom_index[r_canon].get('Index', '?')
                        bom_dupe_warnings.append(f"'{r}' at row {excel_row} (first at row {first_row + 2})")
        dupes = [k for k, v in Counter(all_bom_refs).items() if v > 1]
        self.bom_duplicate_refdes = [(k, Counter(all_bom_refs)[k]) for k in dupes]

        # Build usage base counts for part usage validation
        # Each RefDes maps to a usage base (stripping all suffixes including pins)
        self.usage_base_counts = Counter(get_usage_base_refdes(r) for r in all_bom_refs)

        # Log BOM duplicate warnings if any
        if bom_dupe_warnings:
            self.log(f"WARNING: {len(dupes)} duplicate RefDes in BOM. First occurrence used; duplicates ignored. See BOM_Duplicate_Refs sheet.", "WARNING")
            for warn in bom_dupe_warnings[:5]:  # Show max 5
                self.log(f"  - Duplicate: {warn}")
            if len(bom_dupe_warnings) > 5:
                self.log(f"  ... and {len(dupes) - 5} more (see BOM_Duplicate_Refs sheet)")

        self.hda_index = {}
        hda_dupe_warnings = []  # Track duplicates for logging
        if 'part_number' in hda_df.columns:
            hda_df['canon_pn'] = hda_df['part_number'].apply(canonical_pn)
            for idx, row in enumerate(hda_df.itertuples()):
                if idx % INDEX_CANCEL_CHECK_INTERVAL == 0:
                    self.cancel.check()

                cpn = getattr(row, 'canon_pn', '')
                if cpn:
                    if cpn not in self.hda_index:
                        self.hda_index[cpn] = row._asdict()  # First occurrence wins (consistent with BOM)
                    elif len(hda_dupe_warnings) < 10:
                        hda_dupe_warnings.append(cpn)

        # Log HDA duplicate warnings if any
        if hda_dupe_warnings:
            self.log(f"WARNING: {len(hda_dupe_warnings)}+ duplicate PNs found in HDA (keeping first occurrence)")
            for pn in hda_dupe_warnings[:5]:
                self.log(f"  - Duplicate PN: {pn}")

        self.fm_index.clear()
        self.fm_c1_set = set()
        self.fm_c1_to_c2 = defaultdict(set)
        for idx, row in enumerate(fm_df.itertuples()):
            if idx % INDEX_CANCEL_CHECK_INTERVAL == 0:
                self.cancel.check()

            c1 = clean_string(getattr(row, 'commodity_level1', '')).lower()
            c2 = clean_string(getattr(row, 'commodity_level2', '')).lower()
            self.fm_index[(c1, c2)].append(row._asdict())
            if c1:
                self.fm_c1_set.add(c1)
                if c2:
                    self.fm_c1_to_c2[c1].add(c2)

    def _resolve_hda_dataframe(
        self,
        hda_path: Optional[Union[str, Path]],
        bom_raw_df: pd.DataFrame,
        col_overrides: Optional[Dict[str, str]] = None,
        hda_sheet: Optional[str] = None,
    ) -> pd.DataFrame:
        if hda_path:
            self.log("Loading dedicated HDA file...")
            hda_df = self.read_excel_safe(hda_path, sheet_name=hda_sheet)
            # Codex Finding #1: Separate HDA file should require commodity columns
            # (that's the whole point of HDA files - to provide commodity mappings)
            required_for_hda_file = ['part_number', 'commodity_level1', 'commodity_level2']
            h_map = self.map_columns(hda_df, HEADER_CONFIG['HDA'], required_for_hda_file, source_name="HDA file", overrides=col_overrides)
            renamed = hda_df.rename(columns={v: k for k, v in h_map.items()})
            ensure_columns_exist(renamed, required_for_hda_file, "HDA file")
            return renamed
        self.log("HDA file not provided. Detecting inline HDA columns inside BOM...", "INFO")
        try:
            h_map = self.map_columns(bom_raw_df, HEADER_CONFIG['HDA'], REQUIRED_COLS['HDA'],
                                     source_name="BOM file (inline HDA columns)", overrides=col_overrides)
        except ColumnMappingError:
            raise ColumnMappingError("part_number", "BOM file (inline HDA)")
        renamed = bom_raw_df.rename(columns={v: k for k, v in h_map.items()})
        required_cols = ['part_number', 'commodity_level1', 'commodity_level2', 'description', 'fmd_type1', 'fmd_type2']
        # Issue 4 fix: Log warning for missing columns instead of silent empty
        missing_cols = [col for col in required_cols if col not in renamed.columns]
        if missing_cols:
            self.log(f"WARNING: BOM missing inline HDA columns: {', '.join(missing_cols)}. These default to empty, which may prevent failure mode matching. Consider using a separate HDA file.", "WARNING")
        for col in required_cols:
            if col not in renamed.columns:
                renamed[col] = ''
        self.log("Inline HDA data detected.", "INFO")
        return renamed[required_cols].copy()

    def _describe_fmea_id_mismatch(self, new_id: str, old_id: str) -> str:
        new_id = clean_string(new_id)
        old_id = clean_string(old_id)
        if not new_id or not old_id or new_id == old_id:
            return ''
        new_parts = new_id.split('-')
        old_parts = old_id.split('-')
        if len(new_parts) >= 3 and len(old_parts) >= 3:
            if new_parts[-2:] == old_parts[-2:] and '-'.join(new_parts[:-2]) != '-'.join(old_parts[:-2]):
                return (
                    f"Piece-Part merge found matching RefDes row but the FMEA ID lineage differs: "
                    f"new '{new_id}' vs old '{old_id}'."
                )
        return f"Piece-Part merge found different FMEA IDs for the matched row: new '{new_id}' vs old '{old_id}'."

    def _log_merge_summary(self, merge_type: str) -> None:
        result = self.merge_results.get(merge_type)
        if result is None:
            return
        label = "Functional merge" if merge_type == MERGE_FUNCTIONAL else "Piece-Part merge"
        self.log(
            f"{label} summary: copied {result.copied_count} row(s), skipped {result.skipped_count} row(s), "
            f"{result.warning_count} warning(s), {result.error_count} error(s)."
        )
        for issue in result.issue_rows[:MAX_MERGE_DETAIL_LOGS]:
            level = 'INFO'
            if issue.severity == 'warning':
                level = 'WARNING'
            elif issue.severity == 'error':
                level = 'ERROR'
            self.log(f"{label}: {issue.message} Action: {issue.action}", level)
        remaining = len(result.issue_rows) - MAX_MERGE_DETAIL_LOGS
        if remaining > 0:
            self.log(
                f"{label}: omitted {remaining} additional issue log(s) from the live log. "
                "Review the merge report sheet in the output workbook for full details.",
                "WARNING",
            )

    def _apply_functional_merge(
        self,
        group_rows: List[Dict[str, Any]],
        group_row: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        if not group_rows:
            return group_rows

        grp_id = clean_string(group_row.get('component_group'))
        refs = clean_string(group_row.get('ref_des'))
        base_key = normalize_func_base_id(grp_id)
        source_rows = self.functional_rows_by_base.get(base_key, [])
        result = self._get_merge_result(MERGE_FUNCTIONAL)

        if not source_rows:
            result.skipped_count += 1
            self._record_merge_issue(
                'missing_source_match',
                'info',
                MERGE_FUNCTIONAL,
                {
                    'entity_key': grp_id,
                    'field': 'Function ID',
                    'message': f"No functional merge source rows matched circuit block '{grp_id}'.",
                    'action': 'Kept the generated circuit-block row without merged effects.',
                    'target_row': clean_string(group_rows[0].get('FMEA-ID')),
                },
            )
            return group_rows

        unique_ids = {item['function_id'] for item in source_rows}
        needs_auto_suffix = len(unique_ids) == 1 and len(source_rows) > 1
        merged_rows: List[Dict[str, Any]] = []
        for idx, source_row in enumerate(source_rows):
            self.cancel.check("Functional merge cancelled by user.")
            row = group_rows[0].copy()
            if needs_auto_suffix:
                suffix = _index_to_suffix(idx)
                row['FMEA-ID'] = f"{source_row['function_id']}-{suffix}"
            else:
                row['FMEA-ID'] = source_row['function_id']
            row['Failure Mode'] = source_row['failure_mode']
            row['Failure Mode Causes'] = refs
            copied_fields = self._copy_effect_fields(row, source_row)
            row['FuncFM Source Row'] = source_row['src_idx']
            row['FuncFM Key'] = source_row['source_key']
            row['FuncFM Hash'] = source_row['source_key']
            merged_rows.append(row)
            if copied_fields:
                result.copied_count += 1
            else:
                result.skipped_count += 1
        return merged_rows

    def _build_piecepart_target_rows(self, output_rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        rows_by_refdes: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        raw_values_by_refdes: Dict[str, set] = defaultdict(set)

        for idx, row in enumerate(output_rows):
            if idx % MERGE_CANCEL_CHECK_INTERVAL == 0:
                self.cancel.check("Piece-Part merge cancelled by user.")
                time.sleep(0)  # Yield GIL so UI thread can repaint
            if self._normalize_merge_text(row.get('FMEA Level')) != 'piece-part':
                continue
            refs = split_ref_designators(row.get('Failure Mode Causes', ''))
            if len(refs) != 1:
                continue
            ref_raw = clean_string(refs[0])
            ref_canon = canonicalize_refdes(ref_raw)
            raw_values_by_refdes[ref_canon].add(ref_raw)
            rows_by_refdes[ref_canon].append({
                'row': row,
                'target_index': idx,
                'target_row': idx + 2,
                'target_order': len(rows_by_refdes[ref_canon]),
                'ref_des': ref_raw,
                'ref_des_canon': ref_canon,
                'failure_mode': clean_string(row.get('Failure Mode')),
                'failure_mode_norm': self._normalize_merge_text(row.get('Failure Mode')),
                'fmea_id': clean_string(row.get('FMEA-ID')),
                'part_number': clean_string(row.get('Component Part Number')),
                'part_number_canon': canonical_pn(row.get('Component Part Number')),
                'part_usage': row.get('Part Usage', ''),
                'part_usage_value': self._parse_usage_value_for_merge(row.get('Part Usage', '')),
            })

        for ref_canon, raw_values in raw_values_by_refdes.items():
            if len(raw_values) > 1:
                self._record_merge_issue(
                    'ambiguous_source_match',
                    'warning',
                    MERGE_PIECEPART,
                    {
                        'entity_key': ref_canon,
                        'field': 'Reference Designator',
                        'message': (
                            f"Generated FMEA rows use multiple raw reference designators ({', '.join(sorted(raw_values))}) "
                            f"that normalize to '{ref_canon}'."
                        ),
                        'action': 'Merge continues using normalized matching.',
                    },
                )

        return rows_by_refdes

    def _apply_piecepart_merge(
        self,
        output_rows: List[Dict[str, Any]],
        source_rows_by_refdes: Dict[str, List[Dict[str, Any]]],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        result = self._get_merge_result(MERGE_PIECEPART)
        target_rows_by_refdes = self._build_piecepart_target_rows(output_rows)

        for idx, (refdes, target_rows) in enumerate(target_rows_by_refdes.items()):
            if idx % MERGE_CANCEL_CHECK_INTERVAL == 0:
                self.cancel.check("Piece-Part merge cancelled by user.")
                time.sleep(0)  # Yield GIL so UI thread can repaint
            mode_counts = Counter(item['failure_mode_norm'] for item in target_rows if item['failure_mode_norm'])
            for failure_mode_norm, count in mode_counts.items():
                if count > 1:
                    self._record_merge_issue(
                        'duplicate_target_rows',
                        'error',
                        MERGE_PIECEPART,
                        {
                            'entity_key': refdes,
                            'field': 'Failure Mode',
                            'new_value': failure_mode_norm,
                            'message': (
                                f"Generated FMEA contains {count} piece-part rows for '{refdes}' with the same failure mode '{failure_mode_norm}'."
                            ),
                            'action': 'Skipped effect copy for the duplicated failure mode; unambiguous matches for other failure modes may still proceed.',
                        },
                    )

        total_source_refdes = len(source_rows_by_refdes)
        for idx, (refdes, source_rows) in enumerate(source_rows_by_refdes.items()):
            if idx % MERGE_CANCEL_CHECK_INTERVAL == 0:
                self.cancel.check("Piece-Part merge cancelled by user.")
                time.sleep(0)  # Yield GIL so UI thread can repaint
                if progress_callback:
                    progress_callback(idx + 1, total_source_refdes)
            target_rows = target_rows_by_refdes.get(refdes, [])
            if not target_rows:
                for source_row in source_rows:
                    result.skipped_count += 1
                    self._record_merge_issue(
                        'unmatched_legacy_source_row',
                        'warning',
                        MERGE_PIECEPART,
                        {
                            'entity_key': refdes,
                            'field': 'Reference Designator',
                            'old_value': source_row['ref_des'],
                            'message': (
                                f"Piece-Part merge source row {source_row['source_row']} for '{source_row['ref_des']}' "
                                "does not exist in the newly generated FMEA."
                            ),
                            'action': 'No effects were copied from this old piece-part row.',
                            'source_row': str(source_row['source_row']),
                        },
                    )
                continue

            source_mode_counts = Counter(item['failure_mode_norm'] for item in source_rows if item['failure_mode_norm'])
            for failure_mode_norm, count in source_mode_counts.items():
                if count > 1:
                    self._record_merge_issue(
                        'duplicate_source_rows',
                        'error',
                        MERGE_PIECEPART,
                        {
                            'entity_key': refdes,
                            'field': 'Failure Mode',
                            'old_value': failure_mode_norm,
                            'message': (
                                f"Piece-Part merge source contains {count} rows for '{refdes}' with the same failure mode '{failure_mode_norm}'."
                            ),
                            'action': 'Skipped effect copy for the duplicated failure mode; unambiguous matches for other failure modes may still proceed.',
                        },
                    )

            if len(source_rows) != len(target_rows):
                self._record_merge_issue(
                    'failure_mode_count_mismatch',
                    'warning',
                    MERGE_PIECEPART,
                    {
                        'entity_key': refdes,
                        'field': 'Failure Mode count',
                        'new_value': str(len(target_rows)),
                        'old_value': str(len(source_rows)),
                        'message': (
                            f"Piece-Part merge found a different number of failure mode rows for '{refdes}': "
                            f"new FMEA has {len(target_rows)}, old FMEA has {len(source_rows)}."
                        ),
                        'action': 'Used exact failure-mode name matches only. Row-order matching was not used because row counts differ.',
                    },
                )

            source_modes = {item['failure_mode_norm'] for item in source_rows if item['failure_mode_norm']}
            target_modes = {item['failure_mode_norm'] for item in target_rows if item['failure_mode_norm']}
            if source_modes != target_modes:
                self._record_merge_issue(
                    'failure_mode_set_mismatch',
                    'warning',
                    MERGE_PIECEPART,
                    {
                        'entity_key': refdes,
                        'field': 'Failure Mode',
                        'new_value': ', '.join(sorted(target_modes)) or '(blank)',
                        'old_value': ', '.join(sorted(source_modes)) or '(blank)',
                        'message': (
                            f"Piece-Part merge found different failure mode names for '{refdes}' between the new and old FMEAs."
                        ),
                        'action': 'Used exact failure-mode name matches where possible. For unmatched rows, copied effects by row order (safe: row counts match and no duplicates exist).',
                    },
                )

            matched_source_indices = set()
            matched_target_indices = set()
            target_by_mode: Dict[str, List[int]] = defaultdict(list)
            source_by_mode: Dict[str, List[int]] = defaultdict(list)
            for idx, target_row in enumerate(target_rows):
                target_by_mode[target_row['failure_mode_norm']].append(idx)
            for idx, source_row in enumerate(source_rows):
                source_by_mode[source_row['failure_mode_norm']].append(idx)

            mapping_pairs: List[Tuple[int, int, str]] = []
            ambiguous = False

            for failure_mode_norm, source_indexes in source_by_mode.items():
                if not failure_mode_norm:
                    continue
                target_indexes = target_by_mode.get(failure_mode_norm, [])
                if len(source_indexes) == 1 and len(target_indexes) == 1:
                    mapping_pairs.append((source_indexes[0], target_indexes[0], 'exact_failure_mode'))
                    matched_source_indices.add(source_indexes[0])
                    matched_target_indices.add(target_indexes[0])
                elif source_indexes and target_indexes:
                    ambiguous = True
                    for source_idx in source_indexes:
                        source_row = source_rows[source_idx]
                        self._record_merge_issue(
                            'ambiguous_source_match',
                            'error',
                            MERGE_PIECEPART,
                            {
                                'entity_key': refdes,
                                'field': 'Failure Mode',
                                'old_value': source_row['failure_mode'],
                                'message': (
                                    f"Piece-Part merge found more than one possible target row for '{refdes}' "
                                    f"with failure mode '{source_row['failure_mode']}'."
                                ),
                                'action': 'Skipped copying effects for the ambiguous row.',
                                'source_row': str(source_row['source_row']),
                            },
                        )

            remaining_source = [idx for idx in range(len(source_rows)) if idx not in matched_source_indices]
            remaining_target = [idx for idx in range(len(target_rows)) if idx not in matched_target_indices]
            can_fallback = (
                not ambiguous
                and len(source_rows) == len(target_rows)
                and len(remaining_source) == len(remaining_target)
                and not any(count > 1 for count in source_mode_counts.values())
                and not any(count > 1 for count in (Counter(item['failure_mode_norm'] for item in target_rows if item['failure_mode_norm']).values()))
            )

            if can_fallback and remaining_source:
                source_sorted = sorted(remaining_source, key=lambda idx: source_rows[idx]['source_order'])
                target_sorted = sorted(remaining_target, key=lambda idx: target_rows[idx]['target_order'])
                for source_idx, target_idx in zip(source_sorted, target_sorted):
                    mapping_pairs.append((source_idx, target_idx, 'ordinal_fallback'))
                    matched_source_indices.add(source_idx)
                    matched_target_indices.add(target_idx)

            for source_idx, target_idx, match_method in mapping_pairs:
                source_row = source_rows[source_idx]
                target_row = target_rows[target_idx]
                target_ref = target_row['row']
                copied_fields = self._copy_effect_fields(target_ref, source_row)
                if copied_fields:
                    result.copied_count += 1
                else:
                    result.skipped_count += 1

                new_fmea_id = target_row['fmea_id']
                old_fmea_id = source_row['fmea_id']
                if new_fmea_id and old_fmea_id and new_fmea_id != old_fmea_id:
                    self._record_merge_issue(
                        'fmea_id_mismatch',
                        'warning',
                        MERGE_PIECEPART,
                        {
                            'entity_key': refdes,
                            'field': 'FMEA ID',
                            'new_value': new_fmea_id,
                            'old_value': old_fmea_id,
                            'message': self._describe_fmea_id_mismatch(new_fmea_id, old_fmea_id),
                            'action': 'Copied the effect fields because the row match was otherwise safe.',
                            'source_row': str(source_row['source_row']),
                            'target_row': str(target_row['target_row']),
                            'target_row_ref': target_ref,
                        },
                    )

                if source_row['part_number_canon'] and target_row['part_number_canon'] and source_row['part_number_canon'] != target_row['part_number_canon']:
                    self._record_merge_issue(
                        'part_number_mismatch',
                        'warning',
                        MERGE_PIECEPART,
                        {
                            'entity_key': refdes,
                            'field': 'Part Number',
                            'new_value': target_row['part_number'],
                            'old_value': source_row['part_number'],
                            'message': (
                                f"Piece-Part merge found a part number mismatch for '{refdes}': "
                                f"new '{target_row['part_number']}' vs old '{source_row['part_number']}'."
                            ),
                            'action': 'Copied the effect fields because the row match was otherwise safe.',
                            'source_row': str(source_row['source_row']),
                            'target_row': str(target_row['target_row']),
                            'target_row_ref': target_ref,
                        },
                    )

                old_usage = source_row['part_usage_value']
                new_usage = target_row['part_usage_value']
                if old_usage is not None and new_usage is not None and abs(old_usage - new_usage) > USAGE_TOLERANCE:
                    self._record_merge_issue(
                        'part_usage_mismatch',
                        'warning',
                        MERGE_PIECEPART,
                        {
                            'entity_key': refdes,
                            'field': 'Part Usage',
                            'new_value': str(target_row['part_usage']),
                            'old_value': str(source_row['part_usage']),
                            'message': (
                                f"Piece-Part merge found a part usage mismatch for '{refdes}': "
                                f"new '{target_row['part_usage']}' vs old '{source_row['part_usage']}'."
                            ),
                            'action': 'Copied the effect fields because the row match was otherwise safe.',
                            'source_row': str(source_row['source_row']),
                            'target_row': str(target_row['target_row']),
                            'target_row_ref': target_ref,
                        },
                    )

                if match_method == 'ordinal_fallback':
                    self._record_merge_issue(
                        'ordinal_fallback_applied',
                        'warning',
                        MERGE_PIECEPART,
                        {
                            'entity_key': refdes,
                            'field': 'Failure Mode',
                            'new_value': target_row['failure_mode'],
                            'old_value': source_row['failure_mode'],
                            'message': (
                                f"Piece-Part merge used safe row-order fallback for '{refdes}' because exact failure mode names "
                                f"did not align: new '{target_row['failure_mode']}' vs old '{source_row['failure_mode']}'."
                            ),
                            'action': 'Copied effect fields by matching row order (failure mode names differ but position is unambiguous).',
                            'source_row': str(source_row['source_row']),
                            'target_row': str(target_row['target_row']),
                            'target_row_ref': target_ref,
                        },
                    )

                if not copied_fields:
                    self._record_merge_issue(
                        'blank_effects_in_source',
                        'warning',
                        MERGE_PIECEPART,
                        {
                            'entity_key': refdes,
                            'field': 'effects',
                            'message': (
                                f"Piece-Part merge matched '{refdes}' but source row {source_row['source_row']} had no effect text to copy."
                            ),
                            'action': 'Left the generated effect cells unchanged.',
                            'source_row': str(source_row['source_row']),
                            'target_row': str(target_row['target_row']),
                            'target_row_ref': target_ref,
                        },
                    )

            unmatched_source = [idx for idx in range(len(source_rows)) if idx not in matched_source_indices]
            unmatched_target = [idx for idx in range(len(target_rows)) if idx not in matched_target_indices]
            for source_idx in unmatched_source:
                source_row = source_rows[source_idx]
                result.skipped_count += 1
                self._record_merge_issue(
                    'missing_source_match',
                    'warning',
                    MERGE_PIECEPART,
                    {
                        'entity_key': refdes,
                        'field': 'Failure Mode',
                        'old_value': source_row['failure_mode'],
                        'message': (
                            f"Piece-Part merge could not find a safe target row for old row {source_row['source_row']} "
                            f"('{refdes}' / '{source_row['failure_mode']}')."
                        ),
                        'action': 'Skipped copying effects for this unmatched old row.',
                        'source_row': str(source_row['source_row']),
                    },
                )
            for target_idx in unmatched_target:
                target_row = target_rows[target_idx]
                result.skipped_count += 1
                self._record_merge_issue(
                    'missing_source_match',
                    'warning',
                    MERGE_PIECEPART,
                    {
                        'entity_key': refdes,
                        'field': 'Failure Mode',
                        'new_value': target_row['failure_mode'],
                        'message': (
                            f"Piece-Part merge found no matching old row for generated row {target_row['target_row']} "
                            f"('{refdes}' / '{target_row['failure_mode']}')."
                        ),
                        'action': 'Left the generated effect cells unchanged.',
                        'target_row': str(target_row['target_row']),
                        'target_row_ref': target_row['row'],
                    },
                )

    def _build_merge_summary_sheets(self) -> Dict[str, pd.DataFrame]:
        summaries: Dict[str, pd.DataFrame] = {}
        summary_rows = []
        for merge_type, result in self.merge_results.items():
            summary_rows.append({
                'Merge Type': 'Functional Merge' if merge_type == MERGE_FUNCTIONAL else 'Piece-Part Merge',
                'Copied Rows': result.copied_count,
                'Skipped Rows': result.skipped_count,
                'Warnings': result.warning_count,
                'Errors': result.error_count,
                'Issue Rows': len(result.issue_rows),
            })
            if result.issue_rows:
                report_rows = [{
                    'Severity': issue.severity.title(),
                    'Issue Type': issue.kind,
                    'Entity Key': issue.entity_key,
                    'Field': issue.field,
                    'New Value': issue.new_value,
                    'Old Value': issue.old_value,
                    'What Is Wrong': issue.message,
                    'Merge Action': issue.action,
                    'Source Row': issue.source_row,
                    'Target Row': issue.target_row,
                } for issue in result.issue_rows]
                sheet_name = 'Functional_Merge_Report' if merge_type == MERGE_FUNCTIONAL else 'PiecePart_Merge_Report'
                summaries[sheet_name] = pd.DataFrame(report_rows)
        if summary_rows:
            summaries['Merge_Summary'] = pd.DataFrame(summary_rows)
        return summaries

    def process(
        self,
        inputs: Dict[str, Any],
        progress_callback: Optional[Callable[[int, int], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> pd.DataFrame:
        with self._lock:
            # NOTE: cancel.reset() removed for Tauri sidecar — each run creates a fresh
            # FMEAProcessor, so the token starts clean. Resetting here would race with
            # cancel signals applied via bind_processor() before process() begins.
            self._reset_state()
            self.verbose = bool(inputs.get('verbose'))
            self.bom_only_mode = bool(inputs.get('bom_only_mode'))

        # Extract column overrides (format: {'FILE_TYPE': {'internal_key': 'actual_col_name'}})
        col_overrides = inputs.get('column_overrides') or {}

        if status_callback:
            status_callback("Reading input files...")
        self.log("Reading Input Files...")
        group_df = None
        if not self.bom_only_mode: group_df = self.read_excel_safe(inputs['group'], sheet_name=inputs.get('group_sheet'))
        bom_raw = self.read_excel_safe(inputs['bom'], sheet_name=inputs.get('bom_sheet'))
        fm_df = self.read_excel_safe(inputs['fm'], sheet_name=inputs.get('fm_sheet'))
        hda_df = self._resolve_hda_dataframe(inputs.get('hda'), bom_raw, col_overrides.get('HDA'), inputs.get('hda_sheet'))

        functional_df = self._load_merge_source_df(
            FUNCTIONAL_MERGE_SPEC,
            inputs,
            col_overrides.get(FUNCTIONAL_MERGE_SPEC.config_key) or col_overrides.get('FUNCTIONAL'),
        )
        piecepart_df = self._load_merge_source_df(
            PIECEPART_MERGE_SPEC,
            inputs,
            col_overrides.get(PIECEPART_MERGE_SPEC.config_key),
        )
        piecepart_source_rows = {}
        if piecepart_df is not None:
            piecepart_source_rows = self._normalize_merge_source_rows(piecepart_df, PIECEPART_MERGE_SPEC)

        if group_df is not None:
            g_map = self.map_columns(group_df, HEADER_CONFIG['COMPONENT_GROUPING'], REQUIRED_COLS['COMPONENT_GROUPING'],
                                     source_name="Component Grouping file", overrides=col_overrides.get('COMPONENT_GROUPING'))
            group_df = group_df.rename(columns={v:k for k,v in g_map.items()})
            ensure_columns_exist(group_df, REQUIRED_COLS['COMPONENT_GROUPING'], "Component Grouping file")

        b_map = self.map_columns(bom_raw, HEADER_CONFIG['BOM'], REQUIRED_COLS['BOM'],
                                 source_name="BOM file", overrides=col_overrides.get('BOM'))
        bom_df = bom_raw.rename(columns={v:k for k,v in b_map.items()})
        ensure_columns_exist(bom_df, REQUIRED_COLS['BOM'], "BOM file")

        f_map = self.map_columns(fm_df, HEADER_CONFIG['FAILURE_MODES'], REQUIRED_COLS['FAILURE_MODES'],
                                 source_name="Failure Modes file", overrides=col_overrides.get('FAILURE_MODES'))
        fm_df = fm_df.rename(columns={v:k for k,v in f_map.items()})
        ensure_columns_exist(fm_df, REQUIRED_COLS['FAILURE_MODES'], "Failure Modes file")

        if status_callback:
            status_callback("Building indexes...")
        self.log("Building indexes...")
        self._build_indexes(bom_df, hda_df, fm_df, functional_df)

        output_rows = []
        if status_callback:
            status_callback("Generating FMEA rows...")
        if self.bom_only_mode:
            total = len(bom_df)
            self.log(f"Processing {total} BOM rows...")
            # C4: Use enumerate with start=2 for Excel row numbers (header is row 1)
            for excel_row, row in enumerate(bom_df.itertuples(), start=2):
                self.cancel.check("Processing cancelled by user.")
                if progress_callback:
                    progress_callback(excel_row - 1, total)  # Progress is 1-indexed
                output_rows.extend(self._generate_bom_only_rows(row._asdict(), fm_df, excel_row))
        else:
            total = len(group_df)
            self.log(f"Processing {total} Groups...")
            for idx, row in enumerate(group_df.itertuples()):
                self.cancel.check("Processing cancelled by user.")
                if progress_callback:
                    progress_callback(idx + 1, total)
                row_dict = row._asdict()
                grp_id = clean_string(row_dict.get('component_group'))
                if not grp_id:
                    continue
                group_rows = self._generate_group_rows(row_dict)
                if inputs.get('use_func'):
                    group_rows = self._apply_functional_merge(group_rows, row_dict)
                output_rows.extend(group_rows)
                for ref in split_ref_designators(row_dict.get('ref_des')):
                    output_rows.extend(self._generate_component_rows(ref, row_dict, fm_df))

        if piecepart_source_rows:
            if status_callback:
                status_callback("Applying Piece-Part effect merge...")
            self.log("Applying Piece-Part effect merge...")
            self._apply_piecepart_merge(output_rows, piecepart_source_rows, progress_callback=progress_callback)

        if functional_df is not None:
            self._log_merge_summary(MERGE_FUNCTIONAL)
        if piecepart_df is not None:
            self._log_merge_summary(MERGE_PIECEPART)

        self.log(f"Results: {len(self.successful_matches)} components matched | {len(self.no_matches)} with no failure modes (see No_Matches sheet)", "INFO")
        return pd.DataFrame(output_rows)

    def process_gaps(
        self,
        inputs: Dict[str, Any],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> pd.DataFrame:
        """
        Generate FMEA rows for RefDes in BOM but not in existing FMEA (Fill Gaps mode).

        This mode finds components in the BOM that are missing from an existing FMEA
        and generates complete FMEA piece-part rows for them.

        Required inputs:
            - 'fmea': Path to existing FMEA file
            - 'bom': Path to BOM/PL file
            - 'fm': Path to Failure Modes file

        Optional inputs:
            - 'hda': Path to HDA file
            - 'group': Path to Grouping file (for circuit block assignment)
            - 'fmea_refdes_col': Column name for RefDes in FMEA (auto-detected if not provided)

        Returns:
            DataFrame with generated FMEA rows for missing RefDes
        """
        # Import FMEA detection utilities from common (Refinement 1: avoid app-to-app coupling)
        from common.fmea_utils import detect_refdes_column_for_fmea, classify_fmea_rows

        with self._lock:
            # NOTE: cancel.reset() removed for Tauri sidecar — each run creates a fresh
            # FMEAProcessor, so the token starts clean. Resetting here would race with
            # cancel signals applied via bind_processor() before process_gaps() begins.
            self._reset_state()
            self.verbose = bool(inputs.get('verbose', False))

        # Extract column overrides (format: {'FILE_TYPE': {'internal_key': 'actual_col_name'}})
        col_overrides = inputs.get('column_overrides') or {}

        # 1. Load files
        self.log("Loading input files...")
        fmea_df = self.read_excel_safe(inputs['fmea'], sheet_name=inputs.get('fmea_sheet'))
        bom_raw = self.read_excel_safe(inputs['bom'], sheet_name=inputs.get('bom_sheet'))
        fm_df = self.read_excel_safe(inputs['fm'], sheet_name=inputs.get('fm_sheet'))
        hda_df = self._resolve_hda_dataframe(inputs.get('hda'), bom_raw, col_overrides.get('HDA'), inputs.get('hda_sheet'))

        # 2. Auto-detect FMEA RefDes column
        fmea_refdes_col = inputs.get('fmea_refdes_col')
        if not fmea_refdes_col:
            fmea_refdes_col = detect_refdes_column_for_fmea(fmea_df, self.log)
        if not fmea_refdes_col:
            raise ColumnMappingError("RefDes", "FMEA file", tried_synonyms=["Reference Designator", "Failure Mode Causes", "RefDes"])

        self.log(f"Using FMEA RefDes column: '{fmea_refdes_col}'")

        # 3. Classify FMEA rows to extract piece-part RefDes only
        self.log("Classifying FMEA rows...")
        classifications, level_col, _ = classify_fmea_rows(fmea_df, self.log, self.cancel)

        # Refinement 2: Use position-based iteration (safer than row_index - 2)
        existing_refdes = set()
        for pos, (df_idx, row) in enumerate(fmea_df.iterrows()):
            if pos < len(classifications) and classifications[pos].row_type == 'piece_part':
                val = row.get(fmea_refdes_col)
                if pd.notna(val):
                    for ref in split_refdes_list(str(val)):
                        existing_refdes.add(canonicalize_refdes(ref))

        self.log(f"Found {len(existing_refdes)} unique piece-part RefDes in existing FMEA")

        # 4. Extract BOM RefDes (normalized)
        b_map = self.map_columns(bom_raw, HEADER_CONFIG['BOM'], REQUIRED_COLS['BOM'],
                                 source_name="BOM file", overrides=col_overrides.get('BOM'))
        bom_df = bom_raw.rename(columns={v: k for k, v in b_map.items()})

        bom_refdes = set()
        for val in bom_df['ref_des'].dropna():
            for ref in split_refdes_list(str(val)):
                bom_refdes.add(canonicalize_refdes(ref))

        self.log(f"Found {len(bom_refdes)} unique RefDes in BOM")

        # 5. Find gaps
        missing_refdes = sorted(bom_refdes - existing_refdes)
        self.log(f"Found {len(missing_refdes)} RefDes in BOM but not in FMEA")

        if not missing_refdes:
            self.log("No gaps found - FMEA is complete!", "INFO")
            return pd.DataFrame()

        # 6. Build RefDes→Group lookup (optional Grouping file)
        refdes_to_group = {}
        group_conflicts = []  # Refinement 3: track conflicts
        if inputs.get('group'):
            self.log("Loading Grouping file for circuit block assignment...")
            group_df = self.read_excel_safe(inputs['group'], sheet_name=inputs.get('group_sheet'))
            g_map = self.map_columns(group_df, HEADER_CONFIG['COMPONENT_GROUPING'],
                                     REQUIRED_COLS['COMPONENT_GROUPING'],
                                     source_name="Grouping file", overrides=col_overrides.get('COMPONENT_GROUPING'))
            group_df = group_df.rename(columns={v: k for k, v in g_map.items()})

            for _, row in group_df.iterrows():
                grp_id = clean_string(row.get('component_group'))
                grp_desc = clean_string(row.get('description', ''))
                grp_page = clean_string(row.get('schematic_page', ''))
                for ref in split_refdes_list(row.get('ref_des', '')):
                    ref_canon = canonicalize_refdes(ref)
                    if ref_canon in refdes_to_group:
                        # Refinement 3: Log conflict, keep first (consistent with BOM)
                        if len(group_conflicts) < 10:
                            existing_grp = refdes_to_group[ref_canon]['component_group']
                            group_conflicts.append(f"{ref}: '{existing_grp}' vs '{grp_id}'")
                    else:
                        refdes_to_group[ref_canon] = {
                            'component_group': grp_id,
                            'description': grp_desc,
                            'schematic_page': grp_page
                        }

            if group_conflicts:
                self.log(f"WARNING: {len(group_conflicts)}+ RefDes in multiple groups (using first)", "WARNING")
                for conflict in group_conflicts[:5]:
                    self.log(f"  - {conflict}")

            self.log(f"Loaded {len(refdes_to_group)} RefDes→Group mappings")

        # 7. Map FM columns and build indexes
        f_map = self.map_columns(fm_df, HEADER_CONFIG['FAILURE_MODES'], REQUIRED_COLS['FAILURE_MODES'],
                                 source_name="Failure Modes file", overrides=col_overrides.get('FAILURE_MODES'))
        fm_df = fm_df.rename(columns={v: k for k, v in f_map.items()})

        self._build_indexes(bom_df, hda_df, fm_df, None)

        # 8. Generate rows for missing RefDes
        self.log("Generating FMEA rows for missing RefDes...")
        output_rows = []
        total = len(missing_refdes)
        for idx, ref_des in enumerate(missing_refdes):
            self.cancel.check()
            if progress_callback:
                progress_callback(idx + 1, total)

            # Use Grouping file mapping if available, otherwise GAP_FILL marker
            group_row = refdes_to_group.get(canonicalize_refdes(ref_des), {
                'component_group': 'GAP_FILL',
                'description': 'Auto-generated to fill FMEA gaps',
                'schematic_page': ''
            })

            rows = self._generate_component_rows(ref_des, group_row, fm_df, mode='standard')

            # Add diagnostic note indicating gap-fill origin
            for row in rows:
                existing_diag = row.get('Diagnostic', '')
                gap_note = "Generated by Fill Gaps mode"
                row['Diagnostic'] = f"{gap_note}; {existing_diag}" if existing_diag else gap_note

            output_rows.extend(rows)

        self.log(f"Generated {len(output_rows)} FMEA rows for {len(missing_refdes)} missing RefDes")
        return pd.DataFrame(output_rows)

    def _generate_group_rows(
        self,
        group_row: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        rows = []
        grp_id = clean_string(group_row.get('component_group'))
        desc = clean_string(group_row.get('description'))
        page = clean_string(group_row.get('schematic_page'))
        refs = clean_string(group_row.get('ref_des'))
        base_row = {'Schematic Page': page, 'FMEA-ID': grp_id, 'Function Description': desc, 'FMEA Level': 'Circuit Block', 'Failure Mode Causes': refs, '_row_type': 'circuit_block'}
        for k in OUTPUT_HEADERS: 
            if k not in base_row: base_row[k] = ''
        base_row['Failure Mode Causes'] = refs
        rows.append(base_row)
        return rows

    def _format_fmea_id(
        self,
        group_label: str,
        ref_des: str,
        suffix: str,
        mode: str = "standard",
    ) -> str:
        """Format FMEA ID based on mode."""
        return f"{group_label}-{ref_des}{suffix}" if mode == 'bom_only' else f"{group_label}-{ref_des}-{suffix}"

    def _generate_bom_only_rows(
        self,
        bom_row: Dict[str, Any],
        fm_df: pd.DataFrame,
        row_number: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        refs = split_ref_designators(bom_row.get('ref_des'))
        if not refs:
            # _build_indexes() already tracks missing RefDes rows.
            return []
        desc = clean_string(bom_row.get('description')) or clean_string(bom_row.get('part_number'))
        group_stub = {'component_group': 'BOM', 'description': desc, 'schematic_page': ''}
        rows = []
        for ref in refs: rows.extend(self._generate_component_rows(ref, group_stub, fm_df, mode='bom_only'))
        return rows

    def _check_single_usage(self, ref_des: str, usage_value: float) -> Optional[str]:
        """
        Check if usage value is correct for this RefDes based on instance count.

        Uses the usage base (stripping all suffixes including pins) to count
        how many instances exist in the BOM. Expected usage = 1/count.

        Args:
            ref_des: The RefDes being validated
            usage_value: The numeric usage value from the BOM

        Returns:
            Warning string if mismatch, None if OK
        """
        base = get_usage_base_refdes(ref_des)
        count = self.usage_base_counts.get(base, 0)

        if count == 0:
            return None  # Can't validate without data

        expected = 1.0 / count

        if abs(usage_value - expected) > USAGE_TOLERANCE:
            return f"Usage mismatch: expected {expected:.4g} (1/{count}), listed {usage_value:.4g}"

        return None

    def _generate_component_rows(
        self,
        ref_des: str,
        group_row: Dict[str, Any],
        fm_df: pd.DataFrame,
        mode: str = "standard",
    ) -> List[Dict[str, Any]]:
        rows = []
        group_label = clean_string(group_row.get('component_group')) or 'GROUP'
        # Normalize RefDes for lookup (matches normalization used in index building)
        ref_des_canon = canonicalize_refdes(ref_des)
        bom_row = self.bom_index.get(ref_des_canon)
        if bom_row is None:
            self.group_missing_in_bom.append((group_row.get('component_group'), ref_des))
            return []
        pn = clean_string(bom_row.get('part_number'))
        _usage_value, usage_excel = parse_usage(bom_row.get('part_usage', 1))
        if _usage_value is None:
            raw_usage = bom_row.get('part_usage', 1)
            _logger.warning(f"Part Usage '{raw_usage}' for '{ref_des}' could not be parsed. Defaulting to 1.0.")
            _usage_value, usage_excel = 1.0, 1
            self.usage_warnings.append({
                'RefDes': ref_des,
                'Base': get_usage_base_refdes(ref_des),
                'Usage': 1.0,
                'Expected': 'N/A',
                'Count': 0,
                'ReasonCode': 'PU_PARSE_DEFAULTED',
                'Reason': f"Part Usage value '{raw_usage}' could not be parsed. Defaulted to 1.0.",
            })
        desc_bom = clean_string(bom_row.get('description'))
        c1, c2 = clean_string(bom_row.get('hda_level1')), clean_string(bom_row.get('hda_level2'))
        canon = canonical_pn(pn)
        hda_row = self.hda_index.get(canon)
        hda_c1, hda_c2, fmd_c1, fmd_c2 = c1, c2, c1, c2
        desc = desc_bom
        diag_msgs = []

        # Check part usage against expected (1/instance_count)
        usage_warning = self._check_single_usage(ref_des, _usage_value)
        if usage_warning:
            diag_msgs.append(usage_warning)
            # Capture structured usage warning for Validation_Warnings sheet
            base = get_usage_base_refdes(ref_des)
            count = self.usage_base_counts.get(base, 0)
            expected = 1.0 / count if count > 0 else None
            self.usage_warnings.append({
                'RefDes': ref_des,
                'Base': base,
                'Usage': round(_usage_value, 4),
                'Expected': round(expected, 4) if expected else 'N/A',
                'Count': count,
                'ReasonCode': 'PU_EXPECTED_MISMATCH_BASIC',
                'Reason': usage_warning,
            })

        if hda_row is not None:
            hda_c1 = clean_string(hda_row.get('commodity_level1')) or c1
            hda_c2 = clean_string(hda_row.get('commodity_level2')) or c2
            fmd_c1 = clean_string(hda_row.get('fmd_type1')) or hda_c1
            fmd_c2 = clean_string(hda_row.get('fmd_type2')) or hda_c2
            if not desc: desc = clean_string(hda_row.get('description'))
        else:
            self.unmatched_hda.append((ref_des, pn))
            diag_msgs.append(f"Part Number '{pn}' not found in HDA file. Verify the PN exists in your HDA data or provide a separate HDA file.")
        
        matches = self.fm_index.get((fmd_c1.lower(), fmd_c2.lower()), [])
        if not matches and fmd_c1 and not fmd_c2:
            for (k1, k2), v in self.fm_index.items():
                if k1 == fmd_c1.lower(): matches.extend(v)

        # Validate FMR sum for this RefDes (should sum to 1.0)
        has_fmr_issue = False
        if matches:
            fmr_sum = 0.0
            fmr_values = []
            for m in matches:
                ratio_val = m.get('ratio')
                if ratio_val is not None:
                    try:
                        fmr_val = float(ratio_val)
                        fmr_sum += fmr_val
                        fmr_values.append(fmr_val)
                    except (ValueError, TypeError):
                        _logger.warning(
                            f"Non-numeric Failure Mode Ratio '{ratio_val}' skipped for "
                            f"'{ref_des}' (FMD types: '{fmd_c1}'/'{fmd_c2}')"
                        )

            if fmr_values and abs(fmr_sum - 1.0) > FMR_TOLERANCE:
                has_fmr_issue = True
                self.fmr_warnings.append({
                    'RefDes': ref_des,
                    'Sum': round(fmr_sum, 4),
                    'Expected': 1.0,
                    'Ratios': ', '.join(f'{v:.4g}' for v in fmr_values),
                    'Count': len(fmr_values),
                    'ReasonCode': 'FMR_SUM_MISMATCH',
                    'Status': 'Failure Mode Ratio sum does not equal 1.0',
                })

        # Determine if this RefDes has any validation issues (for row highlighting)
        has_validation_issue = has_fmr_issue or (usage_warning is not None)

        base_row = {'Schematic Page': group_row.get('schematic_page'), 'Function Description': group_row.get('description'), 'FMEA Level': 'Piece-Part', 'Failure Mode Causes': ref_des, 'Component Part Number': pn, 'Component Part Description': desc, 'BAE HDA Commodity I': hda_c1, 'BAE HDA Commodity II': hda_c2, 'FMD-2016 Commodity Type 1': fmd_c1, 'FMD-2016 Commodity Type 2': fmd_c2, 'Part Usage': usage_excel, '_row_type': 'piece_part'}
        for k in OUTPUT_HEADERS:
            if k not in base_row: base_row[k] = ''
        
        if not matches:
            if not fmd_c1 and not fmd_c2: reason = "No FMD Commodity Types assigned. Add Commodity Type I/II in the HDA or BOM file."
            elif fmd_c1.lower() not in self.fm_c1_set: reason = f"FMD Type I '{fmd_c1}' not found in Failure Modes file. Verify the type name matches an entry in the Failure Modes file."
            else: reason = f"FMD Type I '{fmd_c1}' exists in Failure Modes file, but the Type I/II pair '{fmd_c1}'/'{fmd_c2}' has no failure modes defined."
            diag_msgs.append(reason)
            self.no_matches.append((ref_des, pn))
            self.no_match_details.append((ref_des, pn, "; ".join(diag_msgs)))
            row = base_row.copy()
            row['FMEA-ID'] = self._format_fmea_id(group_label, ref_des, 'A', mode)
            row['Failure Mode'] = "No failure mode match found"
            row['Diagnostic'] = "; ".join(diag_msgs)
            row['_row_type'] = 'piece_part_no_match'
            rows.append(row)
        else:
            self.successful_matches.append((ref_des, pn))
            letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
            for idx, m in enumerate(matches):
                row = base_row.copy()
                suffix = letters[idx] if idx < ALPHABET_LENGTH else f"Z{idx}"
                row['FMEA-ID'] = self._format_fmea_id(group_label, ref_des, suffix, mode)
                row['Failure Mode'] = m.get('failure_mode')
                row['Failure Mode Ratio'] = m.get('ratio')
                row['Diagnostic'] = "; ".join(diag_msgs)
                # Mark rows with validation issues for yellow highlighting
                if has_validation_issue:
                    row['_row_type'] = 'validation_warning'
                rows.append(row)
        return rows

def write_excel_report(
    df: pd.DataFrame,
    filename: Union[str, Path],
    proc: FMEAProcessor,
) -> None:
    """Write FMEA report with modern styling using shared utility."""
    from openpyxl import Workbook

    # Prepare summary DataFrames
    summaries = {}
    if proc.no_matches:
        summaries['No_Matches'] = pd.DataFrame(proc.no_match_details, columns=['RefDes', 'PN', 'Reason'])
    if proc.unmatched_hda:
        summaries['Missing_HDA'] = pd.DataFrame(proc.unmatched_hda, columns=['RefDes', 'PN'])
    if proc.group_missing_in_bom:
        summaries['Group_Missing_BOM'] = pd.DataFrame(proc.group_missing_in_bom, columns=['Group', 'Missing RefDes'])
    if proc.bom_missing_ref_rows:
        summaries['BOM_Missing_Refs'] = pd.DataFrame(proc.bom_missing_ref_rows, columns=['Row #', 'Raw Value'])
    if proc.bom_duplicate_refdes:
        summaries['BOM_Duplicate_Refs'] = pd.DataFrame(proc.bom_duplicate_refdes, columns=['RefDes', 'Occurrences'])

    # Combine FMR and Usage validation warnings for dedicated sheet
    validation_warnings = []
    for w in proc.fmr_warnings:
        validation_warnings.append({
            'RefDes': w['RefDes'],
            'Reason Code': to_reason_code_label(w.get('ReasonCode', 'FMR_SUM_MISMATCH')),
            'Type': 'Failure Mode Ratio Sum',
            'Issue': f"Sum={w['Sum']} (expected 1.0)",
            'Details': f"Ratios: {w['Ratios']}",
        })
    for w in proc.usage_warnings:
        validation_warnings.append({
            'RefDes': w['RefDes'],
            'Reason Code': to_reason_code_label(w.get('ReasonCode', 'PU_EXPECTED_MISMATCH_BASIC')),
            'Type': 'Part Usage',
            'Issue': f"Usage={w['Usage']} (expected {w['Expected']})",
            'Details': to_user_facing_text(w.get('Reason', '')),
        })
    if validation_warnings:
        summaries['Validation_Warnings'] = pd.DataFrame(validation_warnings)
    summaries.update(proc._build_merge_summary_sheets())

    # Create workbook
    wb = Workbook()
    ws_fmea = wb.active
    ws_fmea.title = "FMEA"

    # Clean FMEA DataFrame (remove internal row type column)
    clean_df = df.drop(columns=[ROW_TYPE_COL], errors='ignore')

    # Row styling based on FMEA row type
    def fmea_row_style(row, idx):
        # M4: Use try-except for safe index access
        try:
            if ROW_TYPE_COL in df.columns and 0 <= idx < len(df):
                rtype = df.iloc[idx][ROW_TYPE_COL]
                if rtype == 'circuit_block':
                    return 'neutral'
                elif rtype == 'piece_part_no_match':
                    return 'error'
                elif rtype == 'validation_warning':
                    return 'warning'  # Yellow highlighting for FMR/usage issues
                elif rtype == 'merge_warning':
                    return 'warning'
                elif rtype == 'merge_error':
                    return 'error'
        except (IndexError, KeyError) as e:
            _logger.debug(f"Row style lookup failed for idx {idx}: {e}")
        return 'default'

    # Write and style FMEA sheet
    write_df_to_sheet(ws_fmea, clean_df)
    style_worksheet(ws_fmea, clean_df, row_style_func=fmea_row_style, max_width=35)

    # Apply fraction format to Part Usage column
    usage_col_idx = None
    for col_idx, col_name in enumerate(clean_df.columns, start=1):
        if col_name == 'Part Usage':
            usage_col_idx = col_idx
            break
    if usage_col_idx:
        for row_idx in range(2, ws_fmea.max_row + 1):
            cell = ws_fmea.cell(row=row_idx, column=usage_col_idx)
            if cell.value is not None and cell.value != '':
                cell.number_format = '# ???/???'

    # Create summary sheets with appropriate styling
    summary_styles = {
        'No_Matches': 'error',
        'Missing_HDA': 'warning',
        'Functional_Merge_Report': 'default',
        'PiecePart_Merge_Report': 'warning',
        'Merge_Summary': 'default',
        'Group_Missing_BOM': 'warning',
        'BOM_Missing_Refs': 'info',
        'BOM_Duplicate_Refs': 'highlight',
        'Validation_Warnings': 'warning',  # Yellow for FMR/usage validation issues
    }

    for name, frame in summaries.items():
        if not frame.empty:
            ws = wb.create_sheet(name)
            write_df_to_sheet(ws, frame)
            style_name = summary_styles.get(name, 'default')
            if style_name == 'default':
                style_worksheet(ws, frame, max_width=40)
            else:
                style_worksheet(ws, frame, row_style_func=lambda r, i, s=style_name: s, max_width=40)

    try:
        wb.save(filename)
    finally:
        wb.close()
