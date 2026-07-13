#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# Freeze lifted 2026-04-08: this file is now actively maintained as part of
# the Tauri desktop suite. The original "FROZEN -- Do not modify" directive
# has been removed by user request. See plan: mighty-wishing-meadow.md
# ============================================================================
"""
RefDes Extractor - Core Logic (Enhanced with Geometry Analysis)

ARCHITECTURE:
    This module is the main entry point for RefDes extraction logic.
    It has been refactored to improve maintainability:

    - group_detection.py: Group detection from PDF annotations
    - extraction_engine.py: Harvest functions for component extraction

    This file contains:
    - Configuration and constants
    - Blacklist management
    - Mode utilities (Hybrid mode suffix handling)
    - Sequence gap detection
    - Main orchestration function (extract_with_geometry_analysis)

    Backward Compatibility:
    - All functions are re-exported for existing imports
    - detect_groups, harvest_* functions delegate to new modules
"""
import re
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict

import pandas as pd
import fitz  # PyMuPDF

# Import shared utilities from common module
from common import (
    make_run_id,
    ensure_file_available,
    try_read_table,
    get_tool_logger,
    check_cancelled,
    CancellationError,
    ConfigManager,
    canonicalize_refdes,
    IEEE_315_PREFIXES,
)
from common.partition_id import (
    parse_partition_id,
    sanitize_group_label,
    strip_mode_suffixes,
    strip_status_suffixes,
)

# Import geometry analyzer and BOM verifier (Phase 1 enhancement)
from . import geometry_analyzer as ga

# Import from refactored modules (for backward compatibility, re-export from here)
from .group_detection import (
    detect_groups as _detect_groups,
    detect_groups_from_drawings,
    center,
    area_of,
    point_in_rect,
    rect_overlap,
    STOP_WORDS,
    MIN_CONTAINER_AREA,
)
from . import extraction_engine as _engine

# Initialize module logger
_logger = get_tool_logger("refdes_extractor")

# ==================== CONFIGURATION & CONSTANTS ====================

# NOTE: Reference designator prefixes are now centralized in common/refdes_utils.py
# as IEEE_315_PREFIXES. This module imports from there to maintain a single source of truth.

DEFAULT_CONNECTOR_PREFIXES = ("P", "J", "CONN", "X", "CN", "CON", "H", "HDR", "XPSJ")

# NOTE: STOP_WORDS is imported from group_detection.py (line 76) for consistency

class Config:
    """
    Configuration for RefDes extraction.

    Uses IEEE_315_PREFIXES from common/refdes_utils.py as the base set,
    allowing users to extend (not replace) with custom prefixes via config file.
    """
    def __init__(self):
        # Start with IEEE 315 standard prefixes (centralized in common)
        self.ref_prefixes = list(IEEE_315_PREFIXES)
        self.connector_prefixes = list(DEFAULT_CONNECTOR_PREFIXES)
        self.load_custom_config()

    def load_custom_config(self):
        """Load custom prefixes from user config file (extends, doesn't replace)."""
        config_file = Path.home() / ".refdes_extractor_config.json"
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    custom = json.load(f)
                    # Custom prefixes EXTEND the standard list
                    if 'ref_prefixes' in custom:
                        for prefix in custom['ref_prefixes']:
                            if prefix.upper() not in self.ref_prefixes:
                                self.ref_prefixes.append(prefix.upper())
                                _logger.info(f"Added custom prefix: {prefix}")
            except (json.JSONDecodeError, IOError, OSError) as e:
                _logger.warning(f"Failed to load custom config: {e}")
    
    def get_refdes_pattern(self):
        prefixes = '|'.join(sorted(self.ref_prefixes, key=len, reverse=True))
        return re.compile(rf"\b(?:{prefixes})\d+[A-Z]?\b", re.I)

CONFIG = Config()
REFDES_RE = CONFIG.get_refdes_pattern()
POWER_SOURCE_RE = re.compile(r"\bP(?:\d+(?:\.\d+)?V|\dV\d)\b", re.I)
PIN_RE = re.compile(r"\b([A-Z]{1,3}\d{1,3})\b", re.I)
DEFAULT_PROV_DISTANCE = 15.0  # Default pixels - PROV marker should be very close to RefDes

# Lazy initialization flag for extraction engine
# We defer _init_patterns() until first use to avoid circular imports during module load
_engine_initialized = False


def _ensure_engine_initialized():
    """
    Ensure extraction engine patterns are initialized before use.

    This implements lazy initialization to avoid circular imports:
    - refdes_extractor_logic.py imports extraction_engine.py
    - extraction_engine._init_patterns() imports refdes_extractor_logic.py

    By deferring initialization until first harvest call, we avoid the
    circular dependency at module load time.
    """
    global _engine_initialized
    if not _engine_initialized:
        _engine._init_patterns(REFDES_RE, POWER_SOURCE_RE, DEFAULT_PROV_DISTANCE)
        _engine_initialized = True

# ============================================================================
# OUTPUT PIN BLACKLIST
# ============================================================================
# Items that should NEVER be extracted as output pins or RefDes.
# These are common false positives from PDF annotation extraction.
#
# To add new entries:
#   1. Add the exact text (case-insensitive EXACT matching is applied — the
#      text must equal an entry in full; "GND" filters "GND" but NOT "GND1")
#   2. Add a comment explaining WHY it's blacklisted
#   3. Group with similar items for organization
#
# Categories:
#   - Electrical units (uF, mW, V, etc.)
#   - Power/ground signals (GND, VCC, VOUT, etc.)
#   - Test/routing labels (Place, Route, PROV, etc.)
#   - Component types (MOSFET, caps, sensor, etc.)
#   - Generic labels that aren't real outputs
# ============================================================================

