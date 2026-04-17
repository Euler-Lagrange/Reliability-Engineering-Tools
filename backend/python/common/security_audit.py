"""
Static security audit for the offline sidecar.

The Reliability Tools sidecar is offline / air-gapped: it must never reach
the network or hit a database, and the only subprocess commands it is
allowed to invoke are the small set we have explicitly vetted. This module
enforces those rules by AST-walking every ``.py`` file under
``backend/python/`` and reporting:

1. Imports of network modules (``socket``, ``urllib.request``, ``http.client``,
   ``requests``, ``httpx``, ...).
2. Imports of database modules (``sqlite3``, ``psycopg``, ``pymongo``,
   ``sqlalchemy``, ...).
3. ``subprocess.*`` calls whose statically-resolvable command head is not
   in :data:`SUBPROCESS_ALLOWLIST`.

The audit deliberately uses *prefix* matching for forbidden modules so that
pure-string submodules such as ``urllib.parse`` (which performs no I/O) are
not flagged. Bare imports of variable command names are skipped — this
audit is a regression net against accidental introductions, not an
adversarial sandbox.

Run as a CLI:

    python -m common.security_audit [--root backend/python] [--strict]

Used as:

- A pytest regression test (``backend/tests/test_security_audit.py``).
- A pre-flight check inside ``sidecar_main.py --self-test``.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Literal

# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

#: Modules whose import indicates a network capability. Matched by exact name
#: or by dotted prefix (``urllib.request`` matches ``urllib.request.foo`` but
#: NOT ``urllib.parse``). Pure-parsing helpers like ``urllib.parse`` and
#: ``http`` (status-code constants) are intentionally NOT in this set.
FORBIDDEN_NETWORK_MODULES: frozenset[str] = frozenset(
    {
        "socket",
        "ssl",
        "asyncio.streams",
        "urllib.request",
        "urllib.error",
        "urllib.response",
        "urllib.robotparser",
        "http.client",
        "http.server",
        "http.cookiejar",
        "httpx",
        "requests",
        "aiohttp",
        "ftplib",
        "smtplib",
        "imaplib",
        "poplib",
        "telnetlib",
        "nntplib",
        "xmlrpc.client",
        "xmlrpc.server",
    }
)

#: Modules whose import indicates a database client capability.
FORBIDDEN_DATABASE_MODULES: frozenset[str] = frozenset(
    {
        "sqlite3",
        "mysql",
        "mysql.connector",
        "pymysql",
        "psycopg",
        "psycopg2",
        "asyncpg",
        "pymongo",
        "redis",
        "sqlalchemy",
    }
)

#: Subprocess executables we have vetted as safe to invoke.
#:
#: - ``attrib`` — Windows file-attribute query/set, used by
#:   ``common/utils.py`` to detect and hydrate OneDrive cloud-only files.
#:
#: The backend only shells out to ``attrib`` today. The allowlist is
#: deliberately minimal so any new subprocess call is an explicit audit
#: regression that must be justified and added here.
SUBPROCESS_ALLOWLIST: frozenset[str] = frozenset({"attrib"})

#: Subprocess module functions whose first positional argument should be
#: inspected against the allowlist.
_SUBPROCESS_CALL_NAMES: frozenset[str] = frozenset(
    {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"}
)

#: Directory names skipped during a tree walk.
_SKIP_DIR_NAMES: frozenset[str] = frozenset(
    {"__pycache__", ".venv", "venv", ".git", "node_modules", "build", "dist", ".mypy_cache"}
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

ViolationKind = Literal["network_import", "database_import", "subprocess_command"]


@dataclass(frozen=True)
class Violation:
    """A single security policy violation."""

    file: Path
    line: int
    kind: ViolationKind
    detail: str

    def format(self, root: Path | None = None) -> str:
        try:
            display = self.file.relative_to(root) if root is not None else self.file
        except ValueError:
            display = self.file
        return f"{display}:{self.line}: [{self.kind}] {self.detail}"


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------


def _module_matches(module_name: str, forbidden: Iterable[str]) -> str | None:
    """Return the matching forbidden entry, or ``None`` if no match.

    Matching is exact OR by dotted prefix: ``urllib.request`` matches
    ``urllib.request`` and ``urllib.request.urlretrieve``, but does NOT
    match ``urllib.parse``.
    """
    if not module_name:
        return None
    for entry in forbidden:
        if module_name == entry or module_name.startswith(entry + "."):
            return entry
    return None


def _is_subprocess_call(node: ast.Call) -> bool:
    """True iff ``node`` is a call to ``subprocess.<allowed-name>``."""
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id == "subprocess" and func.attr in _SUBPROCESS_CALL_NAMES
    return False


def _resolve_command_head(arg: ast.AST) -> str | None:
    """Statically resolve the command name from a subprocess call's first arg.

    Returns ``None`` when the call form is dynamic (variables, f-strings,
    function results) — those cannot be checked here and are left to runtime.
    """
    # Form: subprocess.run(["attrib", "+P", str(path)])
    if isinstance(arg, (ast.List, ast.Tuple)) and arg.elts:
        head = arg.elts[0]
        if isinstance(head, ast.Constant) and isinstance(head.value, str):
            return Path(head.value).name.lower().removesuffix(".exe")
        return None  # First element is dynamic — skip.
    # Form: subprocess.run("attrib +P file.xlsx")
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        first = arg.value.strip().split(None, 1)[0] if arg.value.strip() else ""
        if first:
            return Path(first).name.lower().removesuffix(".exe")
    return None


# ---------------------------------------------------------------------------
# Per-file audit
# ---------------------------------------------------------------------------


def audit_file(path: Path) -> list[Violation]:
    """Return every policy violation discovered in a single source file."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [
            Violation(
                file=path,
                line=0,
                kind="network_import",
                detail=f"could not read source: {exc}",
            )
        ]

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [
            Violation(
                file=path,
                line=exc.lineno or 0,
                kind="network_import",
                detail=f"syntax error: {exc.msg}",
            )
        ]

    violations: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _check_import(path, node.lineno, alias.name, violations)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            # Treat ``from urllib.request import foo`` as importing
            # ``urllib.request`` (level=0). Relative imports (level>0) are
            # internal-only and need no policy check.
            if node.level == 0 and module:
                _check_import(path, node.lineno, module, violations)
        elif isinstance(node, ast.Call) and _is_subprocess_call(node):
            if not node.args:
                continue
            head = _resolve_command_head(node.args[0])
            if head is None:
                continue  # Dynamic call — out of static-audit scope.
            if head not in SUBPROCESS_ALLOWLIST:
                violations.append(
                    Violation(
                        file=path,
                        line=node.lineno,
                        kind="subprocess_command",
                        detail=(
                            f"subprocess command '{head}' is not in the allowlist "
                            f"{sorted(SUBPROCESS_ALLOWLIST)}"
                        ),
                    )
                )
    return violations


