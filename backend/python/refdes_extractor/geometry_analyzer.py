#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# FROZEN -- Do not modify this file.
# This module is part of a legacy tool whose development is on hold.
# All changes, bug fixes, and refactors are suspended until the freeze is lifted.
# See CLAUDE.md "Frozen Tools" section for details.
# ============================================================================
"""
Geometry Analyzer - Spatial Analysis for Pin-to-RefDes Mapping

This module implements Phase 1 of the RefDes extraction enhancement, performing
global geometric analysis to map pins to their parent RefDes labels using spatial
relationships.

Key responsibilities:
- Extract component body rectangles from vector drawings
- Detect pin ticks on component edges
- Classify text tokens (RefDes, pins, nets, junk)
- Assign pins to bodies using spatial scoring
- Assign RefDes to bodies using proximity with bias
- Build complete pin-to-RefDes mapping

THREAD SAFETY NOTE (H2):
    This module uses ThreadPoolExecutor with non-blocking shutdown (wait=False) to
    implement page-level timeouts. PyMuPDF's get_text("dict") and get_drawings()
    are C library calls that can block indefinitely on pathological PDF pages.

    When a timeout occurs:
    - The future is cancelled but the underlying C thread may continue running
    - Python cannot forcibly terminate native threads
    - Leaked threads will eventually complete or consume resources until process exit

    Mitigation strategies:
    - Page timeouts prevent UI freeze (default 60s per page, 30s for drawings)
    - MAX_DRAWINGS skip threshold aborts pages with >100k drawings before extraction
    - Consider global executor pool with max_workers limit for high-volume processing
    - For PDFs with repeated timeouts, use CLI mode or split into smaller files

Author: Claude Code (Anthropic)
Date: 2025-12-02
"""

import math
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from contextlib import nullcontext
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set, Callable

import fitz  # PyMuPDF

# Import shared utilities
from common import (
    get_tool_logger,
    check_cancelled,
    CancellationError,
)

# Initialize module logger
_logger = get_tool_logger("geometry_analyzer")

# ==================== CONSTANTS & CONFIGURATION ====================

# Body detection parameters
MIN_BODY_WIDTH = 20.0  # pixels
MIN_BODY_HEIGHT = 20.0
MAX_BODY_WIDTH = 500.0
MAX_BODY_HEIGHT = 500.0
MIN_ASPECT_RATIO = 0.3
MAX_ASPECT_RATIO = 3.0

# Pin tick detection parameters
MIN_TICK_LENGTH = 2.0  # pixels
MAX_TICK_LENGTH = 25.0  # Expanded from 10px to catch longer pin stubs (Issue #4)
MIN_TICK_LENGTH_SQ = MIN_TICK_LENGTH ** 2  # Pre-computed for sqrt-free comparisons
MAX_TICK_LENGTH_SQ = MAX_TICK_LENGTH ** 2
TICK_EDGE_TOLERANCE = 5.0  # Distance from body edge

# BGA circle detection parameters (Issue #4 supplement)
MIN_BGA_RADIUS = 1.0   # Minimum circle radius in pixels
MAX_BGA_RADIUS = 8.0   # Maximum circle radius in pixels
BGA_EDGE_TOLERANCE = 15.0  # Distance from body edge

# Wire detection parameters
MIN_WIRE_LENGTH = 50.0  # pixels
MIN_WIRE_LENGTH_SQ = MIN_WIRE_LENGTH ** 2  # Pre-computed for sqrt-free comparisons

# Text classification parameters
REFDES_PATTERN = re.compile(r'^[A-Z]{1,4}\d+[A-Z]?$', re.IGNORECASE)
PIN_PATTERN = re.compile(r'^P(?:IN)?[-_]?\d+$', re.IGNORECASE)  # Legacy pattern (strict)
NET_PATTERN = re.compile(r'^[A-Z0-9_\.\-]+$', re.IGNORECASE)

# SI unit suffixes that should NOT be treated as pin labels
# These commonly appear in schematics as component values but look like valid pins
# NOTE: Single-letter units (A, F, V, W) are EXCLUDED because they're commonly used
# as FPGA/connector pin labels. SI units with magnitude typically appear with numbers
# (e.g., "10A", "5V") which would fail the isalnum() check anyway due to spaces.
SI_UNIT_SUFFIXES = frozenset({
    # Capacitance (excluding single "F" - could be a pin)
    "mF", "uF", "nF", "pF",
    # Voltage (excluding single "V" - could be a pin)
    "mV", "kV", "uV",
    # Power (excluding single "W" - could be a pin)
    "mW", "kW", "uW",
    # Current (excluding single "A" - could be a pin)
    "mA", "uA", "nA",
    # Frequency - "Hz" is 2 chars but unlikely to be a pin
    "Hz", "kHz", "MHz", "GHz",
    # Time
    "ns", "us", "ms",
})
# Pre-compute uppercase versions for O(1) case-insensitive lookup
_SI_UNIT_SUFFIXES_UPPER = frozenset(s.upper() for s in SI_UNIT_SUFFIXES)

# Pre-compile regex for value+unit patterns (e.g., "10uF", "25mW", "3.3V")
# Matches: digits (with optional decimal), followed by any SI unit suffix
# This catches cases where component values like "100pF" look like valid pins
_VALUE_UNIT_RE = re.compile(
    r'^\d+(?:\.\d+)?(' + '|'.join(re.escape(s) for s in SI_UNIT_SUFFIXES) + r')$',
    re.IGNORECASE
)


def is_pin_candidate(text: str, max_length: int = None) -> bool:
    """
    Check if text could be a pin label.

    Pin candidates are short alphanumeric strings without underscores.
    This is intentionally permissive - spatial filtering and BOM checks
    will disambiguate later.

    Accepts:
        - Pure digits: 7, 20, 99
        - Single letters: A, B
        - Letter+digit combos: A1, ab77, R25 (FPGA pins)
        - Classic pin format: P20, PIN24
        - Bonded pin notation: 24/22 (transformer bonded pins)

    Rejects:
        - Underscore-containing (signal names): MISO_34
        - Too long (>max_length chars): likely not a pin

    Args:
        text: Token text to evaluate
        max_length: Maximum allowed length for pin labels (default: DEFAULT_MAX_PIN_LABEL_LENGTH)

    Returns:
        True if text could be a pin label, False otherwise
    """
    if max_length is None:
        max_length = DEFAULT_MAX_PIN_LABEL_LENGTH

    text = text.strip()
    if not text:
        return False
    if '_' in text:
        return False  # Underscore = signal name (e.g., MISO_34)

    # Check for bonded pin notation FIRST (e.g., 24/22 for bonded transformer pins)
    # For slash notation, check each part's length, not the whole string
    if '/' in text:
        parts = text.split('/')
        # All parts must be non-empty and valid (rejects "/22" or "24/")
        return (len(parts) >= 2 and
                all(parts) and
                all(p.isalnum() and len(p) <= max_length for p in parts))

    # For non-slash text, check total length
    if len(text) > max_length:
        return False  # Too long for typical pin label

    # Reject value+unit patterns like "10uF", "25mW", "3.3V" (component values, not pins)
    if _VALUE_UNIT_RE.match(text):
        return False

    # Reject bare SI unit suffixes (e.g., mF, mW, Hz) - these are component values, not pins
    if text.upper() in _SI_UNIT_SUFFIXES_UPPER:
        return False

    # Accept any alphanumeric (letters, digits, or mix)
    return text.isalnum()

# Spatial assignment parameters (defaults, overrideable via config)
DEFAULT_PIN_THRESHOLD = 50.0
DEFAULT_REFDES_RADIUS = 100.0
DEFAULT_Y_OVERLAP_WEIGHT = 0.7
DEFAULT_DX_WEIGHT = 0.3
DEFAULT_TOP_LEFT_BIAS = 0.8
DEFAULT_MAX_PIN_LABEL_LENGTH = 4  # Max length for pin identifiers (e.g., AA27, F123)

# Memory safety limits (M22: documented limitations)
MAX_DRAWINGS_PER_PAGE = 50000  # Limit cached drawings to prevent memory exhaustion
# M22: MAX_UNIQUE_BODIES limits O(n²) deduplication. If a page has more than 5000 unique
# component bodies, excess bodies may contain duplicates. For most engineering drawings
# this limit is sufficient. If you encounter issues, consider pre-processing the PDF
# or splitting into multiple pages.
MAX_UNIQUE_BODIES = 5000  # Limit deduplication to prevent O(n²) explosion
WIRE_PROXIMITY_THRESHOLD = 20.0

# Timeout for per-page extraction (seconds)
PAGE_TIMEOUT_SECONDS = 45  # Reduced from 60 for faster skip of stuck pages

# Timeout for text extraction specifically (prevents indefinite hang on pathological pages)
TEXT_EXTRACTION_TIMEOUT = 30

# Timeout for drawings extraction (prevents indefinite hang on complex vector pages)
DRAWINGS_EXTRACTION_TIMEOUT = 15


