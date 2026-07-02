#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# Freeze lifted 2026-04-08: this file is now actively maintained as part of
# the Tauri desktop suite. The original "FROZEN -- Do not modify" directive
# has been removed by user request. See plan: mighty-wishing-meadow.md
# ============================================================================
"""
Extraction Engine Module for RefDes Extractor

This module handles the actual extraction of reference designators and pins
from annotated PDF files. It supports multiple extraction modes:
- Functional FMEA: RefDes only, with blacklist filtering
- Piece-Part FMEA: RefDes + Pins with geometry analysis
- Hybrid: Per-group mode selection based on -FN/-PN suffix

ARCHITECTURE:
    This module is extracted from refdes_extractor_logic.py to improve
    maintainability and testability. It contains the harvest functions
    that iterate through PDF pages and extract components.

KEY FUNCTIONS:
    - harvest_components(): Legacy extraction (basic mode)
    - harvest_functional_fmea(): Functional FMEA extraction (RefDes only)
    - harvest_hybrid(): Hybrid mode with per-group extraction
    - _format_results(): Format legacy results
    - _format_functional_results(): Format functional mode results
    - _format_hybrid_results(): Format hybrid mode results

THREAD SAFETY:
    All functions accept stop_event for cancellation. Functions use
    check_cancelled() for cooperative cancellation at key checkpoints.

DEPENDENCIES:
    - group_detection: Geometry helper functions
    - geometry_analyzer: Pin-to-RefDes mapping
    - common: Shared utilities (canonicalize_refdes, ensure_file_available, etc.)
    - refdes_extractor_logic: Helper functions (_is_blacklisted, strip_suffix, etc.)
"""

import re
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Callable, Tuple, Set
from collections import defaultdict
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

import fitz  # PyMuPDF


# =============================================================================
# ADAPTIVE GEOMETRY: PageMetrics and GatingConfig
# =============================================================================
# These dataclasses support the two-pass hybrid extraction architecture:
# 1. Fast BOM-only extraction collects metrics per page
# 2. Smart gating decides which pages need expensive geometry analysis
# 3. Selective geometry runs only on problematic pages
# =============================================================================

@dataclass
class PageMetrics:
    """
    Metrics collected per page during fast BOM-only extraction (Phase 1).

    Used by the gating logic to decide which pages need geometry analysis.
    Orphan-based metrics (MVP) detect unresolved pins. Ambiguity and BGA
    metrics (future phases) catch mis-parenting and dense grid patterns.
    """
    page_idx: int

    # Coverage metrics (from debug_shapes analysis)
    total_pin_candidates: int = 0      # All detected pins on page
    parented_count: int = 0            # Resolved: PIN_QUAL, PIN_PARENT, PIN_BOX, PIN_CLUSTER
    orphan_count: int = 0              # Unresolved: PIN_UNQUAL, PIN_EXCLUDED, PIN_FILTERED

    @property
    def orphan_ratio(self) -> float:
        """Ratio of orphan pins to total pin candidates (0.0-1.0)."""
        if self.total_pin_candidates == 0:
            return 0.0
        return self.orphan_count / self.total_pin_candidates

    # Ambiguity metrics (Phase B - future)
    low_margin_count: int = 0          # Pins where best vs second-best parent was close
    avg_margin: float = 1.0            # Average confidence margin (1.0 = high confidence)
    conflict_count: int = 0            # Pins mapping plausibly to multiple ICs

    # BGA signature metrics (Phase C - future)
    grid_pin_count: int = 0            # Tokens matching BGA pattern [A-Z]{1,2}[0-9]{1,2}
    has_bga_context: bool = False      # Nearby "Pin", "Ball", "Signal" headers

    @property
    def grid_pin_ratio(self) -> float:
        """Ratio of grid-style pins to total candidates (indicates BGA page)."""
        if self.total_pin_candidates == 0:
            return 0.0
        return self.grid_pin_count / self.total_pin_candidates

    # Suppression signals (Phase C - future)
    ic_refdes_count: int = 0           # U*/IC* refdes tokens on page
    table_score: float = 0.0           # BOM/parts-list likelihood (0.0-1.0)

    # Metadata
    trigger_reasons: List[str] = field(default_factory=list)
    need_score: float = 0.0            # Combined score for ranking


@dataclass
class GatingConfig:
    """
    Configuration for the smart gating logic that decides which pages
    need geometry analysis.

    Default thresholds are conservative - better to run geometry on pages
    that might not need it than miss pages that do.
    """
    # Orphan-based trigger thresholds (MVP)
    orphan_threshold: int = 5          # Min unresolved pins for orphan trigger
    orphan_ratio_threshold: float = 0.30  # Min % unresolved for orphan trigger

    # Ambiguity-based trigger thresholds (Phase B)
    ambiguity_threshold: int = 3       # Min low-margin pins for ambiguity trigger
    margin_min: float = 0.15           # Margin below which parenting is "low confidence"
    min_pins_for_ambiguity: int = 3    # Min pins to consider ambiguity

    # BGA signature thresholds (Phase C)
    bga_ratio_threshold: float = 0.50  # Grid-pin ratio indicating BGA page

    # Suppression thresholds (Phase C)
    table_score_max: float = 0.70      # Above this, page is likely BOM (suppress)
    min_pins_for_geometry: int = 3     # Pages with fewer pins skip geometry

    # Budget control
    max_geometry_pages: int = 10       # Safety cap on geometry pages per document

    # Scoring weights for ranking
    w_orphan: float = 1.0              # Weight for orphan_count
    w_ratio: float = 100.0             # Weight for orphan_ratio (0-1)
    w_ambig: float = 2.0               # Weight for low_margin_count
    w_bga: float = 0.5                 # Weight for grid_pin_count
    w_table: float = 50.0              # Penalty for table_score


# Import from common module
from common import (
    ensure_file_available,
    check_cancelled,
    CancellationError,
    ConfigManager,
    canonicalize_refdes,
    get_prefix,
    should_analyze_pins,
)

# Import geometry analyzer
from . import geometry_analyzer as ga

# Import group detection helpers
from .group_detection import center, area_of, point_in_rect, rect_overlap

# Import pinlist parenting module (for pinlist-driven pin qualification)
from .pinlist_parenting import qualify_pins_via_pinlist, DEFAULT_PIN_PARENT_PREFIX_ALLOWLIST

# Module logger
_logger = logging.getLogger(__name__)

WORDS_EXTRACTION_TIMEOUT_SECONDS = 30.0

# Thread tracking for safe cleanup before document close
# PyMuPDF C calls can't be interrupted - threads may continue after timeout
# Caller MUST call cleanup_words_extraction_threads() before closing the document
#
# WARNING: This is module-level state. If multiple extractions run simultaneously
# (e.g., user opens multiple instances), cleanup from one operation could affect
# threads from another. The Flet GUI currently enforces single-extraction via
# the Cancel/Run button state, but direct API callers should be aware.
_words_extraction_threads: list = []
_words_thread_lock = threading.Lock()


def _report_words_timeout(
    page_num: int,
    timeout: float,
    log: Optional[Callable[[str], None]],
) -> None:
    """Report a word-extraction timeout to BOTH logs (harvest #2).

    ``page.get_text("words")`` is a PyMuPDF C call that can hang on pathological
    pages; on timeout we return an empty word list, which silently drops that
    page's RefDes + pins. Callers cannot tell "timed out" from "genuinely no
    words". Mirror the ``_report_pinlist_failure`` pattern: log to the rotating
    file log AND surface the WARNING on the streamed run log so the user knows
    the page may be incomplete rather than empty. Shared by BOTH the legacy and
    NextGen harvests because both route page-word extraction through
    ``_get_words_with_timeout``.
    """
    msg = (
        f"WARNING: Word extraction timed out on page {page_num + 1} after "
        f"{timeout:.0f}s; that page's RefDes/pins may be missing."
    )
    _logger.warning(msg)
    if log:
        log(msg)


