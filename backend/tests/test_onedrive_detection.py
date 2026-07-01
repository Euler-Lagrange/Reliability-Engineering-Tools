"""Decision A: OneDrive path detection prefers the OneDrive env vars.

``_is_onedrive_path`` decides whether an unreadable file should run the
``attrib +P`` cloud-hydration path. The original heuristic keyed only on the
substring ``"onedrive"`` in the path, which missed OneDrive mounted at a
non-standard location and false-hit a folder merely named "onedrive". These
tests pin the env-var-first behavior with a substring fallback.
"""

from __future__ import annotations

from pathlib import Path

from common.utils import _is_onedrive_path


def test_onedrive_path_detected_via_env_var(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "OneDrive - Contoso"
    monkeypatch.setenv("OneDriveCommercial", str(root))
    assert _is_onedrive_path(root / "sub" / "bom.xlsx") is True


def test_non_standard_onedrive_location_without_substring(
    monkeypatch, tmp_path: Path
) -> None:
    # OneDrive mounted somewhere with no "onedrive" in the path — the env var
    # still identifies it (the substring heuristic alone would miss this).
    root = tmp_path / "CloudMount"
    monkeypatch.setenv("OneDrive", str(root))
    monkeypatch.delenv("OneDriveCommercial", raising=False)
    monkeypatch.delenv("OneDriveConsumer", raising=False)
    assert _is_onedrive_path(root / "file.xlsx") is True


def test_substring_fallback_when_no_env(monkeypatch) -> None:
    monkeypatch.delenv("OneDrive", raising=False)
    monkeypatch.delenv("OneDriveCommercial", raising=False)
    monkeypatch.delenv("OneDriveConsumer", raising=False)
    assert _is_onedrive_path(Path(r"C:\Users\me\OneDrive\bom.xlsx")) is True


def test_plain_local_path_is_not_treated_as_cloud(monkeypatch) -> None:
    # NB: use a hardcoded path with no "onedrive" token — pytest's tmp_path
    # embeds the TEST NAME, so a test named "...onedrive..." would false-hit the
    # substring fallback (which is exactly the fragility Decision A improves on).
    monkeypatch.delenv("OneDrive", raising=False)
    monkeypatch.delenv("OneDriveCommercial", raising=False)
    monkeypatch.delenv("OneDriveConsumer", raising=False)
    assert _is_onedrive_path(Path(r"C:\Projects\data\bom.xlsx")) is False


def test_directory_boundary_prevents_prefix_false_match(
    monkeypatch, tmp_path: Path
) -> None:
    # A root at .../Cloud must not match a sibling .../CloudX by raw prefix.
    root = tmp_path / "Cloud"
    monkeypatch.setenv("OneDrive", str(root))
    monkeypatch.delenv("OneDriveCommercial", raising=False)
    monkeypatch.delenv("OneDriveConsumer", raising=False)
    sibling = tmp_path / "CloudX" / "file.xlsx"
    assert _is_onedrive_path(sibling) is False
