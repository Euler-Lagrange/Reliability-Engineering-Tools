from __future__ import annotations

from pathlib import Path

from bom_compare.runtime import _resolve_output_directory as resolve_bom_compare_output
from failure_rate.runtime import _resolve_output_directory as resolve_failure_rate_output
from fmea.runtime import _resolve_output_directory as resolve_fmea_output
from refdes_extractor.runtime import _resolve_output_directory as resolve_refdes_output


def _touch(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture", encoding="utf-8")
    return str(path)


def test_fmea_invalid_output_directory_warns_and_falls_back(tmp_path: Path) -> None:
    logs: list[str] = []
    inputs = {"bom": {"path": _touch(tmp_path / "inputs" / "bom.xlsx")}}

    resolved = resolve_fmea_output(
        inputs,
        explicit_directory=str(tmp_path / "missing"),
        log_callback=logs.append,
    )

    assert resolved == tmp_path / "inputs"
    assert any("WARNING:" in line and "outputDirectory" in line for line in logs)


def test_bom_compare_invalid_output_directory_warns_and_falls_back(tmp_path: Path) -> None:
    logs: list[str] = []
    inputs = {"bom": {"path": _touch(tmp_path / "inputs" / "bom.xlsx")}}

    resolved = resolve_bom_compare_output(
        inputs,
        explicit_directory=str(tmp_path / "missing"),
        log_callback=logs.append,
    )

    assert resolved == tmp_path / "inputs"
    assert any("WARNING:" in line and "outputDirectory" in line for line in logs)


def test_failure_rate_invalid_output_directory_warns_and_falls_back(tmp_path: Path) -> None:
    logs: list[str] = []
    inputs = {"prediction": {"path": _touch(tmp_path / "inputs" / "prediction.xlsx")}}

    resolved = resolve_failure_rate_output(
        inputs,
        explicit_directory=str(tmp_path / "missing"),
        log_callback=logs.append,
    )

    assert resolved == tmp_path / "inputs"
    assert any("WARNING:" in line and "outputDirectory" in line for line in logs)


def test_refdes_invalid_output_directory_warns_and_falls_back(tmp_path: Path) -> None:
    logs: list[str] = []
    inputs = {"pdf": {"path": _touch(tmp_path / "inputs" / "schematic.pdf")}}

    resolved = resolve_refdes_output(
        inputs,
        explicit_directory=str(tmp_path / "missing"),
        log_callback=logs.append,
    )

    assert resolved == tmp_path / "inputs"
    assert any("WARNING:" in line and "outputDirectory" in line for line in logs)
