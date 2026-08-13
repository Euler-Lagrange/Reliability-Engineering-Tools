"""Unit tests for bom_compare/unified_bom.py — the Unified BOM merge.

Spec: docs/superpowers/specs/2026-08-13-unified-bom-design.md
"""
from __future__ import annotations

import threading

import pandas as pd
import pytest

from bom_compare.unified_bom import (
    _plan_columns,
    _values_equal,
)


def test_plan_columns_union_order_and_tool_columns():
    old = pd.DataFrame(columns=["RefDes", "Sheet Number", "Commodity L1"])
    new = pd.DataFrame(columns=["RefDes", "Part Number"])
    cols, old_map, tool = _plan_columns(old, new, None)
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


def test_plan_columns_case_insensitive_identity():
    old = pd.DataFrame(columns=["REFDES", "part number"])
    new = pd.DataFrame(columns=["RefDes", "Part Number"])
    cols, old_map, _tool = _plan_columns(old, new, None)
    assert old_map == {"REFDES": "RefDes", "part number": "Part Number"}
    # Identity match must not duplicate the columns.
    assert cols[:2] == ["RefDes", "Part Number"]
    assert "REFDES" not in cols


def test_plan_columns_explicit_pairs_win():
    old = pd.DataFrame(columns=["Ref", "Desc"])
    new = pd.DataFrame(columns=["RefDes", "Part Description"])
    cols, old_map, _tool = _plan_columns(
        old, new, [("Ref", "RefDes"), ("Desc", "Part Description")]
    )
    assert old_map == {"Ref": "RefDes", "Desc": "Part Description"}
    assert cols[:2] == ["RefDes", "Part Description"]
    assert "Ref" not in cols and "Desc" not in cols


def test_plan_columns_tool_name_collision_guard():
    old = pd.DataFrame(columns=["RefDes"])
    new = pd.DataFrame(columns=["RefDes", "Status"])
    cols, _old_map, tool = _plan_columns(old, new, None)
    assert tool["status"] == "Merge Status"
    assert cols.count("Status") == 1
    assert cols.count("Merge Status") == 1


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
    ],
)
def test_values_equal(a, b, equal):
    assert _values_equal(a, b) is equal
