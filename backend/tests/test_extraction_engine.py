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

import threading

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


# ---------------------------------------------------------------------------
# Issue #6: geometry RefDes check must use the SAME prefix-allowlist matcher as
# the harvest engine, not the broad local ^[A-Z]{1,4}\d+[A-Z]?$ pattern.
# ---------------------------------------------------------------------------


def test_geometry_refdes_check_uses_prefix_allowlist() -> None:
    """``_match_refdes`` defers to the engine's prefix-allowlist REFDES_RE, so a
    prefix the harvest never validates is rejected even though the broad local
    pattern accepts it; genuine allowlisted RefDes still pass."""
    from refdes_extractor import refdes_extractor_logic as logic
    from refdes_extractor.geometry_analyzer import _match_refdes, REFDES_PATTERN

    # "ZZ" is not an IEEE-315 / default-config prefix. Sanity-guard the premise
    # so a stray user config that added it fails loudly rather than silently.
    bogus = "ZZ12"
    assert "ZZ" not in logic.CONFIG.ref_prefixes

    # The OLD broad geometry pattern DID accept the bogus token...
    assert REFDES_PATTERN.match(bogus)
    # ...but the aligned prefix-allowlist check rejects it, matching the engine.
    assert not _match_refdes(bogus)
    assert not logic.REFDES_RE.fullmatch(bogus)

    # Valid allowlisted RefDes still pass and agree with the engine's REFDES_RE.
    for good in ("U1", "R15", "J2A"):
        assert _match_refdes(good), good
        assert logic.REFDES_RE.fullmatch(good), good


def test_classify_tokens_rejects_non_allowlisted_refdes() -> None:
    """End-to-end through ``_classify_tokens``: with no bodies/wires the RefDes
    decision is driven purely by the prefix-allowlist check, so a bogus-prefix
    token is NOT classified REFDES while a genuine one is."""
    from refdes_extractor.geometry_analyzer import (
        _classify_tokens,
        Rect,
        Token,
        TokenType,
    )

    def _tok(text: str) -> Token:
        return Token(
            text=text,
            rect=Rect(0.0, 0.0, 5.0, 5.0),
            font_size=8.0,
            token_type=TokenType.JUNK,
            confidence=0.0,
        )

    valid = _tok("U1")
    bogus = _tok("ZZ12")
    # bodies=[] and wire_segments=[] disable the pin/net spatial branches.
    _classify_tokens([valid, bogus], [], [])

    assert valid.token_type == TokenType.REFDES
    assert bogus.token_type != TokenType.REFDES


# ---------------------------------------------------------------------------
# pin_assignment_threshold key mismatch: the typed config sets
# "pin_assignment_threshold", so the classifier must read that key (not the
# never-set legacy "pin_threshold") for a user-set value to actually apply.
# ---------------------------------------------------------------------------


def test_process_page_geometry_reads_pin_assignment_threshold() -> None:
    """``process_page_geometry`` honors the config's "pin_assignment_threshold"
    key; before the fix it read the never-set "pin_threshold" and always logged
    the 50.0 default."""
    from refdes_extractor.geometry_analyzer import (
        GeometryData,
        process_page_geometry,
    )

    logs: list[str] = []
    geometry = GeometryData(
        page_num=0, bodies=[], pins=[], tokens=[], wire_segments=[]
    )
    process_page_geometry(
        geometry,
        {"pin_assignment_threshold": 12.34},
        log_func=logs.append,
    )

    assert any("threshold=12.34px" in line for line in logs)
    assert not any("threshold=50.0px" in line for line in logs)


# ---------------------------------------------------------------------------
# Cap-hit visibility: when a hard cap truncates/drops data the truncation must
# be streamed to the run log (log_func), not just the rotating file log.
# ---------------------------------------------------------------------------


def test_deduplicate_bodies_streams_cap_warning(monkeypatch) -> None:
    """Hitting the MAX_UNIQUE_BODIES cap streams a WARNING via log_func so the
    dropped bodies are visible on the run log (cap value patched down for speed;
    the production cap is unchanged)."""
    from refdes_extractor import geometry_analyzer as ga

    monkeypatch.setattr(ga, "MAX_UNIQUE_BODIES", 3)

    # Five non-overlapping bodies (IoU 0) -> none are deduplicated, so the cap
    # of 3 must fire and truncate.
    bodies = [
        ga.ComponentBody(
            rect=ga.Rect(i * 100.0, 0.0, i * 100.0 + 20.0, 20.0),
            page_num=0,
            body_id=f"body_{i}",
            source="vector",
        )
        for i in range(5)
    ]

    logs: list[str] = []
    kept = ga._deduplicate_bodies(bodies, log_func=logs.append)

    assert len(kept) == 3
    assert any("WARNING" in line and "Body count limit" in line for line in logs)


