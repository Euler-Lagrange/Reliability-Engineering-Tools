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
    ORPHAN_BOX_CONTAINS_BODY,
    ORPHAN_EXCLUDED,
    ORPHAN_PASSIVE_PREFIX,
    ORPHAN_PINLIST_DROP,
    ORPHAN_PINLIST_FILTERED,
    ORPHAN_SUPPRESSED_PASSIVE,
    _adopt_harvest_diagnostics,
    _fold_token_pages_into_diagnostics,
    _format_hybrid_results_nextgen,
    _is_token_bom_member,
    _normalize_bom_set,
    _record_orphan,
    _record_token_diag,
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


def test_diagnostics_recording_is_noop_without_accumulator() -> None:
    # Every capture site sits in the hot token loop — a None accumulator
    # (all legacy callers) must cost one truthiness check and mutate nothing.
    _record_token_diag(None, "U7-38", confidence=0.9)
    _record_orphan(None, page=1, group="G", pin_text="38", disposition=ORPHAN_EXCLUDED)
    _fold_token_pages_into_diagnostics({"G": {"token_pages": {"U7": {1}}}}, None)


def test_token_diag_accumulates_and_skips_none_fields() -> None:
    diag: dict = {}
    _record_token_diag(diag, "U7-38", confidence=0.82, source="geometry", candidates=None)
    _record_token_diag(diag, "U7-38", candidates=3)

    entry = diag["token_diagnostics"]["U7-38"]
    assert entry["confidence"] == 0.82
    assert entry["source"] == "geometry"
    assert entry["candidates"] == 3
    # None fields never erase earlier data.
    _record_token_diag(diag, "U7-38", confidence=None)
    assert diag["token_diagnostics"]["U7-38"]["confidence"] == 0.82


def test_orphan_records_carry_the_pinned_disposition_vocabulary() -> None:
    # The dispositions are user-facing sheet content (Orphan Pins report);
    # pin the literals so engine edits can't silently rename them.
    assert ORPHAN_SUPPRESSED_PASSIVE == "suppressed-passive"
    assert ORPHAN_PINLIST_DROP == "pinlist-drop"
    assert ORPHAN_PINLIST_FILTERED == "pinlist-filtered"
    assert ORPHAN_EXCLUDED == "excluded"
    assert ORPHAN_PASSIVE_PREFIX == "passive-prefix"
    assert ORPHAN_BOX_CONTAINS_BODY == "box-contains-body"

    diag: dict = {}
    _record_orphan(
        diag, page=7, group="DIG-076", pin_text="38",
        disposition=ORPHAN_EXCLUDED, detail="No qualified pinlist cluster matched this pin.",
    )
    assert diag["orphan_pins"] == [
        {
            "page": 7,
            "group": "DIG-076",
            "pin_text": "38",
            "disposition": "excluded",
            "detail": "No qualified pinlist cluster matched this pin.",
        }
    ]


def test_token_pages_fold_covers_every_token_and_strips_mode_suffix() -> None:
    grouped_data = {
        "DIG-076-PN": {"token_pages": {"U7-38": {4, 9}}},
        "CPU-001-FN": {"token_pages": {"R1": {2}}},
    }
    diag: dict = {}
    _fold_token_pages_into_diagnostics(grouped_data, diag)

    u7 = diag["token_diagnostics"]["U7-38"]
    assert u7["group"] == "DIG-076"
    assert u7["pages"] == [4, 9]
    r1 = diag["token_diagnostics"]["R1"]
    assert r1["group"] == "CPU-001"
    assert r1["pages"] == [2]


def test_token_pages_fold_lists_every_group_for_cross_group_duplicates() -> None:
    # A token extracted into two groups (the flagged cross-group duplicate)
    # must list BOTH groups — not let the last iterated group silently win.
    grouped_data = {
        "DIG-076-PN": {"token_pages": {"U9": {3}}},
        "DIG-081-PN": {"token_pages": {"U9": {7}}},
    }
    diag: dict = {}
    _fold_token_pages_into_diagnostics(grouped_data, diag)

    entry = diag["token_diagnostics"]["U9"]
    assert entry["group"] == "DIG-076, DIG-081"
    assert entry["pages"] == [3, 7]


def test_adopting_a_harvest_pass_replaces_rather_than_merges() -> None:
    # The adaptive path harvests more than once (phase-1 metrics pass, then
    # the final geometry pass). Each adoption must REPLACE the accumulator —
    # merging across passes double-records orphan pins and inflates the
    # "pins dropped" note (shipped as an adversarial-review finding).
    acc: dict = {}
    phase1 = {
        "orphan_pins": [{"page": 1, "pin_text": "38"}],
        "token_diagnostics": {"U7": {"pages": [1]}},
    }
    _adopt_harvest_diagnostics(acc, phase1)
    final = {
        "orphan_pins": [{"page": 1, "pin_text": "38"}],
        "token_diagnostics": {"U7": {"pages": [1], "confidence": 0.9}},
    }
    _adopt_harvest_diagnostics(acc, final)

    assert len(acc["orphan_pins"]) == 1  # not 2
    assert acc["token_diagnostics"] == final["token_diagnostics"]

    # None accumulator is a no-op; a None local clears the accumulator.
    _adopt_harvest_diagnostics(None, final)
    _adopt_harvest_diagnostics(acc, None)
    assert acc == {}


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


def test_checkpoint_write_failure_does_not_crash(tmp_path) -> None:
    """Batch 5 follow-up: the checkpoint writer sits on the extraction hot
    path — a write failure (permissions, disk full, bad path) must degrade
    to a logged warning, never crash the run."""
    from pathlib import Path

    from refdes_extractor.runtime import RefDesConfig
    from refdes_test.nextgen_engine import _save_geometry_batch_checkpoint

    # Point out_folder at a FILE so the checkpoint mkdir fails.
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("occupied")

    config = RefDesConfig(geometry_batch_checkpoint_enabled=True).to_config_manager(
        out_folder=str(blocker)
    )
    # Must not raise.
    _save_geometry_batch_checkpoint(
        config, Path("schematic.pdf"), 0, [1, 2], 5, 4, set()
    )


def test_geometry_checkpoints_are_opt_in() -> None:
    """Checkpoints write JSON artifacts into the user's chosen output
    folder — that must be an explicit opt-in, not a default side effect."""
    from refdes_extractor.runtime import RefDesConfig

    assert RefDesConfig().geometry_batch_checkpoint_enabled is False
