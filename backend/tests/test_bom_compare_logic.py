"""Tests for BOM Compare core comparison logic.

Two concerns are covered:

1. RefDes range expansion (``expand_refdes_range`` / ``split_refdes_list``).
   By project convention hyphens denote PINS (U200-1), never ranges, so the
   group-vs-BOM ``analyze`` orchestrator intentionally does NOT expand ranges
   (see ``test_analyze_does_not_expand_ranges_by_default``). These tests pin the
   *opt-in* expansion helper directly: "R200-R205" -> R200..R205, while
   instance/pin notation (U3-7, J1-4) is preserved.

2. The ``analyze`` orchestrator's set math on a tiny discrete fixture:
   exact matches produce no missing/extra rows, a grouping-only RefDes shows
   up as "Missing in BOM", and a BOM-only RefDes shows up as "BOM Not in
   Groups".
"""

from __future__ import annotations

import pandas as pd

from common.refdes_utils import expand_refdes_range, split_refdes_list
from bom_compare.bom_compare_logic import ColumnMapping, AnalyzeOptions
from bom_compare.group_analysis import analyze


# ---------------------------------------------------------------------------
# RefDes range expansion (the opt-in helper)
# ---------------------------------------------------------------------------

def test_expand_refdes_range_expands_passive_range() -> None:
    """'R200-R205' expands to the six individual resistors (expand=True)."""
    assert expand_refdes_range("R200-R205", expand=True) == [
        "R200",
        "R201",
        "R202",
        "R203",
        "R204",
        "R205",
    ]


def test_expand_refdes_range_default_does_not_expand() -> None:
    """Default (expand=False) keeps the range token intact — canonicalized."""
    assert expand_refdes_range("R200-R205") == ["R200-R205"]
    assert expand_refdes_range("r200-r205") == ["R200-R205"]  # uppercased


def test_expand_refdes_range_preserves_instance_and_pin_notation() -> None:
    """Instance (U3-7) and connector-pin (J1-4) notation is NOT expanded."""
    assert expand_refdes_range("U3-7", expand=True) == ["U3-7"]
    assert expand_refdes_range("J1-4", expand=True) == ["J1-4"]


def test_expand_refdes_range_preserves_zero_padding() -> None:
    """Leading-zero width of the start token is preserved across the range."""
    assert expand_refdes_range("R08-R10", expand=True) == ["R08", "R09", "R10"]


def test_expand_refdes_range_reversed_bounds_not_expanded() -> None:
    """A descending range (R5-R1) is invalid and returned as-is."""
    assert expand_refdes_range("R5-R1", expand=True) == ["R5-R1"]


def test_split_refdes_list_expands_only_when_opted_in() -> None:
    """split_refdes_list passes through expand_ranges to per-token expansion."""
    # Default: range stays whole, comma still splits the list.
    assert split_refdes_list("R200-R205, C1") == ["R200-R205", "C1"]
    # Opt-in: the range explodes, the standalone token survives.
    assert split_refdes_list("R200-R205, C1", expand_ranges=True) == [
        "R200",
        "R201",
        "R202",
        "R203",
        "R204",
        "R205",
        "C1",
    ]


# ---------------------------------------------------------------------------
# analyze() orchestrator set math on a discrete fixture
# ---------------------------------------------------------------------------

def _run_analyze(grouping_refs, bom_refs):
    """Run analyze() with minimal grouping + BOM frames and no extra checks."""
    group_df = pd.DataFrame(
        {"Group": [f"G{i}" for i in range(len(grouping_refs))], "RefDes": grouping_refs}
    )
    bom_df = pd.DataFrame(
        {"RefDes": bom_refs, "Description": ["" for _ in bom_refs]}
    )
    mapping = ColumnMapping(
        grouping_group_col="Group",
        grouping_refdes_col="RefDes",
        bom_refdes_col="RefDes",
        bom_desc_col="Description",
    )
    options = AnalyzeOptions(
        run_warning_checks=False,
        run_duplicate_checks=False,
        check_part_usage=False,
        check_fmr=False,
    )
    return analyze(
        group_df,
        bom_df,
        mapping,
        options,
        file_paths=("grouping.xlsx", "bom.xlsx"),
    )


def test_analyze_exact_overlap_has_no_missing_or_extra() -> None:
    """Identical RefDes sets produce zero missing and zero extra rows."""
    results = _run_analyze(["R1", "R2", "C3"], ["R1", "R2", "C3"])

    assert results.missing_in_bom.empty
    assert results.bom_not_in_groups.empty


def test_analyze_flags_grouping_only_refdes_as_missing() -> None:
    """A RefDes present only in grouping is reported 'Missing in BOM'."""
    results = _run_analyze(["R1", "R2", "R3"], ["R1", "R2"])

    missing_tokens = set(results.missing_in_bom["Token"])
    assert missing_tokens == {"R3"}
    # And it is NOT in the extra list.
    assert results.bom_not_in_groups.empty


def test_analyze_flags_bom_only_refdes_as_extra() -> None:
    """A RefDes present only in the BOM is reported 'BOM Not in Groups'."""
    results = _run_analyze(["R1"], ["R1", "C9"])

    extra_bases = set(results.bom_not_in_groups["Base"])
    assert extra_bases == {"C9"}
    assert results.missing_in_bom.empty


def test_analyze_reports_both_directions_simultaneously() -> None:
    """Disjoint extras on each side are reported independently and correctly."""
    results = _run_analyze(["R1", "R2", "Q5"], ["R1", "R2", "U8"])

    assert set(results.missing_in_bom["Token"]) == {"Q5"}
    assert set(results.bom_not_in_groups["Base"]) == {"U8"}

    # Summary counters mirror the table sizes.
    summary = dict(zip(results.summary["Item"], results.summary["Value"]))
    assert summary["Missing in BOM"] == 1
    assert summary["BOM Not in Groups"] == 1


def test_analyze_does_not_expand_ranges_by_default() -> None:
    """INTENDED behavior: the group analyzer never range-expands hyphenated tokens.

    Per the project's RefDes convention, hyphens denote PINS (U200-1 = pin 1 of
    component U200), never numeric ranges — authors do not write 'R1-R3' to mean
    R1/R2/R3 (an 'R1-R3' token would be its own component). So ``analyze`` calls
    ``split_refdes_list`` WITHOUT ``expand_ranges`` and reduces each token to its
    base RefDes. This pins the no-expansion contract: a synthetic 'R1-R3' token
    reduces to base 'R1' and is NOT exploded into R1/R2/R3. Range expansion stays
    opt-in (and unused by this tool).
    """
    results = _run_analyze(["R1-R3"], ["R1", "R2", "R3"])

    # 'R1-R3' is treated as a single token (base 'R1'), not expanded.
    assert results.missing_in_bom.empty
    assert set(results.bom_not_in_groups["Base"]) == {"R2", "R3"}


def test_analyze_matches_hyphenated_pin_to_base_component() -> None:
    """A hyphenated PIN designator reduces to its base component for matching.

    Real-world case (hyphens are pins): a grouping cell 'U200-1' (pin 1 of U200)
    is treated as component U200, so it matches a BOM that lists 'U200'. No
    missing, no extra.
    """
    results = _run_analyze(["U200-1"], ["U200"])

    assert results.missing_in_bom.empty
    assert results.bom_not_in_groups.empty
