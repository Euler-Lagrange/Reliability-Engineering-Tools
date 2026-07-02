"""Tests for the RefDes BOM loader's optional component-metadata capture.

The BOM-coverage feature enriches "BOM not extracted" rows with the Part
Number and Description the BOM already carries. ``load_bom_data`` therefore
gains an opt-in ``include_component_metadata`` flag that builds a
``{base_refdes: {part_number, description}}`` map, keyed identically to the
RefDes set so coverage lookups line up. The flag defaults off so existing
callers see no behavior change.
"""

from __future__ import annotations

import pandas as pd

from refdes_extractor.bom_loader import load_bom_data


def _write_bom(path, frame: dict) -> None:
    pd.DataFrame(frame).to_excel(path, index=False)


def test_metadata_captures_part_number_and_description(tmp_path):
    bom = tmp_path / "bom.xlsx"
    _write_bom(
        bom,
        {
            "RefDes": ["R1", "C2"],
            "Part Number": ["PN-R1", "PN-C2"],
            "Description": ["RES 10K", "CAP 1uF"],
        },
    )
    result = load_bom_data(bom, include_component_metadata=True)

    assert result.refdes == {"R1", "C2"}
    assert result.meta["R1"] == {"part_number": "PN-R1", "description": "RES 10K"}
    assert result.meta["C2"]["description"] == "CAP 1uF"


def test_metadata_keys_match_normalized_refdes(tmp_path):
    # Instance suffixes are stripped for the RefDes set; the meta map must use
    # the same key so coverage enrichment can find it.
    bom = tmp_path / "bom.xlsx"
    _write_bom(
        bom,
        {"RefDes": ["U200A"], "Part Number": ["PN-U200"], "Description": ["MCU"]},
    )
    result = load_bom_data(bom, include_component_metadata=True)

    assert "U200" in result.refdes
    assert result.meta["U200"]["part_number"] == "PN-U200"


def test_metadata_blank_when_columns_absent(tmp_path):
    bom = tmp_path / "bom.xlsx"
    _write_bom(bom, {"RefDes": ["R1"]})
    result = load_bom_data(bom, include_component_metadata=True)

    assert result.refdes == {"R1"}
    assert result.meta.get("R1", {}).get("part_number", "") == ""
    assert result.meta.get("R1", {}).get("description", "") == ""


def test_description_prefers_description_over_name_column(tmp_path):
    # 'Name' is a description synonym but is too generic (net/component names);
    # an explicit 'Description' column must win when both are present.
    bom = tmp_path / "bom.xlsx"
    _write_bom(
        bom,
        {"RefDes": ["R1"], "Name": ["NET_VCC"], "Description": ["RES 10K 1%"]},
    )
    result = load_bom_data(bom, include_component_metadata=True)

    assert result.meta["R1"]["description"] == "RES 10K 1%"


def test_pin_style_bom_row_counts_as_base_component(tmp_path):
    # Regression (U7-38): a piece-part BOM listing component-pin rows was
    # silently dropped by BASE-mode normalization ("U7-38" fails the RefDes
    # fullmatch), so neither "U7-38" nor "U7" reached the verification set
    # and every extracted pin of U7 landed in "(Unverified)". A pin-style
    # row is evidence its parent component exists.
    bom = tmp_path / "bom.xlsx"
    _write_bom(bom, {"RefDes": ["U7-38", "R1"]})
    result = load_bom_data(bom)

    assert "U7" in result.refdes
    assert "R1" in result.refdes
    # Garbage tokens must still be dropped (no partial-match laundering).
    assert "U7-38" not in result.refdes


def test_metadata_not_collected_by_default(tmp_path):
    bom = tmp_path / "bom.xlsx"
    _write_bom(bom, {"RefDes": ["R1"], "Description": ["RES"]})
    result = load_bom_data(bom)

    assert result.meta == {}