def _get_words_with_timeout(
    page: fitz.Page,
    page_num: int = 0,
    timeout: float = WORDS_EXTRACTION_TIMEOUT_SECONDS,
    log_func: Optional[Callable[[str], None]] = None,
) -> list:
    """
    Extract words from a page with a timeout to prevent indefinite blocking.

    PyMuPDF's page.get_text("words") is a C library call and can hang on
    pathological pages. This wrapper runs the extraction in a separate thread
    and returns an empty list on timeout/error.

    IMPORTANT: Spawned thread may continue running after timeout. Caller MUST
    call cleanup_words_extraction_threads() before closing the PDF document
    to prevent crashes from threads accessing freed page objects.
    """
    start_time = time.time()
    result_container = {"result": [], "done": False}

    def extract_sync():
        try:
            result_container["result"] = page.get_text("words") or []
            result_container["done"] = True
        except Exception as e:
            _logger.warning(f"Page {page_num + 1} words extraction error: {e}")
            result_container["done"] = True

    thread = threading.Thread(target=extract_sync, daemon=True)

    with _words_thread_lock:
        _words_extraction_threads.append(thread)

    thread.start()
    thread.join(timeout=timeout)

    if result_container["done"]:
        # Thread finished in time - remove from tracking
        with _words_thread_lock:
            if thread in _words_extraction_threads:
                _words_extraction_threads.remove(thread)
        elapsed = time.time() - start_time
        _logger.debug(f"Page {page_num + 1}: words extraction completed in {elapsed:.2f}s")
        return result_container["result"]
    else:
        # Timeout - thread is still running (zombie)
        # Keep in tracking list for cleanup later.
        # Surface on BOTH the file log and the streamed run log (harvest #2) so a
        # silently-dropped page is visible instead of looking genuinely empty.
        _report_words_timeout(page_num, timeout, log_func)
        return []


def cleanup_words_extraction_threads(timeout_per_thread: float = 2.0) -> int:
    """
    Wait for any zombie word extraction threads before closing document.

    MUST be called before closing the PDF document to prevent crash/corruption
    from threads accessing freed page objects.

    Args:
        timeout_per_thread: Maximum seconds to wait for each thread

    Returns:
        Number of threads that were still running (zombies cleaned up)
    """
    with _words_thread_lock:
        threads_to_wait = list(_words_extraction_threads)
        _words_extraction_threads.clear()

    zombie_count = 0
    for thread in threads_to_wait:
        if thread.is_alive():
            zombie_count += 1
            thread.join(timeout=timeout_per_thread)
            if thread.is_alive():
                _logger.warning(f"Words extraction thread did not finish within {timeout_per_thread}s cleanup window")

    return zombie_count


# =============================================================================
# REGEX PATTERNS AND HELPERS (imported from main logic module at runtime)
# =============================================================================

# These will be set by the main logic module to avoid circular imports
REFDES_RE = None
POWER_SOURCE_RE = None
DEFAULT_PROV_DISTANCE = 15.0

# Late-bound helper functions from refdes_extractor_logic.py
# Set by _init_patterns() to avoid circular imports at module load time
_is_blacklisted = None
_strip_suffix = None
_annotation_box_contains_body = None
_find_refdes_in_box = None


def _init_patterns(refdes_re, power_source_re, prov_distance=15.0):
    """
    Initialize regex patterns and helper functions from main logic module.
    
    Called by refdes_extractor_logic.py to pass its compiled patterns and
    helper functions. This avoids circular imports while keeping the
    centralized implementations in the main logic module.
    
    Args:
        refdes_re: Compiled regex for RefDes matching
        power_source_re: Compiled regex for power source patterns (P3V3, etc.)
        prov_distance: Default PROV marker distance threshold
    """
    global REFDES_RE, POWER_SOURCE_RE, DEFAULT_PROV_DISTANCE
    global _is_blacklisted, _strip_suffix, _annotation_box_contains_body, _find_refdes_in_box
    
    REFDES_RE = refdes_re
    POWER_SOURCE_RE = power_source_re
    DEFAULT_PROV_DISTANCE = prov_distance
    
    # Late import helper functions from main logic module
    try:
        from . import refdes_extractor_logic as logic
    except ImportError:
        import refdes_extractor_logic as logic
    
    _is_blacklisted = logic._is_blacklisted
    _strip_suffix = logic.strip_suffix
    _annotation_box_contains_body = logic.annotation_box_contains_body
    _find_refdes_in_box = logic._find_refdes_in_box


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def natural_key(s) -> tuple:
    """
    Generate a sort key for natural sorting (alphanumeric aware).
    
    Examples:
        R1, R2, R10 -> sorts as 1, 2, 10 (not 1, 10, 2)
        
    Args:
        s: String to generate sort key for
        
    Returns:
        Tuple suitable for sorting
    """
    s = str(s)
    parts = re.findall(r"\d+|\D+", s)
    return tuple((0, int(p)) if p.isdigit() else (1, p.lower()) for p in parts)


# =============================================================================
# RESULT FORMATTING
# =============================================================================

def _add_item(store: dict, group: str, token: str, page: int) -> None:
    """
    Add a token to a group in the result store.
    
    Args:
        store: Dict of {group_name: {"tokens": set, "pages": set}}
        group: Group name to add to
        token: Token (RefDes or pin) to add
        page: Page number where token was found
    """
    if group not in store:
        store[group] = {"tokens": set(), "pages": set()}
    store[group]["tokens"].add(token)
    store[group]["pages"].add(page)


def _add_group_token(store: dict, base_group: str, token: str, page: int, bom_set: set) -> None:
    """
    Add a token to a group, creating "NOT IN BOM" variant if needed.
    
    Args:
        store: Dict of {group_name: {"tokens": set, "pages": set}}
        base_group: Base group name
        token: Token to add
        page: Page number
        bom_set: Set of RefDes from BOM for verification
    """
    target = base_group if token in bom_set else f"{base_group} (NOT IN BOM)"
    _add_item(store, target, token, page)


def _format_results(grouped_data: dict) -> List[dict]:
    """
    Format grouped data into result rows for legacy mode.
    
    Args:
        grouped_data: Dict of {group_name: {"tokens": set, "pages": set}}
        
    Returns:
        List of dicts with group, failure mode causes, component count, pages
    """
    rows = []
    for gname, data in grouped_data.items():
        tokens = sorted(data["tokens"], key=natural_key)
        rows.append({
            "group": gname,
            "failure mode causes": ", ".join(tokens),
            "component count": len(tokens),
            "pages": ", ".join(str(p) for p in sorted(data["pages"]))
        })
    
    def sort_key(row):
        g = row["group"]
        if "UNGROUPED" in g:
            return (2, g)
        if "PROVISIONAL" in g:
            return (1, g)
        return (0, natural_key(g))
    
    return sorted(rows, key=sort_key)


def _report_pinlist_failure(page_idx, exc, log) -> None:
    """Report a pinlist pin-qualification failure to BOTH logs (Tier-2 #20).

    The page's qualified-pin set is emptied on failure, so logging only to the
    rotating file log left the output looking complete while it silently had no
    qualified pins for that page. Surface it on the streamed run log too so the
    user knows to check the pinlist / that page.
    """
    _logger.error(f"Pinlist clustering failed on page {page_idx}: {exc}")
    if log:
        log(
            f"WARNING: Pinlist pin-qualification failed on page {page_idx} "
            f"({exc}); this page has NO qualified pins — verify the pinlist and this page."
        )


def _format_functional_results(grouped_data: dict, log_func: Callable = None) -> List[dict]:
    """
    Format results for Functional FMEA mode.

    ALWAYS outputs both Verified and Unverified rows for every group,
    even if one is empty. This ensures consistent structure for downstream
    FMEA processing.

    Args:
        grouped_data: Dict of {group_name: {"verified": set, "unverified": set, "pages": set}}
        log_func: Optional logging callback for gap detection reporting

    Returns:
        List of dicts with group results
    """
    # Import detect_sequence_gaps here to avoid circular import at module level
    try:
        from .refdes_extractor_logic import detect_sequence_gaps
    except ImportError:
        from refdes_extractor_logic import detect_sequence_gaps
    
    rows = []

    for group_name, data in grouped_data.items():
        verified = sorted(data["verified"], key=natural_key)
        unverified = sorted(data["unverified"], key=natural_key)
        pages = ", ".join(str(p) for p in sorted(data["pages"])) if data["pages"] else ""

        # Handle special groups differently
        if "UNGROUPED" in group_name or "PROVISIONAL" in group_name:
            # For special groups, only output if they have components
            all_components = verified + unverified
            if all_components:
                rows.append({
                    "group": group_name,
                    "failure mode causes": ", ".join(all_components),
                    "component count": len(all_components),
                    "pages": pages
                })
        else:
            # For regular groups, ALWAYS output both Verified and Unverified rows
            rows.append({
                "group": f"{group_name} (Verified)",
                "failure mode causes": ", ".join(verified) if verified else "",
                "component count": len(verified),
                "pages": pages
            })
            rows.append({
                "group": f"{group_name} (Unverified)",
                "failure mode causes": ", ".join(unverified) if unverified else "",
                "component count": len(unverified),
                "pages": pages
            })

    # Detect sequence gaps in regular groups
    regular_groups = [name for name in grouped_data.keys()
                      if "UNGROUPED" not in name and "PROVISIONAL" not in name]
    gap_rows = detect_sequence_gaps(regular_groups, log_func)
    rows.extend(gap_rows)

    # Sort results
    def sort_key(row):
        g = row["group"]
        if "UNGROUPED" in g:
            return (2, "", g)
        if "PROVISIONAL" in g:
            return (1, "", g)
        if row.get("_is_gap") or "GROUP NOT DETECTED" in g:
            # Gap rows: sort by group name in sequence order, after normal groups
            base_name = g.replace(" (GROUP NOT DETECTED)", "")
            return (0, natural_key(base_name), 2)  # Priority 2 = after Unverified (1)
        # Keep Verified and Unverified together for same group
        base_name = g.replace(" (Verified)", "").replace(" (Unverified)", "")
        is_unverified = "(Unverified)" in g
        return (0, natural_key(base_name), 1 if is_unverified else 0)

    return sorted(rows, key=sort_key)