REFDES_BLACKLIST = {
    # -------------------------------------------------------------------------
    # Electrical Engineering Units
    # These appear in component values, not as actual pin outputs
    # -------------------------------------------------------------------------
    "uF",       # Microfarads (capacitor values)
    "mW",       # Milliwatts (power ratings)
    "1V", "3V", "5V", "12V", "15V", "16V", "28V",  # Voltage ratings

    # -------------------------------------------------------------------------
    # Power and Ground Signals
    # Internal power rails, not output pins
    # -------------------------------------------------------------------------
    "GND",      # Ground reference
    "AGND",     # Analog ground
    "CGND",     # Chassis ground
    "SGND",     # Signal ground
    "DGND",     # Digital ground
    "VCC",      # Supply voltage
    "VIN",      # Input voltage
    "VOUT",     # Output voltage label (not a component)
    "OUT",      # Generic output label
    "LDO",      # Low dropout regulator label

    # -------------------------------------------------------------------------
    # Test, Routing, and Manufacturing Labels
    # PDF annotation artifacts from schematic tools
    # -------------------------------------------------------------------------
    "Place",    # Component placement instruction
    "Route",    # Routing instruction
    "Short",    # Short circuit annotation
    "PROV",     # Provisional/test point marker
    "NC",       # No Connect pin designation

    # -------------------------------------------------------------------------
    # Component Type Labels
    # Descriptive text that isn't a pin identifier
    # -------------------------------------------------------------------------
    "caps",     # Capacitor description
    "sensor",   # Sensor description
    "temp",     # Temperature sensor/label
    "MOSFET",   # Transistor type label
    "Func",     # Function description

    # -------------------------------------------------------------------------
    # Specific IC/Module Labels
    # Common power management IC output names
    # -------------------------------------------------------------------------
    "COMP1",    # Compensation pin label
    "PGOOD1",   # Power good signal 1
    "PGOOD2",   # Power good signal 2

    # -------------------------------------------------------------------------
    # Add new blacklist entries below this line
    # Format: "LABEL",  # Reason for blacklisting
    # -------------------------------------------------------------------------
}

# Regex pattern to catch any voltage value dynamically (e.g., 3.3V, 48V, 1.8V)
VOLTAGE_PATTERN = re.compile(r'^\d+\.?\d*V$', re.IGNORECASE)

# Pre-compute uppercase blacklist for O(1) lookup
_BLACKLIST_UPPER = frozenset(item.upper() for item in REFDES_BLACKLIST)


def _is_blacklisted(text: str, config: Optional['ConfigManager'] = None) -> bool:
    """
    Check if text matches any blacklisted pattern.

    Uses case-insensitive EXACT matching against:
    1. User whitelist (if in whitelist, never blacklisted)
    2. Default blacklist + user additions
    3. Voltage pattern (catches any voltage like 3.3V, 48V, etc.)

    Examples:
        _is_blacklisted("GND") -> True   (exact match)
        _is_blacklisted("AGND") -> True  (exact match - in blacklist)
        _is_blacklisted("GND1") -> False (not exact match)
        _is_blacklisted("3.3V") -> True  (voltage pattern)
        _is_blacklisted("U1") -> False

    Args:
        text: The text to check against the blacklist
        config: Optional ConfigManager for user blacklist/whitelist

    Returns:
        True if the text matches any blacklisted pattern
    """
    text_clean = text.strip()
    text_upper = text_clean.upper()

    # Check user whitelist first (takes priority - never filter these)
    if config:
        user_whitelist = {w.upper() for w in config.get("user_whitelist", [])}
        if text_upper in user_whitelist:
            return False

    # Check user blacklist additions
    user_blacklist = set()
    if config:
        user_blacklist = {b.upper() for b in config.get("user_blacklist", [])}

    # Combined blacklist: defaults + user additions
    combined_blacklist = _BLACKLIST_UPPER | user_blacklist

    # EXACT match against blacklist (not substring)
    if text_upper in combined_blacklist:
        return True

    # Check voltage pattern (catches any voltage like 3.3V, 48V, etc.)
    if VOLTAGE_PATTERN.match(text_clean):
        return True

    return False


# ==================== HYBRID MODE UTILITIES ====================
# Functions for per-group extraction mode switching based on -FN/-PN suffixes

def _determine_group_mode(group_name: str, global_mode: str) -> str:
    """
    Determine extraction mode for a specific group based on suffix.

    Suffix takes priority over global setting:
      -FN → "functional" (RefDes only, blacklist filtering, no pins)
      -PN → "piece_part" (RefDes + Pins via geometry analysis)
      (none) → global_mode (from config dropdown)

    Args:
        group_name: Group label from PDF annotation (e.g., "CPU-001-FN")
        global_mode: Config value ("functional" or "piece_part")

    Returns:
        "functional" or "piece_part"

    Examples:
        >>> _determine_group_mode("CPU-001-FN", "piece_part")
        "functional"
        >>> _determine_group_mode("CPU-001-PN", "functional")
        "piece_part"
        >>> _determine_group_mode("CPU-001", "functional")
        "functional"
    """
    name_upper = group_name.strip().upper()
    if name_upper.endswith("-FN"):
        return "functional"
    elif name_upper.endswith("-PN"):
        return "piece_part"
    return global_mode


def _strip_mode_suffix(group_name: str) -> str:
    """
    Remove mode suffixes and verification status from group name for clean output.

    Strips: -FN, -PN, (Verified), (Unverified), (Partial)
    Preserves original case of the base name.

    Args:
        group_name: Group label potentially with mode suffix or verification status

    Returns:
        Group name with suffix removed

    Examples:
        >>> _strip_mode_suffix("CPU-001-FN")
        "CPU-001"
        >>> _strip_mode_suffix("CPU-001-pn")
        "CPU-001"
        >>> _strip_mode_suffix("CPU-001")
        "CPU-001"
        >>> _strip_mode_suffix("CPU-001 (Verified)")
        "CPU-001"
        >>> _strip_mode_suffix("CPU-001 (Unverified)")
        "CPU-001"
    """
    result, _status_suffixes = strip_status_suffixes(group_name)
    result, _mode_suffixes = strip_mode_suffixes(result)

    return result if result else group_name.strip()  # Return original if result is empty


def _parse_group_sequence(group_name: str) -> tuple:
    """
    Parse group name into prefix and sequence number.

    Extracts the sequential numbering portion from group names to enable
    gap detection. Groups without numeric sequences are not parseable.

    Args:
        group_name: Full group name (e.g., "CPU-001", "PSU102")

    Returns:
        (prefix, number) tuple, or (None, None) if not a sequenced group

    Examples:
        >>> _parse_group_sequence("CPU-001")
        ("CPU-", 1)
        >>> _parse_group_sequence("PSU102")
        ("PSU", 102)
        >>> _parse_group_sequence("CONN-P3V3")
        (None, None)
    """
    parsed = parse_partition_id(group_name, parse_mode_suffixes=True)
    if parsed.sequence_info:
        return parsed.sequence_info.prefix, parsed.sequence_info.number
    return None, None


# Wave R4: gap runs of at most this many consecutive missing numbers emit
# individual "GROUP NOT DETECTED" placeholder rows; longer runs collapse to a
# single "RANGE NOT DETECTED" summary row per run. Short interior holes are
# high-signal (a one-number hole is very likely a real miss); long holes are
# usually intentional numbering jumps and get one line instead of dozens.
GAP_RUN_EMIT_LIMIT = 3


