"""Phase D tests for the FMEA Generator backend.

Covers:
- BOM inheritance: pin/variant RefDes (e.g., U200-X) inherits from base U200
- BOM_Additions tracking: each inherited row recorded with usage_fraction = 1/N
- functional_to_piecepart workflow: detects circuit blocks in functional FMEA
  and inserts piece-part rows beneath each
- FMD-91 vs FMD-2016 standard selection: drives output column headers
- Validation: missing failureModesStandard rejected
- Cascade prevention: variant whose base is also missing falls through cleanly

These tests exercise the FMEAProcessor and runtime.validate_run_request directly
rather than spawning the sidecar subprocess, because they're focused unit tests
for the Phase D logic.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from common.exceptions import ValidationError
from fmea.fmea_generator_logic import FMEAProcessor, write_excel_report
from fmea.runtime import execute_run_request, validate_run_request


# ----- helpers ----------------------------------------------------------------


def _write_fixture(
    tmp_path: Path,
    *,
    bom_rows: list[dict],
    grouping_rows: list[dict] | None = None,
    fm_rows: list[dict] | None = None,
    functional_rows: list[dict] | None = None,
) -> dict:
    """Build standard test fixtures and return a dict of paths."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    bom_path = tmp_path / "bom.xlsx"
    pd.DataFrame(bom_rows).to_excel(bom_path, index=False)
    paths["bom"] = bom_path

    if grouping_rows is not None:
        grouping_path = tmp_path / "grouping.xlsx"
        pd.DataFrame(grouping_rows).to_excel(grouping_path, index=False)
        paths["grouping"] = grouping_path

    fm_path = tmp_path / "failure_modes.xlsx"
    pd.DataFrame(
        fm_rows
        or [
            {
                "FMD-2016 Commodity Type 1": "Microcircuit",
                "FMD-2016 Commodity Type 2": "Digital",
                "Failure Mode": "Stuck high",
                "Failure Mode Ratio": 0.5,
            },
            {
                "FMD-2016 Commodity Type 1": "Microcircuit",
                "FMD-2016 Commodity Type 2": "Digital",
                "Failure Mode": "Stuck low",
                "Failure Mode Ratio": 0.5,
            },
        ]
    ).to_excel(fm_path, index=False)
    paths["fm"] = fm_path

    if functional_rows is not None:
        func_path = tmp_path / "functional.xlsx"
        pd.DataFrame(functional_rows).to_excel(func_path, index=False)
        paths["func"] = func_path

    return paths


# ----- D2/D5/D10: Inheritance + BOM Additions sheet ---------------------------


def test_inheritance_creates_bom_addition(tmp_path: Path) -> None:
    """U200-A/B/C reference a base U200 that exists in BOM but the variants
    do not. Each variant should generate a piece-part row that inherits
    Part Number/Description/HDA/FMD from U200, and each should appear in
    proc.bom_additions with usage_fraction == "1/3".
    """
    paths = _write_fixture(
        tmp_path,
        bom_rows=[
            {
                "Reference Designator": "U200",
                "Part Number": "IC-1234",
                "Description": "Microcontroller",
                "BAE HDA Commodity I": "Microcircuit",
                "BAE HDA Commodity II": "Digital",
                "Part Usage": "1/3",
            }
        ],
        grouping_rows=[
            {
                "Component Group": "CPU-001",
                "Reference Designator": "U200-A, U200-B, U200-C",
                "Function Description": "Processor variants",
                "Schematic Page": "12",
            }
        ],
    )

    proc = FMEAProcessor()
    df = proc.process(
        {
            "group": str(paths["grouping"]),
            "bom": str(paths["bom"]),
            "fm": str(paths["fm"]),
            "hda": None,
            "func": None,
            "piecepart_fmea": None,
            "out_folder": str(tmp_path),
            "out_name": "out",
            "bom_only_mode": False,
            "use_func": False,
            "use_piecepart_merge": False,
            "verbose": False,
            "column_overrides": {},
            "template_preserve": False,
            "failure_modes_standard": "FMD-2016",
            "group_sheet": "Sheet1",
            "bom_sheet": "Sheet1",
            "hda_sheet": None,
            "fm_sheet": "Sheet1",
            "func_sheet": None,
            "piecepart_fmea_sheet": None,
        }
    )

    assert not df.empty
    pp_rows = df[df["_row_type"].isin(("piece_part", "validation_warning"))]
    refdes_seen = set(pp_rows["Failure Mode Causes"].dropna().tolist())
    assert refdes_seen == {"U200-A", "U200-B", "U200-C"}, refdes_seen

    # All three variants should inherit Part Number IC-1234 from U200
    inherited_pns = set(pp_rows["Component Part Number"].dropna().tolist())
    assert inherited_pns == {"IC-1234"}, inherited_pns

    # bom_additions captured all three variants with usage_fraction = 1/3
    assert len(proc.bom_additions) == 3
    assert {e["ref_des"] for e in proc.bom_additions} == {"U200-A", "U200-B", "U200-C"}
    assert {e["base_refdes"] for e in proc.bom_additions} == {"U200"}
    assert {e["usage_fraction"] for e in proc.bom_additions} == {"1/3"}
    assert {e["part_number"] for e in proc.bom_additions} == {"IC-1234"}
    assert all(e["source_workflow"] == "piece_part_generate" for e in proc.bom_additions)


