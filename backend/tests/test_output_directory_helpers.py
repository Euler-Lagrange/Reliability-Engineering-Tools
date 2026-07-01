from __future__ import annotations

from pathlib import Path

from bom_compare.runtime import _resolve_output_directory as resolve_bom_compare_output
from failure_rate.runtime import _resolve_output_directory as resolve_failure_rate_output
from fmea.fmea_template_writer import build_template_output_path
from fmea.runtime import _resolve_output_directory as resolve_fmea_output
from fmea.runtime import validate_run_request as validate_fmea_run
from refdes_extractor.runtime import _resolve_output_directory as resolve_refdes_output
from shared.pre_run_validation import output_directory_validation


def test_build_template_output_path_honors_output_directory(tmp_path: Path) -> None:
    # Tier-2 #18: preserve-formatting mode must write the merged workbook to the
    # chosen output folder, not silently next to the template.
    template = str(tmp_path / "src" / "FMEA_v3.xlsx")
    out_dir = tmp_path / "chosen_output"
    result = Path(
        build_template_output_path(template, mode="DarkStar", output_directory=str(out_dir))
    )
    assert result.parent == out_dir
    assert result.name.startswith("FMEA_v3_DarkStar_")
    assert result.suffix == ".xlsx"


def test_build_template_output_path_defaults_to_template_parent(tmp_path: Path) -> None:
    # With no explicit output directory, the behavior is unchanged: next to the
    # template (which is also what FMEA's resolver falls back to via targetWorkbook).
    template = str(tmp_path / "src" / "FMEA_v3.xlsx")
    result = Path(build_template_output_path(template, mode="DarkStar"))
    assert result.parent == (tmp_path / "src")


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


# --- Tier-2 #19: validate-time output-directory warning ---------------------


def test_output_directory_validation_flags_unwritable(tmp_path: Path) -> None:
    warning = output_directory_validation(str(tmp_path / "does_not_exist"))
    assert warning is not None
    assert warning["severity"] == "warning"
    assert warning["id"] == "output_directory_unwritable"


def test_output_directory_validation_passes_a_real_dir(tmp_path: Path) -> None:
    good = tmp_path / "out"
    good.mkdir()
    assert output_directory_validation(str(good)) is None


def test_output_directory_validation_ignores_empty(tmp_path: Path) -> None:
    # No explicit directory means "use the default heuristic" — not a warning.
    assert output_directory_validation("") is None
    assert output_directory_validation(None) is None


def test_fmea_validate_surfaces_a_bad_output_directory(tmp_path: Path) -> None:
    # End-to-end: an invalid outputDirectory now surfaces as a validation
    # warning at validate time instead of silently relocating at execute time.
    result = validate_fmea_run(
        {
            "workflowId": "piece_part_generate",
            "outputStrategyId": "new_workbook_standard",
            "options": {"failureModesStandard": "FMD-2016"},
            "outputDirectory": str(tmp_path / "nonexistent"),
            "inputs": [],
        }
    )
    ids = [v.get("id") for v in result["validations"]]
    assert "output_directory_unwritable" in ids
