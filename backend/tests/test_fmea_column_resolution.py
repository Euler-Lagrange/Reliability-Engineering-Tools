"""Tests for the FMEA generator's own column matcher (``resolve_column``).

2026-07-20 field failure: a BOM headed "BAE PN" failed the run with
"Required column 'part_number' not found in BOM file" even though "PN" is a
registered part-number synonym. ``resolve_column``'s substring pass skipped
every synonym shorter than MIN_SUBSTRING_MATCH_LEN (4), so short synonyms
like "PN" / "P/N" only ever matched a header EXACTLY equal to them. These
pin the word-boundary matching that closes the gap (mirroring
``common.utils.detect_column``'s short-synonym semantics) without
reintroducing the false positives the length gate guards against
("Ref" inside "Reference Designator").
"""
import pandas as pd

from common.column_synonyms import get_synonyms
from fmea.fmea_generator_logic import resolve_column


def test_bae_pn_is_a_registered_part_number_synonym() -> None:
    """The field-failure header is now a first-class synonym (exact pass)."""
    assert "BAE PN" in get_synonyms("part_number")


def test_bae_pn_header_resolves() -> None:
    df = pd.DataFrame(columns=["RefDes", "BAE PN", "Description"])
    assert resolve_column(df, get_synonyms("part_number")) == "BAE PN"


def test_short_synonym_matches_on_word_boundary() -> None:
    """A header NOT in the synonym list still resolves when a short synonym
    ("PN") appears as its own word — the class of header the 4-char length
    gate used to reject wholesale."""
    df = pd.DataFrame(columns=["Customer PN"])
    assert resolve_column(df, get_synonyms("part_number")) == "Customer PN"


def test_short_synonym_with_slash_matches_on_word_boundary() -> None:
    df = pd.DataFrame(columns=["Mfr P/N"])
    assert resolve_column(df, get_synonyms("part_number")) == "Mfr P/N"


def test_short_synonym_requires_word_boundary() -> None:
    """"pn" embedded in a word ("PNP Driver") must NOT match — the boundary
    check replaces the length gate without opening the false-positive door."""
    df = pd.DataFrame(columns=["PNP Driver"])
    assert resolve_column(df, ["PN"]) is None


def test_ref_guard_preserved() -> None:
    """The original M16 case: a short "Ref" synonym must not fuzzy-match
    "Reference Designator" ("ref" is followed by a letter, no boundary)."""
    df = pd.DataFrame(columns=["Reference Designator"])
    assert resolve_column(df, ["Ref"]) is None


def test_exact_short_header_still_resolves() -> None:
    df = pd.DataFrame(columns=["PN"])
    assert resolve_column(df, get_synonyms("part_number")) == "PN"


def test_long_synonym_substring_behavior_unchanged() -> None:
    df = pd.DataFrame(columns=["Custom Part Number (Internal)"])
    assert resolve_column(df, get_synonyms("part_number")) == "Custom Part Number (Internal)"


# ---------------------------------------------------------------------------
# Part Number as a mappable row (2026-07-20). Part Number is one of only two
# hard-required BOM columns (it drives the HDA commodity join) but the
# mapping card never offered it — auto-detect was the only path. These pin
# the new frontend-canonical wiring.
# ---------------------------------------------------------------------------

def test_part_number_canonical_maps_to_bom_part_number() -> None:
    from fmea.runtime import FRONTEND_TO_BACKEND_MAPPING

    assert FRONTEND_TO_BACKEND_MAPPING["Part Number"] == ("BOM", "part_number")


def test_part_number_is_a_required_mapping_canonical() -> None:
    """Do-Not-Map on Part Number must block at validate time
    (invalid_do_not_map) in every workflow — all four consume a BOM."""
    from fmea.runtime import (
        REQUIRED_MAPPING_CANONICALS,
        _required_mapping_canonicals,
    )

    assert "Part Number" in REQUIRED_MAPPING_CANONICALS
    for workflow in (
        "piece_part_generate",
        "bom_only",
        "functional_to_piecepart",
        "fill_gaps",
    ):
        assert "Part Number" in _required_mapping_canonicals(workflow), workflow


def test_part_number_override_reaches_bom_map_columns_shape() -> None:
    from fmea.runtime import _build_column_overrides

    overrides = _build_column_overrides(
        [{"canonical": "Part Number", "mappedTo": "BAE PN", "status": "manual"}]
    )
    assert overrides["Part Number"] == "BAE PN"
    assert overrides["BOM"]["part_number"] == "BAE PN"


# ---------------------------------------------------------------------------
# Frontend synonym mirror lockstep (2026-07-20). The mapping card's automap
# reads frontend/src/features/fmea/columnSynonyms.ts — a mirrored subset of
# COLUMN_SYNONYMS (same two-definition pattern as DO_NOT_MAP_VALUE). This
# scan fails the moment either side drifts.
# ---------------------------------------------------------------------------

def test_frontend_synonym_mirror_matches_backend_lists() -> None:
    import json
    import re
    from pathlib import Path

    ts_path = (
        Path(__file__).resolve().parents[2]
        / "frontend" / "src" / "features" / "fmea" / "columnSynonyms.ts"
    )
    assert ts_path.exists(), "columnSynonyms.ts mirror is missing"
    text = ts_path.read_text(encoding="utf-8")

    # Parse `  key: ["A", "B", ...],` entries from the exported object.
    entries = re.findall(r"^\s{2}(\w+):\s*(\[[^\]]*\])", text, flags=re.M)
    assert entries, "no synonym entries parsed from columnSynonyms.ts"

    mirrored = {}
    for key, array_src in entries:
        # The TS arrays are JSON-compatible (double-quoted strings).
        mirrored[key] = json.loads(re.sub(r",\s*\]", "]", array_src))

    for key, ts_list in mirrored.items():
        assert ts_list == get_synonyms(key), (
            f"columnSynonyms.ts '{key}' drifted from "
            f"common/column_synonyms.py — update both together"
        )