def test_inheritance_writes_bom_additions_sheet(tmp_path: Path) -> None:
    """write_excel_report should emit a BOM_Additions sheet whenever
    proc.bom_additions is non-empty."""
    paths = _write_fixture(
        tmp_path,
        bom_rows=[
            {
                "Reference Designator": "U500",
                "Part Number": "PN-9999",
                "Description": "FPGA",
                "BAE HDA Commodity I": "Microcircuit",
                "BAE HDA Commodity II": "Digital",
                "Part Usage": "1/2",
            }
        ],
        grouping_rows=[
            {
                "Component Group": "FPGA-001",
                "Reference Designator": "U500-X, U500-Y",
                "Function Description": "FPGA pins",
                "Schematic Page": "5",
            }
        ],
    )

    proc = FMEAProcessor()
    df = proc.process(
        {
            "group": str(paths["grouping"]),
            "bom": str(paths["bom"]),
            "fm": str(paths["fm"]),
            "hda": None,
            "func": None,
            "piecepart_fmea": None,
            "out_folder": str(tmp_path),
            "out_name": "out",
            "bom_only_mode": False,
            "use_func": False,
            "use_piecepart_merge": False,
            "verbose": False,
            "column_overrides": {},
            "failure_modes_standard": "FMD-2016",
            "group_sheet": "Sheet1",
            "bom_sheet": "Sheet1",
            "hda_sheet": None,
            "fm_sheet": "Sheet1",
            "func_sheet": None,
            "piecepart_fmea_sheet": None,
        }
    )
    out_path = tmp_path / "report.xlsx"
    write_excel_report(df, out_path, proc)
    assert out_path.exists()

    from openpyxl import load_workbook

    wb = load_workbook(out_path)
    try:
        assert "BOM_Additions" in wb.sheetnames, wb.sheetnames
        sheet = wb["BOM_Additions"]
        # Phase D banner row at row 1 + header row at row 2 + 2 data rows = 4
        assert sheet.max_row >= 4
        # Row 1 is the explanatory banner (merged across the column range)
        banner = sheet.cell(row=1, column=1).value or ""
        assert "RefDes variants" in banner, f"Unexpected banner: {banner!r}"
        assert "inherited" in banner.lower()
        # Row 2 carries the actual column headers
        headers = [sheet.cell(row=2, column=col).value for col in range(1, sheet.max_column + 1)]
        assert "RefDes" in headers
        assert "Base RefDes" in headers
        assert "Usage" in headers
    finally:
        wb.close()


