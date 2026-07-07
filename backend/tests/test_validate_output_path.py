"""validate_output_path exception-type consistency (deferred LOW fix D).

User-actionable failures (missing folder, path escape, MAX_PATH overflow,
non-string filename) must raise the project's ``ValidationError`` rather than
raw ``ValueError`` / ``TypeError`` so they classify like every other tool
error. Message text is unchanged.
"""
from __future__ import annotations

import os

import pytest

from common.exceptions import ValidationError
from common.utils import validate_output_path


def test_happy_path_returns_path_within_folder(tmp_path):
    result = validate_output_path(str(tmp_path), "report.xlsx")
    assert result == os.path.realpath(os.path.join(str(tmp_path), "report.xlsx"))


def test_missing_folder_raises_validation_error(tmp_path):
    missing = tmp_path / "does_not_exist"
    with pytest.raises(ValidationError) as exc:
        validate_output_path(str(missing), "report.xlsx")
    assert "Output folder does not exist" in str(exc.value)


def test_path_escape_raises_validation_error(tmp_path):
    with pytest.raises(ValidationError) as exc:
        validate_output_path(str(tmp_path), os.path.join("..", "..", "escape.xlsx"))
    assert "Output path escapes folder" in str(exc.value)


def test_non_string_filename_raises_validation_error(tmp_path):
    with pytest.raises(ValidationError) as exc:
        validate_output_path(str(tmp_path), 123)  # type: ignore[arg-type]
    assert "filename must be a string" in str(exc.value)


@pytest.mark.skipif(os.name != "nt", reason="MAX_PATH guard is Windows-only")
def test_max_path_overflow_raises_validation_error(tmp_path):
    long_name = ("x" * 300) + ".xlsx"
    with pytest.raises(ValidationError) as exc:
        validate_output_path(str(tmp_path), long_name)
    assert "Windows" in str(exc.value)
