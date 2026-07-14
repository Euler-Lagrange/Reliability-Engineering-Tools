from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import common.utils as common_utils
from bom_compare import runtime as bom_runtime
from bom_compare.runtime import _resolve_output_directory as resolve_bom_compare_output
from common.exceptions import ValidationError
from failure_rate import runtime as failure_rate_runtime
from failure_rate.runtime import _resolve_output_directory as resolve_failure_rate_output
from fmea.fmea_template_writer import build_template_output_path
from fmea import runtime as fmea_runtime
from fmea.runtime import _resolve_output_directory as resolve_fmea_output
from fmea.runtime import validate_run_request as validate_fmea_run
from refdes_extractor import runtime as refdes_runtime
from refdes_extractor.runtime import _resolve_output_directory as resolve_refdes_output
from shared.pre_run_validation import output_directory_validation


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 7, 14, 1, 2, 3, tzinfo=tz)


def _freeze_output_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(common_utils, "datetime", _FixedDatetime)


def test_build_template_output_path_honors_output_directory_without_clobber(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Tier-2 #18: preserve-formatting mode must write the merged workbook to the
    # chosen output folder, not silently next to the template.
    _freeze_output_clock(monkeypatch)
    template = str(tmp_path / "src" / "FMEA_v3.xlsx")
    out_dir = tmp_path / "chosen_output"
    out_dir.mkdir()
    existing = out_dir / "FMEA_v3_Merged_20260714_010203.xlsx"
    existing.write_bytes(b"user-owned output")
    existing_suffix_two = out_dir / "FMEA_v3_Merged_20260714_010203 (2).xlsx"
    existing_suffix_two.write_bytes(b"second user-owned output")
    result = Path(
        build_template_output_path(template, mode="Merged", output_directory=str(out_dir))
    )
    assert result.parent == out_dir
    assert result.name == "FMEA_v3_Merged_20260714_010203 (3).xlsx"
    assert result.suffix == ".xlsx"
    assert existing.read_bytes() == b"user-owned output"
    assert existing_suffix_two.read_bytes() == b"second user-owned output"


def test_build_template_output_path_defaults_to_template_parent(tmp_path: Path) -> None:
    # With no explicit output directory, the behavior is unchanged: next to the
    # template (which is also what FMEA's resolver falls back to via targetWorkbook).
    template = str(tmp_path / "src" / "FMEA_v3.xlsx")
    result = Path(build_template_output_path(template, mode="Merged"))
    assert result.parent == (tmp_path / "src")


def test_build_output_filename_without_directory_keeps_filename_only_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_output_clock(monkeypatch)

    assert common_utils.build_output_filename("Tool", "Mode") == (
        "Tool_Mode_20260714_010203.xlsx"
    )


@pytest.mark.parametrize(
    ("runtime_module", "builder_args", "base_name"),
    [
        (
            bom_runtime,
            ("bom_compare_group",),
            "BomCompare_Group_20260714_010203.xlsx",
        ),
        (
            bom_runtime,
            ("bom_compare_custom",),
            "BomCompare_Custom_20260714_010203.xlsx",
        ),
        (
            bom_runtime,
            ("extraction_compare",),
            "ExtractionCompare_20260714_010203.xlsx",
        ),
        (
            failure_rate_runtime,
            (),
            "FailureRate_Link_20260714_010203.xlsx",
        ),
        (
            refdes_runtime,
            (),
            "RefDesExtract_20260714_010203.xlsx",
        ),
        (
            fmea_runtime,
            ("piece_part_generate",),
            "MergedFMEA_Standard_20260714_010203.xlsx",
        ),
    ],
)
def test_runtime_output_builders_choose_suffix_two_on_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runtime_module,
    builder_args: tuple[str, ...],
    base_name: str,
) -> None:
    _freeze_output_clock(monkeypatch)
    existing = tmp_path / base_name
    existing.write_bytes(b"existing output")
    builder = getattr(runtime_module, "_build_output_name", None)

    assert callable(builder)
    selected_name = builder(*builder_args, output_directory=tmp_path)

    assert selected_name == base_name.replace(".xlsx", " (2).xlsx")
    assert existing.read_bytes() == b"existing output"


def test_build_output_filename_fails_after_collision_suffix_99(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_output_clock(monkeypatch)
    base_name = "CollisionTest_Mode_20260714_010203.xlsx"
    (tmp_path / base_name).write_bytes(b"base")
    for index in range(2, 100):
        (tmp_path / base_name.replace(".xlsx", f" ({index}).xlsx")).write_bytes(
            str(index).encode("ascii")
        )

    with pytest.raises(ValidationError, match=r"through suffix \(99\)"):
        common_utils.build_output_filename(
            "CollisionTest",
            "Mode",
            output_directory=tmp_path,
        )


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