def test_variant_in_bom_does_not_trigger_inheritance(tmp_path: Path) -> None:
    """Phase D regression: when BOTH the variant RefDes AND its base are
    in the BOM, the exact match must win. The variant should get its own
    BOM row (not inherit from the base), and bom_additions must be empty.
    """
    paths = _write_fixture(
        tmp_path,
        bom_rows=[
            {
                "Reference Designator": "U200",
                "Part Number": "IC-BASE",
                "Description": "Base component",
                "BAE HDA Commodity I": "Microcircuit",
                "BAE HDA Commodity II": "Digital",
                "Part Usage": "1",
            },
            {
                "Reference Designator": "U200-X",
                "Part Number": "IC-VARIANT",
                "Description": "Variant component",
                "BAE HDA Commodity I": "Microcircuit",
                "BAE HDA Commodity II": "Digital",
                "Part Usage": "1",
            },
        ],
        grouping_rows=[
            {
                "Component Group": "G-001",
                "Reference Designator": "U200-X",
                "Function Description": "Variant use",
                "Schematic Page": "1",
            }
        ],
    )
    proc = FMEAProcessor()
    df = proc.process(
        {
            "group": str(paths["grouping"]),
            "bom": str(paths["bom"]),
            "fm": str(paths["fm"]),
            "hda": None,
            "func": None,
            "piecepart_fmea": None,
            "out_folder": str(tmp_path),
            "out_name": "out",
            "bom_only_mode": False,
            "use_func": False,
            "use_piecepart_merge": False,
            "verbose": False,
            "column_overrides": {},
            "failure_modes_standard": "FMD-2016",
            "group_sheet": "Sheet1",
            "bom_sheet": "Sheet1",
            "hda_sheet": None,
            "fm_sheet": "Sheet1",
            "func_sheet": None,
            "piecepart_fmea_sheet": None,
        }
    )
    # bom_additions must be empty — U200-X is a direct BOM row, no inheritance
    assert proc.bom_additions == [], proc.bom_additions
    # The generated piece-part row must carry IC-VARIANT (from the exact
    # match), NOT IC-BASE (which would indicate incorrect inheritance).
    pp = df[
        (df["Failure Mode Causes"] == "U200-X")
        & (df["_row_type"].isin(("piece_part", "validation_warning", "piece_part_no_match")))
    ]
    assert len(pp) >= 1, df
    part_numbers = set(pp["Component Part Number"].dropna().tolist())
    assert part_numbers == {"IC-VARIANT"}, (
        f"Expected IC-VARIANT, got {part_numbers}"
    )


def test_variant_base_also_missing_falls_through(tmp_path: Path) -> None:
    """When neither the variant nor its base is in the BOM, no inheritance
    occurs and no bom_additions entry is created."""
    paths = _write_fixture(
        tmp_path,
        bom_rows=[
            {
                "Reference Designator": "C100",
                "Part Number": "CAP-1",
                "Description": "Capacitor",
                "BAE HDA Commodity I": "Capacitor",
                "BAE HDA Commodity II": "Ceramic",
                "Part Usage": "1",
            }
        ],
        grouping_rows=[
            {
                "Component Group": "GAP-001",
                "Reference Designator": "U999-A",
                "Function Description": "Missing variant",
                "Schematic Page": "1",
            }
        ],
    )

    proc = FMEAProcessor()
    df = proc.process(
        {
            "group": str(paths["grouping"]),
            "bom": str(paths["bom"]),
            "fm": str(paths["fm"]),
            "hda": None,
            "func": None,
            "piecepart_fmea": None,
            "out_folder": str(tmp_path),
            "out_name": "out",
            "bom_only_mode": False,
            "use_func": False,
            "use_piecepart_merge": False,
            "verbose": False,
            "column_overrides": {},
            "failure_modes_standard": "FMD-2016",
            "group_sheet": "Sheet1",
            "bom_sheet": "Sheet1",
            "hda_sheet": None,
            "fm_sheet": "Sheet1",
            "func_sheet": None,
            "piecepart_fmea_sheet": None,
        }
    )

    assert proc.bom_additions == [], proc.bom_additions
    # The missing variant must end up in group_missing_in_bom
    assert any(ref == "U999-A" for _, ref in proc.group_missing_in_bom)


# ----- D4: FMD-91 vs FMD-2016 standard selection ------------------------------