def _format_hybrid_results(
    grouped_data: dict,
    group_modes: dict,
    bom_set: set,
    log_func: Callable = None
) -> list:
    """
    Format results with mode-aware structure and suffix stripping.

    - FUNCTIONAL groups: Always output Verified + Unverified rows (even if empty)
    - PIECE_PART groups: Output single row with tokens, apply BOM verification
    - Strip -FN/-PN suffixes from all group names

    Args:
        grouped_data: Dict of accumulated data per group
        group_modes: Dict {(page_idx, name): mode} for mode lookup
        bom_set: BOM set for piece-part verification
        log_func: Optional logging callback for gap detection reporting

    Returns:
        List of formatted result dicts
    """
    # Import helpers from main logic module
    try:
        from .refdes_extractor_logic import _strip_mode_suffix, detect_sequence_gaps
    except ImportError:
        from refdes_extractor_logic import _strip_mode_suffix, detect_sequence_gaps
    
    rows = []
    normalized_bom = {canonicalize_refdes(r) for r in bom_set} if bom_set else set()

    for group_name, data in grouped_data.items():
        # Strip suffix for clean output
        display_name = _strip_mode_suffix(group_name)
        mode = data.get("mode", "functional")
        pages = ", ".join(str(p) for p in sorted(data.get("pages", set()))) if data.get("pages") else ""

        # Handle special groups (UNGROUPED, PROVISIONAL)
        if "UNGROUPED" in group_name or "PROVISIONAL" in group_name:
            if mode == "functional":
                all_components = list(data.get("verified", set())) + list(data.get("unverified", set()))
            else:
                all_components = list(data.get("tokens", set()))

            if all_components:
                rows.append({
                    "group": group_name,  # Keep special names as-is
                    "failure mode causes": ", ".join(sorted(all_components, key=natural_key)),
                    "component count": len(all_components),
                    "pages": pages
                })
            continue

        if mode == "functional":
            # FUNCTIONAL: Dual-row output (Verified + Unverified)
            verified = sorted(data.get("verified", set()), key=natural_key)
            unverified = sorted(data.get("unverified", set()), key=natural_key)

            rows.append({
                "group": f"{display_name} (Verified)",
                "failure mode causes": ", ".join(verified) if verified else "",
                "component count": len(verified),
                "pages": pages
            })
            rows.append({
                "group": f"{display_name} (Unverified)",
                "failure mode causes": ", ".join(unverified) if unverified else "",
                "component count": len(unverified),
                "pages": pages
            })

        else:  # "piece_part"
            # PIECE_PART: Single row with tokens, BOM verification applied
            tokens = data.get("tokens", set())

            # Split tokens into verified/unverified based on BOM
            # FIX: Use EXACT token matching, not base-matching
            # U200-A7 is verified ONLY if BOM contains U200-A7, not just U200
            verified_tokens = []
            unverified_tokens = []
            for token in tokens:
                canon_token = canonicalize_refdes(token)
                if canon_token and canon_token in normalized_bom:
                    verified_tokens.append(token)
                else:
                    unverified_tokens.append(token)

            # Output verified row
            rows.append({
                "group": f"{display_name} (Verified)",
                "failure mode causes": ", ".join(sorted(verified_tokens, key=natural_key)) if verified_tokens else "",
                "component count": len(verified_tokens),
                "pages": pages
            })
            # Output unverified row
            rows.append({
                "group": f"{display_name} (Unverified)",
                "failure mode causes": ", ".join(sorted(unverified_tokens, key=natural_key)) if unverified_tokens else "",
                "component count": len(unverified_tokens),
                "pages": pages
            })

    # Detect sequence gaps in regular groups (strip suffixes for consistent detection)
    try:
        from .refdes_extractor_logic import _strip_mode_suffix
    except ImportError:
        from refdes_extractor_logic import _strip_mode_suffix
        
    regular_groups = [_strip_mode_suffix(name) for name in grouped_data.keys()
                      if "UNGROUPED" not in name and "PROVISIONAL" not in name]
    gap_rows = detect_sequence_gaps(regular_groups, log_func)
    rows.extend(gap_rows)

    # Sort results
    def sort_key(row):
        g = row["group"]
        if "UNGROUPED" in g:
            return (2, "", g)
        if "PROVISIONAL" in g:
            return (1, "", g)
        if row.get("_is_gap") or "GROUP NOT DETECTED" in g:
            # Gap rows: sort by group name in sequence order, after normal groups
            base_name = g.replace(" (GROUP NOT DETECTED)", "")
            return (0, natural_key(base_name), 2)  # Priority 2 = after Unverified (1)
        # Keep Verified and Unverified together for same group
        base_name = g.replace(" (Verified)", "").replace(" (Unverified)", "")
        is_unverified = "(Unverified)" in g
        return (0, natural_key(base_name), 1 if is_unverified else 0)

    return sorted(rows, key=sort_key)


# =============================================================================
# HARVEST FUNCTIONS
# =============================================================================

def harvest_components(
    pdf_path: Path,
    groups: list,
    bom_set: set,
    debug_pdf_path: Path = None,
    log_func: Callable = None,
    progress_func: Callable = None,
    prov_distance: float = None,
    stop_event: threading.Event = None,
    max_pin_length: int = 4,
) -> list:
    """
    Basic component harvesting from annotated PDF (legacy mode).
    
    This function extracts RefDes and pins from annotated PDF pages,
    associating them with detected groups.
    
    Args:
        pdf_path: Path to annotated PDF
        groups: List of (page, label, rect) from detect_groups
        bom_set: Set of RefDes from BOM for verification
        debug_pdf_path: Path for debug overlay PDF (optional)
        log_func: Logging callback
        progress_func: Progress callback
        prov_distance: PROV marker proximity threshold
        stop_event: Cancellation event
        
    Returns:
        List of dicts with group results
    """
    _log_func = log_func or (lambda x: None)
    
    def log(msg):
        _log_func(msg)
        _logger.info(msg)
    
    progress = progress_func or (lambda x: None)
    
    if prov_distance is None:
        prov_distance = DEFAULT_PROV_DISTANCE

    pdf_path = ensure_file_available(pdf_path, log)
    grouped_data = {}
    debug_shapes = [] if debug_pdf_path else None

    with fitz.open(str(pdf_path)) as doc:
        try:
            page_group_map = {i: [] for i in range(len(doc))}
            for p, name, rect in groups:
                page_group_map[p].append({
                    "name": name,
                    "rect": rect,
                    "area": area_of(rect),
                    "is_connector": "CONN" in name.upper()
                })
            for p in page_group_map:
                page_group_map[p].sort(key=lambda x: x["area"])

            for page_idx, page in enumerate(doc):
                check_cancelled(stop_event, "Extraction cancelled by user.")
                if len(doc) > 0:
                    progress((page_idx + 1) / len(doc))

                words = _get_words_with_timeout(page, page_num=page_idx, log_func=log)
                current_groups = page_group_map[page_idx]

                if debug_shapes is not None:
                    for g in current_groups:
                        debug_shapes.append((page_idx, g["rect"], (1, 0, 0), g["name"]))

                prov_markers = []
                for w_idx, w in enumerate(words):
                    if w_idx % 100 == 0:
                        check_cancelled(stop_event, "PROV marker detection cancelled by user.")
                    if (w[4] or "").strip().upper() == "PROV":
                        prov_markers.append((w[0], w[1], w[2], w[3]))

                for w_idx, w in enumerate(words):
                    if w_idx % 50 == 0:
                        check_cancelled(stop_event, "Word processing cancelled by user.")

                    text = (w[4] or "").strip()
                    if not text:
                        continue

                    rect = (w[0], w[1], w[2], w[3])
                    cx, cy = center(rect)

                    is_refdes = REFDES_RE.fullmatch(text) and not POWER_SOURCE_RE.match(text)
                    is_pin = ga.is_pin_candidate(text, max_length=max_pin_length) and not is_refdes

                    if not (is_refdes or is_pin):
                        continue

                    my_group = None
                    for g in current_groups:
                        if point_in_rect(cx, cy, g["rect"]):
                            my_group = g
                            break

                    if my_group:
                        if is_refdes:
                            base = _strip_suffix(text)
                            _add_group_token(grouped_data, my_group["name"], base, page_idx+1, bom_set)
                            if debug_shapes is not None:
                                debug_shapes.append((page_idx, rect, (0, 0, 1), "CONN"))
                        elif is_pin:
                            val = f"PIN-{text}"
                            if text in bom_set:
                                log(f"WARNING: {val} - text '{text}' matches BOM RefDes (uncertain)")
                                val = f"{val} [?]"
                                if debug_shapes is not None:
                                    debug_shapes.append((page_idx, rect, (1, 0.5, 0), "PIN_UNCERTAIN"))
                            else:
                                if debug_shapes is not None:
                                    debug_shapes.append((page_idx, rect, (0, 0.5, 1), "PIN"))
                            _add_item(grouped_data, my_group["name"], val, page_idx+1)
                    elif is_refdes:
                        base = _strip_suffix(text)
                        is_prov = False
                        for p_rect in prov_markers:
                            pcx, pcy = center(p_rect)
                            if ((cx - pcx)**2 + (cy - pcy)**2)**0.5 < prov_distance:
                                is_prov = True
                                break

                        if is_prov:
                            _add_item(grouped_data, "PROVISIONAL", base, page_idx+1)
                            if debug_shapes is not None:
                                debug_shapes.append((page_idx, rect, (1, 0.5, 0), "PROV"))
                        else:
                            cat = "UNGROUPED (IN BOM)" if base in bom_set else "UNGROUPED (NOT IN BOM)"
                            _add_item(grouped_data, cat, base, page_idx+1)
                            if debug_shapes is not None:
                                debug_shapes.append((page_idx, rect, (0.5, 0.5, 0.5), "LOST"))

            if debug_pdf_path and debug_shapes:
                log(f"Generating debug PDF...")
                try:
                    for p_idx, r, col, label in debug_shapes:
                        if stop_event and stop_event.is_set():
                            break
                        pg = doc[p_idx]
                        pg.draw_rect(r, color=col, width=1.5 if label == "GROUP" else 0.75)
                        if col == (1, 0, 0):
                            pg.insert_text((r[0], r[1]-2), label, color=col, fontsize=6)
                    doc.save(str(debug_pdf_path))
                    log(f"  Debug PDF saved: {debug_pdf_path}")
                except Exception as e:
                    error_msg = f"WARNING: Failed to save debug PDF: {e}"
                    log(error_msg)
                    _logger.exception(error_msg)
        finally:
            # CRITICAL: Wait for any zombie word extraction threads before document closes
            zombie_count = cleanup_words_extraction_threads(timeout_per_thread=2.0)
            if zombie_count > 0:
                log(f"Cleaned up {zombie_count} background word extraction thread(s)")

    return _format_results(grouped_data)