# ==================== CANCELLATION HELPER ====================

def _check_cancelled(stop_event, operation_name: str, log_func=None):
    """
    Check if cancellation has been requested and raise if so.

    This helper ensures cancellation requests bubble up to the GUI
    as InterruptedError instead of silently returning.

    Args:
        stop_event: Threading event to check for cancellation
        operation_name: Description of current operation for logging
        log_func: Optional logging callback for UI visibility

    Raises:
        CancellationError: If stop_event is set
    """
    if stop_event and stop_event.is_set():
        msg = f"Cancelled during {operation_name}"
        if log_func:
            log_func(msg)
        _logger.info(msg)
        raise CancellationError(msg)


# ==================== DATA STRUCTURES ====================

class TokenType(Enum):
    """Classification categories for extracted text tokens."""
    REFDES = "refdes"          # U1, R15, J2A
    PIN_LABEL = "pin_label"    # P20, PIN24
    NET_LABEL = "net_label"    # MSIO34, GND, FLASH.SDI
    JUNK = "junk"              # Other text


@dataclass
class Rect:
    """Normalized rectangle (x0, y0, x1, y1) in PDF coordinates."""
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def center(self) -> Tuple[float, float]:
        """Get center point of rectangle."""
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)

    @property
    def width(self) -> float:
        """Get rectangle width."""
        return abs(self.x1 - self.x0)

    @property
    def height(self) -> float:
        """Get rectangle height."""
        return abs(self.y1 - self.y0)

    @property
    def area(self) -> float:
        """Get rectangle area."""
        return self.width * self.height

    def to_fitz_rect(self) -> fitz.Rect:
        """Convert to PyMuPDF Rect object."""
        return fitz.Rect(self.x0, self.y0, self.x1, self.y1)

    @classmethod
    def from_fitz_rect(cls, fitz_rect) -> 'Rect':
        """Create from PyMuPDF Rect object."""
        return cls(fitz_rect.x0, fitz_rect.y0, fitz_rect.x1, fitz_rect.y1)


@dataclass
class Token:
    """Extracted text with metadata and classification."""
    text: str
    rect: Rect
    font_size: float
    token_type: TokenType
    confidence: float  # 0.0-1.0 for classification confidence

    @property
    def center(self) -> Tuple[float, float]:
        """Get center point of token."""
        return self.rect.center


@dataclass
class ComponentBody:
    """Detected component outline."""
    rect: Rect
    page_num: int
    body_id: str  # Auto-generated: "body_p1_0"
    source: str   # "vector" | "raster"
    assigned_refdes: Optional[str] = None  # Assigned by _assign_refdes_to_bodies


@dataclass
class Pin:
    """Pin tick mark on component edge."""
    location: Tuple[float, float]  # (x, y) tick position
    edge: str  # "left" | "right" | "top" | "bottom"
    label_token: Optional[Token]  # Associated P20 label
    body_id: Optional[str]  # Assigned component

    @property
    def x(self) -> float:
        return self.location[0]

    @property
    def y(self) -> float:
        return self.location[1]


@dataclass
class GeometryData:
    """Complete page geometry extraction."""
    page_num: int
    bodies: List[ComponentBody]
    pins: List[Pin]
    tokens: List[Token]
    wire_segments: List[Tuple[Rect, Rect]]  # line endpoints


@dataclass
class PinMapping:
    """Final pin-to-RefDes association."""
    pin_identifier: str  # "p1_pin_15"
    refdes: str  # "U1B"
    pin_label: str  # "P20"
    full_identifier: str  # "U1B-P20"
    confidence: float  # Combined score
    page_num: int


# ==================== MAIN ENTRY POINT ====================

def analyze_document(
    pdf_path: str,
    config: Optional[Dict] = None,
    cancel_token=None,
    log_func: Callable[[str], None] = None,
    stop_event=None,
    status_func: Callable[[str], None] = None,
    progress_func: Callable[[float], None] = None,
    page_filter: Optional[set] = None,
    doc: Optional[fitz.Document] = None,
) -> Tuple[Dict[str, PinMapping], Dict[Tuple[int, str], Rect]]:
    """
    Main entry point: analyze entire PDF and build pin-to-RefDes mapping.

    This performs Phase 1 global geometry analysis to understand the schematic
    layout and associate pins with their parent RefDes labels.

    Now with:
    - Per-page timeout (60s) with auto-skip
    - Detailed progress reporting
    - Proper cancellation that raises InterruptedError
    - Optional page filtering for hybrid mode optimization

    Args:
        pdf_path: Path to PDF schematic
        config: Configuration dict with geometry_analysis settings
        cancel_token: Cancellation support (CancellationToken object)
        log_func: Optional logging callback for execution log
        stop_event: Threading event for cancellation
        status_func: Optional callback for status bar updates
        progress_func: Optional callback for progress bar (0.0-1.0)
        page_filter: Optional set of page indices (0-indexed) to analyze.
                     If None, analyzes all pages. If provided, only analyzes
                     pages in the set (for hybrid mode per-page optimization).

    Returns:
        Tuple of (pin_map, body_rects):
        - pin_map: {pin_identifier: PinMapping}
        - body_rects: {(page_num, refdes): Rect} for containment checks

    Raises:
        FileNotFoundError: If PDF does not exist
        RuntimeError: If PDF cannot be opened
        InterruptedError: If user cancels operation

    Example:
        >>> config = {"pin_assignment_threshold": 50.0, "refdes_search_radius": 100.0}
        >>> pin_map, body_rects = analyze_document("schematic.pdf", config)
        >>> print(pin_map["p1_pin_15"].full_identifier)
        'U1B-P20'

        # Analyze only pages 0 and 2 (for hybrid mode optimization):
        >>> pin_map, body_rects = analyze_document("schematic.pdf", config, page_filter={0, 2})
    """
    def log(msg):
        if log_func:
            log_func(msg)
        _logger.info(msg)

    def status(msg):
        if status_func:
            status_func(msg)

    def progress(pct):
        if progress_func:
            progress_func(pct)

    if config is None:
        config = {}

    log(f"Starting geometry analysis: {pdf_path}")

    # Check file exists (only when we need to open it ourselves)
    if doc is None and not Path(pdf_path).exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    pin_map = {}
    body_rects = {}  # {(page_num, refdes): Rect} for body containment checks

    # Use provided doc (caller owns it) or open from path (we own it)
    doc_ctx = nullcontext(doc) if doc is not None else fitz.open(pdf_path)
    try:
        with doc_ctx as doc:
            total_pages = len(doc)

            # Check for empty PDF
            if total_pages == 0:
                raise ValueError("PDF has no pages - cannot extract geometry")

            any_geometry_found = False

            # Determine which pages to analyze
            pages_to_analyze = set(range(total_pages)) if page_filter is None else page_filter
            pages_to_analyze = sorted(p for p in pages_to_analyze if 0 <= p < total_pages)

            # Warn if page_filter was provided but resulted in empty list
            if page_filter is not None and not pages_to_analyze:
                log(f"WARNING: page_filter {page_filter} contained no valid page indices (PDF has {total_pages} pages)")

            if page_filter is not None:
                log(f"Selective page analysis: {len(pages_to_analyze)} of {total_pages} pages")

            for idx, page_num in enumerate(pages_to_analyze):
                # Check for cancellation BEFORE starting page
                _check_cancelled(stop_event, "geometry analysis", log_func)
                if cancel_token:
                    check_cancelled(cancel_token, "Geometry analysis cancelled by user.")

                page = doc[page_num]
                status(f"Page {page_num + 1}/{total_pages}: Starting analysis...")
                log(f"Analyzing page {page_num + 1}/{total_pages}...")

                # Extract geometry with timeout
                geometry = _extract_page_with_timeout(
                    page, page_num, total_pages,
                    log_func=log, stop_event=stop_event, status_func=status
                )

                # Process geometry to build mappings (if extraction succeeded)
                if geometry.bodies or geometry.tokens:
                    any_geometry_found = True
                    # M3: Log if only one component is present (graceful degradation)
                    if geometry.bodies and not geometry.tokens:
                        log(f"  Page {page_num + 1}: Bodies found but no tokens - RefDes assignment may be incomplete")
                    elif geometry.tokens and not geometry.bodies:
                        log(f"  Page {page_num + 1}: Tokens found but no bodies - pin mapping may be incomplete")
                    status(f"Page {page_num + 1}/{total_pages}: Processing mappings...")
                    page_mappings = process_page_geometry(geometry, config, log_func=log, stop_event=stop_event)

                    # Add to global pin map
                    for mapping in page_mappings:
                        pin_map[mapping.pin_identifier] = mapping

                    # Collect body rectangles for containment checks
                    for body in geometry.bodies:
                        if body.assigned_refdes:
                            body_rects[(body.page_num, body.assigned_refdes)] = body.rect

                    log(f"  Page {page_num + 1}: {len(page_mappings)} pins mapped")
                else:
                    log(f"  Page {page_num + 1}: No geometry extracted (skipped or empty)")

                # Update progress (based on pages analyzed, not total pages)
                progress((idx + 1) / len(pages_to_analyze) if pages_to_analyze else 1.0)

            # Warn if no geometry was found in any page
            if not any_geometry_found:
                log(f"WARNING: No geometry detected in PDF - extraction results may be incomplete")

            log(f"Geometry analysis complete: {len(pin_map)} pins mapped across {total_pages} pages")

    except Exception as e:
        if "PDF" in str(e) or "open" in str(e).lower():
            raise RuntimeError(f"Failed to open PDF: {e}")
        raise

    return pin_map, body_rects