def test_failure_modes_standard_drives_headers(tmp_path: Path) -> None:
    """Output column headers should match the chosen FMD standard."""
    paths = _write_fixture(
        tmp_path,
        bom_rows=[
            {
                "Reference Designator": "R100",
                "Part Number": "RES-1",
                "Description": "Resistor",
                "BAE HDA Commodity I": "Resistor",
                "BAE HDA Commodity II": "Chip",
                "Part Usage": "1",
            }
        ],
        grouping_rows=[
            {
                "Component Group": "RES-001",
                "Reference Designator": "R100",
                "Function Description": "Pull-up",
                "Schematic Page": "3",
            }
        ],
        fm_rows=[
            {
                "FMD-91 Commodity Type 1": "Resistor",
                "FMD-91 Commodity Type 2": "Chip",
                "Failure Mode": "Open",
                "Failure Mode Ratio": 1.0,
            }
        ],
    )

    proc = FMEAProcessor()
    df = proc.process(
        {
            "group": str(paths["grouping"]),
            "bom": str(paths["bom"]),
            "fm": str(paths["fm"]),
            "hda": None,
            "func": None,
            "piecepart_fmea": None,
            "out_folder": str(tmp_path),
            "out_name": "out",
            "bom_only_mode": False,
            "use_func": False,
            "use_piecepart_merge": False,
            "verbose": False,
            "column_overrides": {},
            "failure_modes_standard": "FMD-91",
            "group_sheet": "Sheet1",
            "bom_sheet": "Sheet1",
            "hda_sheet": None,
            "fm_sheet": "Sheet1",
            "func_sheet": None,
            "piecepart_fmea_sheet": None,
        }
    )
    assert "FMD-91 Commodity Type 1" in df.columns
    assert "FMD-91 Commodity Type 2" in df.columns
    assert "FMD-2016 Commodity Type 1" not in df.columns


def test_validate_run_accepts_fill_gaps_with_preserve_formatting(tmp_path: Path) -> None:
    """Phase E: validate_run_request should now accept fill_gaps with the
    preserve-formatting strategy. The legacy block that rejected it
    ("Existing workbook and preserve-formatting paths stay in analysis-only
    mode") was removed in Phase D."""
    paths = _write_fixture(
        tmp_path,
        bom_rows=[
            {
                "Reference Designator": "R100",
                "Part Number": "RES-1",
                "Description": "Resistor",
                "BAE HDA Commodity I": "Resistor",
                "BAE HDA Commodity II": "Chip",
                "Part Usage": "1",
            }
        ],
    )
    # Existing FMEA file (any valid xlsx works for validation level)
    existing_fmea = tmp_path / "existing.xlsx"
    pd.DataFrame([{"FMEA-ID": "X-001", "FMEA Level": "Piece Part"}]).to_excel(
        existing_fmea, index=False,
    )
    target = tmp_path / "target.xlsx"
    pd.DataFrame([{"FMEA-ID": "T-001", "FMEA Level": "Circuit Block"}]).to_excel(
        target, index=False,
    )

    def state(role: str, path: Path, sheet: str = "Sheet1") -> dict:
        return {
            "role": role,
            "label": role,
            "path": str(path),
            "selectedSheet": sheet,
            "source": "desktop-bridge",
            "isResolvingSheets": False,
            "isAnalyzing": False,
            "resolutionError": None,
            "sheets": [{"id": "s1", "label": sheet}],
        }

    body = {
        "workflowId": "fill_gaps",
        "outputStrategyId": "existing_workbook_preserve_formatting",
        "options": {
            "failureModesStandard": "FMD-2016",
            "columnSelection": {"mode": "all", "columns": []},
        },
        "inputs": [
            state("existingFmea", existing_fmea),
            state("bom", paths["bom"]),
            state("failureModes", paths["fm"]),
            state("targetWorkbook", target),
        ],
        "mappings": [],
    }
    result = validate_run_request(body)
    assert result["ok"] is True, result


def test_failure_modes_standard_required_in_validation() -> None:
    """validate_run_request should reject FMEA bodies without failureModesStandard."""
    body = {
        "workflowId": "piece_part_generate",
        "outputStrategyId": "new_workbook_standard",
        "inputs": [
            {
                "role": "grouping",
                "label": "Grouping",
                "path": "/tmp/g.xlsx",
                "selectedSheet": "Sheet1",
                "sheets": [{"id": "s1", "label": "Sheet1"}],
            },
            {
                "role": "bom",
                "label": "BOM",
                "path": "/tmp/b.xlsx",
                "selectedSheet": "Sheet1",
                "sheets": [{"id": "s1", "label": "Sheet1"}],
            },
            {
                "role": "failureModes",
                "label": "FM",
                "path": "/tmp/f.xlsx",
                "selectedSheet": "Sheet1",
                "sheets": [{"id": "s1", "label": "Sheet1"}],
            },
        ],
        "mappings": [],
        # Note: no "options" key, no failureModesStandard.
    }
    result = validate_run_request(body)
    assert result["ok"] is False
    assert result["reason_code"] == "missing_failure_modes_standard"


# ----- D7: functional_to_piecepart workflow -----------------------------------


