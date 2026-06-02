"""Focused numeric tests for the Failure Rate linker math.

The entire purpose of the Failure Rate tool is the per-mode failure-rate
arithmetic:

    Mode_FR = Part_FR * Usage * Corrected_Ratio

and the unit-mode scaling that converts the prediction file's reported
failure rate into per-hour space before the multiply.  These tests build
minimal in-memory DataFrames, drive ``FMEALinkerLogic.process`` directly,
and assert the EXACT computed numbers — so they fail loudly if the linker
math or the unit conversion ever regresses.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from failure_rate.failure_rate_logic import (
    FMEALinkerLogic,
    normalize_refdes_for_lookup,
)


# Column map shared by most tests. Keys mirror what the runtime adapter
# hands ``process`` (see failure_rate/runtime.py).
COL_MAP = {
    "pred_ref": "Reference Designator",
    "pred_fr": "Failure Rate",
    "fmea_cause": "Failure Mode Causes",
    "fmea_ratio": "Failure Mode Ratio",
    "fmea_usage": "Part Usage",
    "fmea_func": "",
}


def _make_logic(pred_df: pd.DataFrame, fmea_df: pd.DataFrame) -> FMEALinkerLogic:
    """Build a linker with DataFrames injected directly (no Excel IO)."""
    logic = FMEALinkerLogic(log_func=lambda _msg: None)
    logic.prediction_df = pred_df
    logic.fmea_df = fmea_df
    return logic


def test_mode_fr_is_part_fr_times_usage_times_ratio() -> None:
    """Mode_FR for a linked row equals Part_FR * Usage * Corrected_Ratio."""
    pred = pd.DataFrame(
        [
            {"Reference Designator": "R1", "Failure Rate": 0.00001},
            {"Reference Designator": "C2", "Failure Rate": 0.000004},
        ]
    )
    fmea = pd.DataFrame(
        [
            # R1: two modes splitting the failure rate 60/40, usage 1.0
            {"Failure Mode Causes": "R1", "Failure Mode Ratio": 0.6, "Part Usage": 1.0},
            {"Failure Mode Causes": "R1", "Failure Mode Ratio": 0.4, "Part Usage": 1.0},
            # C2: single mode, ratio 0.5, usage 2.0 -> exercises usage multiply
            {"Failure Mode Causes": "C2", "Failure Mode Ratio": 0.5, "Part Usage": 2.0},
        ]
    )

    result = _make_logic(pred, fmea).process(COL_MAP)

    # Part_FR is the (unconverted, per_hour) lookup value per row.
    assert list(result["Part_FR"]) == pytest.approx([0.00001, 0.00001, 0.000004])
    assert list(result["Corrected_Ratio"]) == pytest.approx([0.6, 0.4, 0.5])

    # Mode_FR = Part_FR * Usage * Ratio, computed independently here.
    assert result["Mode_FR"].iloc[0] == pytest.approx(0.00001 * 1.0 * 0.6)  # 6e-6
    assert result["Mode_FR"].iloc[1] == pytest.approx(0.00001 * 1.0 * 0.4)  # 4e-6
    assert result["Mode_FR"].iloc[2] == pytest.approx(0.000004 * 2.0 * 0.5)  # 4e-6

    # The two R1 modes must sum back to the full part failure rate (usage 1.0).
    assert result["Mode_FR"].iloc[0] + result["Mode_FR"].iloc[1] == pytest.approx(0.00001)


@pytest.mark.parametrize(
    "unit_mode, scale",
    [
        ("per_hour", 1.0),
        ("per_million_hours", 1e-6),
        ("per_billion_hours", 1e-9),
    ],
)
def test_unit_mode_scales_part_fr_and_mode_fr(unit_mode: str, scale: float) -> None:
    """Each supported unit mode divides the raw prediction value before linking.

    The prediction file reports ``500`` for U10. Interpreted per_hour that's
    500/hr; per_million_hours that's 500e-6/hr; per_billion_hours 500e-9/hr.
    With ratio 1.0 and usage 1.0, Mode_FR must equal the scaled Part_FR.
    """
    raw_fr = 500.0
    pred = pd.DataFrame([{"Reference Designator": "U10", "Failure Rate": raw_fr}])
    fmea = pd.DataFrame(
        [{"Failure Mode Causes": "U10", "Failure Mode Ratio": 1.0, "Part Usage": 1.0}]
    )
    col_map = dict(COL_MAP, unit_mode=unit_mode)

    result = _make_logic(pred, fmea).process(col_map)

    expected = raw_fr * scale
    assert result["Part_FR"].iloc[0] == pytest.approx(expected)
    # ratio=1.0, usage=1.0 -> Mode_FR collapses to the scaled Part_FR.
    assert result["Mode_FR"].iloc[0] == pytest.approx(expected)


def test_unit_modes_produce_distinct_scaled_numbers() -> None:
    """Cross-check: the three unit modes must yield 1 : 1e-6 : 1e-9 ratios.

    This guards against a regression where the conversion branch silently
    falls through to per_hour for the scaled modes.
    """
    raw_fr = 730.0
    pred = pd.DataFrame([{"Reference Designator": "U1", "Failure Rate": raw_fr}])
    fmea = pd.DataFrame(
        [{"Failure Mode Causes": "U1", "Failure Mode Ratio": 1.0, "Part Usage": 1.0}]
    )

    def mode_fr_for(unit: str) -> float:
        result = _make_logic(
            pred.copy(), fmea.copy()
        ).process(dict(COL_MAP, unit_mode=unit))
        return float(result["Mode_FR"].iloc[0])

    per_hour = mode_fr_for("per_hour")
    per_million = mode_fr_for("per_million_hours")
    per_billion = mode_fr_for("per_billion_hours")

    assert per_hour == pytest.approx(730.0)
    assert per_million == pytest.approx(730.0e-6)
    assert per_billion == pytest.approx(730.0e-9)
    # The three are genuinely different (no silent fall-through to per_hour).
    assert per_hour != pytest.approx(per_million)
    assert per_million != pytest.approx(per_billion)


def test_invalid_unit_mode_defaults_to_per_hour() -> None:
    """An unrecognized unit_mode falls back to per_hour (no scaling)."""
    pred = pd.DataFrame([{"Reference Designator": "R5", "Failure Rate": 12.0}])
    fmea = pd.DataFrame(
        [{"Failure Mode Causes": "R5", "Failure Mode Ratio": 1.0, "Part Usage": 1.0}]
    )

    result = _make_logic(pred, fmea).process(dict(COL_MAP, unit_mode="per_zorp"))

    # No conversion applied -> Part_FR is the raw value.
    assert result["Part_FR"].iloc[0] == pytest.approx(12.0)
    assert result["Mode_FR"].iloc[0] == pytest.approx(12.0)


def test_unmatched_refdes_yields_zero_part_fr_and_note() -> None:
    """A FMEA cause with no prediction match gets Part_FR=0 and Mode_FR=0."""
    pred = pd.DataFrame([{"Reference Designator": "R1", "Failure Rate": 0.001}])
    fmea = pd.DataFrame(
        [
            {"Failure Mode Causes": "R1", "Failure Mode Ratio": 1.0, "Part Usage": 1.0},
            {"Failure Mode Causes": "Q99", "Failure Mode Ratio": 1.0, "Part Usage": 1.0},
        ]
    )

    result = _make_logic(pred, fmea).process(COL_MAP)

    # Matched row.
    assert result["Part_FR"].iloc[0] == pytest.approx(0.001)
    assert result["Mode_FR"].iloc[0] == pytest.approx(0.001)
    # Unmatched row: zeroed and annotated.
    assert result["Part_FR"].iloc[1] == 0.0
    assert result["Mode_FR"].iloc[1] == 0.0
    assert "RefDes not in Prediction" in result["Validation_Notes"].iloc[1]


def test_zero_padded_refdes_links_across_sources() -> None:
    """Prediction 'U007' must link to FMEA cause 'U7' (leading zeros stripped)."""
    pred = pd.DataFrame([{"Reference Designator": "U007", "Failure Rate": 0.02}])
    fmea = pd.DataFrame(
        [{"Failure Mode Causes": "U7", "Failure Mode Ratio": 0.25, "Part Usage": 1.0}]
    )

    result = _make_logic(pred, fmea).process(COL_MAP)

    assert result["Extracted_RefDes"].iloc[0] == "U7"
    assert result["Part_FR"].iloc[0] == pytest.approx(0.02)
    assert result["Mode_FR"].iloc[0] == pytest.approx(0.02 * 0.25)  # 0.005


def test_invalid_usage_and_ratio_default_to_one() -> None:
    """Out-of-range usage/ratio default to 1.0 and are annotated.

    Usage of 5_000_000 exceeds the 1e6 cap; ratio of 50 exceeds the 0..10
    band. Both default to 1.0, so Mode_FR collapses to Part_FR.
    """
    pred = pd.DataFrame([{"Reference Designator": "C1", "Failure Rate": 0.003}])
    fmea = pd.DataFrame(
        [{"Failure Mode Causes": "C1", "Failure Mode Ratio": 50.0, "Part Usage": 5_000_000.0}]
    )

    result = _make_logic(pred, fmea).process(COL_MAP)

    assert result["Corrected_Ratio"].iloc[0] == pytest.approx(1.0)
    assert result["Mode_FR"].iloc[0] == pytest.approx(0.003)  # 0.003 * 1.0 * 1.0
    notes = result["Validation_Notes"].iloc[0]
    assert "Invalid Usage" in notes
    assert "Invalid Ratio" in notes


def test_function_fr_sums_mode_fr_within_function_group() -> None:
    """When a function column is mapped, Function_FR sums Mode_FR per function."""
    pred = pd.DataFrame(
        [
            {"Reference Designator": "R1", "Failure Rate": 0.001},
            {"Reference Designator": "R2", "Failure Rate": 0.002},
            {"Reference Designator": "R3", "Failure Rate": 0.004},
        ]
    )
    fmea = pd.DataFrame(
        [
            {"Failure Mode Causes": "R1", "Failure Mode Ratio": 1.0, "Part Usage": 1.0, "Function": "F_A"},
            {"Failure Mode Causes": "R2", "Failure Mode Ratio": 1.0, "Part Usage": 1.0, "Function": "F_A"},
            {"Failure Mode Causes": "R3", "Failure Mode Ratio": 1.0, "Part Usage": 1.0, "Function": "F_B"},
        ]
    )
    col_map = dict(COL_MAP, fmea_func="Function")

    result = _make_logic(pred, fmea).process(col_map)

    # F_A rows: 0.001 + 0.002 = 0.003 for both R1 and R2 rows.
    f_a = result[result["Function"] == "F_A"]["Function_FR"]
    assert list(f_a) == pytest.approx([0.003, 0.003])
    # F_B row: just R3 = 0.004.
    f_b = result[result["Function"] == "F_B"]["Function_FR"]
    assert list(f_b) == pytest.approx([0.004])


def test_normalize_refdes_strips_leading_zeros_and_handles_nan() -> None:
    """Lookup normalization: zero-strip, uppercase, suffix-preserve, NaN-safe."""
    assert normalize_refdes_for_lookup("u01") == "U1"
    assert normalize_refdes_for_lookup("R001") == "R1"
    assert normalize_refdes_for_lookup("U007A") == "U7A"
    assert normalize_refdes_for_lookup("R10") == "R10"  # no spurious stripping
    assert normalize_refdes_for_lookup(float("nan")) == ""
    assert normalize_refdes_for_lookup(None) == ""


def test_fmr_validation_groups_by_instance_not_base() -> None:
    """FMR (ratio) validation sums to 1.0 PER instance/pin designator (U200-1),
    NOT per base component.

    Domain rule: each instance carries its own open/short failure modes whose
    ratios sum to 1.0; component-level roll-up is handled by the Part Usage
    column, not by collapsing instances to a base RefDes. Here U200-1's ratios
    sum to 1.0 (valid) and U200-2's to 0.8 (broken). Instance grouping flags
    ONLY U200-2. If validation were (wrongly) grouped by base U200, the combined
    sum would be 1.8 and U200-1's rows would be falsely flagged too -- this test
    guards against that regression.
    """
    pred = pd.DataFrame([{"Reference Designator": "U200", "Failure Rate": 0.001}])
    fmea = pd.DataFrame(
        [
            {"Failure Mode Causes": "U200-1", "Failure Mode Ratio": 0.6, "Part Usage": 0.5},
            {"Failure Mode Causes": "U200-1", "Failure Mode Ratio": 0.4, "Part Usage": 0.5},
            {"Failure Mode Causes": "U200-2", "Failure Mode Ratio": 0.5, "Part Usage": 0.5},
            {"Failure Mode Causes": "U200-2", "Failure Mode Ratio": 0.3, "Part Usage": 0.5},
        ]
    )

    result = _make_logic(pred, fmea).process(COL_MAP, check_fmr=True)
    notes = result["Validation_Notes"].astype(str)

    # Grouping is by the instance designator extracted from the cause text.
    assert set(result["Validation_RefDes"]) == {"U200-1", "U200-2"}
    # U200-1 ratios sum to 1.0 -> no FMR warning.
    assert all("FMR Sum" not in n for n in notes[result["Validation_RefDes"] == "U200-1"])
    # U200-2 ratios sum to 0.8 -> FMR warning on its rows.
    assert all("FMR Sum" in n for n in notes[result["Validation_RefDes"] == "U200-2"])