def _extract_page_with_timeout(
    page: fitz.Page,
    page_num: int,
    total_pages: int,
    log_func=None,
    stop_event=None,
    status_func=None
) -> GeometryData:
    """
    Extract page geometry with a timeout.

    If extraction takes longer than PAGE_TIMEOUT_SECONDS, returns empty geometry
    and logs a warning.

    Args:
        page: PyMuPDF Page object
        page_num: Zero-indexed page number
        total_pages: Total number of pages
        log_func: Optional logging callback
        stop_event: Threading event for cancellation
        status_func: Optional status callback

    Returns:
        GeometryData (may be empty if timed out)
    """
    def log(msg):
        if log_func:
            log_func(msg)
        _logger.info(msg)

    def extract_sync():
        return extract_page_geometry(
            page, page_num, total_pages,
            log_func=log_func, stop_event=stop_event, status_func=status_func
        )

    # Use ThreadPoolExecutor for timeout support
    # Note: Python threads cannot be forcibly killed - we use non-blocking shutdown
    # to avoid waiting for the thread if it's stuck in a C library call
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(extract_sync)
        try:
            return future.result(timeout=PAGE_TIMEOUT_SECONDS)
        except FuturesTimeoutError:
            future.cancel()  # Attempt to cancel (may not work for running C calls)
            warning_msg = f"WARNING: Page {page_num + 1}/{total_pages} timed out after {PAGE_TIMEOUT_SECONDS}s, skipping..."
            log(warning_msg)
            _logger.warning(f"Page {page_num + 1}/{total_pages} timed out after {PAGE_TIMEOUT_SECONDS}s")
            _logger.debug(f"Page {page_num + 1}: Timeout details - page processing exceeded {PAGE_TIMEOUT_SECONDS}s limit, returning empty geometry")
            return GeometryData(
                page_num=page_num,
                bodies=[],
                pins=[],
                tokens=[],
                wire_segments=[]
            )
        except (CancellationError, InterruptedError):
            # Re-raise cancellation signals
            raise
        except Exception as e:
            error_msg = f"WARNING: Page {page_num + 1} extraction failed: {e}"
            log(error_msg)
            _logger.exception(f"Page {page_num + 1} extraction failed")
            return GeometryData(
                page_num=page_num,
                bodies=[],
                pins=[],
                tokens=[],
                wire_segments=[]
            )
    finally:
        # Non-blocking shutdown to avoid waiting for stuck threads
        executor.shutdown(wait=False, cancel_futures=True)


# ==================== PAGE-LEVEL PROCESSING ====================

def extract_page_geometry(
    page: fitz.Page,
    page_num: int,
    total_pages: int = 1,
    log_func: Callable[[str], None] = None,
    stop_event=None,
    status_func: Callable[[str], None] = None
) -> GeometryData:
    """
    Step 1-4: Extract all geometric primitives from page.

    Now with:
    - Cached drawings (single get_drawings() call instead of 3)
    - Pre-operation cancellation checks
    - Per-step progress logging with timing
    - Status updates for UI

    Args:
        page: PyMuPDF Page object
        page_num: Zero-indexed page number
        total_pages: Total number of pages (for progress display)
        log_func: Optional logging callback for execution log
        stop_event: Threading event for cancellation
        status_func: Optional callback for status bar updates

    Returns:
        GeometryData with bodies, pins, tokens, wires
    """
    def log(msg):
        if log_func:
            log_func(msg)
        _logger.debug(msg)

    def status(msg):
        if status_func:
            status_func(msg)

    page_label = f"Page {page_num + 1}/{total_pages}"
    start_time = time.time()

    # ===== Step 0: Cache drawings ONCE (previously called 3x) =====
    _check_cancelled(stop_event, "drawings extraction", log_func)
    status(f"{page_label}: Extracting vector drawings...")
    log(f"  {page_label}: Extracting vector drawings...")

    # Use timeout wrapper to prevent indefinite hang on complex vector pages
    # Note: We can't pre-check drawing count without extracting; timeout is the main protection
    cached_drawings = _get_drawings_with_timeout(page, page_num, log_func=log_func)
    drawing_count = len(cached_drawings)
    log(f"    Extracted {drawing_count} drawing primitives")

    # Check for cancellation immediately after potentially long blocking operation
    _check_cancelled(stop_event, "after drawings extraction", log_func)

    # Check if page is extremely complex (likely CAD/vector art, not schematic)
    SKIP_GEOMETRY_THRESHOLD = MAX_DRAWINGS_PER_PAGE * 2  # 100k drawings = skip geometry
    if drawing_count > SKIP_GEOMETRY_THRESHOLD:
        log(f"    WARNING: Page has {drawing_count} drawings (>{SKIP_GEOMETRY_THRESHOLD}), skipping geometry analysis")
        _logger.warning(f"Page {page_num + 1}: Skipping geometry analysis - {drawing_count} drawings exceeds skip threshold")
        return GeometryData(
            page_num=page_num,
            bodies=[],
            pins=[],
            tokens=_extract_tokens(page, stop_event, log_func),  # Still extract text
            wire_segments=[]
        )

    # Limit drawings to prevent memory exhaustion on vector-heavy pages
    if drawing_count > MAX_DRAWINGS_PER_PAGE:
        log(f"    WARNING: Page has {drawing_count} drawings, limiting to {MAX_DRAWINGS_PER_PAGE}")
        cached_drawings = cached_drawings[:MAX_DRAWINGS_PER_PAGE]

    # ===== Step 1: Detect component bodies (from cached drawings) =====
    _check_cancelled(stop_event, "component body detection", log_func)
    status(f"{page_label}: Detecting component bodies...")
    log(f"  {page_label}: Detecting component bodies...")

    bodies = _detect_component_bodies_from_drawings(cached_drawings, page_num, stop_event, log_func)
    log(f"    Found {len(bodies)} component bodies")

    # ===== Step 2: Detect pin ticks (from cached drawings) =====
    _check_cancelled(stop_event, "pin tick detection", log_func)
    status(f"{page_label}: Detecting pin ticks...")

    tick_pins = _detect_pin_ticks_from_drawings(cached_drawings, bodies, stop_event, log_func, status_func)
    log(f"    Found {len(tick_pins)} pin ticks")

    # ===== Step 2b: Detect BGA circles (from cached drawings) =====
    _check_cancelled(stop_event, "BGA circle detection", log_func)
    status(f"{page_label}: Detecting BGA circles...")

    bga_pins = _detect_bga_circles(cached_drawings, bodies, stop_event, log_func, status_func)
    log(f"    Found {len(bga_pins)} BGA circles")

    # Merge tick and BGA pins
    pins = tick_pins + bga_pins

    # ===== Step 3: Detect wire segments (from cached drawings) =====
    _check_cancelled(stop_event, "wire segment detection", log_func)
    status(f"{page_label}: Detecting wire segments...")

    wire_segments = _detect_wire_segments_from_drawings(cached_drawings, stop_event, log_func, status)
    log(f"    Found {len(wire_segments)} wire segments")

    # ===== Step 4: Extract text tokens =====
    _check_cancelled(stop_event, "text extraction", log_func)
    status(f"{page_label}: Extracting text tokens...")

    try:
        tokens = _extract_tokens(page, stop_event, log_func)
        log(f"    Found {len(tokens)} text tokens")
    except (CancellationError, InterruptedError):
        raise
    except Exception as e:
        error_msg = f"WARNING: Failed to extract text from page {page_num + 1}: {e}"
        _logger.warning(error_msg)
        log(error_msg)
        tokens = []

    elapsed = time.time() - start_time
    log(f"  {page_label}: Geometry extraction complete ({elapsed:.1f}s)")

    return GeometryData(
        page_num=page_num,
        bodies=bodies,
        pins=pins,
        tokens=tokens,
        wire_segments=wire_segments
    )