def test_usage_fraction_uses_source_variant_count_not_addition_count(tmp_path: Path) -> None:
    """Phase D C5 regression: usage_fraction must reflect the source-derived
    variant count, not the length of bom_additions. When U200 IS in BOM and
    U200-A is the only variant referenced in the grouping file, the variant
    count for U200 is 1 (just U200-A), so usage_fraction == '1/1'. If the
    code were using len(bom_additions), this would also be '1/1', so to
    discriminate we need a second variant that ISN'T in bom_additions.
    We put U200-A in grouping (missing from BOM → inheritance kicks in) AND
    U200 in the grouping file (present in BOM → no inheritance). That gives
    variant_counts_by_base[U200] == 2 but bom_additions has only 1 entry
    (U200-A). Expected usage_fraction == '1/2', NOT '1/1'."""
    paths = _write_fixture(
        tmp_path,
        bom_rows=[
            {
                "Reference Designator": "U200",
                "Part Number": "IC-1234",
                "Description": "Microcontroller",
                "BAE HDA Commodity I": "Microcircuit",
                "BAE HDA Commodity II": "Digital",
                "Part Usage": "1/2",
            }
        ],
        grouping_rows=[
            {
                "Component Group": "CPU-001",
                "Reference Designator": "U200, U200-A",
                "Function Description": "CPU + variant",
                "Schematic Page": "12",
            }
        ],
    )
    proc = FMEAProcessor()
    proc.process(
        {
            "group": str(paths["grouping"]),
            "bom": str(paths["bom"]),
            "fm": str(paths["fm"]),
            "hda": None,
            "func": None,
            "piecepart_fmea": None,
            "out_folder": str(tmp_path),
            "out_name": "out",
            "bom_only_mode": False,
            "use_func": False,
            "use_piecepart_merge": False,
            "verbose": False,
            "column_overrides": {},
            "failure_modes_standard": "FMD-2016",
            "group_sheet": "Sheet1",
            "bom_sheet": "Sheet1",
            "hda_sheet": None,
            "fm_sheet": "Sheet1",
            "func_sheet": None,
            "piecepart_fmea_sheet": None,
        }
    )
    # Only U200-A inherits (U200 is directly in BOM).
    assert len(proc.bom_additions) == 1, proc.bom_additions
    assert proc.bom_additions[0]["ref_des"] == "U200-A"
    # Variant count for U200 base == 2 (U200 + U200-A in grouping).
    # Therefore usage_fraction for the inherited row must be "1/2".
    assert proc.bom_additions[0]["usage_fraction"] == "1/2", proc.bom_additions[0]


def test_inherited_variant_does_not_get_false_usage_warning(tmp_path: Path) -> None:
    """Phase D C5 regression: inherited variants must NOT be flagged as
    "Usage mismatch" validation warnings just because the BOM base has
    count=1. With U200 in BOM (Part Usage=1/3) and 3 variants in grouping,
    the inherited variants should see expected = 1/3 (from variant count),
    NOT 1/1 (from BOM usage_base_count)."""
    paths = _write_fixture(
        tmp_path,
        bom_rows=[
            {
                "Reference Designator": "U200",
                "Part Number": "IC-1234",
                "Description": "Microcontroller",
                "BAE HDA Commodity I": "Microcircuit",
                "BAE HDA Commodity II": "Digital",
                "Part Usage": "1/3",
            }
        ],
        grouping_rows=[
            {
                "Component Group": "CPU-001",
                "Reference Designator": "U200-A, U200-B, U200-C",
                "Function Description": "Processor variants",
                "Schematic Page": "12",
            }
        ],
    )
    proc = FMEAProcessor()
    proc.process(
        {
            "group": str(paths["grouping"]),
            "bom": str(paths["bom"]),
            "fm": str(paths["fm"]),
            "hda": None,
            "func": None,
            "piecepart_fmea": None,
            "out_folder": str(tmp_path),
            "out_name": "out",
            "bom_only_mode": False,
            "use_func": False,
            "use_piecepart_merge": False,
            "verbose": False,
            "column_overrides": {},
            "failure_modes_standard": "FMD-2016",
            "group_sheet": "Sheet1",
            "bom_sheet": "Sheet1",
            "hda_sheet": None,
            "fm_sheet": "Sheet1",
            "func_sheet": None,
            "piecepart_fmea_sheet": None,
        }
    )
    # 3 inherited variants expected
    assert len(proc.bom_additions) == 3
    # ZERO usage warnings — inherited rows use variant_count, not BOM count
    inherited_warnings = [
        w for w in proc.usage_warnings if w.get("ReasonCode") == "PU_INHERITED_MISMATCH"
    ]
    assert inherited_warnings == [], inherited_warnings
    legacy_warnings = [
        w for w in proc.usage_warnings if w.get("ReasonCode") == "PU_EXPECTED_MISMATCH_BASIC"
    ]
    assert legacy_warnings == [], legacy_warnings