def detect_sequence_gaps(group_names: list, log_func=None) -> list:
    """
    Detect missing sequence numbers in group names.

    Analyzes a list of group names to find gaps in numeric sequences.
    For example, if groups CPU-001, CPU-002, CPU-004 exist, this detects
    that CPU-003 is missing.

    Wave R4 (DIG-4xx incident): the old ``MAX_GAP_RANGE=100`` family-span cap
    silently disabled gap detection for any family whose numbering spanned
    more than 100 — the user could not tell dropped groups from
    never-existed ones. Detection now works per GAP RUN between consecutive
    detected numbers: runs of length <= GAP_RUN_EMIT_LIMIT emit individual
    placeholder rows; longer runs collapse to one summary row per run.
    Nothing is ever silently skipped, and iteration is bounded by the number
    of detected groups (long runs are summarized without iterating them).

    Args:
        group_names: List of detected group names (can be None or empty)
        log_func: Optional logging callback for gap reporting

    Returns:
        List of dicts for missing groups, each containing:
        - "group": "CPU-003 (GROUP NOT DETECTED)" for short runs, or
          "CPU-004–CPU-199 (RANGE NOT DETECTED — 196 consecutive)" for
          collapsed long runs
        - "failure mode causes": Empty string
        - "component count": 0
        - "pages": Empty string
        - "_is_gap": True (internal marker for styling)

    Note: This function is thread-safe (pure function with no shared state).
    """
    # Handle null/empty input gracefully
    if not group_names:
        return []

    # Group by prefix
    prefix_numbers = {}  # {prefix: [(number, num_width), ...]}
    for name in group_names:
        parsed = parse_partition_id(name, parse_mode_suffixes=True)
        if not parsed.display_label:
            continue

        sequence_info = parsed.sequence_info
        if sequence_info is None:
            if log_func and parsed.classification != "noise":
                log_func(
                    f"  ⏭ Sequence gap: '{parsed.display_label}' excluded "
                    "(no safe terminal numeric sequence)"
                )
            continue

        prefix_numbers.setdefault(sequence_info.prefix, []).append(
            (sequence_info.number, sequence_info.width)
        )

    missing_groups = []
    for prefix, number_widths in sorted(prefix_numbers.items()):
        numbers = sorted(set(n for n, w in number_widths))
        if len(numbers) < 2:
            continue  # Need at least 2 to detect gaps

        # Determine consistent width from existing numbers
        max_width = max(w for n, w in number_widths)

        def _gap_row(group_label: str) -> dict:
            return {
                "group": group_label,
                "failure mode causes": "",
                "component count": 0,
                "pages": "",
                "_is_gap": True,  # Internal marker for styling
            }

        # Walk consecutive detected numbers; each hole between a pair is one
        # gap RUN. Long runs are summarized without iterating their members,
        # so a family spanning thousands costs O(detected groups), not O(span).
        for lower, upper in zip(numbers, numbers[1:]):
            run_length = upper - lower - 1
            if run_length <= 0:
                continue

            if run_length <= GAP_RUN_EMIT_LIMIT:
                for num in range(lower + 1, upper):
                    missing_name = f"{prefix}{str(num).zfill(max_width)}"
                    if log_func:
                        log_func(f"  ⚠ Gap detected: {missing_name} not found in sequence")
                    missing_groups.append(
                        _gap_row(f"{missing_name} (GROUP NOT DETECTED)")
                    )
            else:
                first_name = f"{prefix}{str(lower + 1).zfill(max_width)}"
                last_name = f"{prefix}{str(upper - 1).zfill(max_width)}"
                if log_func:
                    log_func(
                        f"  ⚠ Gap run detected: {first_name}–{last_name} "
                        f"({run_length} consecutive) not found in sequence"
                    )
                missing_groups.append(
                    _gap_row(
                        f"{first_name}–{last_name} "
                        f"(RANGE NOT DETECTED — {run_length} consecutive)"
                    )
                )

    return missing_groups


# ==================== UTILITY FUNCTIONS (RefDes-specific) ====================
# Shared utilities (make_run_id, ensure_file_available, try_read_table) are imported from common

def natural_key(s) -> tuple:
    s = str(s)
    parts = re.findall(r"\d+|\D+", s)
    return tuple((0, int(p)) if p.isdigit() else (1, p.lower()) for p in parts)

# Geometry helpers are now imported from group_detection module for reuse:
# - center(rect) - Get center point of rectangle
# - area_of(r) - Get absolute area of rectangle
# - point_in_rect(cx, cy, rect) - Check if point is inside rectangle
# - rect_overlap(a, b) - Check if two rectangles overlap


def annotation_box_contains_body(ann_rect, body_rect: 'ga.Rect', margin: float = 5.0) -> bool:
    """
    Check if an annotation box fully contains a component body.

    When a large annotation box encompasses an entire component (not just pins),
    we should extract the RefDes only, not individual pins. This prevents
    extracting U300-P1, U300-P2 when a box is drawn around the whole U300.

    Args:
        ann_rect: Annotation rectangle as (x0, y0, x1, y1) tuple
        body_rect: Component body Rect from geometry analyzer
        margin: Tolerance in pixels (default 5.0)

    Returns:
        True if annotation box fully contains the body (with margin tolerance)
    """
    return (ann_rect[0] - margin <= body_rect.x0 and
            ann_rect[1] - margin <= body_rect.y0 and
            ann_rect[2] + margin >= body_rect.x1 and
            ann_rect[3] + margin >= body_rect.y1)


def strip_suffix(refdes: str) -> str:
    if re.match(r"^[A-Z]+$", refdes): return refdes
    match = re.match(rf"^({'|'.join(CONFIG.ref_prefixes)})(\d+)([A-Z])?$", refdes, re.I)
    if match: return f"{match.group(1)}{match.group(2)}".upper()
    return refdes.upper()


def _find_refdes_in_box(page_words: list, box_rect: tuple, pin_location: tuple) -> str:
    """
    Find RefDes in annotation box to use as prefix for unqualified pins.

    When geometry analysis fails to associate a pin with its parent component,
    this function searches the same annotation box for RefDes patterns and
    uses the nearest one as the pin's parent identifier.

    Args:
        page_words: List of word tuples from page.get_text("words")
                    Format: (x0, y0, x1, y1, text, block_no, line_no, word_no)
        box_rect: Annotation rectangle as (x0, y0, x1, y1)
        pin_location: Pin center as (cx, cy) for nearest-distance calculation

    Returns:
        RefDes string (e.g., "J1", "U308") or None if no RefDes found in box
    """
    candidates = []  # List of (refdes, cx, cy, distance_sq)
    pin_cx, pin_cy = pin_location

    for w in page_words:
        text = (w[4] or "").strip()
        if not text:
            continue

        # Get word center
        word_rect = (w[0], w[1], w[2], w[3])
        wcx, wcy = center(word_rect)

        # Check if word is inside annotation box
        if not point_in_rect(wcx, wcy, box_rect):
            continue

        # Check if word matches RefDes pattern (but not power source like P3V3)
        if REFDES_RE.fullmatch(text) and not POWER_SOURCE_RE.match(text):
            # Calculate distance from pin to this RefDes
            dist_sq = (wcx - pin_cx)**2 + (wcy - pin_cy)**2
            candidates.append((text.upper(), wcx, wcy, dist_sq))

    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0][0]

    # Multiple RefDes found - return nearest to pin location
    candidates.sort(key=lambda x: x[3])  # Sort by distance_sq (ascending)
    return candidates[0][0]


