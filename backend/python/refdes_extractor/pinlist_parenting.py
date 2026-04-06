# ============================================================================
# FROZEN -- Do not modify this file.
# This module is part of a legacy tool whose development is on hold.
# All changes, bug fixes, and refactors are suspended until the freeze is lifted.
# See CLAUDE.md "Frozen Tools" section for details.
# ============================================================================
"""
Pinlist-driven pin qualification for Piece-Part mode.

This module provides lightweight pin-to-parent assignment without
expensive geometry analysis, specifically designed to handle:
- Page-spanning IC symbols (RefDes far from pins)
- Passive terminal suppression (1/2 on C/R/L/D)
- Ambiguous pin token resolution via clustering

IMPORTANT: This module avoids circular imports by accepting callables
for RefDes detection and canonicalization instead of importing them.

Architecture:
1. Token Harvest -> Collect pin candidates from groups
2. Build Spatial Indexes -> Grid-bucket RefDes/value tokens for O(1) lookups
3. Pin Clustering -> Group nearby pins using grid bucketing + union-find
4. Cluster Classification -> ic_like / passive_like / ambiguous
5. Passive Suppression -> Suppress entire passive_like clusters
6. Parent Resolution -> Infer parent via pinlist hits with tie-breaking
7. Acceptance Thresholds -> Hardened rules for {1,2}-only clusters
8. Final Output -> Return qualified tokens grouped by original group
"""

from typing import Dict, Set, List, Tuple, Optional, Callable
from dataclasses import dataclass, field
from collections import defaultdict
import re
import math
import logging
import threading

from common import (
    NO_PIN_ANALYSIS_PREFIXES,
    get_prefix,
    CancellationError,
)

_logger = logging.getLogger(__name__)


# =============================================================================
# CANCELLATION SUPPORT
# =============================================================================

def _check_stop(stop_event: Optional[threading.Event]) -> None:
    """
    Check if cancellation has been requested and raise if so.

    This allows the user to cancel long-running operations via the GUI.
    Must be called periodically in loops to ensure responsiveness.

    Raises:
        CancellationError: If stop_event is set
    """
    if stop_event and stop_event.is_set():
        raise CancellationError("Operation cancelled by user")

# =============================================================================
# CONSTANTS
# =============================================================================

# Minimal default - user explicitly wanted only ICs/connectors
DEFAULT_PIN_PARENT_PREFIX_ALLOWLIST = [
    "U", "IC",           # ICs
    "J", "P", "CN",      # Connectors
    "CONN", "X", "XPSJ", # More connectors
    "AR",                # Amplifiers
]

# Value/unit pattern for detecting component values (10uF, 22K, etc.)
# This helps identify passive component context
# M5 fix: Both alternatives now properly anchored with $ to prevent prefix matching
VALUE_UNIT_RE = re.compile(
    r'^\d+(?:\.\d+)?[munpkMG]?[FfHhVvAaWwRrΩ]+$'
    r'|^\d+(?:\.\d+)?(?:uF|nF|pF|mF|uH|nH|mH|ohm|OHM|Ohm|[kK]|[mM]eg)$',
    re.IGNORECASE
)

# Default configuration values
DEFAULT_CONFIG = {
    "pin_parent_prefix_allowlist": DEFAULT_PIN_PARENT_PREFIX_ALLOWLIST,
    "passive_terminal_labels": ["1", "2"],
    "passive_context_radius_px": 120.0,
    "pin_cluster_cell_size_px": 120.0,
    "pin_cluster_max_dist_px": 150.0,
    "cluster_min_distinct_labels": 2,
    "strict_numeric_pin_parenting": True,
    "parent_refdes_max_radius": 300.0,  # Max distance (px) from group bbox to consider RefDes as parent candidate
}


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class PinToken:
    """
    A pin candidate token with spatial information.

    Attributes:
        text: The pin label text (e.g., "2", "A1", "VCC")
        center: (cx, cy) center point of the token
        rect: (x0, y0, x1, y1) bounding rectangle
        group_name: The annotation group this token belongs to
        cluster_id: Assigned cluster ID after clustering
        parent_refdes: Resolved parent RefDes (e.g., "U92")
        suppressed: True if token is suppressed as passive terminal
        drop_reason: Reason for dropping if not accepted
    """
    text: str
    center: Tuple[float, float]
    rect: Tuple[float, float, float, float]
    group_name: str
    cluster_id: Optional[int] = None
    parent_refdes: Optional[str] = None
    suppressed: bool = False
    drop_reason: Optional[str] = None