def process_page_geometry(
    geometry: GeometryData,
    config: Dict,
    log_func=None,
    stop_event=None
) -> List[PinMapping]:
    """
    Step 5-8: Classify tokens, assign associations, build mappings.

    Args:
        geometry: GeometryData from extract_page_geometry
        config: Configuration dict
        log_func: Optional logging callback
        stop_event: Threading event for cancellation

    Returns:
        List of PinMapping objects for this page

    Raises:
        InterruptedError: If cancelled during processing
    """
    def log(msg):
        if log_func:
            log_func(msg)
        _logger.debug(msg)

    # Step 5: Classify tokens (with spatial context for pin detection)
    pin_threshold = config.get("pin_threshold", DEFAULT_PIN_THRESHOLD)
    max_pin_length = config.get("max_pin_label_length", DEFAULT_MAX_PIN_LABEL_LENGTH)
    _classify_tokens(
        geometry.tokens,
        geometry.bodies,
        geometry.wire_segments,
        pin_threshold,
        max_pin_length,
        stop_event,
        log_func
    )
    refdes_count = sum(1 for t in geometry.tokens if t.token_type == TokenType.REFDES)
    pin_count = sum(1 for t in geometry.tokens if t.token_type == TokenType.PIN_LABEL)
    log(f"    Classified: {refdes_count} RefDes, {pin_count} pin labels (threshold={pin_threshold}px, max_len={max_pin_length})")

    # Step 5.5: Create pins from PIN_LABEL tokens (supplements graphical tick detection)
    graphical_pin_count = len(geometry.pins)
    geometry.pins = _create_pins_from_tokens(
        geometry.tokens,
        geometry.bodies,
        geometry.pins,  # existing graphical tick pins
        config,
        stop_event,
        log_func
    )
    token_pin_count = len(geometry.pins) - graphical_pin_count
    log(f"    Total pins: {len(geometry.pins)} ({graphical_pin_count} graphical, {token_pin_count} from tokens)")

    # Step 6: Assign pins to bodies (for graphical ticks that don't have body_id yet)
    _assign_pins_to_bodies(geometry.pins, geometry.bodies, config, stop_event, log_func)
    assigned_pins = sum(1 for p in geometry.pins if p.body_id)
    log(f"    Assigned {assigned_pins}/{len(geometry.pins)} pins to bodies")

    # Step 7: Assign RefDes to bodies
    body_refdes_map = _assign_refdes_to_bodies(geometry.bodies, geometry.tokens, config, stop_event, log_func)
    log(f"    Assigned RefDes to {len(body_refdes_map)}/{len(geometry.bodies)} bodies")

    # Step 8: Build pin mappings
    mappings = _build_pin_mappings(
        geometry.pins, body_refdes_map, geometry.page_num, stop_event, log_func
    )

    return mappings


# ==================== STEP 1: DETECT COMPONENT BODIES ====================

def _detect_component_bodies_from_drawings(
    drawings: List,
    page_num: int,
    stop_event=None,
    log_func=None
) -> List[ComponentBody]:
    """
    Extract component body rectangles from pre-cached drawings.

    This version takes already-extracted drawings to avoid redundant
    page.get_drawings() calls (which are expensive on vector-heavy pages).

    Strategy:
    - Filter for rectangles (type 're')
    - Apply size filters (min/max width/height)
    - Apply aspect ratio filter
    - Deduplicate overlapping rectangles

    Args:
        drawings: Pre-cached list from page.get_drawings()
        page_num: Zero-indexed page number
        stop_event: Threading event for cancellation
        log_func: Optional logging callback

    Returns:
        List of ComponentBody objects
    """
    bodies = []

    for idx, drawing in enumerate(drawings):
        # Check cancellation periodically (every 100 drawings)
        if idx % 100 == 0:
            _check_cancelled(stop_event, "component body detection", log_func)

        # Extract and validate rectangle from drawing
        rect_tuple = drawing.get('rect')
        if not rect_tuple or len(rect_tuple) != 4:
            continue

        # Validate coordinates are finite numbers
        try:
            x0, y0, x1, y1 = rect_tuple
            if any(not isinstance(v, (int, float)) for v in (x0, y0, x1, y1)):
                continue
            if any(math.isnan(v) or math.isinf(v) for v in (x0, y0, x1, y1)):
                continue
        except (TypeError, ValueError) as e:
            # Debug log for corrupted PDF data diagnosis
            _logger.debug(f"Skipped invalid body rectangle: {e}")
            continue

        # Normalize inverted rectangles (x0 > x1 or y0 > y1)
        if x0 > x1:
            x0, x1 = x1, x0
        if y0 > y1:
            y0, y1 = y1, y0

        rect = Rect(x0, y0, x1, y1)

        # Size filters
        if rect.width < MIN_BODY_WIDTH or rect.height < MIN_BODY_HEIGHT:
            continue
        if rect.width > MAX_BODY_WIDTH or rect.height > MAX_BODY_HEIGHT:
            continue

        # Aspect ratio filter
        if rect.height > 0:
            aspect = rect.width / rect.height
            if aspect < MIN_ASPECT_RATIO or aspect > MAX_ASPECT_RATIO:
                continue

        bodies.append(ComponentBody(
            rect=rect,
            page_num=page_num,
            body_id=f"body_p{page_num}_{idx}",
            source="vector"
        ))

    # Deduplicate overlapping bodies (with cancellation support)
    bodies = _deduplicate_bodies(bodies, stop_event, log_func)

    return bodies


def _deduplicate_bodies(
    bodies: List[ComponentBody],
    stop_event=None,
    log_func=None
) -> List[ComponentBody]:
    """
    Remove overlapping rectangles, keeping larger ones.

    Uses IoU (Intersection over Union) to detect overlaps.
    If two bodies overlap >80%, keep only the larger one.

    Args:
        bodies: List of ComponentBody objects
        stop_event: Threading event for cancellation
        log_func: Optional logging callback

    Returns:
        Deduplicated list
    """
    if not bodies:
        return []

    # Sort by area (largest first)
    sorted_bodies = sorted(bodies, key=lambda b: b.rect.area, reverse=True)

    unique = []
    comparison_count = 0
    for idx, body in enumerate(sorted_bodies):
        # Check cancellation periodically (every 20 bodies for faster cancel response)
        if idx % 20 == 0:
            _check_cancelled(stop_event, "body deduplication", log_func)

        # Check if this body significantly overlaps with any kept body
        is_duplicate = False
        for kept_body in unique:
            comparison_count += 1
            # Also check cancellation inside inner loop for large unique lists
            # (check every 100 comparisons for faster cancel response)
            if comparison_count % 100 == 0:
                _check_cancelled(stop_event, "body deduplication (overlap check)", log_func)
            overlap = _rect_overlap_iou(body.rect, kept_body.rect)
            if overlap > 0.8:
                is_duplicate = True
                break

        if not is_duplicate:
            unique.append(body)

            # Limit unique bodies to prevent O(n²) explosion
            if len(unique) >= MAX_UNIQUE_BODIES:
                if log_func:
                    log_func(f"    WARNING: Body count limit ({MAX_UNIQUE_BODIES}) reached, stopping deduplication")
                break

    return unique


def _rect_overlap_iou(r1: Rect, r2: Rect) -> float:
    """
    Calculate IoU (Intersection over Union) of two rectangles.

    Args:
        r1, r2: Rect objects

    Returns:
        IoU value between 0.0 (no overlap) and 1.0 (identical)
    """
    # Calculate intersection
    x_overlap = max(0, min(r1.x1, r2.x1) - max(r1.x0, r2.x0))
    y_overlap = max(0, min(r1.y1, r2.y1) - max(r1.y0, r2.y0))
    intersection = x_overlap * y_overlap

    # Calculate union
    area1 = r1.area
    area2 = r2.area
    union = area1 + area2 - intersection

    return intersection / union if union > 0 else 0.0


# ==================== STEP 2: DETECT PIN TICKS ====================

def _detect_pin_ticks_from_drawings(
    drawings: List,
    bodies: List[ComponentBody],
    stop_event=None,
    log_func=None,
    status_func=None
) -> List[Pin]:
    """
    Detect small line segments on component edges (pin ticks).

    This version takes pre-cached drawings to avoid redundant
    page.get_drawings() calls.

    Strategy:
    - Extract short lines (2-10 pixels) from drawings
    - Check if perpendicular to body edges
    - Classify edge (left/right/top/bottom)

    Args:
        drawings: Pre-cached list from page.get_drawings()
        bodies: List of detected component bodies
        stop_event: Threading event for cancellation
        log_func: Optional logging callback
        status_func: Optional status bar update callback

    Returns:
        List of Pin objects (label_token assigned later)
    """
    status = status_func or (lambda x: None)
    pins = []
    item_count = 0

    for drawing in drawings:
        # Look for line items in the drawing
        items = drawing.get('items', [])
        for item in items:
            item_count += 1
            # Check cancellation periodically (every 500 items)
            if item_count % 500 == 0:
                _check_cancelled(stop_event, "pin tick detection", log_func)
                status(f"Analyzing pin ticks... ({item_count} items)")

            # item format: ('item_type', point1, point2, ...) or similar
            # We need to identify line segments
            if len(item) < 3:
                continue

            # Try to extract line endpoints
            # Typical format: ('l', p1, p2) for lines
            if item[0] == 'l' and len(item) >= 3:
                p1 = item[1]
                p2 = item[2]

                # M6: Validate coordinate tuples before access
                try:
                    if not (isinstance(p1, (tuple, list)) and len(p1) >= 2):
                        continue
                    if not (isinstance(p2, (tuple, list)) and len(p2) >= 2):
                        continue
                except TypeError as e:
                    # Debug log for corrupted PDF data diagnosis
                    _logger.debug(f"Skipped invalid pin coordinates: {e}")
                    continue

                # Calculate squared line length (avoid sqrt for threshold comparison)
                length_sq = (p2[0] - p1[0])**2 + (p2[1] - p1[1])**2

                if length_sq < MIN_TICK_LENGTH_SQ or length_sq > MAX_TICK_LENGTH_SQ:
                    continue

                # Check if tick is on any body edge
                for body in bodies:
                    edge = _get_edge_alignment(p1, p2, body.rect)
                    if edge:
                        pins.append(Pin(
                            location=((p1[0] + p2[0])/2, (p1[1] + p2[1])/2),
                            edge=edge,
                            label_token=None,
                            body_id=body.body_id
                        ))
                        break  # Pin assigned to first matching body

    return pins


