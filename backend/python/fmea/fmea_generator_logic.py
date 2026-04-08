#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# Freeze lifted 2026-04-08: this file is now actively maintained as part of
# the Tauri desktop suite. The original "FROZEN -- Do not modify" directive
# has been removed by user request. See plan: mighty-wishing-meadow.md
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
from common.exceptions import ProcessingError
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
}

REQUIRED_COLS = {
    'COMPONENT_GROUPING': ['component_group', 'ref_des'],
    'BOM': ['ref_des', 'part_number'],
    'HDA': ['part_number'],
    'FAILURE_MODES': ['commodity_level1', 'failure_mode', 'ratio'],
    'FUNCTIONAL': ['function_id', 'failure_mode'],
}

OUTPUT_HEADERS_TEMPLATE = [
    'Schematic Page', 'FMEA-ID', 'Function Description', 'FMEA Level',
    'Failure Mode Causes', 'Component Part Number', 'Component Part Description',
    'BAE HDA Commodity I', 'BAE HDA Commodity II',
    '{FMD_STD} Commodity Type 1', '{FMD_STD} Commodity Type 2',
    'Failure Mode', 'Failure Mode Ratio',
    'Part Usage', 'Diagnostic',
    'Local Effect', 'Next Higher Effect', 'End Effect',
    'FuncFM Source Row', 'FuncFM Key', 'FuncFM Hash'
]


def output_headers_for(standard: str) -> List[str]:
    """Materialize OUTPUT_HEADERS with the chosen FMD standard label.

    Phase D: replaces the old hardcoded FMD-2016 column headers so the
    output workbook column names match the user-selected failure modes
    standard (FMD-91 or FMD-2016).
    """
    return [h.format(FMD_STD=standard) for h in OUTPUT_HEADERS_TEMPLATE]


# Default backwards-compatible header list (FMD-2016). Existing analyzer/
# writer modules import OUTPUT_HEADERS at module load; keeping the default
# preserves their behavior when no standard is set.
OUTPUT_HEADERS = output_headers_for("FMD-2016")

ROW_TYPE_COL = '_row_type'
ALPHABET_LENGTH = 26  # Length of uppercase alphabet for suffix generation
INDEX_CANCEL_CHECK_INTERVAL = 50  # Rows between cancellation checks during index build

# Phase D/H5: safety caps for process_functional_to_piecepart to prevent
# accidental OOM on pathological functional-FMEA inputs. A single functional
# row can reference many refdes, so output grows quickly. The warning
# threshold is informational; the hard cap raises ProcessingError to give
# the user an actionable error rather than crashing the sidecar.
MAX_FUNCTIONAL_INPUT_ROWS = 100_000   # Warn above this many functional rows
MAX_FUNCTIONAL_OUTPUT_ROWS = 1_000_000  # Hard-fail above this many generated rows

