"""Unit tests for bom_compare/unified_bom.py — the Unified BOM merge.

Spec: docs/superpowers/specs/2026-08-13-unified-bom-design.md
"""
from __future__ import annotations

import threading

import pandas as pd
import pytest

from bom_compare.unified_bom import (
    _cell_text,
    _is_blank,
    _is_suffix_of,
    _plan_columns,
    _row_tokens,
    _values_equal,
)


def test_plan_columns_union_order_and_tool_columns():
    old = pd.DataFrame(columns=["RefDes", "Sheet Number", "Commodity L1"])
    new = pd.DataFrame(columns=["RefDes", "Part Number"])
    cols, old_map, tool, notes = _plan_columns(old, new, None)
    # New file's columns first (original order), then old-only columns
    # (old-file order), then the three tool-authored columns.
    assert cols == [
        "RefDes", "Part Number", "Sheet Number", "Commodity L1",
        "Status", "Source", "Change Notes",
    ]
    assert old_map == {
        "RefDes": "RefDes",
        "Sheet Number": "Sheet Number",
        "Commodity L1": "Commodity L1",
    }
    assert tool == {"status": "Status", "source": "Source", "notes": "Change Notes"}
    assert notes == []


def test_plan_columns_case_insensitive_identity():
    old = pd.DataFrame(columns=["REFDES", "part number"])
    new = pd.DataFrame(columns=["RefDes", "Part Number"])
    cols, old_map, _tool, notes = _plan_columns(old, new, None)
    assert old_map == {"REFDES": "RefDes", "part number": "Part Number"}
    # Identity match must not duplicate the columns.
    assert cols[:2] == ["RefDes", "Part Number"]
    assert "REFDES" not in cols
    assert notes == []


def test_plan_columns_explicit_pairs_win():
    old = pd.DataFrame(columns=["Ref", "Desc"])
    new = pd.DataFrame(columns=["RefDes", "Part Description"])
    cols, old_map, _tool, notes = _plan_columns(
        old, new, [("Ref", "RefDes"), ("Desc", "Part Description")]
    )
    assert old_map == {"Ref": "RefDes", "Desc": "Part Description"}
    assert cols[:2] == ["RefDes", "Part Description"]
    assert "Ref" not in cols and "Desc" not in cols
    assert notes == []


def test_plan_columns_tool_name_collision_guard():
    old = pd.DataFrame(columns=["RefDes"])
    new = pd.DataFrame(columns=["RefDes", "Status"])
    cols, _old_map, tool, notes = _plan_columns(old, new, None)
    assert tool["status"] == "Merge Status"
    assert cols.count("Status") == 1
    assert cols.count("Merge Status") == 1
    assert notes == []


def test_plan_columns_collision_keeps_both_columns():
    old = pd.DataFrame(
        columns=["RefDes", "Part Number", "Part number", "Sheet Number"]
    )
    new = pd.DataFrame(columns=["RefDes", "Part Number"])
    cols, old_map, _tool, notes = _plan_columns(old, new, None)
    assert "Part Number" in cols
    assert "Part number (old)" in cols
    assert old_map["Part number"] == "Part number (old)"
    assert len(notes) == 1
    assert "Part number" in notes[0] and "Part Number" in notes[0]


def test_plan_columns_unresolved_pair_notes():
    old = pd.DataFrame(columns=["Ref"])
    new = pd.DataFrame(columns=["RefDes"])
    cols, old_map, _tool, notes = _plan_columns(old, new, [("Reff", "RefDes")])
    # Falls back to name matching: "Ref" doesn't fold-match "RefDes", so it
    # becomes its own old-only column.
    assert old_map == {"Ref": "Ref"}
    assert "Ref" in cols
    assert len(notes) == 1
    assert "was ignored" in notes[0]


def test_plan_columns_pairs_match_case_insensitively():
    old = pd.DataFrame(columns=["ref"])
    new = pd.DataFrame(columns=["RefDes"])
    cols, old_map, _tool, notes = _plan_columns(old, new, [("REF", "RefDes")])
    assert old_map == {"ref": "RefDes"}
    assert notes == []


def test_plan_columns_old_only_headers_are_trimmed():
    old = pd.DataFrame(columns=["  Sheet Number  "])
    new = pd.DataFrame(columns=["RefDes"])
    cols, old_map, _tool, _notes = _plan_columns(old, new, None)
    assert "Sheet Number" in cols
    assert old_map["  Sheet Number  "] == "Sheet Number"


