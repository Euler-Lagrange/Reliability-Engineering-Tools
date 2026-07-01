# Testing

## Test Inventory

| Suite | Path | Count | Framework |
|-------|------|-------|-----------|
| Backend integration | `backend/tests/test_sidecar_main.py` | 44 | pytest |
| Backend security audit | `backend/tests/test_security_audit.py` | 27 | pytest |
| Backend cancel bridge | `backend/tests/test_cancel_bridge.py` | 12 | pytest |
| Backend output-directory helpers | `backend/tests/test_output_directory_helpers.py` | 10 | pytest |
| Backend FMEA Phase D | `backend/tests/test_fmea_phase_d.py` | 58 | pytest |
| Backend Failure-Rate logic | `backend/tests/test_failure_rate_logic.py` | 24 | pytest |
| Backend RefDes extraction-engine | `backend/tests/test_extraction_engine.py` | 7 | pytest |
| Backend BOM-compare logic | `backend/tests/test_bom_compare_logic.py` | 31 | pytest |
| Backend BOM-compare runtime | `backend/tests/test_bom_compare_runtime.py` | 9 | pytest |
| Backend Failure-Rate runtime | `backend/tests/test_failure_rate_runtime.py` | 2 | pytest |
| Backend read-layer (NA + header dedup) | `backend/tests/test_read_layer.py` | 6 | pytest |
| Backend RefDes BOM-coverage | `backend/tests/test_coverage_report.py` | 19 | pytest |
| Backend BOM-loader metadata | `backend/tests/test_bom_loader.py` | 5 | pytest |
| Backend OneDrive detection | `backend/tests/test_onedrive_detection.py` | 5 | pytest |
| Backend file-size guard | `backend/tests/test_file_guards.py` | 3 | pytest |
| Backend crash-dump | `backend/tests/test_crash_dump.py` | 3 | pytest |
| **Backend subtotal** | | **265** | |
| Frontend shell | `frontend/src/app/App.test.tsx` | 11 | Vitest + RTL |
| Frontend context drawer | `frontend/src/components/ContextDrawer.test.tsx` | 4 | Vitest + RTL |
| Frontend component | `frontend/src/components/CustomSelect.test.tsx` | 1 | Vitest + RTL |
| Frontend mapping table | `frontend/src/components/MappingTable.test.tsx` | 11 | Vitest + RTL |
| Frontend run state panel | `frontend/src/components/RunStatePanel.test.tsx` | 6 | Vitest + RTL |
| Frontend output folder picker | `frontend/src/components/OutputFolderPicker.test.tsx` | 2 | Vitest + RTL |
| Frontend log panel resize | `frontend/src/components/GlobalLogPanel.resize.test.tsx` | 13 | Vitest + RTL |
| Frontend command palette | `frontend/src/components/primitives/CommandPalette.test.tsx` | 5 | Vitest + RTL |
| Frontend hold button | `frontend/src/components/primitives/HoldButton.test.tsx` | 5 | Vitest + RTL |
| Frontend empty state | `frontend/src/components/primitives/EmptyState.test.tsx` | 5 | Vitest + RTL |
| Frontend run lifecycle | `frontend/src/shared/backend/runLifecycle.test.ts` | 9 | Vitest |
| Frontend desktop run controller | `frontend/src/shared/backend/useDesktopRunController.test.ts` | 2 | Vitest |
| Frontend cancel error | `frontend/src/shared/backend/cancelError.test.ts` | 18 | Vitest |
| Frontend cancel run | `frontend/src/shared/backend/client.cancelRun.test.ts` | 2 | Vitest |
| Frontend run event client | `frontend/src/shared/backend/client.runEvents.test.ts` | 2 | Vitest |
| Frontend contract schemas | `frontend/src/contracts/sidecar.test.ts` | 4 | Vitest |
| Frontend busy reset | `frontend/src/shared/backend/useBackendBusyReset.test.ts` | 9 | Vitest |
| Frontend backend bootstrap | `frontend/src/shared/backend/useBackendBootstrap.test.ts` | 2 | Vitest |
| Frontend run subscription | `frontend/src/shared/backend/useBackendRunSubscription.test.ts` | 3 | Vitest |
| Frontend theme registry | `frontend/src/shared/theme/themeRegistry.test.ts` | 10 | Vitest |
| Frontend app shortcuts | `frontend/src/shared/hooks/useAppShortcuts.test.tsx` | 4 | Vitest + RTL |
| Frontend role-request sequence | `frontend/src/shared/hooks/useRoleRequestSequence.test.ts` | 5 | Vitest |
| Frontend copy to clipboard | `frontend/src/shared/hooks/useCopyToClipboard.test.ts` | 3 | Vitest |
| Frontend global log store | `frontend/src/stores/globalLogStore.test.ts` | 6 | Vitest |
| Frontend notification store | `frontend/src/stores/notificationStore.test.ts` | 3 | Vitest |
| Frontend store migrations | `frontend/src/stores/storeMigrations.test.ts` | 7 | Vitest |
| Frontend keep-alive shell | `frontend/src/app/App.keepalive.test.tsx` | 2 | Vitest + RTL |
| Frontend FMEA tool | `frontend/src/features/fmea/FmeaTool.test.tsx` | 11 | Vitest + RTL |
| Frontend FMEA inspection | `frontend/src/features/fmea/FmeaTool.inspection.test.tsx` | 5 | Vitest + RTL |
| Frontend mapping columns | `frontend/src/features/fmea/mappingColumns.test.ts` | 27 | Vitest |
| Frontend mapping analysis | `frontend/src/features/fmea/mappingAnalysis.test.ts` | 7 | Vitest |
| Frontend BOM Compare tool | `frontend/src/features/bom-compare/BomCompareTool.test.tsx` | 18 | Vitest + RTL |
| Frontend Failure Rate tool | `frontend/src/features/failure-rate/FailureRateTool.test.tsx` | 2 | Vitest + RTL |
| Frontend RefDes Extractor tool | `frontend/src/features/refdes-extractor/RefDesExtractorTool.test.tsx` | 10 | Vitest + RTL |
| Frontend number field | `frontend/src/components/primitives/NumberField.test.tsx` | 6 | Vitest + RTL |
| Frontend mapping derivation | `frontend/src/shared/mapping/deriveMappingRows.test.ts` | 6 | Vitest |
| Frontend tool dispatch | `frontend/src/features/toolRunDispatch.test.tsx` | 7 | Vitest + RTL |
| Frontend shell-hook install | `frontend/src/app/App.shellHooks.test.tsx` | 1 | Vitest + RTL |
| Frontend scenario completeness | `frontend/src/mocks/scenarios.test.ts` | 2 | Vitest |
| **Frontend subtotal** | | **256** | |
| Rust bridge unit | `src-tauri/src/lib.rs` | 17 | cargo test |
| **Total** | | **538** | |