# ==================== CORE LOGIC ====================

def load_bom(bom_path: Path, ref_col_name: str = "Auto-Detect", log_func=None, sheet_name=None) -> set:
    try:
        from .bom_loader import load_bom as shared_load_bom
    except ImportError:
        from bom_loader import load_bom as shared_load_bom

    return shared_load_bom(
        bom_path=bom_path,
        ref_col_name=ref_col_name,
        log_func=log_func or print,
        sheet_name=sheet_name,
    )

def load_pinlist(pinlist_path: Path, log_func=None, sheet_name=None) -> set:
    """
    Load a pinlist / netlist file used to filter pin outputs in Piece-Part mode.

    Supported formats:
      - Two columns: RefDes + Pin
          RefDes,Pin
          U54,F11
      - Single column containing full identifiers:
          U54-F11
          U54.F11

    Returns:
        Set[str] of normalized full IDs like "U54-F11".
    """
    _log_func = log_func or print
    def log(msg):
        _log_func(msg)
        _logger.info(msg)

    log(f"Reading pinlist: {pinlist_path.name}")
    pinlist_path = ensure_file_available(pinlist_path, log)
    pins = set()

    def canonicalize_full_id(raw: str) -> str:
        if raw is None:
            return ""
        txt = str(raw).strip().upper()
        if not txt:
            return ""
        # Normalize common delimiters to hyphen
        txt = re.sub(r"\s*[-.:]\s*", "-", txt)
        txt = re.sub(r"-{2,}", "-", txt)
        if "-" not in txt:
            return ""
        ref, pin = txt.rsplit("-", 1)
        ref = canonicalize_refdes(strip_suffix(ref))
        pin = re.sub(r"\s+", "", pin).upper()
        if not ref or not pin:
            return ""
        return f"{ref}-{pin}"

    try:
        df = try_read_table(str(pinlist_path), sheet_name=sheet_name, log_func=log)

        cols_upper = {str(c).strip().upper(): c for c in df.columns}
        ref_col = cols_upper.get("REFDES")
        pin_col = cols_upper.get("PIN")

        if ref_col is not None and pin_col is not None:
            for _, row in df.iterrows():
                full = canonicalize_full_id(f"{row.get(ref_col, '')}-{row.get(pin_col, '')}")
                if full:
                    pins.add(full)
        else:
            # Fall back to the first column as a list of full IDs.
            if df.columns.size == 0:
                raise ValueError("Pinlist file is empty (no columns).")
            col = df.columns[0]
            for val in df[col].dropna().astype(str):
                # Allow comma/semicolon separated lists per cell.
                for token in re.split(r"[;,]+", val):
                    full = canonicalize_full_id(token)
                    if full:
                        pins.add(full)

        log(f"  Loaded {len(pins)} pins from pinlist.")
        return pins
    except Exception as e:
        raise RuntimeError(f"Failed to read pinlist: {e}")

def _sanitize_label(raw: str) -> str:
    """Clean and normalize a text label for use as a group name."""
    return sanitize_group_label(raw)


def detect_groups(annotations, log_func=None, stop_event=None) -> list:
    """
    Detect component groups from PDF annotations.

    Uses flexible detection:
    - ANY annotation with a valid bounding rect is a potential container
    - Minimum area threshold filters out tiny accidental markup
    - Text is assigned to the SMALLEST enclosing container (nested boxes supported)

    Args:
        annotations: List of annotation dicts from PDF
        log_func: Optional logging callback
        stop_event: Optional threading.Event for cancellation

    Returns:
        List of (page, label, rect) tuples representing detected groups

    Note:
        This function delegates to group_detection._detect_groups for implementation.
        Kept here for backward compatibility with existing imports.
    """
    # Delegate to the refactored group_detection module
    return _detect_groups(
        annotations,
        refdes_pattern=REFDES_RE,
        log_func=log_func,
        stop_event=stop_event
    )


def detect_groups_with_fallback(doc, annotations, log_func=None, stop_event=None):
    """
    Detect groups from live annotations first, then use a bounded text/vector fallback.

    Returns:
        (groups, used_fallback, provenance)
    """
    if annotations:
        return detect_groups(annotations, log_func=log_func, stop_event=stop_event), False, "annotation"

    if stop_event and stop_event.is_set():
        raise CancellationError("Cancelled during group detection")

    def get_words(page, page_num):
        return _engine._get_words_with_timeout(
            page,
            page_num=page_num,
            log_func=log_func,
        )

    searchable_text = False
    for page_num, page in enumerate(doc):
        if stop_event and stop_event.is_set():
            raise CancellationError("Cancelled during group detection")
        if get_words(page, page_num):
            searchable_text = True
            break

    if not searchable_text:
        if log_func:
            log_func("No searchable PDF text found for bounded group fallback.")
        return [], False, "image_only"

    groups = detect_groups_from_drawings(
        doc,
        refdes_pattern=REFDES_RE,
        log_func=log_func,
        stop_event=stop_event,
        words_getter=get_words,
    )
    if groups:
        if log_func:
            log_func("Using bounded text/vector fallback for flattened or text-layer-only groups.")
        return groups, True, "text_layer"

    if log_func:
        log_func("No groups recovered from bounded text/vector fallback.")
    return [], False, "text_layer"

# ==================== HARVEST FUNCTIONS (delegated to extraction_engine.py) ====================
# These functions delegate to extraction_engine.py for the actual implementation.
# This avoids code duplication while maintaining backward compatibility.


def harvest_components(
    pdf_path: Path,
    groups: list,
    bom_set: set,
    debug_pdf_path: Path = None,
    log_func=None,
    progress_func=None,
    prov_distance: float = DEFAULT_PROV_DISTANCE,
    stop_event=None
) -> list:
    """
    Basic component harvesting from annotated PDF (legacy mode).

    Delegates to extraction_engine.harvest_components().
    """
    _ensure_engine_initialized()
    return _engine.harvest_components(
        pdf_path=pdf_path,
        groups=groups,
        bom_set=bom_set,
        debug_pdf_path=debug_pdf_path,
        log_func=log_func,
        progress_func=progress_func,
        prov_distance=prov_distance,
        stop_event=stop_event
    )