def harvest_functional_fmea(
    pdf_path: Path,
    groups: list,
    bom_set: set,
    config: Optional[ConfigManager] = None,
    debug_pdf_path: Path = None,
    log_func: Callable = None,
    progress_func: Callable = None,
    prov_distance: float = None,
    stop_event: threading.Event = None
) -> list:
    """
    Functional FMEA extraction mode - RefDes only, no pins.

    This is a fast, annotation-based extraction that:
    1. Extracts ONLY Reference Designators (no PIN-xxx entries)
    2. Applies blacklist filtering to remove false positives
    3. ALWAYS outputs both Verified and Unverified rows for EVERY group

    Args:
        pdf_path: Path to annotated PDF
        groups: List of (page, label, rect) from detect_groups
        bom_set: Set of RefDes from BOM for verification
        config: ConfigManager for user blacklist/whitelist settings
        debug_pdf_path: Path for debug overlay PDF (optional)
        log_func: Logging callback
        progress_func: Progress callback
        prov_distance: Proximity threshold for PROV markers
        stop_event: Cancellation event

    Returns:
        List of dicts with group results
    """
    _log_func = log_func or (lambda x: None)
    
    def log(msg):
        _log_func(msg)
        _logger.info(msg)

    progress = progress_func or (lambda x: None)
    
    if prov_distance is None:
        prov_distance = DEFAULT_PROV_DISTANCE

    # Check for empty groups
    if not groups:
        log("WARNING: No annotation groups detected in PDF - no components to extract")
        return []

    pdf_path = ensure_file_available(pdf_path, log)
    debug_shapes = []

    # Normalize BOM set for comparison
    normalized_bom = {canonicalize_refdes(r) for r in bom_set} if bom_set else set()
    if not normalized_bom:
        log("NOTE: No BOM loaded - all components will be marked as Unverified")

    # Data structure: {group_name: {"verified": set(), "unverified": set(), "pages": set()}}
    grouped_data = {}

    # Initialize all groups with empty sets
    for p, name, rect in groups:
        if name not in grouped_data:
            grouped_data[name] = {"verified": set(), "unverified": set(), "pages": set()}

    with fitz.open(str(pdf_path)) as doc:
        try:
            page_group_map = {i: [] for i in range(len(doc))}
            for p, name, rect in groups:
                page_group_map[p].append({"name": name, "rect": rect, "area": area_of(rect)})
            for p in page_group_map:
                page_group_map[p].sort(key=lambda x: x["area"])

            for page_idx, page in enumerate(doc):
                check_cancelled(stop_event, "Extraction cancelled by user.")
                if len(doc) > 0:
                    progress((page_idx + 1) / len(doc))

                words = _get_words_with_timeout(page, page_num=page_idx, log_func=log)
                current_groups = page_group_map[page_idx]

                for g in current_groups:
                    debug_shapes.append((page_idx, g["rect"], (1, 0, 0), g["name"]))

                prov_markers = []
                for w_idx, w in enumerate(words):
                    if w_idx % 100 == 0:
                        check_cancelled(stop_event, "PROV marker detection cancelled by user.")
                    if (w[4] or "").strip().upper() == "PROV":
                        prov_markers.append((w[0], w[1], w[2], w[3]))

                for w_idx, w in enumerate(words):
                    if w_idx % 50 == 0:
                        check_cancelled(stop_event, "Word processing cancelled by user.")

                    text = (w[4] or "").strip()
                    if not text:
                        continue

                    # Skip blacklisted items using late-bound helper
                    if _is_blacklisted and _is_blacklisted(text, config):
                        _logger.debug(f"Skipped blacklisted: {text}")
                        continue

                    rect = (w[0], w[1], w[2], w[3])
                    cx, cy = center(rect)

                    is_refdes = REFDES_RE.fullmatch(text) and not POWER_SOURCE_RE.match(text)
                    if not is_refdes:
                        continue

                    my_group = None
                    for g in current_groups:
                        if point_in_rect(cx, cy, g["rect"]):
                            my_group = g
                            break

                    base = _strip_suffix(text)

                    is_prov = False
                    for p_rect in prov_markers:
                        pcx, pcy = center(p_rect)
                        if ((cx - pcx)**2 + (cy - pcy)**2)**0.5 < prov_distance:
                            is_prov = True
                            break

                    if is_prov:
                        if "PROVISIONAL" not in grouped_data:
                            grouped_data["PROVISIONAL"] = {"verified": set(), "unverified": set(), "pages": set()}
                        grouped_data["PROVISIONAL"]["unverified"].add(base)
                        grouped_data["PROVISIONAL"]["pages"].add(page_idx + 1)
                        debug_shapes.append((page_idx, rect, (1, 0.5, 0), "PROV"))
                    elif my_group:
                        group_name = my_group["name"]
                        normalized_base = canonicalize_refdes(base)
                        if normalized_base in normalized_bom:
                            grouped_data[group_name]["verified"].add(base)
                            debug_shapes.append((page_idx, rect, (0, 0.8, 0), "VERIFIED"))
                        else:
                            grouped_data[group_name]["unverified"].add(base)
                            debug_shapes.append((page_idx, rect, (0.8, 0.4, 0), "UNVERIFIED"))
                        grouped_data[group_name]["pages"].add(page_idx + 1)
                    else:
                        normalized_base = canonicalize_refdes(base)
                        if normalized_base in normalized_bom:
                            cat = "UNGROUPED (IN BOM)"
                        else:
                            cat = "UNGROUPED (NOT IN BOM)"
                        if cat not in grouped_data:
                            grouped_data[cat] = {"verified": set(), "unverified": set(), "pages": set()}
                        grouped_data[cat]["unverified"].add(base)
                        grouped_data[cat]["pages"].add(page_idx + 1)
                        debug_shapes.append((page_idx, rect, (0.5, 0.5, 0.5), "UNGROUPED"))

            if debug_pdf_path:
                log(f"Generating debug PDF...")
                try:
                    for p_idx, r, col, label in debug_shapes:
                        if stop_event and stop_event.is_set():
                            break
                        pg = doc[p_idx]
                        pg.draw_rect(r, color=col, width=1.5 if label in ("GROUP", "VERIFIED") else 0.75)
                        if col == (1, 0, 0):
                            pg.insert_text((r[0], r[1] - 2), label, color=col, fontsize=6)
                    doc.save(str(debug_pdf_path))
                    log(f"  Debug PDF saved: {debug_pdf_path}")
                except Exception as e:
                    error_msg = f"WARNING: Failed to save debug PDF: {e}"
                    log(error_msg)
                    _logger.exception(error_msg)
        finally:
            # CRITICAL: Wait for any zombie threads before document closes
            zombie_count = cleanup_words_extraction_threads(timeout_per_thread=2.0)
            if zombie_count > 0:
                log(f"Cleaned up {zombie_count} background word extraction thread(s)")

    return _format_functional_results(grouped_data, log)