## Backend Tests

`backend/tests/test_sidecar_main.py` exercises the sidecar end-to-end as a
real subprocess. Every test in that file starts a fresh
`python sidecar_main.py` and talks to it over stdin/stdout.

In-process unit tests (`test_cancel_bridge.py`, `test_fmea_phase_d.py`,
`test_failure_rate_logic.py`, `test_extraction_engine.py`,
`test_bom_compare_logic.py`, `test_read_layer.py`, `test_coverage_report.py`,
`test_bom_loader.py`) import backend modules directly; see
**In-process tests** below for the `conftest.py` shim that makes those
imports resolve.

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
| FMEA Phase D (in-process, 58 tests) | BOM inheritance, variant handling, failure modes standard filtering, fill-gaps validation, usage fraction calculations, legacy enrichment rejection, functional-to-piecepart preservation, CCA prefix handling, output directory configuration (including unwritable-directory fallback), Part Usage (PU) column logic incl. Tier-1 compute-or-blank+flag (instance-count 1/N derivation, blank+PU_GUESSED flag, explicit-value preservation), column override modes, union merge strategies, FMC mapping, bijective FMEA-ID suffix |
| Inspection caps (subprocess, 4 tests) | `inspect_input` row cap at 20 000 rows, column cap at 100 columns, sparse-sheet row cap by physical rows scanned, header-search cap failure within 1 000 rows |
| Failure-Rate logic (in-process, 24 tests) | Failure Rate (FR) linker math driven through `FMEALinkerLogic.process`: per-mode `Mode_FR = Part_FR * Usage * Corrected_Ratio` arithmetic, unit-mode scaling to per-hour space, RefDes lookup normalization, and Tier-1 genuine-gap Part Usage handling (blank usage with real FR → NaN Mode_FR, "=1/N" formula-cell-as-NaN, unmatched-RefDes zero preserved, circuit-block roll-up skips blank children) — asserts exact computed numbers |
| RefDes extraction-engine (in-process, 7 tests) | NextGen `_disambiguate_pin_mapping` pin-label collision resolution across the three-tier priority (body center inside group rect → body overlaps rect → nearest body by distance) when multiple components share a pin label; plus the Tier-2 #20 pinlist-failure surfacing to the streamed run log |
| BOM-compare logic (in-process, 31 tests) | BOM Compare range/set math: opt-in RefDes range expansion (`R200-R205` → R200..R205) while the `analyze` orchestrator never expands by default (hyphens denote pins, e.g. `U200-1` reduces to base `U200`), zero-pad preservation, `analyze` set math (Missing in BOM / BOM Not in Groups, both directions), and the custom per-column value-diff contract (`compare_columns` flags a changed value, omitting it reports none, Numeric rule ignores text formatting) |
| Read layer (in-process, 6 tests) | Excel/CSV `NA`/`N/A` literal-text read parity and duplicate-header dedup matching pandas' `.1`/`.2` scheme |
| RefDes BOM-coverage (in-process, 19 tests) | Reverse-diff of extracted RefDes vs a loaded BOM: `BOM Not Grouped` (Not Extracted / Extracted-Ungrouped / Extracted-Provisional, with Part#/Description), `Extracted Not In BOM`, `Coverage Summary` counts, component-level normalization, unparented-pin rejection, and the sheet writer |
| BOM-loader metadata (in-process, 5 tests) | Opt-in Part Number / Description capture in `load_bom_data`, keyed to the normalized RefDes, with Description-over-Name precedence |

## Frontend Tests

The frontend suite uses **Vitest** with **React Testing Library** and
**jsdom**. The shell is forced into browser-mock mode at test time:
`isTauriRuntime()` checks `window.__TAURI_INTERNALS__` / `window.__TAURI__`,
neither of which exists under jsdom, so the client returns mock data from
`frontend/src/mocks/scenarios.ts` instead of calling Tauri.

| File | Tests |
|------|-------|
| `frontend/src/app/App.test.tsx` | 11 — shell render, tool switching, theme application, notification dismissal, workflow switching, CCA visibility, HDA source toggle, output folder, focus management |
| `frontend/src/contracts/sidecar.test.ts` | 4 — protocol schema gates for run ack, inspect metadata, and nullable Flet config |
| `frontend/src/components/CustomSelect.test.tsx` | 1 — keyboard navigation |
| `frontend/src/components/MappingTable.test.tsx` | 11 — column mapping display, selection, validation, sync, source-aware option labels |
| `frontend/src/components/RunStatePanel.test.tsx` | 6 — run state display, progress, result, cancel, error |
| `frontend/src/components/GlobalLogPanel.resize.test.tsx` | 13 — log panel drag-to-resize, collapse, expand, boundary constraints |
| `frontend/src/components/primitives/CommandPalette.test.tsx` | 5 — command palette open, search, select, keyboard navigation, dismiss |
| `frontend/src/components/primitives/HoldButton.test.tsx` | 5 — hold-to-confirm interaction, cancel on release, progress feedback |
| `frontend/src/components/primitives/EmptyState.test.tsx` | 5 — empty state rendering, icon, message, action slot |
| `frontend/src/shared/backend/runLifecycle.test.ts` | 6 — run lifecycle state transitions (ack, progress, result, cancel, error, reset) |
| `frontend/src/shared/backend/cancelError.test.ts` | 18 — cancel error detection, wrapping, propagation across error types, plus `describeBackendError` normalization of raw-string Tauri rejections |
| `frontend/src/shared/backend/client.cancelRun.test.ts` | 2 — cancel run command dispatch and response handling |
| `frontend/src/shared/backend/client.runEvents.test.ts` | 2 — production run-event subscription schema parsing |
| `frontend/src/shared/backend/useBackendBusyReset.test.ts` | 9 — busy state recovery after run completion, error, or unmount |
| `frontend/src/shared/backend/useBackendBootstrap.test.ts` | 2 — reconnect backoff and active-run clearing |
| `frontend/src/shared/backend/useBackendRunSubscription.test.ts` | 3 — shell-level run-event fanout, global log capture, and result-schema validation-failure → terminal failure |
| `frontend/src/shared/theme/themeRegistry.test.ts` | 10 — theme registry consistency (ids, labels, icons, colorScheme, rail visibility) |
| `frontend/src/shared/hooks/useRoleRequestSequence.test.ts` | 5 — per-role async request sequencing (stale response suppression) |
| `frontend/src/shared/hooks/useCopyToClipboard.test.ts` | 3 — clipboard write, success feedback, error handling |
| `frontend/src/stores/globalLogStore.test.ts` | 6 — global log ring buffer: append, clear, toggle, filter, export format, capacity |
| `frontend/src/app/App.keepalive.test.tsx` | 2 — keep-alive shell: tool-local state survives a tool-switch round-trip, only visited tools mount |
| `frontend/src/features/fmea/FmeaTool.test.tsx` | 9 — FMEA tool rendering, workflow selection, input validation, run integration, mapping-override survival across output-strategy and FMD-standard changes |
| `frontend/src/features/fmea/FmeaTool.inspection.test.tsx` | 5 — sheet selection interactivity during background aggregation, inspection cap warning display, stale-validation clears on browse/sheet change, orphaned-override pruning |
| `frontend/src/features/toolRunDispatch.test.tsx` | 7 — FMEA (option-key payload incl. hdaSource), BOM Compare, Failure Rate, and RefDes workflow dispatch from React tools, validation-failure (execute_run skipped), all six BOM Compare options reach the backend, and Custom Compare column pairs reach `options.compare_columns` |
| `frontend/src/features/bom-compare/BomCompareTool.test.tsx` | 14 — custom-compare slots, pristine exit, workflow round-trip cache, interrupted-inspection recovery, double-start guard, raw-string error surfacing, real-header mapping derivation, dispatch payloads, group-only prov checkbox disabled in custom, column-pair picker auto-pairs in custom / hidden in group |
| `frontend/src/features/failure-rate/FailureRateTool.test.tsx` | 2 — stale-validation clears on browse, real-header mapping derivation |
| `frontend/src/features/refdes-extractor/RefDesExtractorTool.test.tsx` | 9 — piece-part pinlist slot, pristine behavior, empty-input dispatch, adaptive-geometry gating, numeric tuning fields (render, dispatch, geometry gating) |
| `frontend/src/components/primitives/NumberField.test.tsx` | 6 — numeric field value/onChange parsing, NaN guard, min clamp, min/max/step/disabled forwarding |
| `frontend/src/shared/mapping/deriveMappingRows.test.ts` | 6 — mapping-row derivation from inspected headers (exact match, no match, fixture fallback) |
| `frontend/src/features/fmea/mappingColumns.test.ts` | 27 — column synonym matching, priority ordering, ambiguity resolution, FMD override-key migration |
| `frontend/src/features/fmea/mappingAnalysis.test.ts` | 7 — mapping completeness analysis, gap detection, suggestions, multi-source provenance merging |

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
npm run typecheck
npm run typecheck:tests
npm test

# Rust bridge
npm run cargo:test
```

The release pipeline (`scripts/release.bat`) runs frontend production
typecheck, frontend test typecheck, Rust `cargo:check`, backend security
audit, backend tests, and frontend tests before the sidecar and desktop
builds.

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
