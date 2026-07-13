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
    # Wave R6: kept-pin ambiguity flag; the runtime excludes this literal from
    # the dropped-pins note, so it is part of the pinned vocabulary.
    from refdes_test.nextgen_engine import ORPHAN_BOM_COLLISION

    assert ORPHAN_BOM_COLLISION == "bom-collision"

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


def test_bom_collision_flags_kept_pin_without_dropping() -> None:
    """Wave R6 (legacy '[?]' parity): a pin label that also names a real BOM
    RefDes is recorded as a kept-pin ambiguity flag + run-log WARNING; labels
    with no BOM twin record nothing."""
    from refdes_test.nextgen_engine import ORPHAN_BOM_COLLISION, _flag_bom_collision

    diag: dict = {}
    lines: list[str] = []
    bom = _normalize_bom_set({"U7"})

    _flag_bom_collision(diag, lines.append, 3, "DIG-076", "U7", bom)
    assert diag["orphan_pins"][0]["disposition"] == ORPHAN_BOM_COLLISION
    assert diag["orphan_pins"][0]["group"] == "DIG-076"
    assert "KEPT" in diag["orphan_pins"][0]["detail"]
    assert any("WARNING" in line and "U7" in line for line in lines)

    # Negative: an ordinary numeric pin label records nothing.
    _flag_bom_collision(diag, lines.append, 3, "DIG-076", "38", bom)
    assert len(diag["orphan_pins"]) == 1


def test_annotation_extraction_timeout_collects_pages_and_continues() -> None:
    """Wave R2: a page whose annots() call exceeds page_timeout is skipped
    with its 1-based page number reported through timed_out_pages, while
    other pages' annotations survive. The default timeout is 30s (the old
    hardcoded 10s was exceeded by real dense schematic sheets)."""
    import inspect
    import time

    from refdes_test.refdes_test_logic import extract_annotations_from_doc

    assert (
        inspect.signature(extract_annotations_from_doc)
        .parameters["page_timeout"]
        .default
        == 30.0
    )

    class _Rect:
        def normalize(self):
            return (0.0, 0.0, 10.0, 10.0)

    class _Ann:
        info = {"content": "DIG-001"}
        rect = _Rect()
        type = (2, "FreeText")

    class _OkPage:
        def annots(self):
            return [_Ann()]

    class _SlowPage:
        def annots(self):
            time.sleep(0.4)
            return [_Ann()]

    lines: list[str] = []
    timed_out: list[int] = []
    annotations = extract_annotations_from_doc(
        [_OkPage(), _SlowPage(), _OkPage()],
        log_func=lines.append,
        page_timeout=0.05,
        timed_out_pages=timed_out,
    )

    assert len(annotations) == 2
    assert timed_out == [2]
    assert any("timed out" in line and "Page 2" in line for line in lines)


def test_empty_contents_freetext_text_is_recovered_from_appearance(tmp_path) -> None:
    """Wave R3 (DIG-4xx trigger): a FreeText whose /Contents is empty while
    its visible text lives only in the appearance stream must have its text
    recovered from the page textpage clipped to the annotation rect — an
    empty-content group label previously vanished silently (no label, no
    group, no components, no log)."""
    import fitz

    from refdes_test.refdes_test_logic import extract_annotations_from_doc

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    ann = page.add_freetext_annot(fitz.Rect(50, 50, 200, 80), "DIG-418", fontsize=12)
    # Real-world trigger: some tools store FreeText only in the appearance
    # stream. Clearing /Contents at the xref level reproduces it exactly.
    doc.xref_set_key(ann.xref, "Contents", "()")
    pdf_path = tmp_path / "empty_contents.pdf"
    doc.save(str(pdf_path))
    doc.close()

    reopened = fitz.open(str(pdf_path))
    try:
        lines: list[str] = []
        annotations = extract_annotations_from_doc(reopened, log_func=lines.append)
    finally:
        reopened.close()

    freetexts = [a for a in annotations if a.get("type") == "FreeText"]
    assert freetexts, "fixture must produce a FreeText annotation"
    assert freetexts[0]["content"] == "DIG-418"
    assert any(
        "Recovered text for 1 annotation" in line and "page 1" in line
        for line in lines
    )


def _build_words_pdf(tmp_path, words):
    """Write a single-page PDF with plain text words at given baselines."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for text, x, y in words:
        page.insert_text((x, y), text, fontsize=10)
    pdf_path = tmp_path / "hybrid.pdf"
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_ungrouped_and_prov_refdes_outside_groups_survive_as_rows(tmp_path) -> None:
    """Wave R1 parity restore (DIG-4xx incident): a valid RefDes whose word
    center falls outside every detected group rect must land in the
    UNGROUPED (IN BOM) / UNGROUPED (NOT IN BOM) buckets (or PROVISIONAL when
    a PROV marker sits nearby) instead of vanishing without any row. Junk
    words outside groups must still be dropped."""
    pdf_path = _build_words_pdf(
        tmp_path,
        [
            ("R55", 100, 100),  # inside the DIG-001 group rect
            ("C77", 400, 400),  # outside all groups, present in BOM
            ("L42", 400, 430),  # outside all groups, absent from BOM
            ("PROV", 400, 500),  # provisional marker
            ("Q9", 400, 508),  # refdes adjacent to the PROV marker
            ("HELLO", 400, 560),  # junk word outside groups
        ],
    )

    rows = nextgen_engine.harvest_hybrid_nextgen(
        pdf_path=pdf_path,
        groups=[(0, "DIG-001", (50, 50, 250, 250))],
        bom_set={"R55", "C77"},
        bom_page_map=None,
        config={},
        group_modes={(0, "DIG-001"): "functional"},
        pin_map={},
        body_rects={},
    )

    by_group = {row["group"]: row for row in rows}
    assert by_group["DIG-001 (Verified)"]["failure mode causes"] == "R55"
    assert by_group["UNGROUPED (IN BOM)"]["failure mode causes"] == "C77"
    assert by_group["UNGROUPED (IN BOM)"]["pages"] == "1"
    assert by_group["UNGROUPED (NOT IN BOM)"]["failure mode causes"] == "L42"
    assert "Q9" in by_group["PROVISIONAL"]["failure mode causes"]
    # The prov-marked refdes must not double-report as ungrouped.
    assert "Q9" not in by_group.get("UNGROUPED (NOT IN BOM)", {}).get(
        "failure mode causes", ""
    )
    # Junk outside groups stays dropped — no bucket collects arbitrary words.
    assert "HELLO" not in " | ".join(str(row) for row in rows)
