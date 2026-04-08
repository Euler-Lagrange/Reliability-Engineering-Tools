# Testing

## Test Inventory

| Suite | Path | Count | Framework |
|-------|------|-------|-----------|
| Backend integration | `backend/tests/test_sidecar_main.py` | 33 | pytest |
| Backend security audit | `backend/tests/test_security_audit.py` | 17 | pytest |
| Backend cancel bridge | `backend/tests/test_cancel_bridge.py` | 8 | pytest |
| Backend FMEA Phase D | `backend/tests/test_fmea_phase_d.py` | 12 | pytest |
| Frontend shell | `frontend/src/app/App.test.tsx` | 4 | Vitest + RTL |
| Frontend component | `frontend/src/components/CustomSelect.test.tsx` | 1 | Vitest + RTL |
| Frontend run lifecycle | `frontend/src/shared/backend/runLifecycle.test.ts` | 8 | Vitest |
| Frontend theme registry | `frontend/src/shared/theme/themeRegistry.test.ts` | 10 | Vitest |
| Frontend role-request sequence | `frontend/src/shared/hooks/useRoleRequestSequence.test.ts` | 5 | Vitest |
| Frontend global log store | `frontend/src/stores/globalLogStore.test.ts` | 6 | Vitest |
| **Total** | | **104** | |

## Backend Tests

`backend/tests/test_sidecar_main.py` exercises the sidecar end-to-end as a
real subprocess. Every test in that file starts a fresh
`python sidecar_main.py` and talks to it over stdin/stdout.

In-process unit tests (`test_cancel_bridge.py`, `test_fmea_phase_d.py`)
import backend modules directly; see **In-process tests** below for the
`conftest.py` shim that makes those imports resolve.

### Subprocess pattern

Each test calls `_start_sidecar()`, which:

1. Spawns `subprocess.Popen([sys.executable, str(SIDECAR)], stdin=PIPE,
   stdout=PIPE, stderr=DEVNULL, text=True, env=SIDECAR_ENV)`.
2. Wraps the process in a `_SidecarReader` (one persistent reader thread per
   process) that pumps `stdout.readline()` into a `queue.Queue`.
3. Reads the initial `ready` envelope to confirm the sidecar started cleanly.
4. Returns `(process, reader)`. The test must `process.terminate()` and
   `process.wait()` in a `finally` block.

### `_SidecarReader`

```python
class _SidecarReader:
    def __init__(self, process: subprocess.Popen[str]) -> None:
        self._process = process
        self._queue: queue.Queue[str] = queue.Queue()
        self._thread = threading.Thread(target=self._reader, args=(process,), daemon=True)
        self._thread.start()
```

One thread per process drains stdout into a queue. `read_until(...)` filters
queued lines by `request_id`, `run_id`, and `kind` until a match arrives or
the deadline elapses.

### `_READERS` keyed by `id(process)`

```python
_READERS: dict[int, _SidecarReader] = {}

def _get_reader(process: subprocess.Popen[str]) -> _SidecarReader:
    key = id(process)
    ...
```

The cache key is `id(process)`, **not** `process.pid`. PIDs are recycled
quickly on Windows; an `id()` key guarantees that two distinct `Popen`
objects never share a reader, even if the OS reuses the PID slot
immediately after termination.

### `SIDECAR_ENV`

```python
_TEST_LOG_DIR = tempfile.mkdtemp(prefix="sidecar_test_logs_")
SIDECAR_ENV = {
    **os.environ,
    "SIDECAR_HEARTBEAT_INTERVAL": "9999",   # silence heartbeat
    "RELIABILITY_TOOLS_LOG_DIR": _TEST_LOG_DIR,
    "PYTHONDONTWRITEBYTECODE": "1",
    "SIDECAR_LOG_LEVEL": "CRITICAL",        # avoid Windows rotation contention
}
```

`stderr=subprocess.DEVNULL` is mandatory — leaving stderr piped without a
draining thread will deadlock the sidecar once the OS pipe buffer fills.

### Optional dependencies

RefDes Extractor tests start with `pytest.importorskip("fitz")` so the suite
remains usable on machines without PyMuPDF installed.

### In-process tests (`conftest.py` sys.path shim)

`backend/tests/conftest.py` prepends `backend/python/` to `sys.path` so
in-process unit tests can `import fmea.fmea_generator_logic`,
`import common.cancel`, etc. directly:

```python
# backend/tests/conftest.py
import sys
from pathlib import Path

BACKEND_PYTHON = Path(__file__).resolve().parents[1] / "python"
if str(BACKEND_PYTHON) not in sys.path:
    sys.path.insert(0, str(BACKEND_PYTHON))
```

