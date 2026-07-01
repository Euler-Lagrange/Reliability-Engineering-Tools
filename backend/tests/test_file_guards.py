"""Decision C: the file-size guard that protects fully-loaded reads (e.g.
``analyze_template``) from out-of-memory on a pathologically large workbook.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from common.utils import ensure_file_size_within


def test_file_size_guard_allows_a_small_file(tmp_path: Path) -> None:
    target = tmp_path / "ok.bin"
    target.write_bytes(b"x" * 100)
    # Under the cap -> no exception.
    ensure_file_size_within(target, 1024, what="template workbook")


def test_file_size_guard_rejects_an_oversized_file(tmp_path: Path) -> None:
    target = tmp_path / "big.bin"
    target.write_bytes(b"x" * 4096)
    with pytest.raises(ValueError, match="too large"):
        ensure_file_size_within(target, 1024, what="template workbook")


def test_file_size_guard_ignores_a_missing_path(tmp_path: Path) -> None:
    # An unstattable path is deferred to the downstream open, not raised here.
    ensure_file_size_within(tmp_path / "does_not_exist.bin", 1024)
