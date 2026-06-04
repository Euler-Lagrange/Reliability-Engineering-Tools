"""Runtime-adapter-level regression tests for the BOM Compare sidecar tool.

These exercise ``bom_compare/runtime.py`` directly (in-process, via the
conftest sys.path shim) rather than through the subprocess sidecar, so they
can assert on the result-payload metrics that prove the DNP-regex default and
the Do-Not-Map sentinel guards behave correctly.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from bom_compare import runtime as bom_runtime
from shared.pre_run_validation import DO_NOT_MAP_SENTINEL


def _input_state(role: str, label: str, path: Path) -> dict:
    return {
        "role": role,
        "label": label,
        "path": str(path),
        "selectedSheet": "Sheet1",
        "source": "desktop-bridge",
        "isResolvingSheets": False,
        "isAnalyzing": False,
        "resolutionError": None,
        "sheets": [{"id": "s1", "label": "Sheet1"}],
    }


def _build_group_body(tmp_path: Path, *, options: dict | None = None) -> dict:
    """Group-vs-BOM body whose grouping RefDes EXACTLY match the BOM rows.

    None of the BOM descriptions contain a DNP token, so with a correct DNP
    regex every grouping RefDes is covered and nothing is reported missing.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    grouping_path = tmp_path / "grouping.xlsx"
    bom_path = tmp_path / "bom.xlsx"

    pd.DataFrame(
        [
            {"Component Group": "CPU-000", "Reference Designator": "R200, R201, R202"},
        ]
    ).to_excel(grouping_path, index=False)

    pd.DataFrame(
        [
            {"Reference Designator": "R200", "Part Number": "PN-001", "Description": "Resistor 10K"},
            {"Reference Designator": "R201", "Part Number": "PN-002", "Description": "Resistor 4.7K"},
            {"Reference Designator": "R202", "Part Number": "PN-003", "Description": "Resistor 1K"},
        ]
    ).to_excel(bom_path, index=False)

    return {
        "workflowId": "bom_compare_group",
        "outputStrategyId": "new_workbook_standard",
        "outputDirectory": str(tmp_path),
        "inputs": [
            _input_state("grouping", "Grouping workbook", grouping_path),
            _input_state("bom", "BOM workbook", bom_path),
        ],
        "mappings": [
            {"canonical": "grouping_group_col", "mappedTo": "Component Group", "status": "mapped"},
            {"canonical": "grouping_refdes_col", "mappedTo": "Reference Designator", "status": "mapped"},
            {"canonical": "bom_refdes_col", "mappedTo": "Reference Designator", "status": "mapped"},
            {"canonical": "bom_desc_col", "mappedTo": "Description", "status": "mapped"},
        ],
        # The frontend seeds ignore_dnp=True and NEVER sends a dnp_regex key.
        "options": options if options is not None else {"ignore_dnp": True},
    }


# ---------------------------------------------------------------------------
# Bug 1: an omitted/empty dnp_regex must fall back to the canonical pattern
# instead of compiling '' (which matches every string and drops the whole BOM).
# ---------------------------------------------------------------------------

def test_group_compare_omitted_dnp_regex_does_not_drop_bom(tmp_path: Path) -> None:
    """With ignore_dnp=True and NO dnp_regex key, the matching BOM rows must
    NOT be reported missing. Before the fix, empty dnp_regex compiled to a
    match-everything pattern and explode_bom skipped every BOM row, so all
    three grouping RefDes were flagged 'missing in BOM'.
    """
    body = _build_group_body(tmp_path, options={"ignore_dnp": True})

    result = bom_runtime.execute_run_request(body)

    assert result["status"] == "success"
    # The three grouping RefDes (R200/R201/R202) are all present in the BOM.
    assert result["no_match_count"] == 0, (
        "Empty/omitted dnp_regex should not nuke the BOM as all-DNP; "
        f"got {result['no_match_count']} missing. Full summary: {result['summary']}"
    )


def test_group_compare_explicit_empty_dnp_regex_also_safe(tmp_path: Path) -> None:
    """Defense-in-depth: even an explicit empty-string dnp_regex must be
    treated as 'use the default', not 'match everything'.
    """
    body = _build_group_body(tmp_path, options={"ignore_dnp": True, "dnp_regex": ""})

    result = bom_runtime.execute_run_request(body)

    assert result["status"] == "success"
    assert result["no_match_count"] == 0


# ---------------------------------------------------------------------------
# Bug 2: a required mapping set to the Do-Not-Map sentinel must fail
# validate_run cleanly (not crash execute with ColumnMappingError).
# ---------------------------------------------------------------------------

def _group_body_with_sentinel(tmp_path: Path, canonical: str) -> dict:
    body = _build_group_body(tmp_path)
    for row in body["mappings"]:
        if row["canonical"] == canonical:
            row["mappedTo"] = DO_NOT_MAP_SENTINEL
    return body


def test_group_compare_required_mapping_sentinel_blocks_validation(tmp_path: Path) -> None:
    """A required group-compare mapping set to '__do_not_map__' must surface
    as a clean invalid_do_not_map validation failure.
    """
    body = _group_body_with_sentinel(tmp_path, "bom_refdes_col")

    result = bom_runtime.validate_run_request(body)

    assert result["ok"] is False
    assert result["reason_code"] == "invalid_do_not_map"


def _build_custom_body(tmp_path: Path) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    bom_a_path = tmp_path / "bom_a.xlsx"
    bom_b_path = tmp_path / "bom_b.xlsx"
    pd.DataFrame(
        [{"Reference Designator": "R1", "Part Number": "PN-001"}]
    ).to_excel(bom_a_path, index=False)
    pd.DataFrame(
        [{"Reference Designator": "R1", "Part Number": "PN-001"}]
    ).to_excel(bom_b_path, index=False)
    return {
        "workflowId": "bom_compare_custom",
        "outputStrategyId": "new_workbook_standard",
        "outputDirectory": str(tmp_path),
        "inputs": [
            _input_state("bomA", "File 1", bom_a_path),
            _input_state("bomB", "File 2", bom_b_path),
        ],
        "mappings": [
            {"canonical": "refdes_col_a", "mappedTo": "Reference Designator", "status": "mapped"},
            {"canonical": "refdes_col_b", "mappedTo": "Reference Designator", "status": "mapped"},
        ],
        "options": {"key_mode": "refdes_list"},
    }


def test_custom_compare_required_mapping_sentinel_blocks_validation(tmp_path: Path) -> None:
    """A required custom-compare mapping set to '__do_not_map__' must surface
    as a clean invalid_do_not_map validation failure.
    """
    body = _build_custom_body(tmp_path)
    for row in body["mappings"]:
        if row["canonical"] == "refdes_col_a":
            row["mappedTo"] = DO_NOT_MAP_SENTINEL

    result = bom_runtime.validate_run_request(body)

    assert result["ok"] is False
    assert result["reason_code"] == "invalid_do_not_map"
