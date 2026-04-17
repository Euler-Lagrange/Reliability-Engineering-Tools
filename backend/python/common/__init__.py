#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Common Module for Tauri Reliability Tools Backend

Self-contained copy of shared utilities for the Tauri sidecar backend.
No dependency on the Flet source tree (src/).

UI, theme, and Flet-specific modules are excluded — this package only
contains data processing, validation, and I/O utilities needed by the
backend execution engine.
"""
import os
import sys
import json
import logging
from pathlib import Path

_logger = logging.getLogger(__name__)


# =============================================================================
# Version Information
# =============================================================================

__version__ = "0.1.0"
__app_name__ = "Reliability Tools Desktop (Tauri)"


# =============================================================================
# Configuration Manager
# =============================================================================

class ConfigManager:
    """Thread-safe JSON config persistence."""

    def __init__(self, app_name: str = "reliability_tools"):
        import threading
        self._lock = threading.Lock()
        self.app_name = app_name
        self.config_path = Path.home() / f".{app_name}_config.json"
        self.data = {}
        self.load()

    def load(self):
        with self._lock:
            if self.config_path.exists():
                try:
                    with open(self.config_path, "r", encoding="utf-8") as f:
                        self.data = json.load(f)
                except (json.JSONDecodeError, IOError) as e:
                    _logger.warning(f"Could not load config from {self.config_path}: {e}")
                    self.data = {}

    def save(self):
        with self._lock:
            try:
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, indent=2)
            except IOError as e:
                _logger.warning(f"Could not save config to {self.config_path}: {e}")

    def get(self, key: str, default=None):
        with self._lock:
            return self.data.get(key, default)

    def set(self, key: str, value):
        with self._lock:
            self.data[key] = value

    def update(self, updates: dict):
        with self._lock:
            self.data.update(updates)

    def clear(self):
        with self._lock:
            self.data = {}


# =============================================================================
# Re-exports (backend-only — no UI, no Flet, no theme)
# =============================================================================

from .utils import (
    ensure_file_available,
    normalize_input_path,
    preflight_input_file,
    list_excel_sheet_names,
    try_read_table,
    normalize_df_columns,
    detect_column,
    ensure_columns_exist,
    sha256_of_path,
    get_cache_dir,
    make_run_id,
    build_output_filename,
    write_snapshot,
    validate_output_path,
    clean_string,
    canonical_pn,
    is_writable_directory,
    atomic_write_path,
    atomic_finalize,
    verify_excel_readable,
    validate_explicit_output_directory,
)

from .logger import (
    get_logger,
    get_tool_logger,
    get_log_directory,
    GUILogHandler,
    log_session_start,
    log_session_end,
    log_operation,
    log_error,
)

from .excel_styles import (
    ExcelColors,
    StylePresets,
    COLORS,
    PRESETS,
    NUMBER_FORMATS,
    calculate_column_widths,
    style_worksheet,
    write_styled_excel,
    write_df_to_sheet,
    sanitize_for_excel,
)

from .cancellation import (
    CancellationError,
    CancellationToken,
    check_cancelled,
)

from .column_synonyms import (
    COLUMN_SYNONYMS,
    HEADER_CONFIG,
    get_synonyms,
    get_file_config,
)

from .validation_utils import (
    FMR_TOLERANCE,
    USAGE_TOLERANCE,
    validate_fmr_sums,
    get_invalid_fmr_sums,
    validate_part_usage,
    validate_usage_format,
    validate_fmr_usage_product,
    parse_usage,
    find_duplicates,
    find_duplicates_with_context,
)

from .refdes_utils import (
    IEEE_315_PREFIXES,
    PIN_STYLE_PREFIXES,
    INSTANCE_NOTATION_PREFIXES,
    get_prefix,
    is_known_prefix,
    NO_PIN_ANALYSIS_PREFIXES,
    PIN_ANALYSIS_PREFIXES,
    should_analyze_pins,
    canonicalize_refdes,
    expand_refdes_range,
    split_refdes_list,
    get_base_refdes,
    get_usage_base_refdes,
    is_pin_notation,
    is_instance_notation,
    is_valid_refdes,
    extract_base_refdes,
    extract_instance_refdes,
)

from .fmea_utils import (
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

from .exceptions import (
    ReliabilityToolError,
    ValidationError,
    FileAccessError,
    ColumnMappingError,
    ProcessingError,
)

from .user_facing_labels import (
    to_reason_code_label,
    to_user_facing_text,
    expand_reliability_abbreviations,
)