def harvest_hybrid(
    pdf_path: Path,
    groups: list,
    bom_set: set,
    config: ConfigManager,
    group_modes: dict,
    pin_map: dict,
    body_rects: dict,
    pinlist_set: Optional[set] = None,
    debug_pdf_path: Path = None,
    log_func: Callable = None,
    progress_func: Callable = None,
    prov_distance: float = None,
    stop_event: threading.Event = None,
    max_pin_length: int = 4,
    collect_metrics: bool = False,
) -> list:
    """
    Hybrid harvester that processes groups according to their individual modes.

    For FUNCTIONAL groups:
      - RefDes only, blacklist filtering, no pins
      - Output: Verified/Unverified split rows

    For PIECE_PART groups:
      - RefDes + Pins with geometry analysis
      - Output: Single row with all tokens

    Args:
        pdf_path: Path to annotated PDF
        groups: List of (page, label, rect) from detect_groups
        bom_set: Set of RefDes from BOM for verification
        config: ConfigManager for blacklist/whitelist settings
        group_modes: Dict {(page_idx, name): "functional"|"piece_part"}
        pin_map: Dict from geometry analysis
        body_rects: Dict from geometry analysis
        pinlist_set: Optional set of full pin IDs ("U54-F11") to include
        debug_pdf_path: Path for debug overlay PDF (optional)
        log_func: Logging callback
        progress_func: Progress callback
        prov_distance: PROV marker proximity threshold
        stop_event: Cancellation event
        max_pin_length: Maximum pin label length
        collect_metrics: If True, return (results, page_metrics_dict) tuple
                         for adaptive geometry gating

    Returns:
        List of dicts with formatted results, or
        (List, Dict[int, PageMetrics]) tuple if collect_metrics=True
    """
    log = log_func or (lambda x: None)
    progress = progress_func or (lambda x: None)
    
    if prov_distance is None:
        prov_distance = DEFAULT_PROV_DISTANCE

    if not groups:
        log("No groups to process")
        if collect_metrics:
            return [], {}  # Return tuple when metrics requested
        return []

    normalized_bom = {canonicalize_refdes(r) for r in bom_set} if bom_set else set()
    if not normalized_bom:
        log("NOTE: No BOM loaded - all components will be marked as Unverified")

    def _canonicalize_pin_id(token: str) -> str:
        """
        Normalize a pin identifier to "REFDES-PIN" form for set membership checks.

        Accepts common delimiters (., :, -) and strips whitespace.
        """
        if token is None:
            return ""
        t = str(token).strip().upper()
        if not t:
            return ""
        # Skip uncertain markers
        if t.endswith("[?]"):
            t = t[:-3].strip()
        # Normalize delimiters to hyphen
        t = re.sub(r"\s*[-.:]\s*", "-", t)
        t = re.sub(r"-{2,}", "-", t)
        if "-" not in t:
            return ""
        ref, pin = t.rsplit("-", 1)
        ref = canonicalize_refdes(_strip_suffix(ref) if _strip_suffix else ref)
        pin = re.sub(r"\s+", "", pin).upper()
        if not ref or not pin:
            return ""
        return f"{ref}-{pin}"

    normalized_pinlist = set()
    if pinlist_set:
        normalized_pinlist = {p for p in (_canonicalize_pin_id(x) for x in pinlist_set) if p}
        if normalized_pinlist:
            log(f"Pinlist filtering enabled: {len(normalized_pinlist)} pin(s)")
    _qt_lookup_cache: dict = {}

    page_group_map = defaultdict(list)
    for page_idx, name, rect in groups:
        mode = group_modes.get((page_idx, name), "functional")
        page_group_map[page_idx].append({
            "name": name,
            "rect": rect,
            "mode": mode,
            "area": area_of(rect),
            "is_connector": name.upper().startswith(("J", "P", "CONN")),
        })

    for page_idx in page_group_map:
        page_group_map[page_idx].sort(key=lambda g: g["area"])

    grouped_data = {}
    for page_idx, name, rect in groups:
        mode = group_modes.get((page_idx, name), "functional")
        if name not in grouped_data:
            if mode == "functional":
                grouped_data[name] = {"verified": set(), "unverified": set(), "pages": set(), "mode": mode}
            else:
                grouped_data[name] = {"tokens": set(), "pages": set(), "mode": mode}

    # Collect ALL mappings for each (page, pin-label) so that when multiple
    # components share a pin label on a page we disambiguate geometrically
    # (_disambiguate_pin_mapping) instead of letting the last-written one win.
    pin_lookup_by_label = defaultdict(list)
    for pid, mapping in pin_map.items():
        page_idx = mapping.page_num
        label = mapping.pin_label
        pin_lookup_by_label[(page_idx, label)].append(mapping)

    debug_shapes = []

    # Hydrate OneDrive cloud-only files before opening
    pdf_path = ensure_file_available(pdf_path, log)

    with fitz.open(str(pdf_path)) as doc:
        try:
            total_pages = len(doc)

            for page_idx, page in enumerate(doc):
                check_cancelled(stop_event, "Hybrid harvesting cancelled by user.")
                if total_pages > 0:
                    progress(0.4 + 0.5 * (page_idx / total_pages))

                current_groups = page_group_map.get(page_idx, [])

                if not current_groups:
                    continue

                words = _get_words_with_timeout(page, page_num=page_idx, log_func=log)

                for g in current_groups:
                    debug_shapes.append((page_idx, g["rect"], (1, 0, 0), g["name"]))

                prov_markers = []
                for w in words:
                    if (w[4] or "").strip().upper() == "PROV":
                        prov_markers.append((w[0], w[1], w[2], w[3]))

                # Precompute RefDes candidates for parent lookup (include words outside annotations).
                page_refdes_candidates = []
                for w in words:
                    t = (w[4] or "").strip()
                    if not t:
                        continue
                    if REFDES_RE.fullmatch(t) and not POWER_SOURCE_RE.match(t):
                        r = (w[0], w[1], w[2], w[3])
                        rcx, rcy = center(r)
                        page_refdes_candidates.append((canonicalize_refdes(_strip_suffix(t)), rcx, rcy))

                # Assign words to the smallest enclosing annotation once per page.
                group_entries = defaultdict(list)  # group_name -> list[dict]
                for w_idx, w in enumerate(words):
                    if w_idx % 200 == 0:
                        check_cancelled(stop_event, "Word processing cancelled by user.")

                    text = (w[4] or "").strip()
                    if not text:
                        continue

                    rect = (w[0], w[1], w[2], w[3])
                    cx, cy = center(rect)

                    my_group = None
                    for g in current_groups:
                        if point_in_rect(cx, cy, g["rect"]):
                            my_group = g
                            break

                    if not my_group:
                        continue

                    is_prov = False
                    for p_rect in prov_markers:
                        pcx, pcy = center(p_rect)
                        if ((cx - pcx)**2 + (cy - pcy)**2)**0.5 < prov_distance:
                            is_prov = True
                            break

                    group_entries[my_group["name"]].append(
                        {"text": text, "rect": rect, "center": (cx, cy), "is_prov": is_prov}
                    )

                # =====================================================================
                # PINLIST-DRIVEN PIN QUALIFICATION (NEW CLUSTERING PIPELINE)
                # =====================================================================
                # When a pinlist is provided, use the new clustering-based approach to
                # avoid passive terminal contamination (e.g., capacitor 1/2 becoming U92-2)
                pinlist_qualified_pins = {}
                has_piece_part_groups = any(g["mode"] == "piece_part" for g in current_groups)

                if normalized_pinlist and has_piece_part_groups:
                    # Filter to piece_part groups only
                    piece_part_entries = {
                        g["name"]: group_entries.get(g["name"], [])
                        for g in current_groups
                        if g["mode"] == "piece_part"
                    }

                    if piece_part_entries:
                        # Helper to check RefDes (avoids circular import)
                        def _is_refdes_check(text: str) -> bool:
                            return bool(REFDES_RE.fullmatch(text) and not POWER_SOURCE_RE.match(text))

                        # Helper to check pin candidate
                        def _is_pin_candidate_check(text: str) -> bool:
                            return ga.is_pin_candidate(text, max_length=max_pin_length)

                        # Extract config dict from ConfigManager
                        # Apply same radius expansion as legacy path for consistency
                        clustering_parent_radius = float(config.get("parent_refdes_max_radius", 300.0))
                        if normalized_pinlist and clustering_parent_radius < 250:
                            clustering_parent_radius = 500.0  # Expand for page-spanning ICs

                        pinlist_config = {
                            "pin_parent_prefix_allowlist": config.get(
                                "pin_parent_prefix_allowlist",
                                DEFAULT_PIN_PARENT_PREFIX_ALLOWLIST
                            ),
                            "passive_terminal_labels": config.get("passive_terminal_labels", ["1", "2"]),
                            "passive_context_radius_px": config.get("passive_context_radius_px", 120.0),
                            "pin_cluster_cell_size_px": config.get("pin_cluster_cell_size_px", 120.0),
                            "pin_cluster_max_dist_px": config.get("pin_cluster_max_dist_px", 150.0),
                            "cluster_min_distinct_labels": config.get("cluster_min_distinct_labels", 2),
                            "strict_numeric_pin_parenting": config.get("strict_numeric_pin_parenting", True),
                            "parent_refdes_max_radius": clustering_parent_radius,  # Pass through with expansion
                        }

                        try:
                            pinlist_qualified_pins = qualify_pins_via_pinlist(
                                group_entries=piece_part_entries,
                                normalized_pinlist=normalized_pinlist,
                                page_words=words,
                                config=pinlist_config,
                                is_refdes_fn=_is_refdes_check,
                                is_pin_candidate_fn=_is_pin_candidate_check,
                                stop_event=stop_event,  # B1 fix: Pass stop_event for cancellation support
                            )
                            _logger.debug(f"Page {page_idx}: Pinlist clustering qualified {sum(len(v) for v in pinlist_qualified_pins.values())} tokens")
                        except CancellationError:
                            raise  # Re-raise cancellation to propagate up
                        except Exception as e:
                            # Tier-2 #20: surface on the streamed run log too, not
                            # just the rotating file log — emptying this page's
                            # qualified set silently made the output look complete.
                            _report_pinlist_failure(page_idx, e, log)
                            pinlist_qualified_pins = {}

                # Parent RefDes lookup for Piece-Part groups (used when geometry mapping is unavailable).
                page_body_candidates = []
                if body_rects:
                    for (p, ref), b_rect in body_rects.items():
                        if p == page_idx:
                            page_body_candidates.append((canonicalize_refdes(_strip_suffix(ref) if _strip_suffix else ref), b_rect))

                parent_refdes_radius = float(config.get("parent_refdes_max_radius", config.get("refdes_search_radius", 100.0)))
                if normalized_pinlist and parent_refdes_radius < 250:
                    parent_refdes_radius = 500.0
                parent_refdes_radius_sq = parent_refdes_radius ** 2

                def find_parent_refdes(group_rect: tuple, pin_texts: list[str]) -> Optional[str]:
                    gcx, gcy = center(group_rect)

                    candidates = {}
                    # 1) Component body overlap (highest priority when available)
                    for ref, b_rect in page_body_candidates:
                        if _rects_overlap(group_rect, b_rect):
                            bcx = (b_rect.x0 + b_rect.x1) / 2
                            bcy = (b_rect.y0 + b_rect.y1) / 2
                            dist_sq = (gcx - bcx)**2 + (gcy - bcy)**2
                            candidates[ref] = {"source": "body", "dist_sq": dist_sq, "pos": (bcx, bcy)}

                    # 2) Nearest RefDes token, biased to above/left
                    for ref, rcx, rcy in page_refdes_candidates:
                        dx = gcx - rcx
                        dy = gcy - rcy
                        dist_sq = dx * dx + dy * dy
                        if dist_sq > parent_refdes_radius_sq:
                            continue
                        bias = 1.0
                        # Prefer RefDes above-left of the group center (typical placement).
                        if rcx < gcx and rcy < gcy:
                            bias = 0.8
                        elif rcx > gcx and rcy > gcy:
                            bias = 1.4
                        eff_dist_sq = dist_sq * bias

                        existing = candidates.get(ref)
                        if not existing or (existing["source"] != "body" and eff_dist_sq < existing["dist_sq"]):
                            candidates[ref] = {"source": "text", "dist_sq": eff_dist_sq, "pos": (rcx, rcy)}

                    if not candidates:
                        return None

                    # If we have a pinlist, pick the RefDes that produces the most matches.
                    if normalized_pinlist and pin_texts:
                        best_ref = None
                        best_hits = -1
                        best_rank = None
                        for ref, info in candidates.items():
                            hits = 0
                            for p in pin_texts:
                                full = _canonicalize_pin_id(f"{ref}-{p}")
                                if full and full in normalized_pinlist:
                                    hits += 1
                            source_pri = 0 if info["source"] == "body" else 1
                            rank = (-hits, source_pri, info["dist_sq"])
                            if hits > best_hits or (hits == best_hits and (best_rank is None or rank < best_rank)):
                                best_hits = hits
                                best_ref = ref
                                best_rank = rank
                        if best_ref and best_hits > 0:
                            return best_ref

                    # Fallback: closest candidate (prefer body)
                    best_ref = None
                    best_rank = None
                    for ref, info in candidates.items():
                        source_pri = 0 if info["source"] == "body" else 1
                        rank = (source_pri, info["dist_sq"])
                        if best_rank is None or rank < best_rank:
                            best_rank = rank
                            best_ref = ref
                    return best_ref

                parent_refdes_by_group = {}
                for g in current_groups:
                    if g["mode"] != "piece_part":
                        continue
                    entries = group_entries.get(g["name"], [])
                    if not entries:
                        continue
                    pin_texts = []
                    for e in entries:
                        t = e["text"]
                        is_ref = REFDES_RE.fullmatch(t) and not POWER_SOURCE_RE.match(t)
                        if is_ref:
                            continue
                        if ga.is_pin_candidate(t, max_length=max_pin_length):
                            pin_texts.append(t)
                    parent = find_parent_refdes(g["rect"], pin_texts)
                    if parent:
                        parent_refdes_by_group[g["name"]] = parent

                # Process per-group entries
                for g in current_groups:
                    group_name = g["name"]
                    group_mode = g["mode"]
                    entries = group_entries.get(group_name, [])
                    if not entries:
                        continue

                    for e_idx, entry in enumerate(entries):
                        if e_idx % 200 == 0:
                            check_cancelled(stop_event, "Token processing cancelled by user.")

                        text = entry["text"]
                        rect = entry["rect"]
                        cx, cy = entry["center"]
                        is_prov = entry["is_prov"]

                        if group_mode == "functional":
                            if _is_blacklisted and _is_blacklisted(text, config):
                                _logger.debug(f"Skipped blacklisted: {text}")
                                continue

                            is_refdes = REFDES_RE.fullmatch(text) and not POWER_SOURCE_RE.match(text)
                            if not is_refdes:
                                continue

                            base = _strip_suffix(text)

                            if is_prov:
                                if "PROVISIONAL" not in grouped_data:
                                    grouped_data["PROVISIONAL"] = {"verified": set(), "unverified": set(), "tokens": set(), "pages": set(), "mode": "functional"}
                                grouped_data["PROVISIONAL"]["unverified"].add(base)
                                grouped_data["PROVISIONAL"]["pages"].add(page_idx + 1)
                                debug_shapes.append((page_idx, rect, (1, 0.5, 0), "PROV"))
                            else:
                                normalized_base = canonicalize_refdes(base)
                                if normalized_base in normalized_bom:
                                    grouped_data[group_name]["verified"].add(base)
                                    debug_shapes.append((page_idx, rect, (0, 0.8, 0), "VERIFIED"))
                                else:
                                    grouped_data[group_name]["unverified"].add(base)
                                    debug_shapes.append((page_idx, rect, (0.8, 0.4, 0), "UNVERIFIED"))
                                grouped_data[group_name]["pages"].add(page_idx + 1)

                        else:  # "piece_part"
                            # BUG FIX: Apply blacklist filtering (was completely missing in piece-part mode)
                            # This prevents GND, mW, VCC, etc. from being extracted as pins
                            if _is_blacklisted and _is_blacklisted(text, config):
                                _logger.debug(f"Skipped blacklisted in piece_part: {text}")
                                continue

                            is_refdes = REFDES_RE.fullmatch(text) and not POWER_SOURCE_RE.match(text)
                            is_pin = ga.is_pin_candidate(text, max_length=max_pin_length)

                            if is_refdes:
                                base = _strip_suffix(text)
                                if is_prov:
                                    if "PROVISIONAL" not in grouped_data:
                                        grouped_data["PROVISIONAL"] = {"verified": set(), "unverified": set(), "tokens": set(), "pages": set(), "mode": "piece_part"}
                                    grouped_data["PROVISIONAL"]["tokens"].add(base)
                                    grouped_data["PROVISIONAL"]["pages"].add(page_idx + 1)
                                    debug_shapes.append((page_idx, rect, (1, 0.5, 0), "PROV"))
                                else:
                                    grouped_data[group_name]["tokens"].add(base)
                                    grouped_data[group_name]["pages"].add(page_idx + 1)
                                    debug_shapes.append((page_idx, rect, (0, 1, 0), "COMP"))

                            elif is_pin:
                                # =========================================================
                                # PINLIST CLUSTERING PATH (NEW)
                                # =========================================================
                                # If pinlist clustering was used, handle pins via the
                                # pre-qualified results instead of the old logic
                                if pinlist_qualified_pins and group_name in pinlist_qualified_pins:
                                    # Find this token in the pre-qualified results
                                    # C1+C2 fix: Use normalized text and rounded positions for more tolerant matching
                                    # Build lookup dict at start of group for O(1) matching (L2 fix)
                                    qualified_tokens = pinlist_qualified_pins[group_name]
                                    if group_name not in _qt_lookup_cache:
                                        _qt_lookup_cache[group_name] = {
                                            (qt.text, round(qt.center[0] / 5) * 5, round(qt.center[1] / 5) * 5): qt
                                            for qt in qualified_tokens
                                        }

                                    # C2 fix: Use rounded positions (5px tolerance) instead of 1px
                                    # Normalize text to uppercase to match M4 fix in pinlist_parenting
                                    normalized_text = text.upper()
                                    match_key = (normalized_text, round(cx / 5) * 5, round(cy / 5) * 5)

                                    matching_token = _qt_lookup_cache[group_name].get(match_key)

                                    if matching_token:
                                        if matching_token.suppressed:
                                            debug_shapes.append((page_idx, rect, (0.5, 0.5, 0.5), "PIN_SUPPRESS_PASSIVE"))
                                            continue
                                        elif matching_token.drop_reason:
                                            debug_shapes.append((page_idx, rect, (0.7, 0.3, 0.3), f"PIN_DROP:{matching_token.drop_reason}"))
                                            continue
                                        elif matching_token.parent_refdes:
                                            val = f"{matching_token.parent_refdes}-{matching_token.text}"

                                            # CRITICAL: Still enforce pinlist membership as final gate
                                            canon = _canonicalize_pin_id(val)
                                            if not canon or canon not in normalized_pinlist:
                                                debug_shapes.append((page_idx, rect, (0.6, 0.6, 0.6), "PIN_FILTERED"))
                                                continue

                                            grouped_data[group_name]["tokens"].add(val)
                                            grouped_data[group_name]["pages"].add(page_idx + 1)
                                            debug_shapes.append((page_idx, rect, (0, 0.8, 0.4), f"PIN_CLUSTER:{matching_token.parent_refdes}"))
                                            continue

                                    # C1 fix: If clustering was used for this group, NEVER fall through to legacy
                                    # for pin candidates. This prevents the original bug from reappearing.
                                    # The token should have been in qualified list but wasn't found - this means
                                    # either it wasn't collected as a pin candidate or clustering excluded it.
                                    _logger.debug(f"Token '{text}' at ({cx}, {cy}) excluded by clustering (no match in qualified tokens)")
                                    debug_shapes.append((page_idx, rect, (0.6, 0.6, 0.6), "PIN_EXCLUDED"))
                                    continue

                                # =========================================================
                                # LEGACY PIN PROCESSING PATH
                                # =========================================================
                                # Used when pinlist clustering is not available or didn't
                                # process this token
                                mapping = None
                                lookup_key = (page_idx, text)

                                # An "exact" dict keyed by (page, label) used to
                                # shadow this path and let the last-written mapping
                                # win when two components shared a pin label on a
                                # page; always resolve through the full candidate
                                # list so the geometric disambiguation runs.
                                if lookup_key in pin_lookup_by_label:
                                    candidates = pin_lookup_by_label[lookup_key]
                                    if len(candidates) == 1:
                                        mapping = candidates[0]
                                    else:
                                        mapping = _disambiguate_pin_mapping(
                                            candidates, g["rect"], body_rects,
                                            page_idx, (cx, cy)
                                        )

                                parent_refdes = parent_refdes_by_group.get(group_name)

                                # Skip pin analysis for components that don't have pins (R, C, D, etc.)
                                parent_prefix = None
                                if mapping and mapping.refdes:
                                    parent_prefix = get_prefix(mapping.refdes)
                                elif parent_refdes:
                                    parent_prefix = get_prefix(parent_refdes)

                                if parent_prefix and not should_analyze_pins(parent_prefix):
                                    _logger.debug(f"Skipped pin analysis for {parent_prefix} component (text={text})")
                                    continue

                                if mapping:
                                    body_key = (page_idx, mapping.refdes)
                                    if not normalized_pinlist and _annotation_box_contains_body and body_key in body_rects:
                                        if _annotation_box_contains_body(g["rect"], body_rects[body_key]):
                                            continue
                                    val = mapping.full_identifier
                                    debug_shapes.append((page_idx, rect, (0, 0.5, 1), "PIN_QUAL"))
                                elif parent_refdes:
                                    body_key = (page_idx, parent_refdes)
                                    if not normalized_pinlist and _annotation_box_contains_body and body_key in body_rects:
                                        if _annotation_box_contains_body(g["rect"], body_rects[body_key]):
                                            continue
                                    val = f"{parent_refdes}-{text}"
                                    debug_shapes.append((page_idx, rect, (0.2, 0.6, 1), "PIN_PARENT"))
                                else:
                                    if _find_refdes_in_box:
                                        box_refdes = _find_refdes_in_box(words, g["rect"], (cx, cy))
                                        if box_refdes:
                                            val = f"{box_refdes}-{text}"
                                            debug_shapes.append((page_idx, rect, (0.5, 0.5, 1), "PIN_BOX"))
                                        else:
                                            val = f"PIN-{text}"
                                            debug_shapes.append((page_idx, rect, (0.5, 0.5, 0.5), "PIN_UNQUAL"))
                                    else:
                                        val = f"PIN-{text}"
                                        debug_shapes.append((page_idx, rect, (0.5, 0.5, 0.5), "PIN_UNQUAL"))

                                if normalized_pinlist:
                                    canon = _canonicalize_pin_id(val)
                                    if not canon or canon not in normalized_pinlist:
                                        debug_shapes.append((page_idx, rect, (0.6, 0.6, 0.6), "PIN_FILTERED"))
                                        continue

                                grouped_data[group_name]["tokens"].add(val)
                                grouped_data[group_name]["pages"].add(page_idx + 1)

            # Collect page metrics if requested (for adaptive geometry gating)
            page_metrics = None
            if collect_metrics:
                page_metrics = collect_page_metrics_from_debug_shapes(debug_shapes, total_pages)

            if debug_pdf_path:
                log(f"Generating debug PDF...")
                try:
                    for p_idx, r, col, label in debug_shapes:
                        if stop_event and stop_event.is_set():
                            break
                        pg = doc[p_idx]
                        pg.draw_rect(r, color=col, width=1.5 if label in ("GROUP", "VERIFIED") else 0.75)
                        if col == (1, 0, 0):
                            pg.insert_text((r[0], r[1] - 2), label, color=col, fontsize=6)
                    doc.save(str(debug_pdf_path))
                    log(f"  Debug PDF saved: {debug_pdf_path}")
                except Exception as e:
                    log(f"WARNING: Failed to save debug PDF: {e}")
                    _logger.exception(f"Debug PDF save failed")
        finally:
            # CRITICAL: Wait for any zombie threads before document closes
            zombie_count = cleanup_words_extraction_threads(timeout_per_thread=2.0)
            if zombie_count > 0:
                log(f"Cleaned up {zombie_count} background word extraction thread(s)")

    results = _format_hybrid_results(grouped_data, group_modes, bom_set, log)

    if collect_metrics:
        return results, page_metrics
    return results