@dataclass
class PinCluster:
    """
    A spatial cluster of pin tokens.

    Attributes:
        cluster_id: Unique identifier for this cluster
        tokens: List of PinToken objects in this cluster
        parent_refdes: Resolved parent RefDes for the cluster
        hit_count: Number of distinct pinlist hits
        confidence: Resolution status (resolved, ambiguous_tie, no_hits)
        cluster_type: Classification (ic_like, passive_like, ambiguous)
        distinct_labels: Set of unique pin labels in the cluster
    """
    cluster_id: int
    tokens: List[PinToken] = field(default_factory=list)
    parent_refdes: Optional[str] = None
    hit_count: int = 0
    confidence: str = "unknown"
    cluster_type: str = "unknown"  # "ic_like", "passive_like", "ambiguous"
    distinct_labels: Set[str] = field(default_factory=set)


# =============================================================================
# UNION-FIND DATA STRUCTURE (for clustering)
# =============================================================================

class UnionFind:
    """
    Union-Find (Disjoint Set) data structure for efficient clustering.

    Uses path compression and union by rank for near-O(1) operations.
    """

    def __init__(self, n: int):
        """Initialize with n elements (0 to n-1)."""
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        """Find root of x with path compression."""
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, x: int, y: int) -> None:
        """Union sets containing x and y by rank."""
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1


# =============================================================================
# PINLIST INDEX PRECOMPUTATION
# =============================================================================

def build_pinlist_indexes(
    normalized_pinlist: Set[str]
) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    """
    Build fast lookup indexes from pinlist.

    Parses each pinlist entry (e.g., "U92-2") to create bidirectional mappings
    between pin labels and parent RefDes values.

    Args:
        normalized_pinlist: Set of canonical "REFDES-PIN" strings

    Returns:
        Tuple of:
        - parents_by_label: {"2": {"U92", "U105"}, "A1": {"J5"}, ...}
        - labels_by_parent: {"U92": {"1", "2", "3"}, ...}

    Example:
        >>> pinlist = {"U92-1", "U92-2", "J5-A1", "J5-A2"}
        >>> p_by_l, l_by_p = build_pinlist_indexes(pinlist)
        >>> p_by_l["2"]
        {"U92"}
        >>> l_by_p["J5"]
        {"A1", "A2"}
    """
    parents_by_label: Dict[str, Set[str]] = defaultdict(set)
    labels_by_parent: Dict[str, Set[str]] = defaultdict(set)

    for entry in normalized_pinlist:
        if '-' not in entry:
            continue

        # Use rsplit to handle RefDes with hyphens (e.g., "XPSJ1-2-A1" -> "XPSJ1-2", "A1")
        parts = entry.rsplit('-', 1)
        if len(parts) != 2:
            continue

        parent, label = parts
        if not parent or not label:
            continue

        parents_by_label[label].add(parent)
        labels_by_parent[parent].add(label)

    return dict(parents_by_label), dict(labels_by_parent)


# =============================================================================
# SPATIAL INDEXING (O(1) LOOKUPS)
# =============================================================================

def build_spatial_indexes(
    page_words: List[Tuple],
    cell_size: float,
    is_refdes_fn: Callable[[str], bool],
) -> dict:
    """
    Build grid-bucketed indexes for O(1) proximity queries.

    Creates spatial indexes for RefDes tokens and component value tokens,
    enabling fast lookups for passive evidence detection.

    Args:
        page_words: List of word tuples from PyMuPDF: (x0, y0, x1, y1, text, ...)
        cell_size: Grid cell size in pixels
        is_refdes_fn: Callable to check if text is a RefDes

    Returns:
        Dict with:
        - "refdes_grid": {(cell_x, cell_y): [(refdes, cx, cy), ...]}
        - "value_grid": {(cell_x, cell_y): [(value, cx, cy), ...]}
        - "refdes_set": Set of all RefDes on the page
    """
    refdes_grid: Dict[Tuple[int, int], List[Tuple[str, float, float]]] = defaultdict(list)
    value_grid: Dict[Tuple[int, int], List[Tuple[str, float, float]]] = defaultdict(list)
    refdes_set: Set[str] = set()

    for word_tuple in page_words:
        if len(word_tuple) < 5:
            continue

        x0, y0, x1, y1, text = word_tuple[:5]
        text = str(text).strip()
        if not text:
            continue

        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        # M1 fix: Use math.floor() instead of int() for negative coordinate handling
        # int() truncates toward 0, not -∞: int(-0.5) = 0, but math.floor(-0.5) = -1
        cell = (math.floor(cx / cell_size), math.floor(cy / cell_size))

        if is_refdes_fn(text):
            # M4 fix: Normalize RefDes to uppercase for consistent matching
            normalized_text = text.upper()
            refdes_grid[cell].append((normalized_text, cx, cy))
            refdes_set.add(normalized_text)
        elif VALUE_UNIT_RE.match(text):
            value_grid[cell].append((text, cx, cy))

    return {
        "refdes_grid": dict(refdes_grid),
        "value_grid": dict(value_grid),
        "refdes_set": refdes_set,
    }