# ---------------------------------------------------------------------------
# Harvest #2: a word-extraction timeout must SURFACE on the streamed run log,
# not vanish into the rotating file log — otherwise a whole page's RefDes + pins
# disappear silently and look like "genuinely no words". Both the legacy and
# NextGen harvests route page words through _get_words_with_timeout, so the
# surfacing lives there (mirroring the _report_pinlist_failure pattern).
# ---------------------------------------------------------------------------


def test_report_words_timeout_streams_to_run_log() -> None:
    """The ``_report_words_timeout`` helper (twin of ``_report_pinlist_failure``)
    logs the WARNING to the STREAMED run log with the 1-based page number."""
    from refdes_extractor.extraction_engine import _report_words_timeout

    lines: list[str] = []
    # page_num is 0-based; the surfaced message is 1-based (page 5).
    _report_words_timeout(4, 30.0, lines.append)

    assert any("WARNING" in line and "page 5" in line for line in lines)
    assert any("timed out" in line for line in lines)


def test_report_words_timeout_no_log_callback_is_safe() -> None:
    """With no streamed-log callback the helper must not raise (file log only)."""
    from refdes_extractor.extraction_engine import _report_words_timeout

    _report_words_timeout(0, 30.0, None)  # must not raise


def test_get_words_with_timeout_surfaces_warning() -> None:
    """End-to-end: a page whose ``get_text('words')`` blocks past the timeout
    returns ``[]`` AND emits the WARNING to the caller's ``log_func`` — proving
    the timeout is distinguishable from a genuinely empty page. A tiny timeout is
    used so the test does not wait the production 30s (which is unchanged)."""
    from refdes_extractor import extraction_engine as engine

    release = threading.Event()

    class _SlowPage:
        def get_text(self, _kind):
            # Block until released so join(timeout) trips the timeout branch,
            # then return so the daemon thread can be reaped in cleanup.
            release.wait(timeout=5.0)
            return []

    lines: list[str] = []
    try:
        words = engine._get_words_with_timeout(
            _SlowPage(), page_num=6, timeout=0.05, log_func=lines.append
        )
    finally:
        release.set()
        engine.cleanup_words_extraction_threads(timeout_per_thread=5.0)

    assert words == []  # timeout yields an empty word list
    assert any("WARNING" in line and "page 7" in line for line in lines)
    assert any("timed out" in line for line in lines)


def test_group_fallback_routes_all_word_reads_through_timeout_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from refdes_extractor import refdes_extractor_logic as logic

    class _Page:
        def get_text(self, _kind):
            raise AssertionError("group fallback must not call get_text directly")

    page = _Page()
    calls = []

    def timed_words(page_arg, *, page_num=0, log_func=None):
        calls.append((page_arg, page_num, log_func))
        if len(calls) == 1:
            return [(0, 0, 1, 1, "R1", 0, 0, 0)]
        return []

    logs: list[str] = []
    monkeypatch.setattr(logic._engine, "_get_words_with_timeout", timed_words)

    groups, used_fallback, provenance = logic.detect_groups_with_fallback(
        [page],
        [],
        log_func=logs.append,
    )

    assert groups == []
    assert used_fallback is False
    assert provenance == "text_layer"
    assert calls == [
        (page, 0, logs.append),
        (page, 0, logs.append),
    ]


# ---------------------------------------------------------------------------
# Blacklist matching: the header comment once claimed SUBSTRING matching, but
# both the code and the _is_blacklisted docstring use EXACT matching. Switching
# to substring would silently drop legitimate tokens (e.g. "GND1" via "GND"), so
# the comment was corrected to EXACT. This pins the exact-match behavior.
# ---------------------------------------------------------------------------


def test_is_blacklisted_uses_exact_match_not_substring() -> None:
    """``_is_blacklisted`` filters only on a full case-insensitive EXACT match,
    never a substring — so blacklist entries never bleed into longer tokens."""
    from refdes_extractor import refdes_extractor_logic as logic

    # Exact entries are filtered (case-insensitively).
    assert logic._is_blacklisted("GND")
    assert logic._is_blacklisted("gnd")
    assert logic._is_blacklisted("AGND")
    assert logic._is_blacklisted("VCC")
    assert logic._is_blacklisted("OUT")

    # Substring/superstring tokens are NOT filtered — the key exact-vs-substring
    # discriminator. Under substring matching every one of these would be dropped.
    assert not logic._is_blacklisted("GND1")
    assert not logic._is_blacklisted("XGND")
    assert not logic._is_blacklisted("VCCA")
    assert not logic._is_blacklisted("OUTPUT")

    # The dynamic voltage pattern still applies (independent of the exact list).
    assert logic._is_blacklisted("3.3V")
    assert logic._is_blacklisted("48V")

    # A genuine RefDes is never blacklisted.
    assert not logic._is_blacklisted("U1")
