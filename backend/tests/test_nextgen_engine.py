"""Tests for the default (NextGen) RefDes extraction engine.

The NextGen engine (``refdes_test/nextgen_engine.py``) is the default production
extraction path but historically had no unit tests. This file starts that
coverage, beginning with the Tier-2 #20 twin: a pinlist qualification failure
must reach the streamed run log, not just the rotating file log.
"""

from __future__ import annotations

import threading

import pytest

pytest.importorskip("fitz")  # PyMuPDF — nextgen_engine imports it at module load

from refdes_test import nextgen_engine  # noqa: E402
from refdes_test.nextgen_engine import (  # noqa: E402
    _format_hybrid_results_nextgen,
    _is_token_bom_member,
    _normalize_bom_set,
    _report_pinlist_failure,
)


def test_report_pinlist_failure_streams_to_run_log() -> None:
    # Tier-2 #20 (NextGen twin): the failure empties the page's qualified-pin
    # set, so it must be visible on the STREAMED run log with the page number
    # and cause — not silently buried in the rotating file log.
    lines: list[str] = []
    _report_pinlist_failure(7, ValueError("bad cluster"), lines.append)

    assert any("WARNING" in line and "page 7" in line for line in lines)
    assert any("bad cluster" in line for line in lines)


def test_pin_token_verifies_against_pin_level_bom_entry() -> None:
    # Regression (U7-38): verification reduced the token to its base ("U7")
    # while the normalized BOM set preserved pin-level strings ("U7-38"), so
    # a BOM that listed the pin itself could never verify it. Both shapes
    # must verify.
    assert _is_token_bom_member("U7-38", _normalize_bom_set({"U7"}))
    assert _is_token_bom_member("U7-38", _normalize_bom_set({"U7-38"}))
    assert not _is_token_bom_member("U7-38", _normalize_bom_set({"U9"}))


def test_pin_token_lands_in_verified_row_for_piece_part_group() -> None:
    # End-to-end formatting twin of the regression above: a piece-part group
    # whose token is U7-38 must land in the "(Verified)" row when the BOM
    # lists the pin-level entry.
    grouped_data = {
        "DIG-076-PN": {
            "mode": "piece_part",
            "tokens": {"U7-38"},
            "pages": {4},
            "token_pages": {"U7-38": {4}},
        }
    }
    rows = _format_hybrid_results_nextgen(grouped_data, {"U7-38"}, None)
    by_group = {row["group"]: row for row in rows}

    assert by_group["DIG-076 (Verified)"]["failure mode causes"] == "U7-38"
    assert by_group["DIG-076 (Verified)"]["component count"] == 1
    assert by_group["DIG-076 (Unverified)"]["component count"] == 0


def test_nextgen_word_timeout_surfaces_on_run_log() -> None:
    # Harvest #2 (NextGen path): the NextGen harvest extracts page words via
    # ``legacy_engine._get_words_with_timeout``. That must be the SAME shared
    # helper the legacy engine uses, and a timeout must surface on the streamed
    # run log so a silently-dropped page is visible (not mistaken for empty).
    from refdes_extractor import extraction_engine as engine

    # NextGen routes word extraction through the shared legacy helper.
    assert nextgen_engine.legacy_engine._get_words_with_timeout is (
        engine._get_words_with_timeout
    )

    release = threading.Event()

    class _SlowPage:
        def get_text(self, _kind):
            release.wait(timeout=5.0)
            return []

    lines: list[str] = []
    try:
        words = nextgen_engine.legacy_engine._get_words_with_timeout(
            _SlowPage(), page_num=2, timeout=0.05, log_func=lines.append
        )
    finally:
        release.set()
        engine.cleanup_words_extraction_threads(timeout_per_thread=5.0)

    assert words == []
    assert any("WARNING" in line and "page 3" in line for line in lines)
    assert any("timed out" in line for line in lines)