def get_cells_in_radius(
    cx: float, cy: float, radius: float, cell_size: float
) -> List[Tuple[int, int]]:
    """
    Get all grid cells that could contain points within radius.

    Args:
        cx, cy: Center point
        radius: Search radius in pixels
        cell_size: Grid cell size in pixels

    Returns:
        List of (cell_x, cell_y) tuples to check
    """
    # Safety limit to prevent runaway loops with corrupt/extreme coordinates
    MAX_CELLS = 10000

    # Calculate cell range to check
    # M1 fix: Use math.floor() for negative coordinate handling
    min_cell_x = math.floor((cx - radius) / cell_size)
    max_cell_x = math.floor((cx + radius) / cell_size)
    min_cell_y = math.floor((cy - radius) / cell_size)
    max_cell_y = math.floor((cy + radius) / cell_size)

    # B2 fix: Check cell count before creating loop to prevent hang
    num_cells_x = max_cell_x - min_cell_x + 1
    num_cells_y = max_cell_y - min_cell_y + 1
    total_cells = num_cells_x * num_cells_y

    if total_cells > MAX_CELLS:
        _logger.warning(
            f"Cell count {total_cells} exceeds limit {MAX_CELLS} "
            f"(radius={radius:.1f}, cell_size={cell_size:.1f}), clamping to center region"
        )
        # Clamp to a square centered on the point
        max_dim = int(math.sqrt(MAX_CELLS))
        half_dim = max_dim // 2
        center_cell_x = math.floor(cx / cell_size)
        center_cell_y = math.floor(cy / cell_size)
        min_cell_x = center_cell_x - half_dim
        max_cell_x = center_cell_x + half_dim
        min_cell_y = center_cell_y - half_dim
        max_cell_y = center_cell_y + half_dim

    cells = []
    for cell_x in range(min_cell_x, max_cell_x + 1):
        for cell_y in range(min_cell_y, max_cell_y + 1):
            cells.append((cell_x, cell_y))

    return cells


def _distance_sq(x1: float, y1: float, x2: float, y2: float) -> float:
    """Calculate squared Euclidean distance (avoids sqrt for comparisons)."""
    return (x2 - x1) ** 2 + (y2 - y1) ** 2


def compute_group_bbox(entries: List[dict]) -> Tuple[float, float, float, float]:
    """
    Compute bounding box encompassing all entries in a group.

    Args:
        entries: List of entry dicts with 'rect' key

    Returns:
        Tuple (x0, y0, x1, y1) bounding box
    """
    # B4 fix: Maximum reasonable coordinate for PDF (prevents explosion from corrupt data)
    MAX_COORD = 50000

    if not entries:
        return (0, 0, 0, 0)

    rects = [e.get("rect", (0, 0, 0, 0)) for e in entries if e.get("rect")]
    if not rects:
        return (0, 0, 0, 0)

    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[2] for r in rects)
    y1 = max(r[3] for r in rects)

    # B4 fix: Validate coordinates to prevent extreme values causing cell explosion
    coords = (x0, y0, x1, y1)
    if any(math.isnan(v) or math.isinf(v) for v in coords):
        _logger.warning(f"Invalid bbox coordinates (NaN/Inf): {coords}, using fallback")
        return (0, 0, 0, 0)

    if any(abs(v) > MAX_COORD for v in coords):
        _logger.warning(f"Bbox coordinates exceed limit: {coords}, clamping to valid range")
        x0 = max(-MAX_COORD, min(MAX_COORD, x0))
        y0 = max(-MAX_COORD, min(MAX_COORD, y0))
        x1 = max(-MAX_COORD, min(MAX_COORD, x1))
        y1 = max(-MAX_COORD, min(MAX_COORD, y1))

    return (x0, y0, x1, y1)


def distance_to_bbox(px: float, py: float, bbox: Tuple[float, float, float, float]) -> float:
    """
    Calculate minimum distance from point (px, py) to a bounding box.

    Returns 0 if point is inside the bbox.

    Args:
        px, py: Point coordinates
        bbox: (x0, y0, x1, y1) bounding box

    Returns:
        Minimum distance from point to bbox edge (0 if inside)
    """
    x0, y0, x1, y1 = bbox

    # Clamp point to bbox to find nearest point on/in bbox
    nearest_x = max(x0, min(px, x1))
    nearest_y = max(y0, min(py, y1))

    # Distance from original point to nearest point
    dx = px - nearest_x
    dy = py - nearest_y
    return math.sqrt(dx * dx + dy * dy)