def _get_edge_alignment(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    rect: Rect,
    tolerance: float = TICK_EDGE_TOLERANCE
) -> Optional[str]:
    """
    Check if line segment is perpendicular to rectangle edge.

    Args:
        p1, p2: Line endpoints (x, y)
        rect: Rectangle to check against
        tolerance: Distance threshold from edge

    Returns:
        "left" | "right" | "top" | "bottom" | None
    """
    # Get midpoint of line
    mid_x, mid_y = (p1[0] + p2[0])/2, (p1[1] + p2[1])/2

    # Check proximity to each edge
    if abs(mid_x - rect.x0) < tolerance and rect.y0 <= mid_y <= rect.y1:
        return "left"
    if abs(mid_x - rect.x1) < tolerance and rect.y0 <= mid_y <= rect.y1:
        return "right"
    if abs(mid_y - rect.y0) < tolerance and rect.x0 <= mid_x <= rect.x1:
        return "top"
    if abs(mid_y - rect.y1) < tolerance and rect.x0 <= mid_x <= rect.x1:
        return "bottom"

    return None


# ==================== STEP 2b: DETECT BGA CIRCLES ====================

def _detect_bga_circles(
    drawings: List,
    bodies: List[ComponentBody],
    stop_event=None,
    log_func=None,
    status_func=None
) -> List[Pin]:
    """
    Detect small circles on component edges (BGA ball pads).

    BGA (Ball Grid Array) packages show pins as small filled circles
    near component body edges. This supplements line-based tick detection.

    Args:
        drawings: Pre-cached list from page.get_drawings()
        bodies: List of detected component bodies
        stop_event: Threading event for cancellation
        log_func: Optional logging callback
        status_func: Optional status bar update callback

    Returns:
        List of Pin objects detected from circular primitives
    """
    status = status_func or (lambda x: None)
    pins = []
    item_count = 0

    for drawing in drawings:
        items = drawing.get('items', [])
        for item in items:
            item_count += 1
            # Check cancellation every 500 items
            if item_count % 500 == 0:
                _check_cancelled(stop_event, "BGA circle detection", log_func)
                status(f"Detecting BGA circles... ({item_count} items)")

            # Look for circle primitives: ('c', center, radius) or similar
            if len(item) < 3:
                continue

            if item[0] == 'c':  # Circle primitive
                try:
                    center = item[1]
                    # Validate center is a valid point tuple
                    if not (isinstance(center, (tuple, list)) and len(center) >= 2):
                        continue

                    # Radius might be the third element or embedded differently
                    radius = item[2] if len(item) > 2 else 0
                    if not isinstance(radius, (int, float)):
                        continue

                    # Validate radius is in BGA range
                    if not (MIN_BGA_RADIUS <= radius <= MAX_BGA_RADIUS):
                        continue

                    # Check if circle is near any body edge
                    for body in bodies:
                        edge, dist = _nearest_edge(center, body.rect)
                        if dist < BGA_EDGE_TOLERANCE:
                            pins.append(Pin(
                                location=(float(center[0]), float(center[1])),
                                edge=edge,
                                label_token=None,
                                body_id=body.body_id
                            ))
                            break  # Assign to first matching body

                except (TypeError, IndexError) as e:
                    # Debug log for corrupted PDF data diagnosis
                    _logger.debug(f"Skipped malformed BGA circle data: {e}")
                    continue

    return pins


# ==================== STEP 3: DETECT WIRE SEGMENTS ====================

def _detect_wire_segments_from_drawings(
    drawings: List,
    stop_event=None,
    log_func=None,
    status_func=None
) -> List[Tuple[Rect, Rect]]:
    """
    Extract line segments representing wires (for net label classification).

    This version takes pre-cached drawings to avoid redundant
    page.get_drawings() calls.

    Strategy:
    - Extract long lines (>50 pixels) from drawings
    - Store as (start_rect, end_rect) for proximity checks

    Args:
        drawings: Pre-cached list from page.get_drawings()
        stop_event: Threading event for cancellation
        log_func: Optional logging callback
        status_func: Optional status bar update callback

    Returns:
        List of line endpoints as small Rects (for proximity testing)
    """
    status = status_func or (lambda x: None)
    wires = []
    item_count = 0

    for drawing in drawings:
        items = drawing.get('items', [])
        for item in items:
            item_count += 1
            # Check cancellation periodically (every 500 items) using standard helper
            if item_count % 500 == 0:
                _check_cancelled(stop_event, "wire segment detection", log_func)
                status(f"Detecting wires... ({item_count} items)")

            if len(item) < 3:
                continue

            # Look for line items
            if item[0] == 'l' and len(item) >= 3:
                p1 = item[1]
                p2 = item[2]

                # Validate coordinate tuples before access (match pin tick validation pattern)
                try:
                    if not (isinstance(p1, (tuple, list)) and len(p1) >= 2):
                        continue
                    if not (isinstance(p2, (tuple, list)) and len(p2) >= 2):
                        continue
                except TypeError as e:
                    _logger.debug(f"Skipped invalid wire coordinates: {e}")
                    continue

                # Calculate squared line length (avoid sqrt for threshold comparison)
                length_sq = (p2[0] - p1[0])**2 + (p2[1] - p1[1])**2

                if length_sq < MIN_WIRE_LENGTH_SQ:
                    continue

                # Create small rects at endpoints for proximity checks
                start = Rect(p1[0]-2, p1[1]-2, p1[0]+2, p1[1]+2)
                end = Rect(p2[0]-2, p2[1]-2, p2[0]+2, p2[1]+2)
                wires.append((start, end))

    return wires


# ==================== STEP 4: EXTRACT TOKENS ====================

