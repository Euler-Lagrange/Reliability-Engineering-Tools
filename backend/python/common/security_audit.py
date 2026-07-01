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

#: Modules that grant native / arbitrary-code execution. ``ctypes`` can call
#: into any DLL and would bypass every other rule in this file; the offline
#: sidecar has no legitimate use for it, so its import is a hard violation.
FORBIDDEN_NATIVE_MODULES: frozenset[str] = frozenset({"ctypes"})

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

#: ``os`` functions that execute a command or launch a file. ``system`` and
#: ``popen`` take a command line and are checked against the same allowlist as
#: subprocess; ``startfile`` launches an arbitrary file with its default app
#: (no command head to vet) and is flagged on any use.
_OS_EXEC_NAMES: frozenset[str] = frozenset({"system", "popen", "startfile"})
_OS_EXEC_ALWAYS_FLAG: frozenset[str] = frozenset({"startfile"})

#: Directory names skipped during a tree walk.
_SKIP_DIR_NAMES: frozenset[str] = frozenset(
    {"__pycache__", ".venv", "venv", ".git", "node_modules", "build", "dist", ".mypy_cache"}
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

ViolationKind = Literal[
    "network_import",
    "database_import",
    "native_import",
    "subprocess_command",
    "os_exec",
]


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


@dataclass
class _ExecBindings:
    """Local names bound to the ``subprocess`` / ``os`` modules and their
    exec-related functions within a single source file.

    Collected in a first pass so the call check works regardless of import
    form: ``import subprocess as sp`` (module alias) or ``from subprocess
    import run`` (bare-name import) both resolve back to the real function.
    """

    subprocess_modules: set[str]      # names bound to the subprocess module
    subprocess_funcs: dict[str, str]  # local name -> original subprocess func
    os_modules: set[str]              # names bound to the os module
    os_funcs: dict[str, str]          # local name -> original os func


def _classify_exec_call(
    node: ast.Call, bindings: _ExecBindings
) -> tuple[str, str | None] | None:
    """Classify a call node as command execution, honoring import aliases.

    Returns ``("subprocess", None)`` for a subprocess call,
    ``("os", <func>)`` for ``os.system``/``popen``/``startfile``, or ``None``
    when the call is not a monitored exec primitive.
    """
    func = node.func
    # Attribute form: ``<name>.<attr>(...)`` — e.g. subprocess.run, sp.run,
    # os.system.
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        recv, attr = func.value.id, func.attr
        if recv in bindings.subprocess_modules and attr in _SUBPROCESS_CALL_NAMES:
            return ("subprocess", None)
        if recv in bindings.os_modules and attr in _OS_EXEC_NAMES:
            return ("os", attr)
        return None
    # Bare-name form: ``<name>(...)`` — e.g. run(...) after ``from subprocess
    # import run``, or system(...) after ``from os import system``.
    if isinstance(func, ast.Name):
        origin = bindings.subprocess_funcs.get(func.id)
        if origin is not None and origin in _SUBPROCESS_CALL_NAMES:
            return ("subprocess", None)
        origin = bindings.os_funcs.get(func.id)
        if origin is not None and origin in _OS_EXEC_NAMES:
            return ("os", origin)
    return None


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


def _collect_bindings_and_imports(
    tree: ast.AST, path: Path, violations: list[Violation]
) -> _ExecBindings:
    """Report forbidden imports and record subprocess/os exec bindings."""
    subprocess_modules: set[str] = set()
    subprocess_funcs: dict[str, str] = {}
    os_modules: set[str] = set()
    os_funcs: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _check_import(path, node.lineno, alias.name, violations)
                if alias.name == "subprocess":
                    subprocess_modules.add(alias.asname or "subprocess")
                elif alias.name == "os":
                    os_modules.add(alias.asname or "os")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            # ``from urllib.request import foo`` imports ``urllib.request``
            # (level 0). Relative imports (level>0) are internal-only.
            if node.level == 0 and module:
                _check_import(path, node.lineno, module, violations)
                if module == "subprocess":
                    for alias in node.names:
                        subprocess_funcs[alias.asname or alias.name] = alias.name
                elif module == "os":
                    for alias in node.names:
                        os_funcs[alias.asname or alias.name] = alias.name
    return _ExecBindings(subprocess_modules, subprocess_funcs, os_modules, os_funcs)


def _check_exec_calls(
    tree: ast.AST, path: Path, bindings: _ExecBindings, violations: list[Violation]
) -> None:
    """Flag command-execution calls whose command is not in the allowlist."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        classified = _classify_exec_call(node, bindings)
        if classified is None:
            continue
        category, os_func = classified
        # os.startfile launches an arbitrary file — there is no command head
        # to vet, so any use is a violation.
        if os_func in _OS_EXEC_ALWAYS_FLAG:
            violations.append(
                Violation(
                    file=path,
                    line=node.lineno,
                    kind="os_exec",
                    detail=(
                        f"os.{os_func}(...) launches an arbitrary file and is "
                        f"not part of the vetted subprocess flow"
                    ),
                )
            )
            continue
        if not node.args:
            continue
        head = _resolve_command_head(node.args[0])
        if head is None:
            continue  # Dynamic call — out of static-audit scope.
        if head in SUBPROCESS_ALLOWLIST:
            continue
        if category == "subprocess":
            kind: ViolationKind = "subprocess_command"
            via = "subprocess"
        else:
            kind = "os_exec"
            via = f"os.{os_func}"
        violations.append(
            Violation(
                file=path,
                line=node.lineno,
                kind=kind,
                detail=(
                    f"{via} command '{head}' is not in the allowlist "
                    f"{sorted(SUBPROCESS_ALLOWLIST)}"
                ),
            )
        )


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
    # First pass: report forbidden imports and record how subprocess/os are
    # bound in this file. Second pass: check exec calls against those bindings.
    bindings = _collect_bindings_and_imports(tree, path, violations)
    _check_exec_calls(tree, path, bindings, violations)
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
        return
    native = _module_matches(module_name, FORBIDDEN_NATIVE_MODULES)
    if native is not None:
        violations.append(
            Violation(
                file=path,
                line=line,
                kind="native_import",
                detail=f"import of '{module_name}' matches forbidden native module '{native}'",
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