def find_refdes_near_bbox(
    bbox: Tuple[float, float, float, float],
    refdes_grid: Dict[Tuple[int, int], List[Tuple[str, float, float]]],
    cell_size: float,
    radius: float,
) -> Set[str]:
    """
    Find all RefDes within radius of a bounding box.

    This is used to limit parent resolution to only RefDes that are
    spatially near the group being processed, preventing cross-contamination.

    Args:
        bbox: (x0, y0, x1, y1) bounding box of the group
        refdes_grid: Grid-indexed RefDes positions from build_spatial_indexes()
        cell_size: Grid cell size in pixels
        radius: Maximum distance from bbox to consider

    Returns:
        Set of RefDes strings that are within radius of the bbox
    """
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    # Expand search radius by bbox half-diagonal to cover entire bbox
    half_diag = math.sqrt((x1 - x0)**2 + (y1 - y0)**2) / 2
    search_radius = radius + half_diag

    nearby: Set[str] = set()
    cells = get_cells_in_radius(cx, cy, search_radius, cell_size)

    for cell in cells:
        for refdes, rx, ry in refdes_grid.get(cell, []):
            # Check if refdes is within radius of bbox (not just center)
            dist = distance_to_bbox(rx, ry, bbox)
            if dist <= radius:
                nearby.add(refdes)

    return nearby


# =============================================================================
# PIN CLUSTERING (Grid Bucketing + Union-Find)
# =============================================================================

def cluster_pin_tokens(
    pin_tokens: List[PinToken],
    config: dict
) -> List[PinCluster]:
    """
    Cluster pin tokens by spatial proximity using grid bucketing + union-find.

    Algorithm:
    1. Assign each token to a grid cell based on its center
    2. For each token, check same cell + 8 adjacent cells for neighbors
    3. Merge tokens within cluster_max_dist_px using union-find
    4. Group tokens by their final cluster assignment

    This is O(n) per page and stable on large documents.

    Args:
        pin_tokens: List of PinToken objects to cluster
        config: Configuration dict with clustering parameters

    Returns:
        List of PinCluster objects
    """
    if not pin_tokens:
        return []

    cell_size = config.get("pin_cluster_cell_size_px", DEFAULT_CONFIG["pin_cluster_cell_size_px"])
    max_dist = config.get("pin_cluster_max_dist_px", DEFAULT_CONFIG["pin_cluster_max_dist_px"])
    max_dist_sq = max_dist ** 2

    n = len(pin_tokens)
    uf = UnionFind(n)

    # Build grid index for tokens
    token_grid: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for i, token in enumerate(pin_tokens):
        cx, cy = token.center
        # M1 fix: Use math.floor() for negative coordinate handling
        cell = (math.floor(cx / cell_size), math.floor(cy / cell_size))
        token_grid[cell].append(i)

    # For each token, check neighbors in same + adjacent cells
    for i, token in enumerate(pin_tokens):
        cx, cy = token.center
        # M1 fix: Use math.floor() for negative coordinate handling
        cell_x = math.floor(cx / cell_size)
        cell_y = math.floor(cy / cell_size)

        # Check 3x3 neighborhood of cells
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                neighbor_cell = (cell_x + dx, cell_y + dy)
                for j in token_grid.get(neighbor_cell, []):
                    if j <= i:
                        continue  # Avoid duplicate checks
                    other = pin_tokens[j]
                    dist_sq = _distance_sq(cx, cy, other.center[0], other.center[1])
                    if dist_sq <= max_dist_sq:
                        uf.union(i, j)

    # Group tokens by cluster root
    cluster_groups: Dict[int, List[int]] = defaultdict(list)
    for i in range(n):
        root = uf.find(i)
        cluster_groups[root].append(i)

    # Build PinCluster objects
    clusters = []
    for cluster_id, token_indices in enumerate(cluster_groups.values()):
        cluster = PinCluster(cluster_id=cluster_id)
        for i in token_indices:
            token = pin_tokens[i]
            token.cluster_id = cluster_id
            cluster.tokens.append(token)
        cluster.distinct_labels = {t.text for t in cluster.tokens}
        clusters.append(cluster)

    _logger.debug(f"Clustered {n} tokens into {len(clusters)} clusters")
    return clusters


# =============================================================================
# PASSIVE EVIDENCE DETECTION
# =============================================================================