This is safe for `test_sidecar_main.py` because those tests spawn fresh
Python interpreters with their own path resolution — the parent pytest
process's `sys.path` is inherited through env vars, not through the
subprocess's own module cache.

Use the in-process pattern for:

- Pure-logic tests that don't need protocol framing (`test_fmea_phase_d.py`
  mostly builds fixtures on disk, calls
  `fmea.fmea_generator_logic.generate_fmea(...)`, and asserts on the
  resulting workbook).
- Unit tests for shared utilities (`test_cancel_bridge.py` exercises the
  `_CancelBridge` class used by every runtime adapter).

Use the subprocess pattern (`test_sidecar_main.py`) whenever you need to
test the NDJSON protocol, command routing, heartbeats, run lifecycle,
cancellation signals, or any multi-command interaction.

### `options` in request bodies

`validate_run` and `execute_run` no longer accept an `enrichments` field —
the backend hard-fails on any truthy value. FMEA workflows now require an
`options` object:

- `options.failureModesStandard`: `"FMD-91"` or `"FMD-2016"` (required for
  all FMEA workflows)
- `options.columnSelection`: `{ mode, columns }` (optional)

The FMEA-related test fixtures in `test_sidecar_main.py` send
`"options": {"failureModesStandard": "FMD-2016"}` in every request body;
new FMEA tests must do the same or validation will reject the request.

## Backend Test Categories

| Category | Representative tests |
|----------|----------------------|
| Health and heartbeat | `test_sidecar_health_check_round_trip`, `test_sidecar_emits_heartbeat_within_interval` |
| Inspect, list_sheets, analyze_template | `test_sidecar_lists_excel_sheets`, `test_sidecar_inspects_input_headers_and_preview`, `test_sidecar_analyzes_template_metadata` |
| FMEA validate | `test_sidecar_validates_phase4_standard_run`, `test_sidecar_validates_fill_gaps_run`, `test_sidecar_validates_template_preserve_run`, `test_sidecar_rejects_unmigrated_output_strategy` |
| FMEA execute | `test_sidecar_executes_phase4_standard_run`, `test_sidecar_executes_fill_gaps_run`, `test_sidecar_executes_template_preserve_run` |
| BOM Compare | `test_sidecar_validates_bom_compare_group`, `test_sidecar_executes_bom_compare_group`, `test_sidecar_validates_bom_compare_custom`, `test_sidecar_executes_bom_compare_custom` |
| Failure Rate | `test_sidecar_validates_failure_rate_link`, `test_sidecar_executes_failure_rate_link` |
| RefDes Extractor | `test_sidecar_validates_refdes_extract`, `test_sidecar_executes_refdes_extract`, `test_sidecar_rejects_refdes_missing_pdf` |
| Cancel flow | `test_sidecar_cancels_active_run`, `test_sidecar_cancel_of_nonexistent_run_returns_error` |
| Single-active-run guard | `test_sidecar_rejects_second_execute_while_run_is_active` |
| Error recovery | `test_sidecar_execute_emits_backend_error_on_missing_columns`, `test_sidecar_remains_responsive_after_failed_run` |
| Missing-file validation | `test_sidecar_validate_rejects_missing_required_files` |
| FMEA Phase D (in-process) | `test_inheritance_creates_bom_addition`, `test_inheritance_writes_bom_additions_sheet`, `test_variant_in_bom_does_not_trigger_inheritance`, `test_variant_base_also_missing_falls_through`, `test_failure_modes_standard_drives_headers`, `test_validate_run_accepts_fill_gaps_with_preserve_formatting`, `test_failure_modes_standard_required_in_validation`, `test_usage_fraction_uses_source_variant_count_not_addition_count`, `test_inherited_variant_does_not_get_false_usage_warning`, `test_legacy_enrichment_payload_is_rejected`, `test_failure_modes_standard_filters_mixed_standard_file`, `test_functional_to_piecepart_preserves_functional_rows` |

## Frontend Tests

The frontend suite uses **Vitest** with **React Testing Library** and
**jsdom**. The shell is forced into browser-mock mode at test time:
`isTauriRuntime()` checks `window.__TAURI_INTERNALS__` / `window.__TAURI__`,
neither of which exists under jsdom, so the client returns mock data from
`frontend/src/mocks/scenarios.ts` instead of calling Tauri.

