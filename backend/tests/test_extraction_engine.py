"""Tests for the pin-disambiguation logic in the RefDes extraction engine.

``_disambiguate_pin_mapping`` decides which component owns a pin label when
two or more components on a page share that label. The selection follows a
strict three-tier priority:

  1. body CENTER inside the annotation group rect (strictest)
  2. body OVERLAPS the group rect
  3. nearest body by Euclidean distance to the pin token (fallback)

These tests construct competing :class:`PinMapping` candidates with bodies at
controlled positions and assert which candidate is chosen at each tier. Before
this fix the multi-candidate path was unreachable (an exact (page,label) dict
let the last-written mapping win), so this locks in the disambiguation.
"""

from __future__ import annotations

import pytest

fitz = pytest.importorskip("fitz")  # PyMuPDF — required for fitz.Rect bodies

from refdes_extractor.extraction_engine import (  # noqa: E402
    _disambiguate_pin_mapping,
    _rects_overlap,
)
from refdes_extractor.geometry_analyzer import PinMapping  # noqa: E402


def test_report_pinlist_failure_streams_to_run_log() -> None:
    # Tier-2 #20: a pinlist qualification failure empties the page's qualified
    # set. It must reach the STREAMED run log (not just the rotating file log),
    # with the page number and cause, so a silently-emptied page is visible.
    from refdes_extractor.extraction_engine import _report_pinlist_failure

    lines: list[str] = []
    _report_pinlist_failure(3, ValueError("bad cluster"), lines.append)

    assert any("WARNING" in line and "page 3" in line for line in lines)
    assert any("bad cluster" in line for line in lines)


def _mapping(refdes: str, pin_label: str = "P1") -> PinMapping:
    """Build a minimal PinMapping; only ``refdes`` drives body_rects lookup."""
    return PinMapping(
        pin_identifier=f"id_{refdes}",
        refdes=refdes,
        pin_label=pin_label,
        full_identifier=f"{refdes}-{pin_label}",
        confidence=1.0,
        page_num=0,
    )


# A square annotation group spanning (0,0)-(100,100). Center is (50,50).
GROUP_RECT = (0.0, 0.0, 100.0, 100.0)
PAGE_IDX = 0


def test_priority1_body_center_inside_group_wins() -> None:
    """The candidate whose body CENTER is inside group_rect is selected,
    even if a competitor's body is geometrically closer to the token."""
    cand_inside = _mapping("U1")
    cand_outside = _mapping("U2")
    candidates = [cand_outside, cand_inside]  # order: non-winner first

    body_rects = {
        # U2 body center at (250,250): OUTSIDE the group rect, and it sits
        # very close to the token to prove proximity does NOT override tier 1.
        (PAGE_IDX, "U2"): fitz.Rect(240, 240, 260, 260),
        # U1 body center at (50,50): INSIDE the group rect.
        (PAGE_IDX, "U1"): fitz.Rect(40, 40, 60, 60),
    }
    # Token placed right next to U2 to bias the distance fallback toward U2.
    token_center = (250.0, 250.0)

    chosen = _disambiguate_pin_mapping(
        candidates, GROUP_RECT, body_rects, PAGE_IDX, token_center
    )

    assert chosen is cand_inside
    assert chosen.refdes == "U1"


def test_priority2_overlap_only_wins_when_no_center_inside() -> None:
    """When no body center is inside, the candidate whose body OVERLAPS the
    group rect wins over one that neither contains-center nor overlaps."""
    cand_overlap = _mapping("U10")
    cand_far = _mapping("U20")
    candidates = [cand_far, cand_overlap]

    body_rects = {
        # U10 body (80..180 x 80..180): overlaps the (0..100) group rect, but its
        # CENTER (130,130) is OUTSIDE the group rect — so tier 1 (center-inside) is
        # skipped and tier 2 (overlap) is what selects U10.
        (PAGE_IDX, "U10"): fitz.Rect(80, 80, 180, 180),
        # U20 body far away: no overlap, no center-inside.
        (PAGE_IDX, "U20"): fitz.Rect(400, 400, 450, 450),
    }
    token_center = (420.0, 420.0)  # nearer to U20 to ensure tier-2 beats tier-3

    # Sanity: confirm our geometry actually exercises tier 2, not tier 1.
    u10_center = (130.0, 130.0)  # center of (80,80,180,180)
    assert not (
        GROUP_RECT[0] <= u10_center[0] <= GROUP_RECT[2]
        and GROUP_RECT[1] <= u10_center[1] <= GROUP_RECT[3]
    ), "U10 center must be OUTSIDE group_rect for this to test tier 2"
    assert _rects_overlap(GROUP_RECT, body_rects[(PAGE_IDX, "U10")])
    assert not _rects_overlap(GROUP_RECT, body_rects[(PAGE_IDX, "U20")])

    chosen = _disambiguate_pin_mapping(
        candidates, GROUP_RECT, body_rects, PAGE_IDX, token_center
    )

    assert chosen is cand_overlap
    assert chosen.refdes == "U10"


def test_priority3_nearest_body_by_distance_is_fallback() -> None:
    """When no body is inside or overlapping the group, the body whose center
    is closest to the token center is chosen."""
    cand_near = _mapping("U100")
    cand_far = _mapping("U200")
    candidates = [cand_far, cand_near]  # order: far first to prove it's not order

    body_rects = {
        # Both bodies are well away from the (0..100) group rect: no overlap.
        # U100 center (300,300); U200 center (900,900).
        (PAGE_IDX, "U100"): fitz.Rect(290, 290, 310, 310),
        (PAGE_IDX, "U200"): fitz.Rect(890, 890, 910, 910),
    }
    token_center = (320.0, 320.0)  # closest to U100's center (300,300)

    # Sanity: neither body overlaps the group rect (so we are in tier 3).
    assert not _rects_overlap(GROUP_RECT, body_rects[(PAGE_IDX, "U100")])
    assert not _rects_overlap(GROUP_RECT, body_rects[(PAGE_IDX, "U200")])

    chosen = _disambiguate_pin_mapping(
        candidates, GROUP_RECT, body_rects, PAGE_IDX, token_center
    )

    assert chosen is cand_near
    assert chosen.refdes == "U100"

    # And flipping the token to be nearest U200 flips the winner.
    chosen_far = _disambiguate_pin_mapping(
        candidates, GROUP_RECT, body_rects, PAGE_IDX, (880.0, 880.0)
    )
    assert chosen_far is cand_far
    assert chosen_far.refdes == "U200"


def test_single_candidate_returns_immediately() -> None:
    """A lone candidate is returned without consulting body_rects."""
    only = _mapping("U1")
    chosen = _disambiguate_pin_mapping(
        [only], GROUP_RECT, {}, PAGE_IDX, (0.0, 0.0)
    )
    assert chosen is only


def test_empty_candidates_returns_none() -> None:
    """No candidates -> None."""
    assert (
        _disambiguate_pin_mapping([], GROUP_RECT, {}, PAGE_IDX, (0.0, 0.0))
        is None
    )


def test_no_body_rects_returns_none_for_multiple_candidates() -> None:
    """With >1 candidate and no body geometry to break the tie, none of the
    three tiers can resolve a winner, so the function returns None."""
    candidates = [_mapping("U1"), _mapping("U2")]
    chosen = _disambiguate_pin_mapping(
        candidates, GROUP_RECT, {}, PAGE_IDX, (10.0, 10.0)
    )
    assert chosen is None