def has_passive_evidence_nearby(
    center: Tuple[float, float],
    radius: float,
    spatial_indexes: dict,
    cell_size: float,
) -> Tuple[bool, Optional[str]]:
    """
    O(1) check for passive evidence within radius.

    Looks for:
    1. RefDes with passive prefix (C, R, L, D, FB, etc.) within radius
    2. Component value token (10uF, 22K, etc.) within radius

    Args:
        center: (cx, cy) point to check from
        radius: Search radius in pixels
        spatial_indexes: Dict from build_spatial_indexes()
        cell_size: Grid cell size

    Returns:
        Tuple of (has_evidence: bool, evidence_type: str or None)
        evidence_type is "refdes" or "value" if found
    """
    cx, cy = center
    radius_sq = radius ** 2
    cells_to_check = get_cells_in_radius(cx, cy, radius, cell_size)

    refdes_grid = spatial_indexes.get("refdes_grid", {})
    value_grid = spatial_indexes.get("value_grid", {})

    # Check for passive RefDes
    for cell in cells_to_check:
        for refdes, rx, ry in refdes_grid.get(cell, []):
            if _distance_sq(cx, cy, rx, ry) <= radius_sq:
                prefix = get_prefix(refdes)
                if prefix and prefix.upper() in NO_PIN_ANALYSIS_PREFIXES:
                    return (True, "refdes")

    # Check for value tokens
    for cell in cells_to_check:
        for value, vx, vy in value_grid.get(cell, []):
            if _distance_sq(cx, cy, vx, vy) <= radius_sq:
                return (True, "value")

    return (False, None)


def check_cluster_passive_evidence(
    cluster: PinCluster,
    spatial_indexes: dict,
    config: dict
) -> bool:
    """
    Check if a cluster has passive evidence nearby.

    Checks each token in the cluster for passive evidence within the
    configured radius. Returns True if ANY token has passive evidence.

    Args:
        cluster: PinCluster to check
        spatial_indexes: Dict from build_spatial_indexes()
        config: Configuration dict

    Returns:
        True if passive evidence found near any token in the cluster
    """
    radius = config.get("passive_context_radius_px", DEFAULT_CONFIG["passive_context_radius_px"])
    cell_size = config.get("pin_cluster_cell_size_px", DEFAULT_CONFIG["pin_cluster_cell_size_px"])

    for token in cluster.tokens:
        has_evidence, _ = has_passive_evidence_nearby(
            token.center, radius, spatial_indexes, cell_size
        )
        if has_evidence:
            return True

    return False


# =============================================================================
# CLUSTER CLASSIFICATION
# =============================================================================

def classify_cluster(
    cluster: PinCluster,
    spatial_indexes: dict,
    config: dict,
    group_has_ic_refdes: bool = False
) -> str:
    """
    Classify cluster as 'ic_like', 'passive_like', or 'ambiguous'.

    CRITICAL: Base decisions on distinct_labels, not token count.
    Token count can be inflated by many capacitors with same terminals.

    Classification rules:
    1. {1,2}-only clusters -> passive_like (unless group has IC/connector RefDes - M3 fix)
    2. Clusters with >= 4 distinct labels -> ic_like
    3. Clusters with passive evidence AND numeric-only AND <= 2 labels -> passive_like
    4. Clusters with passive evidence -> ambiguous
    5. Otherwise -> ic_like

    Args:
        cluster: PinCluster to classify
        spatial_indexes: Dict from build_spatial_indexes()
        config: Configuration dict
        group_has_ic_refdes: True if the group contains an IC/connector RefDes (M3 fix)

    Returns:
        Classification string: "ic_like", "passive_like", or "ambiguous"
    """
    distinct_labels = cluster.distinct_labels
    passive_terminals = set(config.get("passive_terminal_labels", DEFAULT_CONFIG["passive_terminal_labels"]))

    numeric_only = all(label.isdigit() for label in distinct_labels)

    # {1,2}-only clusters are suspicious, but check for exceptions
    if distinct_labels and distinct_labels <= passive_terminals:
        # M2 fix: Removed dead code branch (len >= 4 impossible when subset of {"1","2"})
        # M3 fix: Exception - if the GROUP contains an IC/connector RefDes, don't auto-suppress
        # This prevents false negatives for small connectors with only pins 1 and 2
        if group_has_ic_refdes:
            _logger.debug(f"Cluster {cluster.cluster_id}: classified as ambiguous (group has IC/connector RefDes)")
            return "ambiguous"  # Will require pinlist validation, not auto-suppress

        # Otherwise assume passive
        _logger.debug(f"Cluster {cluster.cluster_id}: classified as passive_like (only terminal labels)")
        return "passive_like"

    # Clusters with 4+ distinct labels are likely IC
    if len(distinct_labels) >= 4:
        return "ic_like"

    # Check passive evidence
    has_passive = check_cluster_passive_evidence(cluster, spatial_indexes, config)

    if has_passive:
        if numeric_only and len(distinct_labels) <= 2:
            _logger.debug(f"Cluster {cluster.cluster_id}: classified as passive_like (passive evidence + numeric)")
            return "passive_like"
        _logger.debug(f"Cluster {cluster.cluster_id}: classified as ambiguous (passive evidence present)")
        return "ambiguous"

    return "ic_like"