def test_legacy_enrichment_payload_is_rejected(tmp_path: Path) -> None:
    """Phase D C6: a stale client sending enrichments.functional=true must
    hit a hard ValidationError, not get silently migrated into the new
    primary-workflow path (which would produce output without the merge
    the user requested)."""
    paths = _write_fixture(
        tmp_path,
        bom_rows=[
            {
                "Reference Designator": "R100",
                "Part Number": "RES-1",
                "Description": "Resistor",
                "BAE HDA Commodity I": "Resistor",
                "BAE HDA Commodity II": "Chip",
                "Part Usage": "1",
            }
        ],
        grouping_rows=[
            {
                "Component Group": "RES-001",
                "Reference Designator": "R100",
                "Function Description": "Pull-up",
                "Schematic Page": "3",
            }
        ],
    )

    def state(role: str, path: Path) -> dict:
        return {
            "role": role,
            "label": role,
            "path": str(path),
            "selectedSheet": "Sheet1",
            "source": "desktop-bridge",
            "isResolvingSheets": False,
            "isAnalyzing": False,
            "resolutionError": None,
            "sheets": [{"id": "s1", "label": "Sheet1"}],
        }

    body = {
        "workflowId": "piece_part_generate",
        "outputStrategyId": "new_workbook_standard",
        # Legacy enrichment toggle — should be rejected.
        "enrichments": {"functional": True, "piecePart": False},
        "options": {"failureModesStandard": "FMD-2016"},
        "inputs": [
            state("grouping", paths["grouping"]),
            state("bom", paths["bom"]),
            state("failureModes", paths["fm"]),
        ],
        "mappings": [],
    }
    with pytest.raises(ValidationError, match="enrichment toggles have been removed"):
        execute_run_request(body)


def test_failure_modes_standard_filters_mixed_standard_file(tmp_path: Path) -> None:
    """Phase D L6: FM file with a 'Standard' column and mixed FMD-91 +
    FMD-2016 rows should filter to only the selected standard when the
    user picks FMD-91."""
    paths = _write_fixture(
        tmp_path,
        bom_rows=[
            {
                "Reference Designator": "R100",
                "Part Number": "RES-1",
                "Description": "Resistor",
                "BAE HDA Commodity I": "Resistor",
                "BAE HDA Commodity II": "Chip",
                "Part Usage": "1",
            }
        ],
        grouping_rows=[
            {
                "Component Group": "RES-001",
                "Reference Designator": "R100",
                "Function Description": "Pull-up",
                "Schematic Page": "3",
            }
        ],
        fm_rows=[
            {
                "Standard": "FMD-91",
                "Commodity Type 1": "Resistor",
                "Commodity Type 2": "Chip",
                "Failure Mode": "Open (FMD-91)",
                "Failure Mode Ratio": 1.0,
            },
            {
                "Standard": "FMD-2016",
                "Commodity Type 1": "Resistor",
                "Commodity Type 2": "Chip",
                "Failure Mode": "Open (FMD-2016)",
                "Failure Mode Ratio": 1.0,
            },
        ],
    )

    proc = FMEAProcessor()
    df = proc.process(
        {
            "group": str(paths["grouping"]),
            "bom": str(paths["bom"]),
            "fm": str(paths["fm"]),
            "hda": None,
            "func": None,
            "piecepart_fmea": None,
            "out_folder": str(tmp_path),
            "out_name": "out",
            "bom_only_mode": False,
            "use_func": False,
            "use_piecepart_merge": False,
            "verbose": False,
            "column_overrides": {},
            "failure_modes_standard": "FMD-91",
            "group_sheet": "Sheet1",
            "bom_sheet": "Sheet1",
            "hda_sheet": None,
            "fm_sheet": "Sheet1",
            "func_sheet": None,
            "piecepart_fmea_sheet": None,
        }
    )
    # Only the FMD-91 failure mode should appear in the piece-part rows
    pp_rows = df[df["_row_type"].isin(("piece_part", "validation_warning"))]
    failure_modes = set(pp_rows["Failure Mode"].dropna().tolist())
    assert "Open (FMD-91)" in failure_modes
    assert "Open (FMD-2016)" not in failure_modes


