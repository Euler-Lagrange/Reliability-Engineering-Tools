#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# FROZEN -- Do not modify this file.
# This module is part of a legacy tool whose development is on hold.
# All changes, bug fixes, and refactors are suspended until the freeze is lifted.
# See CLAUDE.md "Frozen Tools" section for details.
# ============================================================================
"""
Group Detection Module for RefDes Extractor

This module handles the detection and classification of component groups
from PDF annotations. Groups are identified by analyzing annotation
rectangles and associating them with text labels.

ARCHITECTURE:
    This module is extracted from refdes_extractor_logic.py to improve
    maintainability and testability. It contains pure functions that:
    1. Parse PDF annotations to identify container rectangles
    2. Match text labels to containers using spatial analysis
    3. Handle nested containers with "smallest box wins" logic

KEY FUNCTIONS:
    - detect_groups(): Main entry point - finds groups from annotations
    - center(), area_of(), point_in_rect(), rect_overlap(): Geometry helpers
    - _sanitize_label(): Cleans annotation text for use as group names

CONSTANTS:
    - STOP_WORDS: Labels to ignore (e.g., "NOTE", "TODO", "REV")
    - MIN_CONTAINER_AREA: Minimum area to consider as valid container

THREAD SAFETY:
    All functions are pure (no shared state) and thread-safe.
"""

import threading
import logging
import re
from typing import Callable, List, Optional, Tuple

from common.partition_id import classify_group_label, sanitize_group_label, STOP_WORDS

# Module logger
_logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

# STOP_WORDS imported from common.partition_id (single source of truth)

# 10 sq pixels (~3x3) - very permissive to catch small nested boxes
# User can still filter results; better to over-detect than miss
MIN_CONTAINER_AREA = 10


# =============================================================================
# GEOMETRY HELPER FUNCTIONS
# =============================================================================