# =============================================================================
# CLUSTER PARENT RESOLUTION
# =============================================================================

def extract_page_refdes_set(
    page_words: List[Tuple],
    is_refdes_fn: Callable[[str], bool],
) -> Set[str]:
    """
    Extract set of all RefDes values on the page.

    Args:
        page_words: List of word tuples from PyMuPDF
        is_refdes_fn: Callable to check if text is a RefDes

    Returns:
        Set of RefDes strings found on the page
    """
    refdes_set = set()
    for word_tuple in page_words:
        if len(word_tuple) < 5:
            continue
        text = str(word_tuple[4]).strip()
        if text and is_refdes_fn(text):
            # M4 fix: Normalize RefDes to uppercase for consistent matching
            refdes_set.add(text.upper())
    return refdes_set


def resolve_cluster_parent(
    cluster: PinCluster,
    pinlist_parents_by_label: Dict[str, Set[str]],
    page_refdes_set: Set[str],
    config: dict,
    nearby_refdes: Optional[Set[str]] = None,
) -> Tuple[Optional[str], int, str]:
    """
    Infer best parent RefDes for a cluster using pinlist.

    Algorithm:
    1. Collect candidate parents from pinlist for all labels in cluster
    2. Filter to allowed prefixes only
    3. Filter to nearby RefDes only (if provided) - CRITICAL for preventing cross-contamination
    4. Score each candidate by distinct pinlist hits
    5. Apply tie-breaking: hits -> on-page -> lexicographic
    6. Apply "don't guess" rule: if tied, mark ambiguous

    Args:
        cluster: PinCluster to resolve
        pinlist_parents_by_label: Mapping from label -> set of possible parents
        page_refdes_set: Set of RefDes present on this page
        config: Configuration dict
        nearby_refdes: Optional set of RefDes that are spatially near this cluster's group.
                       If provided, only these candidates are considered. This prevents
                       a connector J1 from being assigned as parent for a capacitor group
                       that happens to have pin labels "1" and "2".

    Returns:
        Tuple of (parent_refdes, hit_count, resolution_status)
        resolution_status is "resolved", "ambiguous_tie", "no_nearby_candidates", or "no_hits"
    """
    allowlist = set(config.get("pin_parent_prefix_allowlist", DEFAULT_CONFIG["pin_parent_prefix_allowlist"]))
    allowlist_upper = {p.upper() for p in allowlist}

    # Collect all candidate parents from pinlist
    candidate_parents: Set[str] = set()
    for label in cluster.distinct_labels:
        parents = pinlist_parents_by_label.get(label, set())
        for parent in parents:
            prefix = get_prefix(parent)
            if prefix and prefix.upper() in allowlist_upper:
                # CRITICAL FIX: If nearby_refdes is provided, filter to only nearby candidates
                # This prevents J1 from being assigned as parent for a distant capacitor group
                if nearby_refdes is not None and parent not in nearby_refdes:
                    continue
                candidate_parents.add(parent)

    if not candidate_parents:
        return (None, 0, "no_hits")

    # Score each candidate by distinct label hits
    scored: List[Tuple[int, bool, str]] = []
    for parent in candidate_parents:
        hits = 0
        for label in cluster.distinct_labels:
            if parent in pinlist_parents_by_label.get(label, set()):
                hits += 1
        on_page = parent in page_refdes_set
        scored.append((hits, on_page, parent))

    # Sort: descending hits, prefer on-page, then lexicographic for determinism
    scored.sort(key=lambda x: (-x[0], not x[1], x[2]))

    if not scored:
        return (None, 0, "no_hits")

    best_hits, best_on_page, best_parent = scored[0]

    # "Don't guess" rule: if best and second-best have same hits AND same on-page status, mark ambiguous
    # Note: if hits are equal but on-page status differs, that's NOT a tie - on-page wins
    if len(scored) >= 2 and scored[0][0] == scored[1][0] and scored[0][1] == scored[1][1]:
        _logger.debug(
            f"Cluster {cluster.cluster_id}: tie between {scored[0][2]} and {scored[1][2]} "
            f"(both have {best_hits} hits, both {'on' if best_on_page else 'off'} page)"
        )
        return (None, best_hits, "ambiguous_tie")

    if best_hits == 0:
        return (None, 0, "no_hits")

    _logger.debug(f"Cluster {cluster.cluster_id}: resolved to {best_parent} with {best_hits} hits")
    return (best_parent, best_hits, "resolved")