def _get_text_with_timeout(page: fitz.Page, page_num: int = 0, timeout: float = TEXT_EXTRACTION_TIMEOUT, log_func=None) -> dict:
    """
    Extract text dict from page with timeout to prevent indefinite blocking.

    PyMuPDF's page.get_text("dict") is a C library call that can hang indefinitely
    on pathological pages (malformed fonts, corrupted metadata, etc.). This wrapper
    runs the extraction in a separate thread with a timeout.

    Args:
        page: PyMuPDF Page object
        page_num: Page number (0-based) for logging
        timeout: Maximum seconds to wait (default TEXT_EXTRACTION_TIMEOUT)
        log_func: Optional callback to notify user of timeouts

    Returns:
        Text dict from get_text("dict"), or empty dict {"blocks": []} on timeout/error
    """
    import time
    start_time = time.time()

    def extract_sync():
        return page.get_text("dict")

    # Use non-blocking shutdown to avoid waiting for stuck threads
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(extract_sync)
        try:
            result = future.result(timeout=timeout)
            elapsed = time.time() - start_time
            _logger.debug(f"Page {page_num + 1}: Text extraction completed in {elapsed:.2f}s")
            return result
        except FuturesTimeoutError:
            future.cancel()  # Attempt to cancel
            elapsed = time.time() - start_time
            warning_msg = f"Page {page_num + 1}: Text extraction TIMED OUT after {elapsed:.2f}s - text tokens skipped"
            _logger.warning(warning_msg)
            if log_func:
                log_func(f"    WARNING: {warning_msg}")
            return {"blocks": []}
        except (CancellationError, InterruptedError):
            raise
        except Exception as e:
            warning_msg = f"Page {page_num + 1}: Text extraction failed: {e}"
            _logger.warning(warning_msg)
            if log_func:
                log_func(f"    WARNING: {warning_msg}")
            return {"blocks": []}
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _get_drawings_with_timeout(page: fitz.Page, page_num: int = 0, timeout: float = DRAWINGS_EXTRACTION_TIMEOUT, log_func=None) -> list:
    """
    Extract drawings from page with timeout to prevent indefinite blocking.

    PyMuPDF's page.get_drawings() is a C library call that can hang indefinitely
    on complex vector pages (pathological drawing primitives, circular references, etc.).
    This wrapper runs the extraction in a separate thread with a timeout.

    Args:
        page: PyMuPDF Page object
        page_num: Page number (0-based) for logging
        timeout: Maximum seconds to wait (default DRAWINGS_EXTRACTION_TIMEOUT)
        log_func: Optional callback to notify user of timeouts

    Returns:
        List of drawings from get_drawings(), or empty list [] on timeout/error
    """
    import time
    start_time = time.time()

    def extract_sync():
        return page.get_drawings()

    # Use non-blocking shutdown to avoid waiting for stuck threads
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(extract_sync)
        try:
            result = future.result(timeout=timeout)
            elapsed = time.time() - start_time
            _logger.debug(f"Page {page_num + 1}: Drawings extraction completed in {elapsed:.2f}s ({len(result)} drawings)")
            return result
        except FuturesTimeoutError:
            future.cancel()  # Attempt to cancel
            elapsed = time.time() - start_time
            warning_msg = f"Page {page_num + 1}: Drawings extraction TIMED OUT after {elapsed:.2f}s - geometry analysis skipped"
            _logger.warning(warning_msg)
            _logger.debug(f"Page {page_num + 1}: Timeout occurred during 'get_drawings()' C library call - page skipped")
            if log_func:
                log_func(f"    WARNING: {warning_msg}")
            return []
        except (CancellationError, InterruptedError):
            raise
        except Exception as e:
            warning_msg = f"Page {page_num + 1}: Drawings extraction failed: {e}"
            _logger.warning(warning_msg)
            if log_func:
                log_func(f"    WARNING: {warning_msg}")
            return []
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _extract_tokens(page: fitz.Page, stop_event=None, log_func=None) -> List[Token]:
    """
    Extract all text with bounding boxes and font metadata.

    Uses page.get_text("dict") for rich metadata including font size.

    Args:
        page: PyMuPDF Page object
        stop_event: Threading event for cancellation
        log_func: Optional logging callback

    Returns:
        List of Token objects (token_type assigned later in Step 5)

    Raises:
        InterruptedError: If cancelled during extraction
    """
    tokens = []

    # Pre-check cancellation before the blocking get_text() call
    _check_cancelled(stop_event, "text extraction", log_func)

    # Use timeout wrapper to prevent indefinite blocking on pathological pages
    text_dict = _get_text_with_timeout(page, page.number, log_func=log_func)

    # Check if extraction returned empty (timeout or error)
    if not text_dict.get("blocks"):
        # Note: timeout/error already logged by _get_text_with_timeout if log_func provided
        return tokens

    # Check again after blocking operation for faster cancellation response
    _check_cancelled(stop_event, "text extraction", log_func)

    span_count = 0
    for block in text_dict.get("blocks", []):
        # Check cancellation periodically
        _check_cancelled(stop_event, "text token processing", log_func)

        if block.get("type") != 0:  # 0 = text block
            continue

        for line in block.get("lines", []):
            for span in line.get("spans", []):
                span_count += 1
                # Check cancellation every 200 spans
                if span_count % 200 == 0:
                    _check_cancelled(stop_event, "text token processing", log_func)

                text = span.get("text", "").strip()
                if not text:
                    continue

                bbox = span.get("bbox", [0, 0, 0, 0])
                font_size = span.get("size", 10.0)

                tokens.append(Token(
                    text=text,
                    rect=Rect(*bbox),
                    font_size=font_size,
                    token_type=TokenType.JUNK,  # Classified in Step 5
                    confidence=0.0
                ))

    return tokens


# ==================== STEP 5: CLASSIFY TOKENS ====================

def _distance_to_body_edge(token_rect: Rect, body: 'ComponentBody') -> float:
    """
    Calculate minimum distance from token center to nearest body edge.

    Args:
        token_rect: Token bounding box
        body: ComponentBody to check distance to

    Returns:
        Distance in pixels from token center to nearest body edge
    """
    tx, ty = token_rect.center
    bx0, by0, bx1, by1 = body.rect.x0, body.rect.y0, body.rect.x1, body.rect.y1

    # Calculate distance to each edge
    dx = max(bx0 - tx, 0, tx - bx1)  # 0 if inside horizontally
    dy = max(by0 - ty, 0, ty - by1)  # 0 if inside vertically

    # Euclidean distance to nearest point on body rectangle
    return (dx * dx + dy * dy) ** 0.5


def _is_near_body_edge(
    token_rect: Rect,
    bodies: List['ComponentBody'],
    threshold: float
) -> bool:
    """
    Check if token is within threshold distance of any component body.

    Args:
        token_rect: Token bounding box
        bodies: List of ComponentBody objects
        threshold: Maximum distance in pixels

    Returns:
        True if near any body edge, False otherwise
    """
    for body in bodies:
        if _distance_to_body_edge(token_rect, body) <= threshold:
            return True
    return False


def _nearest_edge(point: Tuple[float, float], rect: Rect) -> Tuple[str, float]:
    """
    Find which edge of rect is nearest to point.

    Determines both the edge name and distance, preferring edges where
    the point aligns with the edge span (i.e., within the perpendicular range).

    Args:
        point: (x, y) coordinates of the point
        rect: Rectangle to check against

    Returns:
        Tuple of (edge_name, distance) where edge_name is
        "left", "right", "top", or "bottom"
    """
    px, py = point

    # First pass: check aligned distances (point is within edge span)
    distances = {
        "left": abs(px - rect.x0) if rect.y0 <= py <= rect.y1 else float('inf'),
        "right": abs(px - rect.x1) if rect.y0 <= py <= rect.y1 else float('inf'),
        "top": abs(py - rect.y0) if rect.x0 <= px <= rect.x1 else float('inf'),
        "bottom": abs(py - rect.y1) if rect.x0 <= px <= rect.x1 else float('inf'),
    }

    # If point is outside body bounds in both dimensions, use direct distances
    if all(d == float('inf') for d in distances.values()):
        distances = {
            "left": abs(px - rect.x0),
            "right": abs(px - rect.x1),
            "top": abs(py - rect.y0),
            "bottom": abs(py - rect.y1),
        }

    best_edge = min(distances, key=distances.get)
    return best_edge, distances[best_edge]


