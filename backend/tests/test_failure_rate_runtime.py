"""Runtime-adapter-level regression tests for the Failure Rate sidecar tool.

Exercises ``failure_rate/runtime.py`` validate path directly (in-process via
the conftest sys.path shim) to prove a required mapping pinned to the
Do-Not-Map sentinel fails validation cleanly rather than crashing execute with
a ColumnMappingError about a column named '__do_not_map__'.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from common.cancellation import CancellationError
from failure_rate import runtime as fr_runtime
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


def _build_body(tmp_path: Path) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    pred_path = tmp_path / "prediction.xlsx"
    fmea_path = tmp_path / "fmea.xlsx"
    pd.DataFrame(
        [{"Reference Designator": "R1", "Failure Rate": 0.001}]
    ).to_excel(pred_path, index=False)
    pd.DataFrame(
        [{"Failure Mode Causes": "R1", "Failure Mode Ratio": 1.0, "Part Usage": 1.0}]
    ).to_excel(fmea_path, index=False)
    return {
        "workflowId": "failure_rate_link",
        "outputStrategyId": "new_workbook_standard",
        "outputDirectory": str(tmp_path),
        "inputs": [
            _input_state("prediction", "Prediction workbook", pred_path),
            _input_state("fmea", "FMEA workbook", fmea_path),
        ],
        "mappings": [
            {"canonical": "pred_ref", "mappedTo": "Reference Designator", "status": "mapped"},
            {"canonical": "pred_fr", "mappedTo": "Failure Rate", "status": "mapped"},
            {"canonical": "fmea_cause", "mappedTo": "Failure Mode Causes", "status": "mapped"},
            {"canonical": "fmea_ratio", "mappedTo": "Failure Mode Ratio", "status": "mapped"},
            {"canonical": "fmea_usage", "mappedTo": "Part Usage", "status": "mapped"},
        ],
        "options": {"unit_mode": "per_hour"},
    }


def test_failure_rate_valid_body_passes_validation(tmp_path: Path) -> None:
    """Sanity guard: a fully-mapped body still validates ok."""
    result = fr_runtime.validate_run_request(_build_body(tmp_path))
    assert result["ok"] is True


def test_failure_rate_required_mapping_sentinel_blocks_validation(tmp_path: Path) -> None:
    """A required Failure Rate mapping set to '__do_not_map__' must surface as
    a clean invalid_do_not_map validation failure rather than passing
    validation (the sentinel is a non-empty string) and then crashing execute.
    """
    body = _build_body(tmp_path)
    for row in body["mappings"]:
        if row["canonical"] == "fmea_cause":
            row["mappedTo"] = DO_NOT_MAP_SENTINEL

    result = fr_runtime.validate_run_request(body)

    assert result["ok"] is False
    assert result["reason_code"] == "invalid_do_not_map"
    # Batch 6 #7: the message names the mapping the way the UI labels it, not
    # the raw canonical token (fmea_cause).
    assert "FMEA: failure mode causes" in result["toast_text"]
    assert "fmea_cause" not in result["toast_text"]


def test_failure_rate_missing_mapping_uses_display_label(tmp_path: Path) -> None:
    """A missing required mapping is reported with the human display label
    ('FMEA: failure mode ratio'), never the raw canonical ('fmea_ratio')."""
    body = _build_body(tmp_path)
    # Drop the fmea_ratio mapping so it reads as absent.
    body["mappings"] = [
        row for row in body["mappings"] if row["canonical"] != "fmea_ratio"
    ]

    result = fr_runtime.validate_run_request(body)

    assert result["ok"] is False
    assert result["reason_code"] == "missing_mappings"
    assert "FMEA: failure mode ratio" in result["toast_text"]
    assert "fmea_ratio" not in result["toast_text"]


def test_failure_rate_cancel_after_verify_cleans_temp_and_skips_promote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    def capture_processor(processor) -> None:
        captured["processor"] = processor

    def cancel_after_verify(temp_path: Path) -> bool:
        assert Path(temp_path).exists()
        captured["processor"].cancel.cancel()
        return True

    monkeypatch.setattr(fr_runtime, "verify_excel_readable", cancel_after_verify)

    with pytest.raises(CancellationError):
        fr_runtime.execute_run_request(
            _build_body(tmp_path),
            processor_ready_callback=capture_processor,
        )

    assert not list(tmp_path.glob("FailureRate_Link_*.xlsx"))
    assert not list(tmp_path.glob(".*.part.xlsx"))