def harvest_functional_fmea(
    pdf_path: Path,
    groups: list,
    bom_set: set,
    config: Optional[ConfigManager] = None,
    debug_pdf_path: Path = None,
    log_func=None,
    progress_func=None,
    prov_distance: float = DEFAULT_PROV_DISTANCE,
    stop_event=None
) -> list:
    """
    Functional FMEA extraction mode - RefDes only, no pins.

    Delegates to extraction_engine.harvest_functional_fmea().
    """
    _ensure_engine_initialized()
    return _engine.harvest_functional_fmea(
        pdf_path=pdf_path,
        groups=groups,
        bom_set=bom_set,
        config=config,
        debug_pdf_path=debug_pdf_path,
        log_func=log_func,
        progress_func=progress_func,
        prov_distance=prov_distance,
        stop_event=stop_event
    )


def harvest_hybrid(
    pdf_path: Path,
    groups: list,
    bom_set: set,
    config: 'ConfigManager',
    group_modes: dict,
    pin_map: dict,
    body_rects: dict,
    pinlist_set: Optional[set] = None,
    debug_pdf_path: Path = None,
    log_func=None,
    progress_func=None,
    prov_distance: float = DEFAULT_PROV_DISTANCE,
    stop_event=None,
    max_pin_length: int = 4,
    collect_metrics: bool = False,
) -> list:
    """
    Hybrid harvester that processes groups according to their individual modes.

    Delegates to extraction_engine.harvest_hybrid().

    Args:
        collect_metrics: If True, return (results, page_metrics_dict) tuple
                         for adaptive geometry gating

    Returns:
        List of dicts with formatted results, or
        (List, Dict[int, PageMetrics]) tuple if collect_metrics=True
    """
    _ensure_engine_initialized()
    return _engine.harvest_hybrid(
        pdf_path=pdf_path,
        groups=groups,
        bom_set=bom_set,
        config=config,
        group_modes=group_modes,
        pin_map=pin_map,
        body_rects=body_rects,
        pinlist_set=pinlist_set,
        debug_pdf_path=debug_pdf_path,
        log_func=log_func,
        progress_func=progress_func,
        prov_distance=prov_distance,
        stop_event=stop_event,
        max_pin_length=max_pin_length,
        collect_metrics=collect_metrics,
    )


# ==================== BOM VERIFICATION HELPERS ====================


def _extract_base_refdes(component: str) -> Optional[str]:
    """
    Extract base RefDes from a component identifier for BOM verification.

    Examples:
        "J1-1" -> "J1"
        "U308-C17" -> "U308"
        "R400" -> "R400"
        "PIN-1" -> None (not verifiable)

    Args:
        component: Component string (may include pin suffix)

    Returns:
        Base RefDes string, or None if not extractable
    """
    component = component.strip()
    if not component:
        return None

    # Skip uncertain markers
    if component.endswith("[?]"):
        component = component[:-3].strip()

    # Handle PIN-X format (not verifiable)
    if component.upper().startswith("PIN-"):
        return None

    # Handle qualified pins: RefDes-Pin format (e.g., J1-1, U308-C17)
    if "-" in component:
        base = component.split("-")[0]
        # Verify it looks like a RefDes pattern
        if REFDES_RE.fullmatch(base):
            return base.upper()
        return None

    # Handle plain RefDes (e.g., R400, C123)
    if REFDES_RE.fullmatch(component):
        return component.upper()

    return None


def _apply_bom_verification(results: list, bom_set: set) -> list:
    """
    Post-process extraction results to apply BOM verification.

    For each group, splits components into verified (in BOM) and unverified (not in BOM).
    Creates separate rows for each status:
    - "GroupName (Verified)" - components whose base RefDes is in BOM
    - "GroupName (Unverified)" - components whose base RefDes is NOT in BOM

    Args:
        results: List of dicts from _format_results
        bom_set: Set of normalized RefDes from BOM

    Returns:
        Modified list with verification status in group names
    """
    if not bom_set:
        # No BOM loaded - mark all as unverified
        verified_results = []
        for row in results:
            new_row = row.copy()
            new_row["group"] = f"{row['group']} (Unverified)"
            verified_results.append(new_row)
        return verified_results

    # Normalize BOM set for case-insensitive matching
    normalized_bom = {canonicalize_refdes(r) for r in bom_set if r}

    verified_results = []

    for row in results:
        group_name = row["group"]
        components_str = row["failure mode causes"]
        pages = row["pages"]

        # Skip special groups that shouldn't be split
        if "UNGROUPED" in group_name or "PROVISIONAL" in group_name:
            verified_results.append(row)
            continue

        # Parse components
        components = [c.strip() for c in components_str.split(",") if c.strip()]

        verified_components = []
        unverified_components = []

        for comp in components:
            base_refdes = _extract_base_refdes(comp)
            if base_refdes and canonicalize_refdes(base_refdes) in normalized_bom:
                verified_components.append(comp)
            else:
                unverified_components.append(comp)

        # Create output rows
        if verified_components and not unverified_components:
            # All verified - single row
            verified_results.append({
                "group": f"{group_name} (Verified)",
                "failure mode causes": ", ".join(sorted(verified_components, key=natural_key)),
                "component count": len(verified_components),
                "pages": pages
            })
        elif unverified_components and not verified_components:
            # All unverified - single row
            verified_results.append({
                "group": f"{group_name} (Unverified)",
                "failure mode causes": ", ".join(sorted(unverified_components, key=natural_key)),
                "component count": len(unverified_components),
                "pages": pages
            })
        else:
            # Mixed - two rows
            if verified_components:
                verified_results.append({
                    "group": f"{group_name} (Verified)",
                    "failure mode causes": ", ".join(sorted(verified_components, key=natural_key)),
                    "component count": len(verified_components),
                    "pages": pages
                })
            if unverified_components:
                verified_results.append({
                    "group": f"{group_name} (Unverified)",
                    "failure mode causes": ", ".join(sorted(unverified_components, key=natural_key)),
                    "component count": len(unverified_components),
                    "pages": pages
                })

    return verified_results


# ==================== ENHANCED EXTRACTION WITH GEOMETRY ANALYSIS ====================