def _classify_tokens(
    tokens: List[Token],
    bodies: List['ComponentBody'],
    wire_segments: List[Tuple[Rect, Rect]],
    pin_threshold: float = DEFAULT_PIN_THRESHOLD,
    max_pin_length: int = DEFAULT_MAX_PIN_LABEL_LENGTH,
    stop_event=None,
    log_func=None
) -> None:
    """
    Classify each token as REFDES, PIN_LABEL, NET_LABEL, or JUNK.

    Strategy (with spatial context for pin detection):
    1. Underscore in text → NET_LABEL (signal names like MISO_34)
    2. RefDes pattern match → REFDES
    3. Pin candidate (short alphanumeric, no underscore):
       - Near body edge → PIN_LABEL
       - Not near body → JUNK (stray text)
    4. Near wire, uppercase, length >= 3 → NET_LABEL
    5. Default → JUNK

    Modifies tokens in-place (sets token_type and confidence).

    Args:
        tokens: List of Token objects
        bodies: List of ComponentBody for spatial pin detection
        wire_segments: List of wire endpoints for net classification
        pin_threshold: Max distance from body edge for pin classification
        max_pin_length: Maximum length for pin identifier strings (default: 4)
        stop_event: Optional event to check for cancellation
        log_func: Optional logging callback

    Raises:
        InterruptedError: If cancelled during classification
    """
    # Pre-build a lightweight spatial index for wire proximity checks.
    # This prevents worst-case O(tokens * wires) behavior on dense vector pages.
    wire_index = None
    wire_cell_size = max(50.0, WIRE_PROXIMITY_THRESHOLD * 5.0)
    max_wire_endpoints_for_index = 50_000  # guardrail: skip wire proximity when extremely dense
    if wire_segments:
        endpoint_count = len(wire_segments) * 2
        if endpoint_count <= max_wire_endpoints_for_index:
            wire_index = _build_wire_endpoint_index(wire_segments, cell_size=wire_cell_size)
        else:
            # Too many endpoints: skip wire proximity checks entirely to keep pin/refdes extraction responsive.
            # This may reduce NET_LABEL classification accuracy but avoids hangs.
            wire_segments = []

    for idx, token in enumerate(tokens):
        # Check cancellation frequently to keep UI responsive on heavy pages
        if idx % 10 == 0:
            _check_cancelled(stop_event, "token classification", log_func)

        # 1. Underscore check FIRST - signal names like MISO_34, VCC_3V3
        if '_' in token.text:
            # Could be a net/signal name if near wire
            if token.text.isupper() and len(token.text) >= 3:
                if _is_near_wire(token.rect, wire_segments, stop_event=stop_event, wire_index=wire_index, cell_size=wire_cell_size):
                    token.token_type = TokenType.NET_LABEL
                    token.confidence = 0.7
                    continue
            # Otherwise it's junk (has underscore but not a net)
            token.token_type = TokenType.JUNK
            token.confidence = 0.0
            continue

        # 2. Classic PIN_PATTERN first (P20, PIN24, P-5) - these look like RefDes but are pins
        # Check before RefDes pattern to avoid misclassifying P20 as a RefDes
        if PIN_PATTERN.match(token.text):
            token.token_type = TokenType.PIN_LABEL
            token.confidence = 0.85
            continue

        # 3. RefDes pattern detection (U1, R15, J2A, etc.)
        # But first check for spatial ambiguity - tokens like "R25" could be FPGA pins
        if REFDES_PATTERN.match(token.text):
            # Check if this could be a pin label (short enough and near body edge)
            # FPGA pins often use patterns like R25, A12, B7 that look like RefDes
            if (is_pin_candidate(token.text, max_length=max_pin_length) and
                bodies and _is_near_body_edge(token.rect, bodies, pin_threshold)):
                # Ambiguous: matches RefDes pattern but spatially looks like a pin
                token.token_type = TokenType.PIN_LABEL
                token.confidence = 0.7  # Lower confidence due to ambiguity
                continue
            # Not near body edge - treat as RefDes
            token.token_type = TokenType.REFDES
            token.confidence = 0.9
            continue

        # 4. Pin candidate check (flexible alphanumeric, no underscore)
        # This catches: 7, A, ab77, etc. that don't match RefDes pattern
        if is_pin_candidate(token.text, max_length=max_pin_length):
            # Spatial filter: only classify as pin if near a component body
            if bodies and _is_near_body_edge(token.rect, bodies, pin_threshold):
                token.token_type = TokenType.PIN_LABEL
                token.confidence = 0.75  # Slightly lower than strict pattern match
                continue
            # Not near body - fall through to other checks or JUNK

        # 5. Net label: near wire, all uppercase, longer text (no underscore at this point)
        if token.text.isupper() and len(token.text) >= 3:
            if _is_near_wire(token.rect, wire_segments, stop_event=stop_event, wire_index=wire_index, cell_size=wire_cell_size):
                token.token_type = TokenType.NET_LABEL
                token.confidence = 0.7
                continue

        # 6. Default: junk
        token.token_type = TokenType.JUNK
        token.confidence = 0.0