def test_functional_to_piecepart_preserves_functional_rows(tmp_path: Path) -> None:
    """A 3-row functional FMEA with one circuit-block row containing
    "R100, C200" should produce: 3 functional rows preserved + 2 piece-part
    rows generated under the block."""
    paths = _write_fixture(
        tmp_path,
        bom_rows=[
            {
                "Reference Designator": "R100",
                "Part Number": "RES-1",
                "Description": "Resistor",
                "BAE HDA Commodity I": "Resistor",
                "BAE HDA Commodity II": "Chip",
                "Part Usage": "1",
            },
            {
                "Reference Designator": "C200",
                "Part Number": "CAP-1",
                "Description": "Capacitor",
                "BAE HDA Commodity I": "Capacitor",
                "BAE HDA Commodity II": "Ceramic",
                "Part Usage": "1",
            },
        ],
        fm_rows=[
            {
                "FMD-2016 Commodity Type 1": "Resistor",
                "FMD-2016 Commodity Type 2": "Chip",
                "Failure Mode": "Open",
                "Failure Mode Ratio": 1.0,
            },
            {
                "FMD-2016 Commodity Type 1": "Capacitor",
                "FMD-2016 Commodity Type 2": "Ceramic",
                "Failure Mode": "Short",
                "Failure Mode Ratio": 1.0,
            },
        ],
        functional_rows=[
            # Row 1: a function header / not a circuit block
            {
                "FMEA Level": "Function",
                "FMEA-ID": "FN-001",
                "Failure Mode Causes": "",
                "Function Description": "Power conditioning",
                "Schematic Page": "1",
            },
            # Row 2: a circuit block with two RefDes
            {
                "FMEA Level": "Circuit Block",
                "FMEA-ID": "CB-001",
                "Failure Mode Causes": "R100, C200",
                "Function Description": "RC filter",
                "Schematic Page": "2",
            },
            # Row 3: another function header
            {
                "FMEA Level": "Function",
                "FMEA-ID": "FN-002",
                "Failure Mode Causes": "",
                "Function Description": "Output stage",
                "Schematic Page": "3",
            },
        ],
    )

    proc = FMEAProcessor()
    df = proc.process_functional_to_piecepart(
        {
            "func": str(paths["func"]),
            "bom": str(paths["bom"]),
            "fm": str(paths["fm"]),
            "hda": None,
            "out_folder": str(tmp_path),
            "out_name": "out",
            "verbose": False,
            "column_overrides": {},
            "failure_modes_standard": "FMD-2016",
            "func_sheet": "Sheet1",
            "bom_sheet": "Sheet1",
            "hda_sheet": None,
            "fm_sheet": "Sheet1",
        }
    )

    assert not df.empty
    # All 3 functional passthrough rows should be preserved AS-IS.
    # They're tagged with their classification rtype (circuit_block for
    # row 2; whatever classify_fmea_rows returns for the others — most
    # likely 'other' since they don't have level/refdes indicators).
    func_rows = df[~df["_row_type"].isin(("piece_part", "piece_part_no_match", "validation_warning"))]
    assert len(func_rows) == 3, (
        f"Expected 3 functional passthrough rows, got {len(func_rows)}: "
        f"{func_rows['_row_type'].tolist()}"
    )
    # Original column names should be preserved on passthrough rows
    assert "FMEA Level" in df.columns
    assert "FMEA-ID" in df.columns
    assert "Function Description" in df.columns
    # Exactly 2 piece-part rows should be generated (one per RefDes),
    # since each FM file row has ratio 1.0 (no multi-mode multiplication).
    pp_rows = df[df["_row_type"].isin(("piece_part", "validation_warning"))]
    assert len(pp_rows) == 2, f"Expected 2 piece-part rows, got {len(pp_rows)}"
    refdes_seen = set(pp_rows["Failure Mode Causes"].dropna().tolist())
    assert refdes_seen == {"R100", "C200"}, refdes_seen