def test_plan_columns_duplicate_pair_note():
    old = pd.DataFrame(columns=["Ref"])
    new = pd.DataFrame(columns=["RefDes", "Part Number"])
    cols, old_map, _tool, notes = _plan_columns(
        old, new, [("Ref", "RefDes"), ("Ref", "Part Number")]
    )
    # First pair wins; the second pair references an old column that's
    # already mapped, which is a truthfully different situation from an
    # unresolved pair.
    assert old_map == {"Ref": "RefDes"}
    assert len(notes) == 1
    assert "already mapped by an earlier pair" in notes[0]
    assert '"Ref"' in notes[0] and '"Part Number"' in notes[0]


def test_plan_columns_malformed_pair_note():
    old = pd.DataFrame(columns=["Ref"])
    new = pd.DataFrame(columns=["RefDes"])
    cols, old_map, _tool, notes = _plan_columns(old, new, [("Ref",)])
    assert len(notes) == 1
    assert notes[0] == "A malformed column pair entry was ignored"
    # The malformed pair doesn't block normal fold-identity fallback... but
    # "Ref" doesn't fold-match "RefDes" so it becomes its own old-only column.
    assert old_map == {"Ref": "Ref"}


def test_plan_columns_tool_collision_case_insensitive():
    old = pd.DataFrame(columns=["status"])
    new = pd.DataFrame(columns=["RefDes"])
    cols, _old_map, tool, _notes = _plan_columns(old, new, None)
    assert tool["status"] == "Merge Status"
    # The user's own "status" column must survive untouched in the union.
    assert "status" in cols
    assert "Status" not in cols


def test_plan_columns_readable_uniquification():
    old = pd.DataFrame(columns=["Qty", "QTY", "qty"])
    new = pd.DataFrame(columns=["Qty"])
    cols, old_map, _tool, _notes = _plan_columns(old, new, None)
    assert "QTY (old)" in cols
    assert "qty (old 2)" in cols
    # No triple-stacked "(old) (old) (old)" suffixes.
    assert not any("(old) (old)" in c for c in cols)
    assert old_map["QTY"] == "QTY (old)"
    assert old_map["qty"] == "qty (old 2)"


@pytest.mark.parametrize(
    ("a", "b", "equal"),
    [
        ("10", "10.0", True),
        (10, "10", True),
        ("RES 10K", "res 10k", True),
        ("  x ", "x", True),
        ("", None, True),
        (float("nan"), "", True),
        ("10", "10.5", False),
        ("A", "B", False),
        ("0123", "123", False),
        ("1e3", "1000", False),
        ("12345678901234567890", "12345678901234567891", False),
        ("1_000", "1000", False),
        ("+123", "123", True),
        ("10.50", "10.5", True),
        ("5", "5.00", True),
    ],
)
def test_values_equal(a, b, equal):
    assert _values_equal(a, b) is equal


def test_cell_text_handles_na_variants():
    assert _cell_text(pd.NA) == ""
    assert _cell_text(float("nan")) == ""
    assert _cell_text(None) == ""
    # A non-scalar cell must not crash pd.isna() and should str()-ify.
    assert _cell_text([1, 2, 3]) == "[1, 2, 3]"


def test_is_blank_basics():
    assert _is_blank("") is True
    assert _is_blank("  ") is True
    assert _is_blank(None) is True
    assert _is_blank(float("nan")) is True
    assert _is_blank("x") is False
    # 0 is a real value, not blank.
    assert _is_blank(0) is False


def test_row_tokens_variants():
    assert _row_tokens(pd.NA) == []
    assert _row_tokens(None) == []
    assert _row_tokens(float("nan")) == []
    assert _row_tokens("R1, R2") == ["R1", "R2"]
    assert _row_tokens("  r5 ") == ["R5"]


@pytest.mark.parametrize(
    ("token", "base", "expected"),
    [
        ("U2000-1", "U2000", True),
        ("U2000-D4", "U2000", True),
        ("J4-P1", "J4", True),
        ("J4-20", "J4", True),
        ("R1-R3", "R1", False),
        ("U1A", "U1", False),
        ("u2000-1", "U2000", True),
        ("u2000", "U2000", False),
        ("U2000", "U2000", False),
        ("", "U2000", False),
        ("J1-J5", "J1", False),
        ("P2-P4", "P2", False),
        ("CN1-CN3", "CN1", False),
        ("X1-X9", "X1", False),
    ],
)
def test_is_suffix_of_matrix(token, base, expected):
    assert _is_suffix_of(token, base) is expected
