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
from bom_compare.bom_compare_logic import ColumnMapping, AnalyzeOptions, compare_two_boms
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


# ---------------------------------------------------------------------------
# Phase 1 regression: the group default run is byte-stable with loose OFF.
#
# The frontend "base match" checkbox now defaults to FALSE and maps to
# loose_base_match. A default run (loose off) must NOT fuzzy-prefix-match
# bases: a grouping base 'U20' is NOT covered by a BOM base 'U200'.
# ---------------------------------------------------------------------------

def test_analyze_default_loose_off_no_prefix_match() -> None:
    """Default (loose_base_match=False): a prefix-only base is NOT covered.

    Grouping has U20; BOM has U200. With loose OFF these are distinct bases,
    so U20 is missing-in-BOM and U200 is extra. This pins the behavior a
    default desktop run must preserve (loose matching is opt-in).
    """
    results = _run_analyze(["U20"], ["U200"])

    assert set(results.missing_in_bom["Token"]) == {"U20"}
    assert set(results.bom_not_in_groups["Base"]) == {"U200"}


def test_analyze_loose_on_prefix_base_is_covered() -> None:
    """loose_base_match=True: a BOM base that starts with the grouping base
    (and whose remainder is not all digits) covers it.

    Grouping base 'U20A' is covered by BOM base 'U20AB' (remainder 'B' is not
    all-digits), so nothing is missing and nothing is extra.
    """
    group_df = pd.DataFrame({"Group": ["G0"], "RefDes": ["U20A"]})
    bom_df = pd.DataFrame({"RefDes": ["U20AB"], "Description": [""]})
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
        loose_base_match=True,
    )
    results = analyze(
        group_df, bom_df, mapping, options,
        file_paths=("grouping.xlsx", "bom.xlsx"),
    )

    assert results.missing_in_bom.empty
    assert results.bom_not_in_groups.empty


# ---------------------------------------------------------------------------
# Phase 2: custom (BOM-vs-BOM) compare must honor exact_match, ignore_dnp,
# loose_base_match, and check_fmr with the SAME user-facing semantics as the
# group path.
# ---------------------------------------------------------------------------

def _custom_df(rows):
    return pd.DataFrame(rows)


def test_custom_base_match_default_reduces_pins_to_base() -> None:
    """Default custom compare (exact_match=False) reduces tokens to base
    RefDes, mirroring the group path. 'U200-1' (pin 1) in File 1 matches
    'U200' in File 2: nothing only-in-A, nothing only-in-B.
    """
    bom_a = _custom_df([{"RefDes": "U200-1"}])
    bom_b = _custom_df([{"RefDes": "U200"}])

    result = compare_two_boms(
        bom_a, bom_b, refdes_col_a="RefDes", refdes_col_b="RefDes",
        check_part_usage=False,
    )

    assert result.only_in_a == []
    assert result.only_in_b == []
    assert result.in_both_count == 1


def test_custom_exact_match_keeps_full_token() -> None:
    """exact_match=True compares full canonical tokens: 'U200-1' does NOT
    match 'U200', so each side reports a unique entry.
    """
    bom_a = _custom_df([{"RefDes": "U200-1"}])
    bom_b = _custom_df([{"RefDes": "U200"}])

    result = compare_two_boms(
        bom_a, bom_b, refdes_col_a="RefDes", refdes_col_b="RefDes",
        exact_match=True,
        check_part_usage=False,
    )

    assert [r["RefDes"] for r in result.only_in_a] == ["U200-1"]
    assert [r["RefDes"] for r in result.only_in_b] == ["U200"]
    assert result.in_both_count == 0


def test_custom_ignore_dnp_skips_dnp_rows() -> None:
    """ignore_dnp=True drops rows whose RefDes/Description marks them DNP.

    File 1 lists C1 (live) and C2 (marked DNP in its description). With DNP
    filtering on, C2 is removed before comparison, so File 2 (only C1) has
    nothing extra and File 1 has nothing only-in-A.
    """
    bom_a = _custom_df([
        {"RefDes": "C1", "Description": "Cap 10uF"},
        {"RefDes": "C2", "Description": "Cap DNP"},
    ])
    bom_b = _custom_df([{"RefDes": "C1", "Description": "Cap 10uF"}])

    result = compare_two_boms(
        bom_a, bom_b, refdes_col_a="RefDes", refdes_col_b="RefDes",
        ignore_dnp=True, desc_col_a="Description", desc_col_b="Description",
        check_part_usage=False,
    )

    assert result.only_in_a == []
    assert result.only_in_b == []
    assert result.in_both_count == 1


def test_custom_ignore_dnp_false_keeps_dnp_rows() -> None:
    """ignore_dnp=False keeps the DNP-marked row, so C2 is reported only-in-A."""
    bom_a = _custom_df([
        {"RefDes": "C1", "Description": "Cap 10uF"},
        {"RefDes": "C2", "Description": "Cap DNP"},
    ])
    bom_b = _custom_df([{"RefDes": "C1", "Description": "Cap 10uF"}])

    result = compare_two_boms(
        bom_a, bom_b, refdes_col_a="RefDes", refdes_col_b="RefDes",
        ignore_dnp=False, desc_col_a="Description", desc_col_b="Description",
        check_part_usage=False,
    )

    assert [r["RefDes"] for r in result.only_in_a] == ["C2"]


def test_custom_loose_base_match_prefix_covered() -> None:
    """loose_base_match=True suppresses an only-in-A base whose prefix matches
    an only-in-B base (and vice-versa), mirroring the group path.
    """
    bom_a = _custom_df([{"RefDes": "U20A"}])
    bom_b = _custom_df([{"RefDes": "U20AB"}])

    result = compare_two_boms(
        bom_a, bom_b, refdes_col_a="RefDes", refdes_col_b="RefDes",
        loose_base_match=True,
        check_part_usage=False,
    )

    assert result.only_in_a == []
    assert result.only_in_b == []


def test_custom_check_fmr_flags_bad_sum() -> None:
    """check_fmr=True validates per-RefDes FMR sums on each file. A RefDes
    whose failure-mode ratios do not sum to 1.0 is reported in fmr_warnings.
    """
    bom_a = _custom_df([
        {"RefDes": "U1", "Ratio": 0.5},
        {"RefDes": "U1", "Ratio": 0.2},  # sums to 0.7 -> bad
        {"RefDes": "U2", "Ratio": 1.0},  # ok
    ])
    bom_b = _custom_df([{"RefDes": "U1", "Ratio": 1.0}, {"RefDes": "U2", "Ratio": 1.0}])

    result = compare_two_boms(
        bom_a, bom_b, refdes_col_a="RefDes", refdes_col_b="RefDes",
        check_fmr=True,
        check_part_usage=False,
    )

    bad = {w["RefDes"] for w in result.fmr_warnings}
    assert "U1" in bad
    assert "U2" not in bad


def test_custom_check_fmr_off_by_default() -> None:
    """When check_fmr is not requested, fmr_warnings stays empty even if a
    Ratio column exists with non-summing ratios.
    """
    bom_a = _custom_df([{"RefDes": "U1", "Ratio": 0.5}])
    bom_b = _custom_df([{"RefDes": "U1", "Ratio": 0.5}])

    result = compare_two_boms(
        bom_a, bom_b, refdes_col_a="RefDes", refdes_col_b="RefDes",
        check_part_usage=False,
    )

    assert result.fmr_warnings == []