def _check_import(
    path: Path, line: int, module_name: str, violations: list[Violation]
) -> None:
    network = _module_matches(module_name, FORBIDDEN_NETWORK_MODULES)
    if network is not None:
        violations.append(
            Violation(
                file=path,
                line=line,
                kind="network_import",
                detail=f"import of '{module_name}' matches forbidden network module '{network}'",
            )
        )
        return
    database = _module_matches(module_name, FORBIDDEN_DATABASE_MODULES)
    if database is not None:
        violations.append(
            Violation(
                file=path,
                line=line,
                kind="database_import",
                detail=f"import of '{module_name}' matches forbidden database module '{database}'",
            )
        )


# ---------------------------------------------------------------------------
# Tree walk
# ---------------------------------------------------------------------------


def _iter_python_files(root: Path) -> Iterator[Path]:
    if root.is_file():
        if root.suffix == ".py":
            yield root
        return
    for entry in sorted(root.iterdir()):
        if entry.is_dir():
            if entry.name in _SKIP_DIR_NAMES:
                continue
            yield from _iter_python_files(entry)
        elif entry.suffix == ".py":
            yield entry


def audit_tree(root: Path) -> list[Violation]:
    """Audit every Python file under ``root`` and return all violations."""
    root = root.resolve()
    violations: list[Violation] = []
    for file_path in _iter_python_files(root):
        violations.extend(audit_file(file_path))
    return violations


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="security_audit",
        description="Static security audit for the Reliability Tools sidecar.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Directory to audit (default: backend/python).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any violations are found.",
    )
    args = parser.parse_args(argv)

    root: Path = args.root.resolve()
    if not root.exists():
        print(f"security_audit: root path does not exist: {root}", file=sys.stderr)
        return 2

    violations = audit_tree(root)
    if not violations:
        print(f"security_audit: clean ({root})")
        return 0

    for violation in violations:
        print(violation.format(root=root))
    print(f"security_audit: {len(violations)} violation(s) under {root}", file=sys.stderr)
    return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
