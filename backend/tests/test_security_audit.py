"""
Regression test for the static security audit.

The audit lives at ``backend/python/common/security_audit.py``. These tests:

1. Assert that the current backend tree is clean — no forbidden imports and
   no out-of-allowlist subprocess calls. This is the long-lived guardrail
   that catches accidental introductions during code review.
2. Exercise the policy logic against synthetic source files so that the
   detection itself stays honest as the codebase evolves.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# Make ``common.security_audit`` importable when this test runs from the
# repo root via ``pytest backend/tests``. Mirrors the sidecar's import policy:
# everything resolves from ``backend/python``.
ROOT = Path(__file__).resolve().parents[2]
BACKEND_PYTHON = ROOT / "backend" / "python"
if str(BACKEND_PYTHON) not in sys.path:
    sys.path.insert(0, str(BACKEND_PYTHON))

from common.security_audit import (  # noqa: E402  (sys.path manipulation above)
    FORBIDDEN_DATABASE_MODULES,
    FORBIDDEN_NETWORK_MODULES,
    SUBPROCESS_ALLOWLIST,
    audit_file,
    audit_tree,
    main,
)


# ---------------------------------------------------------------------------
# Live regression — the real backend tree must be clean.
# ---------------------------------------------------------------------------


def test_backend_tree_has_no_violations() -> None:
    """The shipping backend tree must satisfy the security policy."""
    violations = audit_tree(BACKEND_PYTHON)
    if violations:
        formatted = "\n".join(v.format(root=BACKEND_PYTHON) for v in violations)
        pytest.fail(
            f"Security audit found {len(violations)} violation(s) in {BACKEND_PYTHON}:\n{formatted}"
        )


def test_test_tree_is_also_clean() -> None:
    """The integration tests themselves must respect the same policy."""
    test_root = Path(__file__).parent
    violations = audit_tree(test_root)
    if violations:
        formatted = "\n".join(v.format(root=test_root) for v in violations)
        pytest.fail(
            f"Security audit found {len(violations)} violation(s) in {test_root}:\n{formatted}"
        )


# ---------------------------------------------------------------------------
# Synthetic positive cases — the audit must catch known-bad patterns.
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, name: str, source: str) -> Path:
    target = tmp_path / name
    target.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
    return target


def test_detects_network_import_via_import(tmp_path: Path) -> None:
    target = _write(tmp_path, "uses_socket.py", "import socket\n")
    violations = audit_file(target)
    assert len(violations) == 1
    assert violations[0].kind == "network_import"
    assert "socket" in violations[0].detail


def test_detects_network_import_via_from(tmp_path: Path) -> None:
    target = _write(tmp_path, "uses_requests.py", "from requests import get\n")
    violations = audit_file(target)
    assert len(violations) == 1
    assert violations[0].kind == "network_import"
    assert "requests" in violations[0].detail


def test_detects_urllib_request_but_not_urllib_parse(tmp_path: Path) -> None:
    target = _write(
        tmp_path,
        "mixed_urllib.py",
        """
        from urllib.parse import urlparse, unquote
        from urllib.request import urlopen
        """,
    )
    violations = audit_file(target)
    assert len(violations) == 1
    assert violations[0].kind == "network_import"
    assert "urllib.request" in violations[0].detail


def test_detects_database_import(tmp_path: Path) -> None:
    target = _write(tmp_path, "uses_sqlite.py", "import sqlite3\n")
    violations = audit_file(target)
    assert len(violations) == 1
    assert violations[0].kind == "database_import"
    assert "sqlite3" in violations[0].detail


def test_detects_subprocess_command_outside_allowlist(tmp_path: Path) -> None:
    target = _write(
        tmp_path,
        "bad_subprocess.py",
        """
        import subprocess
        subprocess.run(["curl", "https://example.com"], check=True)
        """,
    )
    violations = audit_file(target)
    assert len(violations) == 1
    assert violations[0].kind == "subprocess_command"
    assert "curl" in violations[0].detail


def test_allows_attrib_subprocess_call(tmp_path: Path) -> None:
    target = _write(
        tmp_path,
        "uses_attrib.py",
        """
        import subprocess
        from pathlib import Path
        path = Path("foo.xlsx")
        subprocess.run(["attrib", "+P", str(path)], check=True)
        """,
    )
    violations = audit_file(target)
    assert violations == []


def test_skips_dynamic_subprocess_first_arg(tmp_path: Path) -> None:
    """A subprocess call whose first arg is a variable is out of static scope."""
    target = _write(
        tmp_path,
        "dynamic_subprocess.py",
        """
        import subprocess
        import sys
        subprocess.Popen([sys.executable, "-c", "print(1)"])
        """,
    )
    violations = audit_file(target)
    # ``sys.executable`` is dynamic — the audit cannot statically resolve it
    # and must skip rather than false-positive.
    assert violations == []


def test_handles_bare_string_subprocess_call(tmp_path: Path) -> None:
    target = _write(
        tmp_path,
        "string_subprocess.py",
        """
        import subprocess
        subprocess.run("rm -rf /tmp/whatever")
        """,
    )
    violations = audit_file(target)
    assert len(violations) == 1
    assert violations[0].kind == "subprocess_command"
    assert "rm" in violations[0].detail


def test_relative_imports_are_ignored(tmp_path: Path) -> None:
    target = _write(
        tmp_path,
        "relative.py",
        "from .helpers import thing\n",
    )
    violations = audit_file(target)
    assert violations == []


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------


def test_cli_returns_zero_on_clean_tree(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path, "ok.py", "x = 1\n")
    exit_code = main(["--root", str(tmp_path), "--strict"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "clean" in out


def test_cli_returns_one_on_dirty_tree_when_strict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path, "bad.py", "import socket\n")
    exit_code = main(["--root", str(tmp_path), "--strict"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "socket" in captured.out


def test_cli_default_is_non_strict(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path, "bad.py", "import socket\n")
    exit_code = main(["--root", str(tmp_path)])
    # Without --strict, the CLI prints violations but does not fail.
    assert exit_code == 0


# ---------------------------------------------------------------------------
# Policy sanity — make sure the public sets are well-formed.
# ---------------------------------------------------------------------------


def test_allowlist_is_lowercase() -> None:
    assert all(name == name.lower() for name in SUBPROCESS_ALLOWLIST)


def test_forbidden_sets_are_disjoint() -> None:
    overlap = FORBIDDEN_NETWORK_MODULES & FORBIDDEN_DATABASE_MODULES
    assert overlap == set(), f"Network/database forbidden sets overlap: {overlap}"


# ---------------------------------------------------------------------------
# End-to-end via the sidecar self-test path.
# ---------------------------------------------------------------------------


def test_sidecar_self_test_runs_security_audit() -> None:
    """``sidecar_main.py --self-test`` should embed the audit and pass cleanly."""
    sidecar = BACKEND_PYTHON / "sidecar_main.py"
    result = subprocess.run(
        [sys.executable, str(sidecar), "--self-test"],
        cwd=str(BACKEND_PYTHON),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"sidecar self-test failed:\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "security_audit: clean" in result.stdout