def _is_near_wire(
    token_rect: Rect,
    wire_segments: List[Tuple[Rect, Rect]],
    threshold: float = WIRE_PROXIMITY_THRESHOLD,
    stop_event=None,
    wire_index=None,
    cell_size: float = None,
) -> bool:
    """
    Check if token is within threshold pixels of any wire endpoint.

    Args:
        token_rect: Token bounding box
        wire_segments: List of (start_rect, end_rect) tuples
        threshold: Distance threshold in pixels
        stop_event: Optional event to check for cancellation

    Returns:
        True if near any wire, False otherwise
    """
    token_center = token_rect.center
    threshold_sq = threshold ** 2  # Pre-compute for sqrt-free comparisons

    # Fast path: use a spatial hash of wire endpoints if provided.
    if wire_index and cell_size:
        cx, cy = token_center
        cell_x = int(cx // cell_size)
        cell_y = int(cy // cell_size)
        checks = 0

        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                points = wire_index.get((cell_x + dx, cell_y + dy), [])
                for px, py in points:
                    checks += 1
                    if checks % 5000 == 0 and stop_event and stop_event.is_set():
                        raise CancellationError("Cancelled during wire proximity check")
                    dist_sq = ((cx - px) ** 2 + (cy - py) ** 2)
                    if dist_sq < threshold_sq:
                        return True
        return False

    # Fallback: linear scan (kept for safety when index isn't built).
    for idx, (start, end) in enumerate(wire_segments):
        # Check cancellation periodically (this function can be hot on dense pages)
        if idx % 200 == 0 and stop_event and stop_event.is_set():
            raise CancellationError("Cancelled during wire proximity check")

        for wire_rect in (start, end):
            wire_center = wire_rect.center
            dist_sq = ((token_center[0] - wire_center[0])**2 +
                       (token_center[1] - wire_center[1])**2)
            if dist_sq < threshold_sq:
                return True

    return False


def _build_wire_endpoint_index(
    wire_segments: List[Tuple[Rect, Rect]],
    cell_size: float = 100.0,
) -> dict:
    """
    Build a simple grid index of wire endpoint centers for fast proximity queries.

    The index maps (cell_x, cell_y) -> list[(x, y)] of endpoint centers.
    """
    index = defaultdict(list)
    if cell_size <= 0:
        return index

    for start, end in wire_segments:
        for wire_rect in (start, end):
            cx, cy = wire_rect.center
            key = (int(cx // cell_size), int(cy // cell_size))
            index[key].append((cx, cy))

    return index


# ==================== STEP 5.5: CREATE PINS FROM TOKENS ====================

def _create_pins_from_tokens(
    tokens: List[Token],
    bodies: List[ComponentBody],
    existing_pins: List[Pin],
    config: Dict,
    stop_event=None,
    log_func=None
) -> List[Pin]:
    """
    Create Pin objects from PIN_LABEL tokens near body edges.

    This supplements graphical tick detection for cases where:
    - PDF has no graphical primitives for pins
    - Component bodies are large (FPGA, CPUs)
    - Ticks use non-standard formats (circles, long lines)

    Algorithm:
    1. For each PIN_LABEL token
    2. Find nearest body edge within threshold
    3. If not already covered by a graphical tick pin, create a new Pin
    4. Return merged list (graphical + token-based)

    Args:
        tokens: List of Token objects (already classified)
        bodies: List of ComponentBody objects
        existing_pins: List of Pin objects from graphical detection
        config: Configuration dict with pin_threshold
        stop_event: Optional event to check for cancellation
        log_func: Optional logging callback

    Returns:
        Merged list of existing pins + token-derived pins
    """
    def log(msg):
        if log_func:
            log_func(msg)
        _logger.debug(msg)

    pin_threshold = config.get("pin_threshold", DEFAULT_PIN_THRESHOLD)
    text_pins = []

    for idx, token in enumerate(tokens):
        # Check cancellation every 100 tokens
        if idx % 100 == 0:
            _check_cancelled(stop_event, "token-to-pin creation", log_func)

        if token.token_type != TokenType.PIN_LABEL:
            continue

        # Find nearest body and edge
        best_body = None
        best_edge = None
        best_dist = float('inf')

        for body in bodies:
            # Token has page_num attribute through its confidence field's context
            # For now, we assume single-page processing (bodies on same page)
            edge, dist = _nearest_edge(token.center, body.rect)
            if dist < best_dist and dist < pin_threshold:
                best_dist = dist
                best_body = body
                best_edge = edge

        if best_body:
            # Check if already covered by graphical tick (same body + same label)
            covered = any(
                p.body_id == best_body.body_id and
                p.label_token is not None and
                p.label_token.text == token.text
                for p in existing_pins
            )
            if not covered:
                text_pins.append(Pin(
                    location=token.center,
                    edge=best_edge,
                    label_token=token,
                    body_id=best_body.body_id
                ))

    log(f"    Created {len(text_pins)} pins from PIN_LABEL tokens")
    return existing_pins + text_pins


# ==================== STEP 6: ASSIGN PINS TO BODIES ====================

def _point_inside_rect(point: Tuple[float, float], rect) -> bool:
    """
    Check if a point is inside a rectangle (inclusive of boundaries).

    Args:
        point: (x, y) coordinates
        rect: Rectangle with x0, y0, x1, y1 attributes

    Returns:
        True if point is inside or on the boundary of the rectangle
    """
    px, py = point
    return rect.x0 <= px <= rect.x1 and rect.y0 <= py <= rect.y1


def _assign_pins_to_bodies(
    pins: List[Pin],
    bodies: List[ComponentBody],
    config: Dict,
    stop_event=None,
    log_func=None
) -> None:
    """
    Associate each pin with nearest component body using spatial scoring.

    Scoring formula:
        score = y_overlap_weight * y_overlap - dx_weight * dx

    Where:
    - y_overlap: How well pin aligns vertically with body (0-1)
    - dx: Horizontal distance from body edge (normalized)

    Modifies pins in-place (sets body_id).

    Args:
        pins: List of Pin objects
        bodies: List of ComponentBody objects
        config: Configuration dict with threshold and weights
        stop_event: Optional event to check for cancellation
        log_func: Optional logging callback

    Raises:
        InterruptedError: If cancelled during assignment
    """
    threshold = config.get("pin_assignment_threshold", DEFAULT_PIN_THRESHOLD)
    threshold_sq = threshold ** 2  # Pre-compute for sqrt-free comparisons
    y_weight = config.get("y_overlap_weight", DEFAULT_Y_OVERLAP_WEIGHT)
    dx_weight = config.get("dx_weight", DEFAULT_DX_WEIGHT)

    total_comparisons = 0
    for pin_idx, pin in enumerate(pins):
        # Check cancellation every 50 pins
        if pin_idx % 50 == 0:
            _check_cancelled(stop_event, "pin-to-body assignment", log_func)

        # SMALLEST ENCLOSING BODY WINS: First find all bodies that contain the pin
        containing_bodies = []
        for body in bodies:
            total_comparisons += 1
            if total_comparisons % 100 == 0:
                _check_cancelled(stop_event, "pin containment check", log_func)
            if _point_inside_rect(pin.location, body.rect):
                containing_bodies.append(body)

        # If pin is inside any bodies, assign to the SMALLEST one (by area)
        if containing_bodies:
            smallest_body = min(
                containing_bodies,
                key=lambda b: b.rect.width * b.rect.height
            )
            pin.body_id = smallest_body.body_id
            continue  # Move to next pin - no need for scoring

        # Pin is outside all bodies - fall back to score-based matching
        best_score = -float('inf')
        best_body_id = None

        for body in bodies:
            total_comparisons += 1
            # Check cancellation every 100 comparisons for faster cancel response
            if total_comparisons % 100 == 0:
                _check_cancelled(stop_event, "pin-to-body scoring", log_func)

            # Distance check: skip if pin is too far from body edge
            px, py = pin.location
            rect = body.rect

            # Calculate squared distance to nearest point on rectangle (sqrt-free)
            nearest_x = max(rect.x0, min(px, rect.x1))
            nearest_y = max(rect.y0, min(py, rect.y1))
            distance_sq = (px - nearest_x)**2 + (py - nearest_y)**2

            if distance_sq > threshold_sq:
                continue  # Skip this body - pin is too far away

            score = _calculate_pin_body_score(
                pin, body, y_weight, dx_weight
            )

            if score > best_score:
                best_score = score
                best_body_id = body.body_id

        # Only assign if we found a reasonably good match (positive score)
        if best_score > 0:
            pin.body_id = best_body_id


def _calculate_pin_body_score(
    pin: Pin,
    body: ComponentBody,
    y_weight: float,
    dx_weight: float
) -> float:
    """
    Calculate spatial affinity score for pin-body association.

    Higher score = better match.

    Args:
        pin: Pin object
        body: ComponentBody object
        y_weight: Weight for Y-overlap term
        dx_weight: Weight for horizontal distance term

    Returns:
        Affinity score (higher is better)
    """
    px, py = pin.location
    rect = body.rect

    # Early return for degenerate bodies (zero or negative dimensions)
    if rect.width <= 0 or rect.height <= 0:
        return 0.0  # No score for degenerate bodies

    # Y-overlap calculation (use small epsilon for floating-point tolerance)
    EPSILON = 0.5  # Half-pixel tolerance for boundary comparisons
    if rect.height > 0:
        # How much of the pin's Y coordinate overlaps with body height
        if (rect.y0 - EPSILON) <= py <= (rect.y1 + EPSILON):
            y_overlap_normalized = 1.0  # Perfect vertical alignment
        else:
            # Distance outside body bounds
            if py < rect.y0:
                dist = rect.y0 - py
            else:
                dist = py - rect.y1
            y_overlap_normalized = max(0, 1.0 - dist / rect.height)
    else:
        y_overlap_normalized = 0.0

    # Horizontal distance from appropriate edge
    if pin.edge in ["left", "right"]:
        edge_x = rect.x0 if pin.edge == "left" else rect.x1
        dx = abs(px - edge_x)
    else:  # top/bottom pins
        # Distance from nearest horizontal edge
        dx = min(abs(px - rect.x0), abs(px - rect.x1))

    # Normalize dx by body width
    dx_normalized = dx / (rect.width if rect.width > 0 else 1.0)

    # Combined score
    score = y_weight * y_overlap_normalized - dx_weight * dx_normalized

    return score


# ==================== STEP 7: ASSIGN REFDES TO BODIES ====================

def _assign_refdes_to_bodies(
    bodies: List[ComponentBody],
    tokens: List[Token],
    config: Dict,
    stop_event=None,
    log_func=None
) -> Dict[str, str]:
    """
    Assign RefDes labels to component bodies.

    Strategy:
    - Find nearest REFDES token to body center
    - Prefer top-left quadrant (typical placement)
    - Cap search radius

    Args:
        bodies: List of ComponentBody objects
        tokens: List of Token objects (already classified)
        config: Configuration dict with search radius
        stop_event: Optional event to check for cancellation
        log_func: Optional logging callback

    Returns:
        {body_id: "U1B"}

    Raises:
        InterruptedError: If cancelled during assignment
    """
    radius = config.get("refdes_search_radius", DEFAULT_REFDES_RADIUS)
    min_font_size = config.get("refdes_font_size_min", 8.0)

    # Filter for RefDes tokens
    refdes_tokens = [
        t for t in tokens
        if t.token_type == TokenType.REFDES and t.font_size >= min_font_size
    ]

    body_refdes_map = {}
    total_comparisons = 0

    for body_idx, body in enumerate(bodies):
        # Check cancellation every 20 bodies
        if body_idx % 20 == 0:
            _check_cancelled(stop_event, "RefDes-to-body assignment", log_func)

        best_distance = float('inf')
        best_refdes = None

        body_center = body.rect.center

        # Dynamic radius: scale for large bodies (Issue #3)
        # Large FPGA/CPU bodies may have RefDes labels farther than 100px
        body_diagonal = (body.rect.width**2 + body.rect.height**2)**0.5
        dynamic_radius = max(radius, body_diagonal * 0.3)

        for token in refdes_tokens:
            total_comparisons += 1
            # Check cancellation every 100 comparisons for faster cancel response
            if total_comparisons % 100 == 0:
                _check_cancelled(stop_event, "RefDes distance calculation", log_func)

            # Calculate distance with bias
            dist = _distance_with_bias(body_center, token.center)

            if dist < best_distance and dist < dynamic_radius:
                best_distance = dist
                best_refdes = token.text

        if best_refdes:
            body_refdes_map[body.body_id] = best_refdes
            body.assigned_refdes = best_refdes  # Also store on body object

    return body_refdes_map


def _distance_with_bias(
    body_center: Tuple[float, float],
    token_center: Tuple[float, float],
    top_left_bias: float = DEFAULT_TOP_LEFT_BIAS
) -> float:
    """
    Calculate distance with bias toward top-left quadrant.

    RefDes labels are typically placed above and to the left of components.
    This bias reduces the effective distance for tokens in that quadrant.

    Args:
        body_center: (x, y) center of component body
        token_center: (x, y) center of token
        top_left_bias: Multiplier for top-left tokens (< 1.0 = preference)

    Returns:
        Effective distance (lower = better match)
    """
    dx = token_center[0] - body_center[0]
    dy = token_center[1] - body_center[1]
    euclidean = (dx**2 + dy**2)**0.5

    # Reduce distance if token is top-left of body
    if dx < 0 and dy < 0:
        euclidean *= top_left_bias

    return euclidean


# ==================== STEP 8: BUILD PIN MAPPINGS ====================

def _build_pin_mappings(
    pins: List[Pin],
    body_refdes_map: Dict[str, str],
    page_num: int,
    stop_event=None,
    log_func=None
) -> List[PinMapping]:
    """
    Combine pin, body, and RefDes associations into final mappings.

    Args:
        pins: List of Pin objects (with body_id assigned)
        body_refdes_map: {body_id: "U1B"} from _assign_refdes_to_bodies
        page_num: Zero-indexed page number
        stop_event: Optional event to check for cancellation
        log_func: Optional logging callback

    Returns:
        List of PinMapping objects
    """
    mappings = []

    for idx, pin in enumerate(pins):
        # Check cancellation every 100 pins
        if idx % 100 == 0:
            _check_cancelled(stop_event, "building pin mappings", log_func)
        # Skip pins not assigned to a body
        if not pin.body_id:
            continue

        # Get RefDes for this pin's body
        refdes = body_refdes_map.get(pin.body_id)
        if not refdes:
            continue

        # Get pin label (from associated token or generate)
        if pin.label_token:
            pin_label = pin.label_token.text
            confidence = pin.label_token.confidence
        else:
            pin_label = f"PIN{idx}"
            confidence = 0.5  # Lower confidence for generated labels

        # Create pin identifier
        pin_identifier = f"p{page_num}_pin_{idx}"

        # Build full identifier
        full_identifier = f"{refdes}-{pin_label}"

        mappings.append(PinMapping(
            pin_identifier=pin_identifier,
            refdes=refdes,
            pin_label=pin_label,
            full_identifier=full_identifier,
            confidence=confidence,
            page_num=page_num
        ))

    return mappings