def _rects_overlap(rect1: tuple, rect2) -> bool:
    """
    Check if two rectangles overlap.

    Args:
        rect1: Tuple (x0, y0, x1, y1)
        rect2: Rect object with x0, y0, x1, y1 attributes

    Returns:
        True if rectangles overlap
    """
    x0_1, y0_1, x1_1, y1_1 = rect1
    x0_2, y0_2, x1_2, y1_2 = rect2.x0, rect2.y0, rect2.x1, rect2.y1
    return not (x1_1 < x0_2 or x1_2 < x0_1 or y1_1 < y0_2 or y1_2 < y0_1)


def _disambiguate_pin_mapping(
    candidates: List,
    group_rect: tuple,
    body_rects: Dict[tuple, any],
    page_idx: int,
    token_center: tuple
):
    """
    Select the best pin mapping when multiple components share the same pin label.

    Priority:
    1. Candidate whose body CENTER is INSIDE the group rect (strictest)
    2. Candidate whose body OVERLAPS the group rect
    3. Nearest body by proximity (fallback)

    Args:
        candidates: List of PinMapping objects
        group_rect: Annotation group rectangle
        body_rects: {(page, refdes): Rect}
        page_idx: Current page index
        token_center: (cx, cy) center of the pin token

    Returns:
        Best matching PinMapping, or None
    """
    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0]

    # Priority 1: Body CENTER is INSIDE the group rect (strictest check)
    for mapping in candidates:
        body_key = (page_idx, mapping.refdes)
        if body_key in body_rects:
            body_rect = body_rects[body_key]
            body_cx = (body_rect.x0 + body_rect.x1) / 2
            body_cy = (body_rect.y0 + body_rect.y1) / 2
            if point_in_rect(body_cx, body_cy, group_rect):
                return mapping

    # Priority 2: Body OVERLAPS the group rect (less strict)
    for mapping in candidates:
        body_key = (page_idx, mapping.refdes)
        if body_key in body_rects:
            body_rect = body_rects[body_key]
            if _rects_overlap(group_rect, body_rect):
                return mapping

    # Priority 3: Nearest body by proximity (fallback)
    best_mapping = None
    best_dist = float('inf')
    for mapping in candidates:
        body_key = (page_idx, mapping.refdes)
        if body_key in body_rects:
            body_rect = body_rects[body_key]
            body_center = ((body_rect.x0 + body_rect.x1) / 2,
                           (body_rect.y0 + body_rect.y1) / 2)
            dist = ((token_center[0] - body_center[0])**2 +
                    (token_center[1] - body_center[1])**2)
            if dist < best_dist:
                best_dist = dist
                best_mapping = mapping

    return best_mapping


