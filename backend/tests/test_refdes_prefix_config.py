"""In-process tests for the sidecar's RefDes prefix config helpers.

Complements the subprocess round-trip tests in ``test_sidecar_main.py`` with
focused, monkeypatchable coverage of ``sidecar_main`` internals that can't be
exercised from outside the process:

- Batch 6 #4a: a CORRUPT (invalid-JSON / non-dict) config surfaces a warning
  while an ABSENT config stays warning-free — ``_load_refdes_config`` and
  ``_read_refdes_prefixes``.
- Batch 6 #4b: a failed ``os.replace`` during the atomic write must unlink the
  orphaned ``.tmp`` file and re-raise the original error rather than leaking it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import sidecar_main


def _isolate_config(monkeypatch, tmp_path: Path) -> Path:
    """Point the prefix config path at an isolated tmp file."""
    config_path = tmp_path / ".refdes_extractor_config.json"
    monkeypatch.setattr(sidecar_main, "_refdes_config_path", lambda: config_path)
    return config_path


# ---------------------------------------------------------------------------
# #4a: absent vs corrupt config
# ---------------------------------------------------------------------------

def test_load_refdes_config_absent_returns_no_warning(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    data, warning = sidecar_main._load_refdes_config()
    assert data == {}
    assert warning is None


def test_load_refdes_config_corrupt_json_returns_warning(monkeypatch, tmp_path: Path) -> None:
    config_path = _isolate_config(monkeypatch, tmp_path)
    config_path.write_text("{ not valid json ", encoding="utf-8")

    data, warning = sidecar_main._load_refdes_config()
    assert data == {}
    assert warning is not None
    assert "invalid JSON" in warning


def test_load_refdes_config_non_dict_returns_warning(monkeypatch, tmp_path: Path) -> None:
    config_path = _isolate_config(monkeypatch, tmp_path)
    # Valid JSON, but not an object — still unusable as a config.
    config_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    data, warning = sidecar_main._load_refdes_config()
    assert data == {}
    assert warning is not None


def test_read_refdes_prefixes_surfaces_corrupt_warning(monkeypatch, tmp_path: Path) -> None:
    config_path = _isolate_config(monkeypatch, tmp_path)
    config_path.write_text("{ broken", encoding="utf-8")

    result = sidecar_main._read_refdes_prefixes({})
    assert result["custom"] == []
    assert result["defaults"]  # IEEE-315 defaults still present
    assert "warning" in result
    assert "invalid JSON" in result["warning"]


def test_read_refdes_prefixes_absent_config_has_no_warning(monkeypatch, tmp_path: Path) -> None:
    _isolate_config(monkeypatch, tmp_path)
    result = sidecar_main._read_refdes_prefixes({})
    assert result["custom"] == []
    assert "warning" not in result


# ---------------------------------------------------------------------------
# #4b: os.replace failure must not orphan the .tmp file
# ---------------------------------------------------------------------------

def test_write_refdes_prefixes_cleans_up_tmp_on_replace_failure(
    monkeypatch, tmp_path: Path
) -> None:
    config_path = _isolate_config(monkeypatch, tmp_path)
    tmp_leftover = config_path.with_name(config_path.name + ".tmp")

    def _boom(_src, _dst):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(sidecar_main.os, "replace", _boom)

    with pytest.raises(OSError, match="simulated rename failure"):
        sidecar_main._write_refdes_prefixes({"prefixes": ["XU"]})

    # The orphaned temp file is cleaned up, and the destination was not created.
    assert not tmp_leftover.exists()
    assert not config_path.exists()


def test_write_refdes_prefixes_succeeds_and_persists(monkeypatch, tmp_path: Path) -> None:
    config_path = _isolate_config(monkeypatch, tmp_path)

    result = sidecar_main._write_refdes_prefixes({"prefixes": ["xu", "PS"]})
    assert result["custom"] == ["XU", "PS"]
    assert result["restart_required"] is True
    assert json.loads(config_path.read_text(encoding="utf-8"))["ref_prefixes"] == ["XU", "PS"]
    # No temp file left behind on the happy path.
    assert not config_path.with_name(config_path.name + ".tmp").exists()