ROW_STYLE_PRIORITY = {
    'default': 0,
    'neutral': 1,
    'warning': 2,
    'validation_warning': 2,
    'error': 3,
    'piece_part_no_match': 3,
}

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
        # Phase D: BOM Additions tracking. Each entry is a pin/variant
        # RefDes that wasn't in the BOM but inherited its data from a
        # base component (e.g. U200-X inheriting from U200). Drives the
        # new BOM_Additions sheet in the output workbook.
        self.bom_additions: List[Dict[str, Any]] = []
        # Phase D: failure modes standard selected by the user (FMD-91 or
        # FMD-2016). Drives output column headers and FM file row filtering.
        self.failure_modes_standard: str = "FMD-2016"
        # Phase D: variant counts per base RefDes from the SOURCE document
        # (grouping/functional/BOM). Drives the usage_fraction display in
        # BOM_Additions entries (1/N where N is the variant count).
        self.variant_counts_by_base: Dict[str, int] = defaultdict(int)

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
        self.bom_index = {}
        self.hda_index = {}
        self.fm_c1_set = set()
        self.fm_c1_to_c2 = defaultdict(set)
        self.usage_base_counts = {}
        self.fmr_warnings = []
        self.usage_warnings = []
        self.bom_additions = []
        self.failure_modes_standard = "FMD-2016"
        self.variant_counts_by_base = defaultdict(int)

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

    def _build_indexes(
        self,
        bom_df: pd.DataFrame,
        hda_df: pd.DataFrame,
        fm_df: pd.DataFrame,
    ) -> None:
        self._build_base_indexes(bom_df, hda_df, fm_df)

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

    def _filter_failure_modes_by_standard(
        self, fm_df: pd.DataFrame, standard: str,
    ) -> pd.DataFrame:
        """Phase D: filter the failure modes DataFrame by the chosen FMD standard.

        Looks for a "standard" / "fmd standard" / "fmd version" column and
        filters rows whose normalized value matches the chosen standard
        (FMD-91 or FMD-2016). If no such column exists OR the filter would
        return an empty DataFrame, returns the original frame unchanged
        with a warning log — single-standard FM files don't get blocked.
        """
        candidates = ['standard', 'fmd standard', 'fmd version', 'source standard',
                      'fmd_source', 'source']
        cols_lower = {c.lower().strip(): c for c in fm_df.columns}
        found = next((cols_lower[k] for k in candidates if k in cols_lower), None)
        if not found:
            self.log(
                f"Failure Modes file has no standard-selector column; "
                f"all rows will be used regardless of selected standard '{standard}'.",
                "INFO",
            )
            return fm_df

        target = standard.upper().replace('-', '').replace(' ', '')

        def _match(v):
            if v is None:
                return False
            try:
                if pd.isna(v):
                    return False
            except (TypeError, ValueError):
                pass
            # Exact equality after normalization — tighter than substring
            # match so "FMD91legacy" or "FMD91/2016 combined" do NOT
            # accidentally match "FMD91".
            s = str(v).upper().replace('-', '').replace(' ', '')
            return s == target

        try:
            filtered = fm_df[fm_df[found].apply(_match)]
        except (TypeError, ValueError, KeyError) as exc:
            # Narrow catch: we must NOT swallow CancellationError (which
            # inherits from Exception per common.cancellation) or any
            # backend_error-worthy exception. Only filter-shape issues
            # (bad column types, weird pandas coercion) are forgiven.
            self.log(
                f"Failure Modes standard filter failed ({exc}); using all rows.",
                "WARNING",
            )
            return fm_df

        if filtered.empty:
            self.log(
                f"Failure Modes standard filter '{standard}' matched no rows; "
                f"falling back to all {len(fm_df)} rows.",
                "WARNING",
            )
            return fm_df

        self.log(
            f"Filtered failure modes by standard '{standard}': "
            f"{len(filtered)} of {len(fm_df)} rows kept.",
            "INFO",
        )
        return filtered

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
            # Phase D: capture FMD standard for use during row generation.
            self.failure_modes_standard = str(inputs.get('failure_modes_standard') or 'FMD-2016')

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

        # Phase D: enrichment merges removed from primary path. functional FMEA
        # is now its own primary workflow (process_functional_to_piecepart).
        # piece-part enrichment was deprecated entirely.

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

        # Phase D: filter failure modes by selected standard.
        fm_df = self._filter_failure_modes_by_standard(fm_df, self.failure_modes_standard)

        if status_callback:
            status_callback("Building indexes...")
        self.log("Building indexes...")
        self._build_indexes(bom_df, hda_df, fm_df)

        # Phase D: variant_counts_by_base counts every occurrence of a
        # base RefDes across the workflow's SOURCE-OF-TRUTH document:
        #   - process() with grouping file → counts come from grouping
        #   - process() in bom_only mode  → counts come from the BOM
        #   - process_functional_to_piecepart() → counts come from the
        #     functional FMEA (see that method for its own clear())
        #   - process_gaps() intentionally does NOT populate this map
        #     because fill_gaps never triggers the inheritance path
        #     (missing_refdes ⊆ bom_refdes)
        #
        # The resulting `usage_fraction` ("1/N") on each BOM_Additions
        # row therefore reflects "1 of N total instances of this base in
        # the workflow's source document" — which is what the user wants
        # for paste-back guidance. The count is NOT comparable across
        # workflows because each workflow has a different source-of-truth,
        # and that's intentional: the advice for a user running Fill Gaps
        # should differ from the advice for a user running Generate-from-
        # Grouping.
        self.variant_counts_by_base.clear()
        if group_df is not None:
            for _, grow in group_df.iterrows():
                for ref in split_ref_designators(grow.get("ref_des", "")):
                    base = canonicalize_refdes(get_usage_base_refdes(ref))
                    if base:
                        self.variant_counts_by_base[base] += 1
        else:
            for _, brow in bom_df.iterrows():
                for ref in split_ref_designators(brow.get("ref_des", "")):
                    base = canonicalize_refdes(get_usage_base_refdes(ref))
                    if base:
                        self.variant_counts_by_base[base] += 1

        source_workflow_tag = "bom_only" if self.bom_only_mode else "piece_part_generate"

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
                output_rows.extend(group_rows)
                for ref in split_ref_designators(row_dict.get('ref_des')):
                    output_rows.extend(
                        self._generate_component_rows(
                            ref, row_dict, fm_df, source_workflow=source_workflow_tag,
                        )
                    )

        self.log(f"Results: {len(self.successful_matches)} components matched | {len(self.no_matches)} with no failure modes (see No_Matches sheet)", "INFO")
        if self.bom_additions:
            self.log(f"BOM Additions: {len(self.bom_additions)} variant RefDes inherited from base components (see BOM_Additions sheet)", "INFO")
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
            self.failure_modes_standard = str(inputs.get('failure_modes_standard') or 'FMD-2016')

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
        # Phase D note: fill_gaps never triggers the inheritance code path.
        # missing_refdes = bom_refdes - existing_refdes, so by construction
        # the RefDes we generate piece-part rows for are ALREADY in the BOM.
        # The base-variant fallback in _generate_component_rows therefore
        # never fires for fill_gaps. We intentionally DO NOT populate
        # variant_counts_by_base here — it would be built from the BOM,
        # which is the wrong source for inheritance accounting anyway.
        for val in bom_df['ref_des'].dropna():
            for ref in split_refdes_list(str(val)):
                canon = canonicalize_refdes(ref)
                bom_refdes.add(canon)

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

        # 7. Map FM columns, filter by FMD standard, and build indexes
        f_map = self.map_columns(fm_df, HEADER_CONFIG['FAILURE_MODES'], REQUIRED_COLS['FAILURE_MODES'],
                                 source_name="Failure Modes file", overrides=col_overrides.get('FAILURE_MODES'))
        fm_df = fm_df.rename(columns={v: k for k, v in f_map.items()})
        fm_df = self._filter_failure_modes_by_standard(fm_df, self.failure_modes_standard)

        self._build_indexes(bom_df, hda_df, fm_df)

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

            rows = self._generate_component_rows(ref_des, group_row, fm_df, mode='standard', source_workflow='fill_gaps')

            # Add diagnostic note indicating gap-fill origin
            for row in rows:
                existing_diag = row.get('Diagnostic', '')
                gap_note = "Generated by Fill Gaps mode"
                row['Diagnostic'] = f"{gap_note}; {existing_diag}" if existing_diag else gap_note

            output_rows.extend(rows)

        self.log(f"Generated {len(output_rows)} FMEA rows for {len(missing_refdes)} missing RefDes")
        if self.bom_additions:
            self.log(f"BOM Additions: {len(self.bom_additions)} variant RefDes inherited from base components (see BOM_Additions sheet)", "INFO")
        return pd.DataFrame(output_rows)

    def process_functional_to_piecepart(
        self,
        inputs: Dict[str, Any],
        progress_callback: Optional[Callable[[int, int], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> pd.DataFrame:
        """Phase D: generate piece-part rows beneath each functional FMEA block.

        Reads a functional FMEA, identifies circuit-block rows, parses the
        comma-separated RefDes column ("Failure Mode Causes (RefDes)" or
        equivalent), and for each RefDes generates piece-part rows via the
        same _generate_component_rows() machinery used by piece_part_generate.
        Original functional rows are preserved AS-IS so the user can review
        their own structure unchanged.

        Required inputs:
            - 'func': Path to functional FMEA file
            - 'bom': Path to BOM file
            - 'fm':  Path to Failure Modes file
            - 'failure_modes_standard': "FMD-91" or "FMD-2016"

        Optional inputs:
            - 'hda': Path to HDA file
        """
        from common.fmea_utils import detect_refdes_column_for_fmea, classify_fmea_rows

        with self._lock:
            self._reset_state()
            self.verbose = bool(inputs.get('verbose'))
            self.failure_modes_standard = str(inputs.get('failure_modes_standard') or 'FMD-2016')

        col_overrides = inputs.get('column_overrides') or {}

        if status_callback:
            status_callback("Reading input files...")
        self.log("Reading input files...")
        func_raw = self.read_excel_safe(inputs['func'], sheet_name=inputs.get('func_sheet'))
        bom_raw = self.read_excel_safe(inputs['bom'], sheet_name=inputs.get('bom_sheet'))
        fm_df = self.read_excel_safe(inputs['fm'], sheet_name=inputs.get('fm_sheet'))
        hda_df = self._resolve_hda_dataframe(
            inputs.get('hda'), bom_raw, col_overrides.get('HDA'), inputs.get('hda_sheet'),
        )

        # Map BOM and FM columns to canonical names
        b_map = self.map_columns(
            bom_raw, HEADER_CONFIG['BOM'], REQUIRED_COLS['BOM'],
            source_name="BOM file", overrides=col_overrides.get('BOM'),
        )
        bom_df = bom_raw.rename(columns={v: k for k, v in b_map.items()})
        ensure_columns_exist(bom_df, REQUIRED_COLS['BOM'], "BOM file")

        f_map = self.map_columns(
            fm_df, HEADER_CONFIG['FAILURE_MODES'], REQUIRED_COLS['FAILURE_MODES'],
            source_name="Failure Modes file", overrides=col_overrides.get('FAILURE_MODES'),
        )
        fm_df = fm_df.rename(columns={v: k for k, v in f_map.items()})
        ensure_columns_exist(fm_df, REQUIRED_COLS['FAILURE_MODES'], "Failure Modes file")
        fm_df = self._filter_failure_modes_by_standard(fm_df, self.failure_modes_standard)

        if status_callback:
            status_callback("Building indexes...")
        self.log("Building indexes...")
        self._build_indexes(bom_df, hda_df, fm_df)

        if status_callback:
            status_callback("Parsing functional FMEA blocks...")
        # Detect the RefDes column on the functional sheet
        refdes_col = detect_refdes_column_for_fmea(func_raw, self.log)
        if not refdes_col:
            raise ColumnMappingError(
                "RefDes",
                "Functional FMEA",
                tried_synonyms=["Failure Mode Causes", "Reference Designator", "RefDes"],
            )
        self.log(f"Using functional FMEA RefDes column: '{refdes_col}'")

        # Phase D: resolve the other functional-FMEA columns via synonyms
        # so we don't hardcode header names like "FMEA-ID" that real
        # workbooks rarely use literally. Each of these can be None if
        # not present — the row loop handles fallbacks.
        fmea_id_col = resolve_column(
            func_raw, ['FMEA-ID', 'FMEA ID', 'Function ID', 'Component Group', 'ID']
        )
        func_desc_col = resolve_column(
            func_raw, ['Function Description', 'Description', 'Functional Description']
        )
        sch_page_col = resolve_column(
            func_raw, ['Schematic Page', 'Page', 'Sheet', 'Schematic']
        )
        self.log(
            f"Functional FMEA column resolution: id='{fmea_id_col}', "
            f"desc='{func_desc_col}', page='{sch_page_col}'",
            "DEBUG",
        )

        # Phase H5: warn on pathologically large functional FMEAs. We
        # only warn here; the hard cap is checked after row generation
        # since output row count is what actually blows up memory.
        input_row_count = len(func_raw)
        if input_row_count > MAX_FUNCTIONAL_INPUT_ROWS:
            self.log(
                f"WARNING: functional FMEA has {input_row_count:,} rows — exceeding "
                f"{MAX_FUNCTIONAL_INPUT_ROWS:,} may produce very large output. "
                "Consider narrowing the sheet selection or splitting the input.",
                "WARNING",
            )

        # Classify rows so we know which are circuit blocks
        classifications, _, _ = classify_fmea_rows(func_raw, self.log, self.cancel)

        # First pass: build variant counts from every RefDes seen on the
        # functional FMEA. This is the source-of-truth for this workflow
        # (see the detailed comment in process() for how each workflow
        # picks its own source and why that's intentional — not a bug to
        # reconcile across workflows).
        self.variant_counts_by_base.clear()
        for pos, (_, row_series) in enumerate(func_raw.iterrows()):
            # Cooperative cancellation during the scan pass
            if pos % INDEX_CANCEL_CHECK_INTERVAL == 0:
                self.cancel.check("Processing cancelled by user.")
            val = row_series.get(refdes_col)
            if val is None:
                continue
            try:
                if pd.isna(val):
                    continue
            except (TypeError, ValueError):
                pass
            for ref in split_refdes_list(str(val)):
                base = canonicalize_refdes(get_usage_base_refdes(ref))
                if base:
                    self.variant_counts_by_base[base] += 1

        if status_callback:
            status_callback("Generating piece-part rows under blocks...")
        output_rows: List[Dict[str, Any]] = []
        total_blocks = sum(1 for c in classifications if c.row_type == 'circuit_block')
        block_idx = 0

        for pos, (_, row_series) in enumerate(func_raw.iterrows()):
            self.cancel.check("Processing cancelled by user.")

            # Emit the functional row as-is. Tag _row_type so the writer
            # knows. Use whatever columns the functional file has.
            # Preserve the actual classification tag where we recognize
            # it; otherwise collapse to 'other' so the styler has a safe
            # default.
            passthrough = {k: row_series.get(k) for k in func_raw.columns}
            rtype = classifications[pos].row_type if pos < len(classifications) else 'other'
            passthrough[ROW_TYPE_COL] = rtype or 'other'
            output_rows.append(passthrough)

            if rtype != 'circuit_block':
                continue

            block_idx += 1
            if progress_callback:
                progress_callback(block_idx, total_blocks or 1)

            refdes_value = row_series.get(refdes_col)
            try:
                if pd.isna(refdes_value):
                    continue
            except (TypeError, ValueError):
                pass
            if refdes_value is None:
                continue

            # NOTE: bool(float('nan')) is True, so naive `X or 'BLOCK'`
            # does NOT fall through to the default when X is NaN.
            # clean_string() converts NaN → '' first, so then `'' or ...`
            # correctly picks up the fallback.
            _raw_id = row_series.get(fmea_id_col) if fmea_id_col else None
            _raw_desc = row_series.get(func_desc_col) if func_desc_col else None
            _raw_page = row_series.get(sch_page_col) if sch_page_col else None
            group_stub = {
                'component_group': clean_string(_raw_id) or 'BLOCK',
                'description': clean_string(_raw_desc) or '',
                'schematic_page': clean_string(_raw_page) or '',
            }
            for ref in split_refdes_list(str(refdes_value)):
                output_rows.extend(
                    self._generate_component_rows(
                        ref, group_stub, fm_df,
                        mode='standard',
                        source_workflow='functional_to_piecepart',
                    )
                )

            # Phase H5: fail early if output grows beyond the safety cap,
            # rather than waiting for the final DataFrame construction
            # (which might OOM). Check at block boundaries — cheap.
            if len(output_rows) > MAX_FUNCTIONAL_OUTPUT_ROWS:
                raise ProcessingError(
                    f"Functional-to-piecepart would emit more than "
                    f"{MAX_FUNCTIONAL_OUTPUT_ROWS:,} rows "
                    f"(at least {len(output_rows):,} generated so far). "
                    "Narrow the input sheet or split the functional FMEA "
                    "into smaller files, then re-run.",
                    context="functional_to_piecepart",
                )

        self.log(
            f"Emitted {len(output_rows)} rows ({total_blocks} circuit blocks processed; "
            f"{len(self.bom_additions)} BOM additions inferred)"
        )
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
        # Phase D: parametrize column headers by selected FMD standard so
        # circuit-block rows match the piece-part rows below them.
        for k in output_headers_for(self.failure_modes_standard or "FMD-2016"):
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
        for ref in refs:
            rows.extend(self._generate_component_rows(
                ref, group_stub, fm_df, mode='bom_only', source_workflow='bom_only',
            ))
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
        source_workflow: str = "",
    ) -> List[Dict[str, Any]]:
        rows = []
        group_label = clean_string(group_row.get('component_group')) or 'GROUP'
        # Normalize RefDes for lookup (matches normalization used in index building)
        ref_des_canon = canonicalize_refdes(ref_des)
        bom_row = self.bom_index.get(ref_des_canon)
        # Phase D: BOM inheritance for pin/variant RefDes. If the exact
        # RefDes is missing from the BOM, fall back to its base component
        # (e.g. U200-X inherits from U200). Inherited entries are recorded
        # in self.bom_additions for the BOM_Additions sheet.
        inherited_from_base: Optional[str] = None
        if bom_row is None:
            base_canon = canonicalize_refdes(get_usage_base_refdes(ref_des))
            if base_canon and base_canon != ref_des_canon:
                bom_row = self.bom_index.get(base_canon)
                if bom_row is not None:
                    inherited_from_base = base_canon
        if bom_row is None:
            # Logged ONCE for the variant, with helpful base-also-missing diagnostic
            base_canon = canonicalize_refdes(get_usage_base_refdes(ref_des))
            if base_canon and base_canon != ref_des_canon:
                self.log(
                    f"RefDes '{ref_des}' and its base '{base_canon}' are both missing from the BOM.",
                    "WARNING",
                )
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

        # Check part usage against expected (1/instance_count). Phase D:
        # inherited variants need their expected usage computed against the
        # SOURCE-derived variant count (variant_counts_by_base), NOT the
        # BOM-derived usage_base_counts — because by definition the base
        # has count=1 in the BOM but N in the source document. Running the
        # standard check on an inherited variant produces a false-positive
        # "Usage mismatch" on every inherited row, which makes the main
        # FMEA sheet look broken in the BOM Additions case.
        if inherited_from_base is not None:
            variant_count = self.variant_counts_by_base.get(inherited_from_base, 0) or 1
            expected = 1.0 / variant_count
            if abs(_usage_value - expected) > USAGE_TOLERANCE:
                usage_warning = (
                    f"Usage mismatch for inherited variant: expected "
                    f"{expected:.4g} (1/{variant_count}), listed {_usage_value:.4g}"
                )
            else:
                usage_warning = None
        else:
            usage_warning = self._check_single_usage(ref_des, _usage_value)
        if usage_warning:
            diag_msgs.append(usage_warning)
            # Capture structured usage warning for Validation_Warnings sheet
            base = get_usage_base_refdes(ref_des)
            if inherited_from_base is not None:
                count = self.variant_counts_by_base.get(inherited_from_base, 0)
                reason_code = 'PU_INHERITED_MISMATCH'
            else:
                count = self.usage_base_counts.get(base, 0)
                reason_code = 'PU_EXPECTED_MISMATCH_BASIC'
            expected = 1.0 / count if count > 0 else None
            self.usage_warnings.append({
                'RefDes': ref_des,
                'Base': base,
                'Usage': round(_usage_value, 4),
                'Expected': round(expected, 4) if expected else 'N/A',
                'Count': count,
                'ReasonCode': reason_code,
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

        # Phase D: record BOM inheritance for the BOM_Additions sheet.
        # Done AFTER HDA/FMD lookup so the entry has the full enrichment.
        if inherited_from_base is not None:
            count = self.variant_counts_by_base.get(inherited_from_base, 0) or 1
            usage_fraction = f"1/{count}"
            self.bom_additions.append({
                "ref_des": ref_des,
                "base_refdes": inherited_from_base,
                "usage_fraction": usage_fraction,
                "part_number": pn,
                "description": desc or desc_bom,
                "hda1": hda_c1,
                "hda2": hda_c2,
                "fmd1": fmd_c1,
                "fmd2": fmd_c2,
                "source_workflow": source_workflow,
                "notes": "",
            })
            self.log(
                f"BOM addition inferred: '{ref_des}' inherited from '{inherited_from_base}' "
                f"(usage {usage_fraction}, PN={pn})",
                "INFO",
            )
            diag_msgs.append(
                f"Inherited BOM data from base '{inherited_from_base}'; review and add '{ref_des}' to BOM."
            )

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

        # Phase D: FMD column headers parametrized by selected standard.
        fmd_std = self.failure_modes_standard or "FMD-2016"
        base_row = {
            'Schematic Page': group_row.get('schematic_page'),
            'Function Description': group_row.get('description'),
            'FMEA Level': 'Piece-Part',
            'Failure Mode Causes': ref_des,
            'Component Part Number': pn,
            'Component Part Description': desc,
            'BAE HDA Commodity I': hda_c1,
            'BAE HDA Commodity II': hda_c2,
            f'{fmd_std} Commodity Type 1': fmd_c1,
            f'{fmd_std} Commodity Type 2': fmd_c2,
            'Part Usage': usage_excel,
            '_row_type': 'piece_part',
        }
        for k in output_headers_for(fmd_std):
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

    # Phase D: BOM Additions sheet — pin/variant RefDes that inherited
    # data from a base component during piece-part generation. Gives the
    # user a paste-back list to add to their BOM.
    if proc.bom_additions:
        summaries['BOM_Additions'] = pd.DataFrame([
            {
                'RefDes': e['ref_des'],
                'Base RefDes': e['base_refdes'],
                'Usage': e['usage_fraction'],
                'Part Number': e['part_number'],
                'Part Description': e['description'],
                'HDA Commodity 1': e['hda1'],
                'HDA Commodity 2': e['hda2'],
                'FMD Commodity 1': e['fmd1'],
                'FMD Commodity 2': e['fmd2'],
                'Source Workflow': e['source_workflow'],
                'Notes': e['notes'],
            }
            for e in proc.bom_additions
        ])

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
        'Group_Missing_BOM': 'warning',
        'BOM_Missing_Refs': 'info',
        'BOM_Duplicate_Refs': 'highlight',
        'Validation_Warnings': 'warning',  # Yellow for FMR/usage validation issues
        'BOM_Additions': 'highlight',      # Phase D: variant rows inherited from base components
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

            # Phase D: prepend an explanation banner row on the BOM_Additions
            # sheet so the paste-back intent is obvious at a glance.
            if name == 'BOM_Additions':
                col_count = len(frame.columns)
                if col_count > 0:
                    ws.insert_rows(1)
                    banner = (
                        "These rows are RefDes variants found in the source that were "
                        "not in the BOM. Their data was inherited from a matching base "
                        "component. Review and copy these into your BOM."
                    )
                    ws.cell(row=1, column=1, value=banner)
                    try:
                        ws.merge_cells(
                            start_row=1, start_column=1,
                            end_row=1, end_column=col_count,
                        )
                    except ValueError:
                        # Single-column frames can't be merged; ignore.
                        pass

    try:
        wb.save(filename)
    finally:
        wb.close()