# =============================================================================
# ADAPTIVE GEOMETRY: Metrics Collection and Analysis
# =============================================================================

# Debug shape labels that indicate parented (resolved) pins
_PARENTED_LABELS = frozenset([
    "PIN_QUAL",      # Geometry-qualified
    "PIN_PARENT",    # Parent RefDes found nearby
    "PIN_BOX",       # RefDes found in annotation box
    "PIN_CLUSTER",   # Pinlist clustering resolved
])

# Debug shape labels that indicate orphan (unresolved) pins
_ORPHAN_LABELS = frozenset([
    "PIN_UNQUAL",        # Unqualified pin (no parent found)
    "PIN_UNCERTAIN",     # Ambiguous pin/refdes - treat as orphan for gating
    "PIN_EXCLUDED",      # Excluded by clustering
    "PIN_FILTERED",      # Filtered by pinlist
    "PIN_SUPPRESS_PASSIVE",  # Suppressed passive terminal
    "PIN_DROP",          # Dropped by clustering reason (PIN_DROP:*)
])

# Labels that count as pin candidates (both parented and orphan)
_PIN_CANDIDATE_LABELS = _PARENTED_LABELS | _ORPHAN_LABELS | frozenset([
    "PIN_UNCERTAIN",     # BOM collision (might be RefDes or pin)
    "PIN",               # Basic pin (legacy mode)
])