def extract_with_geometry_analysis(
    pdf_path: Path,
    groups: list,
    bom_set: set,
    config: Optional[ConfigManager] = None,
    pinlist_set: Optional[set] = None,
    debug_pdf_path: Path = None,
    log_func=None,
    progress_func=None,
    status_func=None,
    stop_event=None
) -> list:
    """
    Enhanced extraction with Adaptive Geometry Analysis (Two-Pass Architecture).

    This is the main entry point that intelligently decides when to run expensive
    geometry analysis. The algorithm:

    1. PHASE 1: Fast BOM-only extraction on all pages, collecting metrics
    2. PHASE 2: Smart gating - analyze metrics to find problematic pages
    3. PHASE 3: Selective geometry - run expensive analysis only on flagged pages
    4. PHASE 4: Re-harvest problematic pages and merge with Phase 1 results

    This approach typically reduces geometry analysis from all pages to just 2-5
    problematic pages, saving 80-90% of processing time.

    Args:
        pdf_path: Path to annotated PDF
        groups: List of (page, label, rect) from detect_groups
        bom_set: Set of RefDes from BOM (optional, can be empty)
        config: ConfigManager instance (optional)
        pinlist_set: Optional set of full pin IDs ("U54-F11") to filter pins
        debug_pdf_path: Path for debug overlay PDF (optional)
        log_func: Logging callback
        progress_func: Progress callback (for progress bar percentage)
        status_func: Status callback (for real-time status bar text)
        stop_event: Cancellation event

    Returns:
        List of dicts with group results
    """
    _log_func = log_func or print
    def log(msg):
        _log_func(msg)
        _logger.info(msg)

    progress = progress_func or (lambda x: None)
    status = status_func or (lambda x: None)

    # Get config or use defaults
    if config is None:
        config = ConfigManager("refdes_extractor")

    # Check feature flags
    geometry_enabled = config.get("geometry_analysis_enabled", True)
    adaptive_geometry_enabled = config.get("adaptive_geometry_enabled", True)

    # Extract prov_distance from config with validation
    prov_distance = config.get("prov_distance", DEFAULT_PROV_DISTANCE)
    if prov_distance <= 0:
        log(f"WARNING: Invalid PROV distance ({prov_distance}), using default {DEFAULT_PROV_DISTANCE}px")
        prov_distance = DEFAULT_PROV_DISTANCE
    log(f"Using PROV proximity threshold: {prov_distance}px")

    # =========================================================================
    # HYBRID MODE: Per-group extraction mode based on -FN/-PN suffix
    # =========================================================================
    global_mode = config.get("extraction_mode", "functional")
    log(f"Global extraction mode: {global_mode}")

    # Build per-group mode assignments and track pages needing geometry
    group_modes = {}
    pn_pages = set()  # Pages that have at least one -PN group

    for page_idx, name, rect in groups:
        mode = _determine_group_mode(name, global_mode)
        group_modes[(page_idx, name)] = mode
        if mode == "piece_part":
            pn_pages.add(page_idx)

    # Log mode distribution
    fn_count = sum(1 for m in group_modes.values() if m == "functional")
    pn_count = sum(1 for m in group_modes.values() if m == "piece_part")
    log(f"Hybrid mode: {fn_count} Functional groups, {pn_count} Piece-Part groups")

    if pn_count > 0:
        log(f"  Piece-Part pages: {sorted(p + 1 for p in pn_pages)}")  # 1-indexed for user

    max_pin_length = config.get("max_pin_label_length", 4)

    # =========================================================================
    # FAST PATH: No piece-part groups or pinlist provided
    # =========================================================================
    if not pn_pages:
        log("No Piece-Part groups detected, skipping geometry analysis")
        return _run_harvest_only(
            pdf_path, groups, bom_set, config, group_modes,
            pinlist_set, debug_pdf_path, log_func, progress_func,
            prov_distance, stop_event, max_pin_length
        )

    if pinlist_set:
        log("Pinlist provided - using annotation-based pin qualification (no geometry)")
        return _run_harvest_only(
            pdf_path, groups, bom_set, config, group_modes,
            pinlist_set, debug_pdf_path, log_func, progress_func,
            prov_distance, stop_event, max_pin_length
        )

    if not geometry_enabled:
        log("WARNING: Piece-Part groups detected but geometry analysis is disabled")
        log("  Falling back to unqualified pin extraction for -PN groups")
        return _run_harvest_only(
            pdf_path, groups, bom_set, config, group_modes,
            pinlist_set, debug_pdf_path, log_func, progress_func,
            prov_distance, stop_event, max_pin_length
        )

    # =========================================================================
    # ADAPTIVE GEOMETRY: Two-Pass Architecture
    # =========================================================================
    if adaptive_geometry_enabled:
        return _run_adaptive_geometry(
            pdf_path, groups, bom_set, config, group_modes, pn_pages,
            pinlist_set, debug_pdf_path, log_func, progress_func, status_func,
            prov_distance, stop_event, max_pin_length
        )

    # =========================================================================
    # LEGACY PATH: Full geometry on all piece-part pages
    # =========================================================================
    log(f"Running full geometry analysis on {len(pn_pages)} pages (adaptive disabled)...")
    return _run_full_geometry(
        pdf_path, groups, bom_set, config, group_modes, pn_pages,
        pinlist_set, debug_pdf_path, log_func, progress_func, status_func,
        prov_distance, stop_event, max_pin_length
    )


def _run_harvest_only(
    pdf_path: Path,
    groups: list,
    bom_set: set,
    config: ConfigManager,
    group_modes: dict,
    pinlist_set: Optional[set],
    debug_pdf_path: Path,
    log_func,
    progress_func,
    prov_distance: float,
    stop_event,
    max_pin_length: int,
) -> list:
    """Run harvest without geometry analysis (fast path)."""
    progress = progress_func or (lambda x: None)
    progress(0.1)

    results = harvest_hybrid(
        pdf_path, groups, bom_set, config,
        group_modes=group_modes,
        pin_map={},
        body_rects={},
        pinlist_set=pinlist_set,
        debug_pdf_path=debug_pdf_path,
        log_func=log_func,
        progress_func=progress_func,
        prov_distance=prov_distance,
        stop_event=stop_event,
        max_pin_length=max_pin_length,
    )

    progress(1.0)
    return results