def center(rect: Tuple[float, float, float, float]) -> Tuple[float, float]:
    """
    Calculate the center point of a rectangle.
    
    Args:
        rect: Rectangle as (x0, y0, x1, y1) tuple
        
    Returns:
        Center point as (cx, cy) tuple
    """
    return ((rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2)


def area_of(r: Tuple[float, float, float, float]) -> float:
    """
    Calculate the absolute area of a rectangle.

    Args:
        r: Rectangle as (x0, y0, x1, y1) tuple

    Returns:
        Absolute area in square units
    """
    return abs((r[2] - r[0]) * (r[3] - r[1]))


def normalize_rect(rect: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
    """
    Normalize rectangle coordinates to ensure x0 <= x1 and y0 <= y1.

    PDF annotation tools may create rectangles with inverted coordinates
    (x0 > x1 or y0 > y1). This function ensures consistent ordering.

    Args:
        rect: Rectangle as (x0, y0, x1, y1) tuple (may be inverted)

    Returns:
        Normalized rectangle with x0 <= x1 and y0 <= y1
    """
    x0, y0, x1, y1 = rect
    if x0 > x1:
        x0, x1 = x1, x0
    if y0 > y1:
        y0, y1 = y1, y0
    return (x0, y0, x1, y1)


def point_in_rect(cx: float, cy: float, rect: Tuple[float, float, float, float]) -> bool:
    """
    Check if a point is inside a rectangle.

    Handles inverted rectangles (x0 > x1 or y0 > y1) by normalizing first.

    Args:
        cx: X coordinate of point
        cy: Y coordinate of point
        rect: Rectangle as (x0, y0, x1, y1) tuple (may be inverted)

    Returns:
        True if point is inside or on the boundary of the rectangle
    """
    x0, y0, x1, y1 = rect
    # Handle inverted rectangles from PDF annotation tools
    if x0 > x1:
        x0, x1 = x1, x0
    if y0 > y1:
        y0, y1 = y1, y0
    return x0 <= cx <= x1 and y0 <= cy <= y1


def rect_overlap(a: Tuple[float, float, float, float],
                 b: Tuple[float, float, float, float]) -> bool:
    """
    Check if two rectangles overlap.

    Handles inverted rectangles (x0 > x1 or y0 > y1) by normalizing first.

    Args:
        a: First rectangle as (x0, y0, x1, y1) (may be inverted)
        b: Second rectangle as (x0, y0, x1, y1) (may be inverted)

    Returns:
        True if rectangles overlap
    """
    # Normalize both rectangles to handle inverted coords
    a = normalize_rect(a)
    b = normalize_rect(b)
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


# =============================================================================
# LABEL PROCESSING
# =============================================================================

def _sanitize_label(raw: str) -> str:
    """
    Clean and normalize a text label for use as a group name.
    
    Processing steps:
    1. Take only first line (for multiline annotations)
    2. Strip whitespace
    3. Remove non-alphanumeric characters (except space, underscore, dash, slash, dot)
    4. Convert to uppercase
    
    Args:
        raw: Raw text from annotation
        
    Returns:
        Cleaned, uppercase label string
    """
    return sanitize_group_label(raw)


# =============================================================================
# MAIN GROUP DETECTION
# =============================================================================

def detect_groups(
    annotations: List[dict],
    refdes_pattern: re.Pattern = None,
    log_func: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None
) -> List[Tuple[int, str, Tuple[float, float, float, float]]]:
    """
    Detect component groups from PDF annotations.

    Uses flexible detection:
    - ANY annotation with a valid bounding rect is a potential container
    - Minimum area threshold filters out tiny accidental markup
    - Text is assigned to the SMALLEST enclosing container (nested boxes supported)

    Args:
        annotations: List of annotation dicts from PDF. Each dict should contain:
            - "page": int page number (0-indexed)
            - "rect": tuple (x0, y0, x1, y1) bounding rectangle
            - "content": str (optional) text content of annotation
            - "type": str (optional) annotation type
        refdes_pattern: Compiled regex for RefDes matching (to filter out RefDes from labels)
        log_func: Optional logging callback
        stop_event: Optional threading.Event for cancellation

    Returns:
        List of (page, label, rect) tuples representing detected groups
        
    Raises:
        InterruptedError: If stop_event is set (cancellation requested)
    """
    _log_func = log_func or (lambda x: None)
    
    def log(msg):
        _log_func(msg)
        _logger.info(msg)

    def _check_cancelled():
        """Check for cancellation request."""
        if stop_event and stop_event.is_set():
            from common import CancellationError
            raise CancellationError("Cancelled during group detection")

    # Default RefDes pattern if not provided (basic pattern)
    if refdes_pattern is None:
        refdes_pattern = re.compile(r"\b[A-Z]{1,3}\d+[A-Z]?\b", re.I)

    # Track filtered boxes for debug logging
    filtered_small_box_counts = {}

    def _has_valid_rect(ann: dict, page_num: int = None) -> bool:
        """Check if annotation has a usable bounding rect with minimum area."""
        rect = ann.get("rect")
        if not rect or len(rect) < 4:
            return False
        try:
            area = area_of(rect)
            if area < MIN_CONTAINER_AREA:
                # Track filtered boxes for debug output (count only to avoid memory growth)
                if page_num is not None:
                    filtered_small_box_counts[page_num] = filtered_small_box_counts.get(page_num, 0) + 1
                return False
            return True
        except (TypeError, ValueError):
            return False

    groups = []
    by_page = {}
    for ann in annotations:
        by_page.setdefault(ann["page"], []).append(ann)

    for page, items in by_page.items():
        # Check for cancellation at page level
        _check_cancelled()

        # Debug: Log annotation types found on each page
        if items:
            types_found = set(x.get("type", "Unknown") for x in items)
            log(f"    Page {page + 1}: annotation types found: {types_found}")

        # ANY annotation with a valid rect is a potential container
        containers = [x for x in items if _has_valid_rect(x, page)]

        # ANY annotation with text content (for labeling containers)
        # Note: PyMuPDF's ann.info uses "content" key for annotation text
        texts_with_content = [x for x in items if x.get("content", "").strip()]

        log(f"    Page {page + 1}: {len(containers)} containers (area >= {MIN_CONTAINER_AREA}), {len(texts_with_content)} annotations with text")

        # Debug: Log filtered small boxes for this page
        page_filtered_count = filtered_small_box_counts.get(page, 0)
        if page_filtered_count:
            log(f"    Page {page + 1}: {page_filtered_count} small boxes filtered (area < {MIN_CONTAINER_AREA})")

        if not containers:
            continue

        # Pre-compute container metadata once per page (avoids repeated area calculations)
        containers_info = []
        any_unlabeled = False
        for idx, container in enumerate(containers):
            rect = container.get("rect")
            if not rect:
                continue
            try:
                a = area_of(rect)
            except (TypeError, ValueError):
                continue
            label = _sanitize_label(container.get("content", ""))
            if not label:
                any_unlabeled = True
            containers_info.append(
                {
                    "idx": idx,
                    "rect": normalize_rect(rect),  # Normalize to ensure x0 <= x1, y0 <= y1
                    "area": a,
                    "label": label,
                }
            )

        if not containers_info:
            continue

        # Label assignment map: container idx -> ordered list of candidate labels inside it
        assigned_labels = {c["idx"]: [] for c in containers_info}

        # Only do "smallest enclosing container wins" work if we have any unlabeled containers
        # (keeps FreeText-only PDFs fast when every annotation already has its own label).
        if any_unlabeled and texts_with_content:
            # Guardrails: avoid worst-case O(N*M) blowups on pathological pages.
            # If triggered, we fall back to "only containers with self-label" behavior.
            MAX_CONTAINERS_FOR_ASSIGNMENT = 2500
            MAX_TEXTS_FOR_ASSIGNMENT = 2500
            MAX_CONTAINS_CHECKS = 2_000_000  # N*M upper bound on point-in-rect checks

            # Pre-filter label candidates (apply the same validity rules used later)
            label_candidates = []
            for t in texts_with_content:
                t_rect = t.get("rect")
                if not t_rect:
                    continue
                label = _sanitize_label(t.get("content", ""))
                if not label:
                    continue
                if label in STOP_WORDS:
                    continue
                if refdes_pattern and refdes_pattern.fullmatch(label):
                    continue
                if label.isdigit():
                    continue
                cx, cy = center(t_rect)
                label_candidates.append((cx, cy, label))

            n = len(containers_info)
            m = len(label_candidates)
            if n and m and (n > MAX_CONTAINERS_FOR_ASSIGNMENT or m > MAX_TEXTS_FOR_ASSIGNMENT or (n * m) > MAX_CONTAINS_CHECKS):
                log(
                    f"    WARNING: Page {page + 1}: Too many annotations (containers={n}, labels={m}). "
                    f"Using simplified detection - some component labels may be missing. "
                    f"Consider splitting the PDF or simplifying annotations."
                )
            elif label_candidates:
                # Sort containers smallest->largest; first match is the smallest enclosing container.
                # Secondary sort by position (x, then y) for deterministic behavior across runs.
                containers_by_area = sorted(
                    containers_info,
                    key=lambda c: (c["area"], c["rect"][0], c["rect"][1], c["idx"])
                )

                for t_idx, (cx, cy, label) in enumerate(label_candidates):
                    # Frequent cancellation checks to keep UI responsive under load
                    if t_idx % 100 == 0:
                        _check_cancelled()

                    for c_idx, c in enumerate(containers_by_area):
                        if c_idx % 500 == 0:
                            _check_cancelled()
                        if point_in_rect(cx, cy, c["rect"]):
                            assigned_labels[c["idx"]].append(label)
                            break

        # For each container, compute its label (self-label preferred, then assigned labels)
        for container_idx, c in enumerate(containers_info):
            if container_idx % 50 == 0:
                _check_cancelled()

            label = c["label"]
            if not label:
                assigned = assigned_labels.get(c["idx"], [])
                if assigned:
                    label = next((L for L in assigned if "CONN" in L), assigned[0])

            # Only add if we have a valid label
            if label and label not in STOP_WORDS and (not refdes_pattern or not refdes_pattern.fullmatch(label)):
                groups.append((page, label, c["rect"]))

    # Deduplicate by (page, label, position)
    unique = []
    seen = set()
    for p, l, r in groups:
        key = (p, l, round(r[0]), round(r[1]), round(r[2]), round(r[3]))
        if key not in seen:
            seen.add(key)
            unique.append((p, l, r))

    log(f"  Detected {len(unique)} component groups.")
    return unique


def detect_groups_from_drawings(
    doc,
    refdes_pattern: re.Pattern = None,
    log_func: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
    sample_pages: int = 10,
    max_pages_to_inspect: Optional[int] = None,
    max_candidates_per_page: int = 40,
    min_container_area: float = 10000.0,
    min_container_width: float = 150.0,
    min_container_height: float = 100.0,
    top_band: float = 30.0,
    above_margin: float = 20.0,
) -> List[Tuple[int, str, Tuple[float, float, float, float]]]:
    """
    Recover likely group containers from searchable text plus simple vector rectangles.

    This is intentionally bounded and cheap:
    - samples at most a few pages
    - uses drawing bounding rectangles only
    - associates only nearby text tokens
    """
    _log_func = log_func or (lambda x: None)

    def log(msg):
        _log_func(msg)
        _logger.info(msg)

    def _check_cancelled():
        if stop_event and stop_event.is_set():
            from common import CancellationError

            raise CancellationError("Cancelled during drawing fallback detection")

    if refdes_pattern is None:
        refdes_pattern = re.compile(r"\b[A-Z]{1,3}\d+[A-Z]?\b", re.I)

    groups = []
    text_pages_scanned = 0
    for page_num, page in enumerate(doc):
        if max_pages_to_inspect is not None and page_num >= max_pages_to_inspect:
            break
        _check_cancelled()

        words = page.get_text("words") or []
        if not words:
            continue
        if text_pages_scanned >= sample_pages:
            log(f"  Drawing fallback: sampled {sample_pages} text pages, skipping remaining pages.")
            break
        text_pages_scanned += 1

        page_rect = tuple(page.rect)
        candidates = []
        for drawing in page.get_drawings() or []:
            rect = drawing.get("rect")
            if not rect or len(rect) < 4:
                continue
            rect = normalize_rect(tuple(rect))
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
            if width < min_container_width or height < min_container_height:
                continue
            if area_of(rect) < min_container_area:
                continue
            # Reject near-full-page rectangles (drawing borders/frames)
            page_w = page_rect[2] - page_rect[0]
            page_h = page_rect[3] - page_rect[1]
            page_area = page_w * page_h
            if page_area > 0 and area_of(rect) > 0.90 * page_area:
                continue
            if (
                abs(rect[0] - page_rect[0]) <= 5
                and abs(rect[1] - page_rect[1]) <= 5
                and abs(rect[2] - page_rect[2]) <= 5
                and abs(rect[3] - page_rect[3]) <= 5
            ):
                continue
            candidates.append(rect)
            if len(candidates) >= max_candidates_per_page:
                log(f"  Skipping remaining drawing candidates on page {page_num + 1}: cap reached")
                break

        for rect in candidates:
            label = ""
            best_y = None
            x0, y0, x1, y1 = rect
            for word in words:
                wx0, wy0, wx1, wy1, text = word[:5]
                if wx1 < x0 or wx0 > x1:
                    continue

                near_top = y0 <= wy0 <= y0 + top_band
                just_above = y0 - above_margin <= wy1 <= y0
                if not near_top and not just_above:
                    continue

                candidate = sanitize_group_label(text)
                if not candidate:
                    continue
                if refdes_pattern.fullmatch(candidate):
                    continue
                if classify_group_label(candidate) == "noise":
                    continue

                if best_y is None or wy0 < best_y:
                    label = candidate
                    best_y = wy0

            if label:
                groups.append((page_num, label, rect))

    unique = []
    seen = set()
    for p, l, r in groups:
        key = (p, l, round(r[0]), round(r[1]), round(r[2]), round(r[3]))
        if key not in seen:
            seen.add(key)
            unique.append((p, l, r))

    if unique:
        log(f"  Recovered {len(unique)} component group(s) from bounded drawing fallback.")
    return unique