def collect_page_metrics_from_debug_shapes(
    debug_shapes: List[Tuple],
    page_count: int,
) -> Dict[int, PageMetrics]:
    """
    Analyze debug_shapes to produce PageMetrics for each page.

    This is the MVP metrics collection that counts orphans from debug_shapes
    annotations. Future phases will add ambiguity and BGA detection.

    Args:
        debug_shapes: List of (page_idx, rect, color, label) tuples
        page_count: Total number of pages in document

    Returns:
        Dict mapping page_idx to PageMetrics
    """
    # Initialize metrics for all pages
    metrics_by_page: Dict[int, PageMetrics] = {
        i: PageMetrics(page_idx=i) for i in range(page_count)
    }

    for shape in debug_shapes:
        page_idx, rect, color, label = shape

        # Skip non-pin labels
        base_label = label.split(":")[0] if ":" in label else label

        if base_label not in _PIN_CANDIDATE_LABELS:
            continue

        # This is a pin candidate - bounds check for safety
        if page_idx not in metrics_by_page:
            _logger.warning(f"debug_shapes contains unknown page_idx {page_idx}, skipping")
            continue
        metrics = metrics_by_page[page_idx]
        metrics.total_pin_candidates += 1

        # PIN_CLUSTER is already in _PARENTED_LABELS, no need for startswith check
        if base_label in _PARENTED_LABELS:
            metrics.parented_count += 1
        elif base_label in _ORPHAN_LABELS:
            metrics.orphan_count += 1
        # PIN_UNCERTAIN and basic PIN are counted but not classified

    return metrics_by_page


def should_run_geometry(
    metrics: PageMetrics,
    config: GatingConfig,
) -> Tuple[bool, List[str]]:
    """
    Determine if a page should trigger geometry analysis.

    Returns (should_trigger, reasons_list).

    MVP implements orphan-based triggering only.
    Phase B will add ambiguity detection.
    Phase C will add BGA detection.
    """
    reasons = []

    # TRIGGER 1: Orphan-based (MVP baseline)
    if (metrics.orphan_count >= config.orphan_threshold and
            metrics.orphan_ratio >= config.orphan_ratio_threshold):
        reasons.append("orphan_trigger")

    # TRIGGER 2: Ambiguity-based (Phase B - placeholder)
    # Uncomment when low_margin tracking is implemented:
    # if metrics.low_margin_count >= config.ambiguity_threshold:
    #     reasons.append("ambiguity_trigger")
    # if (metrics.avg_margin <= config.margin_min and
    #         metrics.total_pin_candidates >= config.min_pins_for_ambiguity):
    #     reasons.append("low_confidence_trigger")

    # TRIGGER 3: BGA signature (Phase C - placeholder)
    # Uncomment when BGA detection is implemented:
    # if (metrics.grid_pin_ratio >= config.bga_ratio_threshold and
    #         metrics.ic_refdes_count > 0):
    #     if metrics.orphan_count > 0 or metrics.low_margin_count > 0:
    #         reasons.append("bga_trigger")

    return len(reasons) > 0, reasons


def apply_suppressions(
    metrics: PageMetrics,
    triggered: bool,
    config: GatingConfig,
) -> Tuple[bool, List[str]]:
    """
    Apply suppression rules to prevent geometry on pages that won't benefit.

    Returns (allow_geometry, suppression_reasons).
    """
    reasons = []
    if not triggered:
        return False, reasons

    # SUPPRESS 1: BOM/parts-list pages (Phase C - placeholder)
    # Uncomment when table_score detection is implemented:
    # if metrics.table_score >= config.table_score_max and metrics.ic_refdes_count == 0:
    #     reasons.append("suppressed_bom_table")

    # SUPPRESS 2: Pages with too few pin candidates
    if metrics.total_pin_candidates < config.min_pins_for_geometry:
        reasons.append("suppressed_too_few_pins")

    if reasons:
        return False, reasons

    return True, reasons


def select_pages_for_geometry(
    page_metrics: Dict[int, PageMetrics],
    config: GatingConfig,
) -> Tuple[Set[int], Dict[int, List[str]]]:
    """
    Select pages that need geometry analysis, respecting budget cap.

    Ranks pages by combined need_score and returns the top N.

    Args:
        page_metrics: Dict mapping page_idx to PageMetrics
        config: Gating configuration with thresholds and weights

    Returns:
        (selected_pages, suppressed_pages) tuple
    """
    scored_pages = []
    suppressed_pages: Dict[int, List[str]] = {}

    for page_idx, metrics in page_metrics.items():
        triggered, reasons = should_run_geometry(metrics, config)

        if triggered:
            allowed, suppress_reasons = apply_suppressions(metrics, triggered, config)
            if not allowed:
                metrics.trigger_reasons = reasons
                suppressed_pages[page_idx] = suppress_reasons
                continue

            # Calculate combined need score
            score = (
                config.w_orphan * metrics.orphan_count +
                config.w_ratio * metrics.orphan_ratio +
                config.w_ambig * metrics.low_margin_count +
                config.w_bga * metrics.grid_pin_count -
                config.w_table * metrics.table_score
            )
            metrics.trigger_reasons = reasons
            metrics.need_score = score

            scored_pages.append((page_idx, score, reasons))

    # Sort by score descending, take top N
    scored_pages.sort(key=lambda x: -x[1])
    selected = {p[0] for p in scored_pages[:config.max_geometry_pages]}

    return selected, suppressed_pages