def _run_full_geometry(
    pdf_path: Path,
    groups: list,
    bom_set: set,
    config: ConfigManager,
    group_modes: dict,
    pn_pages: set,
    pinlist_set: Optional[set],
    debug_pdf_path: Path,
    log_func,
    progress_func,
    status_func,
    prov_distance: float,
    stop_event,
    max_pin_length: int,
) -> list:
    """Legacy path: run full geometry on all piece-part pages."""
    log = log_func or (lambda x: None)
    progress = progress_func or (lambda x: None)

    progress(0.1)

    geo_config = {
        "pin_assignment_threshold": config.get("pin_assignment_threshold", 50.0),
        "refdes_search_radius": config.get("refdes_search_radius", 100.0),
        "y_overlap_weight": config.get("y_overlap_weight", 0.7),
        "dx_weight": config.get("dx_weight", 0.3),
        "refdes_font_size_min": config.get("refdes_font_size_min", 8.0),
        "max_pin_label_length": max_pin_length,
    }

    pin_map = {}
    body_rects = {}

    try:
        pin_map, body_rects = ga.analyze_document(
            str(pdf_path),
            geo_config,
            stop_event=stop_event,
            log_func=log,
            status_func=status_func,
            progress_func=progress_func,
            page_filter=pn_pages
        )
        log(f"  Geometry analysis complete: {len(pin_map)} pins mapped, {len(body_rects)} bodies tracked")
        progress(0.3)
    except (CancellationError, InterruptedError):
        raise
    except Exception as e:
        log(f"  ERROR: Geometry analysis failed ({e}), continuing without pin qualification")
        _logger.error(f"Geometry analysis failed: {e}")

    progress(0.4)

    results = harvest_hybrid(
        pdf_path, groups, bom_set, config,
        group_modes=group_modes,
        pin_map=pin_map,
        body_rects=body_rects,
        pinlist_set=pinlist_set,
        debug_pdf_path=debug_pdf_path,
        log_func=log_func,
        progress_func=progress_func,
        prov_distance=prov_distance,
        stop_event=stop_event,
        max_pin_length=max_pin_length,
    )

    progress(1.0)
    return results


def _parse_tokens(value: str) -> set:
    if not value:
        return set()
    tokens = set()
    for part in str(value).split(","):
        token = part.strip()
        if token:
            tokens.add(token)
    return tokens


def _parse_pages(value: str) -> set:
    if not value:
        return set()
    pages = set()
    for part in str(value).split(","):
        token = part.strip()
        if not token:
            continue
        try:
            pages.add(int(token))
        except ValueError:
            continue
    return pages


def _format_pages(pages: set) -> str:
    if not pages:
        return ""
    return ", ".join(str(p) for p in sorted(pages))


def _merge_hybrid_results(base_results: list, override_results: list) -> list:
    """
    Merge two hybrid result lists by unioning tokens and pages for matching groups.

    Intended for combining disjoint page subsets (e.g., flagged vs unflagged pages).
    Gap rows from the override set are ignored to avoid partial-gap noise.
    """
    merged = [dict(row) for row in (base_results or [])]
    index = {row.get("group"): i for i, row in enumerate(merged) if row.get("group")}

    for row in (override_results or []):
        if row.get("_is_gap"):
            continue
        group = row.get("group")
        if not group:
            continue

        tokens = _parse_tokens(row.get("failure mode causes", ""))
        pages = _parse_pages(row.get("pages", ""))

        if group in index:
            base_row = merged[index[group]]
            base_tokens = _parse_tokens(base_row.get("failure mode causes", ""))
            base_pages = _parse_pages(base_row.get("pages", ""))

            merged_tokens = base_tokens | tokens
            merged_pages = base_pages | pages

            base_row["failure mode causes"] = ", ".join(sorted(merged_tokens, key=natural_key)) if merged_tokens else ""
            base_row["component count"] = len(merged_tokens)
            base_row["pages"] = _format_pages(merged_pages)
        else:
            new_row = dict(row)
            new_row["failure mode causes"] = ", ".join(sorted(tokens, key=natural_key)) if tokens else ""
            new_row["component count"] = len(tokens)
            new_row["pages"] = _format_pages(pages)
            merged.append(new_row)
            index[group] = len(merged) - 1  # Track newly added group

    # Sort merged results to restore natural group order
    def _result_sort_key(row):
        """Sort key: regular groups first (natural order), then PROVISIONAL, then UNGROUPED."""
        g = row.get("group", "")
        if row.get("_is_gap"):
            return (3, "", "")  # Gaps at the very end
        if "UNGROUPED" in g:
            return (2, "", g)
        if "PROVISIONAL" in g:
            return (1, "", g)
        return (0, natural_key(g), "")

    merged.sort(key=_result_sort_key)
    return merged


