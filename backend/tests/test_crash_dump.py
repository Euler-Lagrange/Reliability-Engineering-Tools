"""Decision B: crash dumps carry a "review before sharing" banner and bound any
embedded value so a BOM / part value echoed in an error can't leak in full.
"""

from __future__ import annotations

from pathlib import Path

from common.logger import _truncate_for_crash, write_crash_dump


def test_truncate_for_crash_bounds_long_text() -> None:
    assert _truncate_for_crash("short", 100) == "short"
    out = _truncate_for_crash("y" * 1000, 100)
    assert out.startswith("y" * 100)
    assert "truncated" in out
    assert len(out) < 1000


def test_crash_dump_has_banner_and_truncates_a_long_value(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RELIABILITY_TOOLS_LOG_DIR", str(tmp_path))
    secret = "X" * 5000
    try:
        raise ValueError("part " + secret)
    except ValueError as exc:
        path = write_crash_dump("sidecar", type(exc), exc, exc.__traceback__)

    assert path is not None and path.exists()
    text = path.read_text(encoding="utf-8")
    assert "may contain source data" in text.lower()
    assert "review it before" in text.lower()
    assert "truncated" in text
    # The full 5000-char value must NOT appear anywhere (bounded per line).
    assert secret not in text


def test_crash_dump_short_exception_is_intact(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RELIABILITY_TOOLS_LOG_DIR", str(tmp_path))
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        path = write_crash_dump(
            "thread", type(exc), exc, exc.__traceback__, thread_name="worker-1"
        )

    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "may contain source data" in text.lower()
    assert "review it before" in text.lower()
    assert "RuntimeError: boom" in text
    assert "Thread:     worker-1" in text
    # A short, benign dump is not truncated.
    assert "truncated" not in text