# =============================================================================
# ACCEPTANCE THRESHOLDS
# =============================================================================

def should_accept_cluster(
    cluster: PinCluster,
    config: dict
) -> Tuple[bool, Optional[str]]:
    """
    Apply acceptance thresholds based on cluster type.

    Acceptance rules by cluster type:
    - passive_like: REJECT ALL (suppress entire cluster)
    - ambiguous: Require min distinct labels AND stricter numeric rules
    - ic_like: Accept if parent resolved

    For numeric-only labels (especially {1,2}), apply stricter thresholds
    to prevent passive terminals from leaking through.

    Args:
        cluster: PinCluster to evaluate
        config: Configuration dict

    Returns:
        Tuple of (accept: bool, drop_reason: str or None)
    """
    # Passive clusters are always rejected
    if cluster.cluster_type == "passive_like":
        return (False, "passive_cluster")

    # No parent resolved
    if cluster.parent_refdes is None:
        if cluster.confidence == "ambiguous_tie":
            return (False, "ambiguous_tie")
        return (False, "no_parent_resolved")

    # Ambiguous clusters need higher confidence
    if cluster.cluster_type == "ambiguous":
        min_labels = config.get("cluster_min_distinct_labels", DEFAULT_CONFIG["cluster_min_distinct_labels"])
        if cluster.hit_count < min_labels:
            return (False, "ambiguous_low_hits")

        # For ambiguous with numeric-only labels, require even stricter evidence
        if all(l.isdigit() for l in cluster.distinct_labels):
            strict = config.get("strict_numeric_pin_parenting", DEFAULT_CONFIG["strict_numeric_pin_parenting"])
            if strict and cluster.hit_count < 3:
                return (False, "ambiguous_numeric")

    return (True, None)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def qualify_pins_via_pinlist(
    group_entries: Dict[str, List[dict]],
    normalized_pinlist: Set[str],
    page_words: List[Tuple],
    config: dict,
    is_refdes_fn: Callable[[str], bool],
    is_pin_candidate_fn: Callable[[str], bool],
    stop_event: Optional[threading.Event] = None,
) -> Dict[str, List[PinToken]]:
    """
    Main entry point: qualify pin tokens using pinlist-driven clustering.

    This function implements the full pin qualification pipeline:
    1. Build pinlist indexes for fast lookup
    2. Build spatial indexes for O(1) proximity queries
    3. For EACH GROUP independently:
       a. Collect pin candidates from that group
       b. Cluster pins spatially (per-group to prevent cross-contamination)
       c. Check if group contains IC/connector RefDes (for M3 fix)
       d. Classify each cluster (ic_like / passive_like / ambiguous)
       e. Suppress passive_like clusters
       f. Resolve parent for remaining clusters via pinlist
       g. Apply acceptance thresholds
    4. Return qualified tokens grouped by original group

    CRITICAL FIX (C3): Clustering is now done PER-GROUP, not page-wide.
    This prevents a capacitor terminal "2" from joining an IC's pin cluster
    just because they happen to be within clustering radius on the same page.

    Args:
        group_entries: Dict mapping group_name -> list of entry dicts
            Each entry has: text, center, rect, is_prov, etc.
        normalized_pinlist: Set of canonical "REFDES-PIN" strings
        page_words: List of word tuples from PyMuPDF
        config: Dict of configuration values (extracted from ConfigManager)
        is_refdes_fn: Callable to check if text is a RefDes (avoids circular import)
        is_pin_candidate_fn: Callable to check if text could be a pin label
        stop_event: Optional threading.Event for cancellation support. If set,
            the function will raise CancellationError at the next check point.

    Returns:
        Dict mapping group_name -> list of PinToken objects
        Each PinToken has parent_refdes set (if accepted) or suppressed/drop_reason set

    Raises:
        CancellationError: If stop_event is set during processing
    """
    # Merge config with defaults
    effective_config = {**DEFAULT_CONFIG, **config}

    # Validate critical config values (L1 fix)
    cell_size = effective_config["pin_cluster_cell_size_px"]
    if cell_size <= 0:
        raise ValueError(f"pin_cluster_cell_size_px must be positive, got {cell_size}")

    # 1. Build pinlist indexes
    parents_by_label, labels_by_parent = build_pinlist_indexes(normalized_pinlist)
    _logger.debug(f"Built pinlist indexes: {len(parents_by_label)} labels, {len(labels_by_parent)} parents")

    # 2. Build spatial indexes for O(1) lookups
    spatial_indexes = build_spatial_indexes(page_words, cell_size, is_refdes_fn)
    page_refdes_set = spatial_indexes["refdes_set"]
    _logger.debug(f"Found {len(page_refdes_set)} RefDes tokens on page")

    # Get allowlist for checking IC/connector RefDes in groups (M3 fix)
    allowlist = set(effective_config.get("pin_parent_prefix_allowlist", DEFAULT_PIN_PARENT_PREFIX_ALLOWLIST))
    allowlist_upper = {p.upper() for p in allowlist}

    # 3. Process EACH GROUP independently (C3 fix: per-group clustering)
    results: Dict[str, List[PinToken]] = {}

    for group_name, entries in group_entries.items():
        # B1 fix: Check for cancellation at start of each group
        _check_stop(stop_event)

        # 3a. Collect pin candidates from THIS group only
        group_tokens: List[PinToken] = []
        group_has_ic_refdes = False  # M3 fix: track if group has IC/connector RefDes

        for entry in entries:
            text = entry.get("text", "")
            if not text:
                continue

            # Check if this is an IC/connector RefDes (M3 fix)
            if is_refdes_fn(text):
                prefix = get_prefix(text)
                if prefix and prefix.upper() in allowlist_upper:
                    group_has_ic_refdes = True
                continue

            # Only include pin candidates
            if not is_pin_candidate_fn(text):
                continue

            # Normalize text to uppercase for consistent matching (M4 fix)
            normalized_text = text.upper()

            group_tokens.append(PinToken(
                text=normalized_text,
                center=entry.get("center", (0, 0)),
                rect=entry.get("rect", (0, 0, 0, 0)),
                group_name=group_name,
            ))

        if not group_tokens:
            _logger.debug(f"Group '{group_name}': No pin candidates found")
            continue

        _logger.debug(f"Group '{group_name}': Collected {len(group_tokens)} pin candidates, has_ic_refdes={group_has_ic_refdes}")

        # 3b. Cluster THIS group's tokens only (C3 fix)
        group_clusters = cluster_pin_tokens(group_tokens, effective_config)

        # 3c. Compute nearby RefDes for this group (CRITICAL FIX for cross-contamination)
        # This ensures parent resolution only considers RefDes that are spatially near this group,
        # preventing J1 from being assigned as parent for a distant capacitor group.
        group_bbox = compute_group_bbox(entries)
        parent_radius = effective_config.get("parent_refdes_max_radius", 300.0)
        refdes_grid = spatial_indexes.get("refdes_grid", {})
        nearby_refdes = find_refdes_near_bbox(group_bbox, refdes_grid, cell_size, parent_radius)
        _logger.debug(f"Group '{group_name}': Found {len(nearby_refdes)} nearby RefDes within {parent_radius}px")

        # 3d. Classify each cluster, passing group_has_ic_refdes for M3 fix
        for cluster in group_clusters:
            cluster.cluster_type = classify_cluster(
                cluster, spatial_indexes, effective_config, group_has_ic_refdes
            )

        # 3e/3f/3g. Process each cluster
        for cluster in group_clusters:
            if cluster.cluster_type == "passive_like":
                # Mark all tokens as suppressed
                for token in cluster.tokens:
                    token.suppressed = True
                _logger.debug(f"Group '{group_name}': Suppressed cluster {cluster.cluster_id} ({len(cluster.tokens)} tokens)")
                continue

            # Resolve parent for non-passive clusters, using ONLY nearby RefDes
            parent, hits, status = resolve_cluster_parent(
                cluster, parents_by_label, page_refdes_set, effective_config,
                nearby_refdes=nearby_refdes  # CRITICAL: Filter to nearby candidates only
            )
            cluster.parent_refdes = parent
            cluster.hit_count = hits
            cluster.confidence = status

            # Apply acceptance thresholds
            accept, drop_reason = should_accept_cluster(cluster, effective_config)
            if not accept:
                for token in cluster.tokens:
                    token.drop_reason = drop_reason
                _logger.debug(f"Group '{group_name}': Dropped cluster {cluster.cluster_id}: {drop_reason}")
            else:
                for token in cluster.tokens:
                    token.parent_refdes = parent

        # Store results for this group
        results[group_name] = group_tokens

    return results
