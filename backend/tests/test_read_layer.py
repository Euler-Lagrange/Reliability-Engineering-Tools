"""Read-layer parity tests (Tier-1 fixes #10 and #11).

#10: literal 'NA' / 'N/A' text must NOT be coerced to NaN when read from .xlsx
     (it already isn't for .csv), while genuinely-empty cells still read as NaN.
#11: duplicate header names must be deduped with pandas' '.1' suffix scheme so
     the inspect dropdown matches the column names the runtime binds against.
"""
from __future__ import annotations

import openpyxl
import pandas as pd
import pytest

from common.utils import try_read_table
from sidecar_main import _finalize_headers


@pytest.fixture
def na_workbook(tmp_path):
    p = tmp_path / "na.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["RefDes", "Note"])
    ws.append(["U1", None])      # truly empty
    ws.append(["U2", "NA"])
    ws.append(["U3", "N/A"])
    ws.append(["U4", "normal"])
    wb.save(p)
    return str(p)


def test_excel_preserves_na_literal_text_but_keeps_empty_nan(na_workbook):
    """'NA'/'N/A' survive as text; the genuinely-empty cell still reads NaN."""
    df = try_read_table(na_workbook)
    notes = list(df["Note"])
    assert pd.isna(notes[0])      # empty cell stays NaN (behavior preserved)
    assert notes[1] == "NA"       # literal text preserved (was silently NaN before)
    assert notes[2] == "N/A"
    assert notes[3] == "normal"


def test_csv_and_excel_agree_on_na_literal(tmp_path, na_workbook):
    """The same NA-literal data reads identically from .xlsx and .csv."""
    csv = tmp_path / "na.csv"
    csv.write_text("RefDes,Note\nU1,\nU2,NA\nU3,N/A\nU4,normal\n", encoding="utf-8")
    df_xlsx = try_read_table(na_workbook)
    df_csv = try_read_table(str(csv))
    assert list(df_xlsx["Note"])[1:] == ["NA", "N/A", "normal"]
    assert list(df_csv["Note"])[1:] == ["NA", "N/A", "normal"]


def test_finalize_headers_dedupes_like_pandas():
    """Duplicate headers get pandas' '.1'/'.2' suffixes; uniques are untouched."""
    assert _finalize_headers(["Part Number", "Part Number", "Desc"]) == [
        "Part Number", "Part Number.1", "Desc",
    ]
    assert _finalize_headers(["A", "A", "A"]) == ["A", "A.1", "A.2"]
    assert _finalize_headers(["RefDes", "Qty"]) == ["RefDes", "Qty"]


def test_finalize_headers_matches_pandas_runtime_frame(tmp_path):
    """The inspect dropdown names equal the column names the runtime binds."""
    p = tmp_path / "dup.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["RefDes", "Part Number", "Desc", "Part Number"])
    ws.append(["U1", "PN-A", "x", "PN-B"])
    wb.save(p)
    runtime_cols = list(try_read_table(str(p)).columns)
    inspect_cols = _finalize_headers(["RefDes", "Part Number", "Desc", "Part Number"])
    assert inspect_cols == runtime_cols


def test_finalize_headers_collision_with_preexisting_dotted_header():
    """A pre-existing 'Name.1' alongside duplicate 'Name's must still match
    pandas' mangle and produce NO duplicate names (QA collision case)."""
    assert _finalize_headers(["A", "A", "A", "B", "A.1"]) == ["A", "A.2", "A.3", "B", "A.1"]
    assert _finalize_headers(["Part", "Part", "Part.1"]) == ["Part", "Part.2", "Part.1"]
    out = _finalize_headers(["A", "A", "A", "B", "A.1"])
    assert len(out) == len(set(out))  # no duplicate names


def test_finalize_headers_matches_pandas_on_collision(tmp_path):
    """inspect names == runtime frame names even with a pre-existing dotted header."""
    p = tmp_path / "collide.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    headers = ["A", "A", "A", "B", "A.1"]
    ws.append(headers)
    ws.append(["x"] * len(headers))
    wb.save(p)
    runtime_cols = list(try_read_table(str(p)).columns)
    assert _finalize_headers(headers) == runtime_cols