| File | Tests |
|------|-------|
| `frontend/src/app/App.test.tsx` | 4 — shell render, tool switching, theme application, notification dismissal |
| `frontend/src/components/CustomSelect.test.tsx` | 1 — keyboard navigation |
| `frontend/src/shared/backend/runLifecycle.test.ts` | 8 — run lifecycle state transitions (ack, progress, result, cancel, error, reset) |
| `frontend/src/shared/theme/themeRegistry.test.ts` | 10 — theme registry consistency (ids, labels, icons, colorScheme, rail visibility) |
| `frontend/src/shared/hooks/useRoleRequestSequence.test.ts` | 5 — per-role async request sequencing (stale response suppression) |
| `frontend/src/stores/globalLogStore.test.ts` | 6 — global log ring buffer: append, clear, toggle, filter, export format, capacity |

`vitest.setup.ts` is configured in `vite.config.ts`. It registers
`@testing-library/jest-dom` matchers and shims `matchMedia`, pointer
capture, and `scrollIntoView` so Radix components render under jsdom.
Component tests run **without** the global `frontend/src/theme/styles.css`
(that file is only imported by `main.tsx`, which Vitest never executes);
tests that depend on theme tokens should mount the relevant CSS-module
file directly.

## Run Commands

```bash
# Backend (full suite)
.venv/Scripts/python.exe -m pytest backend/tests -q

# Backend (single test)
.venv/Scripts/python.exe -m pytest backend/tests/test_sidecar_main.py::test_sidecar_health_check_round_trip -v

# Frontend
cd frontend
npm test
npm run typecheck
```

The release pipeline (`scripts/release.bat`) runs `pytest backend/tests -q`
followed by `npm test` before the sidecar and desktop builds.

## Writing New Backend Tests

Use the existing helpers — do not invent new ones.

```python
def test_my_new_command(tmp_path: Path) -> None:
    process, _reader = _start_sidecar()
    try:
        result = _send_command(
            process,
            request_id="req-1",
            command="my_command",
            body={"path": str(tmp_path / "file.xlsx")},
        )
        assert result["kind"] == "result"
        assert result["payload"]["status"] == "ok"
    finally:
        process.terminate()
        process.wait(timeout=10)
```

### Streaming runs

For `execute_run` tests, send the command, read the `ack` to capture
`run_id`, then call `_read_until(process, run_id=run_id, kind="result")`
(or `"backend_error"`, `"cancelled"`).

```python
ack = _send_command(process, "req-2", "execute_run", body)
run_id = ack["run_id"]
final = _read_until(process, run_id=run_id, kind="result", timeout=60)
assert final["payload"]["status"] == "success"
```

Always wrap the entire test body in `try` / `finally: process.terminate(); process.wait()`.
A leaked sidecar will hold file handles and break later tests.

## Writing New Frontend Tests

Place test files next to the component as `{Component}.test.tsx`. Vitest
discovers them automatically.

```typescript
import { describe, expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MyComponent } from "./MyComponent";

describe("MyComponent", () => {
  test("renders title", () => {
    render(<MyComponent title="Hello" />);
    expect(screen.getByRole("heading", { name: "Hello" })).toBeInTheDocument();
  });
});
```

Use `userEvent` for keyboard and click interactions. Avoid `fireEvent` for
new tests — it bypasses React's event scheduling and produces flaky results.

## Known Gotchas

These are scars from the test infrastructure stabilization. Do not undo any
of them without strong evidence.

- **stderr deadlock** — leaving `stderr=subprocess.PIPE` without a draining
  thread will hang the sidecar once the pipe buffer fills (~64 KB on
  Windows). Always use `stderr=subprocess.DEVNULL` in tests.
- **Reader races** — earlier versions spawned a fresh reader per command,
  which let one reader steal lines another was waiting on. The persistent
  `_SidecarReader` per process plus the `_READERS` cache fixes this.
- **PID recycling** — Windows re-uses PIDs aggressively. The cache key in
  `_READERS` is `id(process)`, not `process.pid`, so a recycled PID never
  hits a stale reader.
- **Heartbeat noise** — at the default 5 s interval, heartbeats interleave
  with command responses and force every test to filter them. Setting
  `SIDECAR_HEARTBEAT_INTERVAL=9999` makes test output deterministic.
- **Log file contention** — multiple sidecars writing to the same default
  log directory triggered Windows `PermissionError` on rotation.
  `RELIABILITY_TOOLS_LOG_DIR` points each test session at a fresh temp dir
  and `SIDECAR_LOG_LEVEL=CRITICAL` suppresses most writes.
- **`PYTHONDONTWRITEBYTECODE=1`** — prevents `__pycache__` directories from
  being created mid-test, which can race with file watchers and cleanup.
