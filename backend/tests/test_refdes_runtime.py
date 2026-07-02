"""Tests for RefDes Extractor runtime helpers (backend/python/refdes_extractor/runtime.py)."""

from __future__ import annotations

from refdes_extractor.runtime import _results_dataframe


def test_results_dataframe_drops_internal_gap_column() -> None:
    # #4: a gap row's internal "_is_gap" styling marker must not leak into the
    # user-facing "RefDes Extraction" sheet as a stray column.
    rows = [
        {"group": "U200", "failure mode causes": "Open", "component count": 3, "pages": "1"},
        {
            "group": "U201 (GROUP NOT DETECTED)",
            "failure mode causes": "",
            "component count": 0,
            "pages": "",
            "_is_gap": True,  # internal styling marker from detect_sequence_gaps
        },
    ]
    df = _results_dataframe(rows)
    assert "_is_gap" not in df.columns
    assert list(df.columns) == ["group", "failure mode causes", "component count", "pages"]
    assert len(df) == 2  # rows preserved; only the internal column dropped


def test_results_dataframe_without_internal_columns_is_unchanged() -> None:
    rows = [
        {"group": "U200", "failure mode causes": "Open", "component count": 3, "pages": "1"},
    ]
    df = _results_dataframe(rows)
    assert list(df.columns) == ["group", "failure mode causes", "component count", "pages"]
    assert len(df) == 1