def _run_adaptive_geometry(
    pdf_path: Path,
    groups: list,
    bom_set: set,
    config: ConfigManager,
    group_modes: dict,
    pn_pages: set,
    pinlist_set: Optional[set],
    debug_pdf_path: Path,
    log_func,
    progress_func,
    status_func,
    prov_distance: float,
    stop_event,
    max_pin_length: int,
) -> list:
    """
    Adaptive Geometry Analysis - Two-Pass Architecture.

    Phase 1: Fast BOM-only extraction with metrics collection
    Phase 2: Smart gating to select problematic pages
    Phase 3: Selective geometry on flagged pages only
    Phase 4: Re-harvest and merge results
    """
    from common import check_cancelled

    log = log_func or (lambda x: None)
    progress = progress_func or (lambda x: None)
    status = status_func or (lambda x: None)

    log("Adaptive Geometry Analysis enabled")

    # =========================================================================
    # PHASE 1: Fast BOM-only extraction with metrics collection
    # =========================================================================
    log("Phase 1: Fast extraction (collecting metrics)...")
    status("Phase 1: Fast extraction...")
    progress(0.05)

    check_cancelled(stop_event, "Cancelled before Phase 1")

    # Run harvest WITHOUT geometry to collect baseline metrics
    phase1_result = harvest_hybrid(
        pdf_path, groups, bom_set, config,
        group_modes=group_modes,
        pin_map={},           # No geometry data
        body_rects={},        # No body data
        pinlist_set=pinlist_set,
        debug_pdf_path=None,  # No debug PDF in Phase 1
        log_func=log_func,
        progress_func=lambda p: progress(0.05 + p * 0.15),  # 5-20%
        prov_distance=prov_distance,
        stop_event=stop_event,
        max_pin_length=max_pin_length,
        collect_metrics=True,  # NEW: Collect PageMetrics
    )

    # Unpack metrics
    phase1_results, page_metrics = phase1_result

    progress(0.20)

    # =========================================================================
    # PHASE 2: Smart Gating - Analyze metrics to find problematic pages
    # =========================================================================
    log("Phase 2: Analyzing metrics for geometry gating...")
    status("Phase 2: Analyzing metrics...")

    check_cancelled(stop_event, "Cancelled before Phase 2")

    # Build gating config from user config (use defaults for now)
    gating_config = _engine.GatingConfig(
        orphan_threshold=config.get("adaptive_orphan_threshold", 5),
        orphan_ratio_threshold=config.get("adaptive_orphan_ratio", 0.30),
        max_geometry_pages=config.get("adaptive_max_pages", 10),
    )

    # Filter to only piece-part pages for gating
    pn_page_metrics = {k: v for k, v in page_metrics.items() if k in pn_pages}

    # Select pages that need geometry
    problematic_pages, suppressed_pages = _engine.select_pages_for_geometry(pn_page_metrics, gating_config)

    # Log gating decisions (telemetry)
    total_orphans = sum(m.orphan_count for m in pn_page_metrics.values())
    total_candidates = sum(m.total_pin_candidates for m in pn_page_metrics.values())

    log(f"  Phase 1 metrics: {total_candidates} pin candidates, {total_orphans} orphans")

    if problematic_pages:
        log(f"  Flagged {len(problematic_pages)} page(s) for geometry: {sorted(p + 1 for p in problematic_pages)}")
        for page_idx in sorted(problematic_pages):
            m = page_metrics[page_idx]
            log(f"    Page {page_idx + 1}: {m.orphan_count} orphans ({m.orphan_ratio:.1%}), "
                f"triggers: {m.trigger_reasons}, score: {m.need_score:.1f}")
    else:
        log("  No pages flagged for geometry analysis (metrics look clean)")

    if suppressed_pages:
        log(f"  Suppressed {len(suppressed_pages)} triggered page(s):")
        for page_idx in sorted(suppressed_pages):
            m = page_metrics[page_idx]
            reasons = ", ".join(suppressed_pages[page_idx]) if suppressed_pages[page_idx] else "suppressed"
            log(f"    Page {page_idx + 1}: {m.orphan_count} orphans ({m.orphan_ratio:.1%}), "
                f"triggers: {m.trigger_reasons}, {reasons}")

    progress(0.25)

    # =========================================================================
    # PHASE 3: Selective Geometry Analysis
    # =========================================================================
    pin_map = {}
    body_rects = {}

    if problematic_pages:
        log(f"Phase 3: Running geometry on {len(problematic_pages)} flagged page(s)...")
        status(f"Phase 3: Geometry on {len(problematic_pages)} page(s)...")

        check_cancelled(stop_event, "Cancelled before Phase 3")

        geo_config = {
            "pin_assignment_threshold": config.get("pin_assignment_threshold", 50.0),
            "refdes_search_radius": config.get("refdes_search_radius", 100.0),
            "y_overlap_weight": config.get("y_overlap_weight", 0.7),
            "dx_weight": config.get("dx_weight", 0.3),
            "refdes_font_size_min": config.get("refdes_font_size_min", 8.0),
            "max_pin_label_length": max_pin_length,
        }

        try:
            pin_map, body_rects = ga.analyze_document(
                str(pdf_path),
                geo_config,
                stop_event=stop_event,
                log_func=log,
                status_func=status,
                progress_func=lambda p: progress(0.25 + p * 0.35),  # 25-60%
                page_filter=problematic_pages  # Only flagged pages
            )
            log(f"  Geometry complete: {len(pin_map)} pins mapped, {len(body_rects)} bodies")
        except (CancellationError, InterruptedError):
            raise
        except Exception as e:
            log(f"  ERROR: Geometry failed ({e}), using Phase 1 results")
            _logger.error(f"Geometry analysis failed: {e}")
            pin_map = {}
            body_rects = {}
    else:
        log("Phase 3: Skipped (no pages need geometry)")

    progress(0.60)

    # =========================================================================
    # PHASE 4: Re-harvest problematic pages and merge
    # =========================================================================
    debug_requested = bool(debug_pdf_path)
    phase4_metrics = None
    results = phase1_results

    if problematic_pages and (pin_map or body_rects):
        log("Phase 4: Re-harvesting with geometry data...")
        status("Phase 4: Merging results...")

        check_cancelled(stop_event, "Cancelled before Phase 4")

        if debug_requested:
            # Full pass to generate complete debug overlay
            final_results = harvest_hybrid(
                pdf_path, groups, bom_set, config,
                group_modes=group_modes,
                pin_map=pin_map,
                body_rects=body_rects,
                pinlist_set=pinlist_set,
                debug_pdf_path=debug_pdf_path,
                log_func=log_func,
                progress_func=lambda p: progress(0.60 + p * 0.35),  # 60-95%
                prov_distance=prov_distance,
                stop_event=stop_event,
                max_pin_length=max_pin_length,
                collect_metrics=True,
            )
            results, phase4_metrics = final_results
        else:
            flagged_groups = [g for g in groups if g[0] in problematic_pages]
            unflagged_groups = [g for g in groups if g[0] not in problematic_pages]

            flagged_results = []
            unflagged_results = []

            if flagged_groups:
                flagged_results_tuple = harvest_hybrid(
                    pdf_path, flagged_groups, bom_set, config,
                    group_modes=group_modes,
                    pin_map=pin_map,
                    body_rects=body_rects,
                    pinlist_set=pinlist_set,
                    debug_pdf_path=None,
                    log_func=log_func,
                    progress_func=lambda p: progress(0.60 + p * 0.20),  # 60-80%
                    prov_distance=prov_distance,
                    stop_event=stop_event,
                    max_pin_length=max_pin_length,
                    collect_metrics=True,
                )
                flagged_results, phase4_metrics = flagged_results_tuple

            if unflagged_groups:
                unflagged_results = harvest_hybrid(
                    pdf_path, unflagged_groups, bom_set, config,
                    group_modes=group_modes,
                    pin_map={},
                    body_rects={},
                    pinlist_set=pinlist_set,
                    debug_pdf_path=None,
                    log_func=log_func,
                    progress_func=lambda p: progress(0.80 + p * 0.15),  # 80-95%
                    prov_distance=prov_distance,
                    stop_event=stop_event,
                    max_pin_length=max_pin_length,
                )

            results = _merge_hybrid_results(unflagged_results, flagged_results)

        # Log improvement (telemetry)
        if phase4_metrics:
            phase4_orphans = sum(m.orphan_count for m in phase4_metrics.values() if m.page_idx in problematic_pages)
            phase1_flagged_orphans = sum(m.orphan_count for m in page_metrics.values() if m.page_idx in problematic_pages)

            if phase1_flagged_orphans > 0:
                improvement = (phase1_flagged_orphans - phase4_orphans) / phase1_flagged_orphans
                log(f"  Orphan reduction: {phase1_flagged_orphans} → {phase4_orphans} ({improvement:.0%} improvement)")
            else:
                log(f"  Orphans after geometry: {phase4_orphans}")

        progress(0.95)
    else:
        log("Phase 4: Using Phase 1 results (no geometry improvement)")

        if debug_requested:
            # Generate debug PDF from Phase 1 results
            check_cancelled(stop_event, "Cancelled before debug PDF generation")
            _ = harvest_hybrid(
                pdf_path, groups, bom_set, config,
                group_modes=group_modes,
                pin_map={},
                body_rects={},
                pinlist_set=pinlist_set,
                debug_pdf_path=debug_pdf_path,
                log_func=log_func,
                progress_func=lambda p: progress(0.60 + p * 0.35),  # 60-95%
                prov_distance=prov_distance,
                stop_event=stop_event,
                max_pin_length=max_pin_length,
            )

        progress(0.95)

    progress(1.0)
    return results
