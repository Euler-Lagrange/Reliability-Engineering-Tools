# Development

## Prerequisites

- **Node.js** `^20.19.0 || >=22.12.0` (for Vite, Vitest, and the Tauri CLI)
- **Rust** stable, installed via `rustup` (any version that supports Tauri 2)
- **Python** 3.11 or newer (tested on 3.12-3.14; pinned in `requirements.txt`)
- **Windows 10 or 11** with the Microsoft Visual C++ Build Tools (MSVC) —
  required for the `x86_64-pc-windows-msvc` Rust target

The release build (`scripts/release.bat`) assumes a Windows host because
the desktop target is Windows-only.

## Initial Setup

```bash
# 1. Clone and enter the repo
cd C:/Reliability_Eng_Tools

# 2. Frontend dependencies (npm uses the repo-root package.json — run from root)
npm install

# 3. Python virtual environment
python -m venv .venv
.venv/Scripts/python.exe -m pip install --upgrade pip

# 4. Backend dependencies (runtime + test/build tooling, pinned)
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
```

`pymupdf` is the package name; the import is `import fitz`.

## Dev Loops

### Browser preview (no backend)

```bash
npm run dev
```

Opens Vite at `http://localhost:5173`. The shell detects it is not running
inside Tauri (`isTauriRuntime()` returns false) and serves mock data from
`frontend/src/mocks/scenarios.ts`. Scenario-seeded state and run results are
useful for UI iteration without the Python toolchain. Native file/folder
pickers return no selection outside Tauri. The BOM Compare, Failure Rate, and
RefDes **Load example** actions reveal the staged demo scenario in browser
preview (labelled `Example:` paths), so the input grids are walkthrough-
reachable; on the desktop runtime the same buttons surface a truthful
"coming soon" notice because no example workbooks ship on disk. Real
picker-to-grid flows still need desktop hot reload.

### Desktop hot reload

```bash
npm run tauri:dev
```

Spawns the Vite dev server, builds the Rust desktop binary in debug mode,
and launches the Tauri window pointing at the dev server. The Rust bridge
finds the sidecar by walking ancestors of the executable / manifest dir for
`.venv/Scripts/python.exe + backend/python/sidecar_main.py` (development
fallback). Frontend edits hot-reload; Rust edits require restarting
`tauri:dev`.

### Sidecar standalone

```bash
.venv/Scripts/python.exe backend/python/sidecar_main.py --self-test
# → SELF-TEST OK: python-sidecar 0.1.0 (security_audit: clean)
```

Run the sidecar without arguments to drive it manually by pasting NDJSON
command envelopes into stdin.

## Running Tests

```bash
# Frontend (from repo root)
npm run typecheck         # production TS project
npm run typecheck:tests   # Vitest files
npm test                  # vitest run (with coverage)

# Backend
.venv/Scripts/python.exe -m pytest backend/tests -q
```

Single-test execution:

```bash
.venv/Scripts/python.exe -m pytest backend/tests/test_sidecar_main.py::test_sidecar_health_check_round_trip -v
```

See `docs/TESTING.md` for the full test inventory and gotchas.

## Building

### Sidecar exe

```bash
.venv/Scripts/python.exe scripts/build_sidecar.py
```

Produces `build/sidecar_dev/reliability-tools-sidecar.exe` via PyInstaller.
The script self-tests the resulting binary with `--self-test` before exiting.
This is a component-development artifact, not a distributable pair; use the
full release pipeline to populate `local_build/`.

### Portable desktop exe (frontend + Rust only)

```bash
npm run tauri:build:portable
```

Produces a single-file portable executable under
`src-tauri/target/x86_64-pc-windows-msvc/release/reliability-tools-desktop.exe`.
The packaged desktop resolves the sidecar exe-adjacent only, so
`reliability-tools-sidecar.exe` must be in the same directory at runtime.

### Full release pipeline

```bash
scripts/release.bat
```

The script runs the following 16 steps and stops on the first failure
(logs go to `logs/release_<timestamp>.log`):

1. Toolchain check (node, npm, backend Python)
2. Version consistency check (`npm run version:check`)
3. Frontend production typecheck (`npm run typecheck`)
4. Frontend test typecheck (`npm run typecheck:tests`)
5. Rust bridge check (`npm run cargo:check`)
6. Rust bridge tests (`npm run cargo:test`)
7. Backend security audit (`python -m common.security_audit --strict` from `backend/python`)
8. Backend tests (`pytest backend/tests -q`)
9. Frontend tests (`npm test`)
10. Sidecar build (`scripts/build_sidecar.py`) into a run-specific directory under `build/release_staging/`
11. Portable desktop build (`npm run tauri:build:portable`)
12. Locate the packaged exe under `src-tauri/target/...`
13. Assemble the exact two-file desktop/sidecar pair in that run-specific staging directory
14. Self-test the staged desktop (`ReliabilityToolsDesktop.exe --self-test`)
15. Self-test the staged desktop with the staged sidecar (`ReliabilityToolsDesktop.exe --self-test-backend`)
16. Atomically promote the verified staged directory to `local_build/` with bounded retries for transient Windows locks, restoring the previous pair if promotion still fails

The outputs are `local_build/ReliabilityToolsDesktop.exe` and
`local_build/reliability-tools-sidecar.exe`. They are one release unit and
must be distributed together.

## Adding a New Tool

This is the end-to-end checklist. The work touches Python, Rust contracts
(implicitly, through routing), and the React shell.

### 1. Backend package

Create `backend/python/{tool}/__init__.py` (empty) and `backend/python/{tool}/runtime.py`.
Use `backend/python/fmea/runtime.py` as the template — it has the simplest
adapter shape. The new module must export `validate_run_request(body)` and
`execute_run_request(body, **kwargs)` with the signatures defined in
`docs/ARCHITECTURE.md` (Runtime Adapter Pattern).

### 2. Wire routing in `sidecar_main.py`

Add a new workflow set, the imports, and the route branches:

```python
from {tool}.runtime import (
    execute_run_request as {tool}_execute,
    validate_run_request as {tool}_validate,
)

{TOOL}_WORKFLOWS = {"my_workflow_one", "my_workflow_two"}

def route_validate(body: dict) -> dict:
    wf = str(body.get("workflowId", "")).strip()
    ...
    if wf in {TOOL}_WORKFLOWS:
        return {tool}_validate(body)
    return fmea_validate(body)

def route_execute(body: dict, **kwargs) -> dict:
    wf = str(body.get("workflowId", "")).strip()
    ...
    if wf in {TOOL}_WORKFLOWS:
        return {tool}_execute(body, **kwargs)
    return fmea_execute(body, **kwargs)
```

### 3. Backend tests

Add validate + execute tests to `backend/tests/test_sidecar_main.py`. Use
the existing `_start_sidecar()`, `_send_command()`, `_read_until()` helpers
exactly as the FMEA / BOM Compare tests do. Always wrap the test body in
`try` / `finally: process.terminate(); process.wait()`.

### 4. Frontend types

Extend `frontend/src/app/types.ts`:

```typescript
export type WorkflowId =
  | "piece_part_generate"
  | "bom_only"
  | ...
  | "my_workflow_one"
  | "my_workflow_two";

export type FileRole =
  | "grouping"
  | "bom"
  | ...
  | "myInput";
```

### 5. Mock scenario

Add a `DemoScenario` entry to `frontend/src/mocks/scenarios.ts` so the
browser preview has something to render.

### 6. Tool component

Create `frontend/src/features/{tool}/{Tool}Tool.tsx`. Copy
`frontend/src/features/fmea/FmeaTool.tsx` as the starting template and
strip / replace FMEA-specific selectors. The structure is:

- Inputs panel using `<InputGrid>`
- Workflow / strategy selectors using `<WorkflowSelector>` and `<StrategySelector>`
- Mapping table using `<MappingTable>`
- Validation preview using `<ValidationPreview>`
- Run state panel using `<RunStatePanel>` driven by `useBackendRunLifecycle`

### 7. ToolId

Extend the union in `frontend/src/stores/shellStore.ts`:

```typescript
export type ToolId =
  | "dark_star_fmea"
  | "bom_compare"
  | ...
  | "my_tool";
```

### 8. Tool registry

Append to `toolDefinitions` in `frontend/src/app/toolRegistry.tsx`:

```typescript
const MyTool = lazy(() =>
  import("../features/{tool}/MyTool").then((module) => ({ default: module.MyTool })),
);

export const toolDefinitions: ToolDefinition[] = [
  ...,
  {
    id: "my_tool",
    label: "My Tool",
    eyebrow: "Active tool",
    description: "One sentence describing the tool.",
    icon: SomeIcon,           // from @phosphor-icons/react
    status: "active",
    component: MyTool,
  },
];
```

### 9. Sidecar bundling

Add the new package to `scripts/build_sidecar.py`:

```python
"--add-data", f"{BACKEND / '{tool}'};{tool}",
"--hidden-import", "{tool}",
"--hidden-import", "{tool}.runtime",
"--hidden-import", "{tool}.{tool}_logic",
```

PyInstaller will not pick these up automatically — every direct or
transitive import the runtime needs must be listed.

## Runtime Adapter Template

```python
def validate_run_request(body: dict[str, Any]) -> dict[str, Any]:
    workflow_id = str(body.get("workflowId", "")).strip()
    inputs_by_role = _collect_inputs(body)

    required_files = [
        LabeledValue(_role_label(role), _input_path(inputs_by_role, role))
        for role in _required_roles(workflow_id)
    ]
    loaded_states = [
        LabeledState(_role_label(role), _is_input_loaded(inputs_by_role.get(role) or {}))
        for role in _required_roles(workflow_id)
    ]
    result = validate_pre_run_state(
        required_files=required_files,
        load_in_progress=...,
        loaded_states=loaded_states,
        not_loaded_message="Load current files and sheets for: {labels}.",
    )
    return {
        "ok": result.ok,
        "reason_code": result.reason_code,
        "toast_text": result.toast_text,
        "validations": [...],
        "mode": "desktop-bridge",
    }

def execute_run_request(body, *, log_callback=None, status_callback=None,
                        progress_callback=None, processor_ready_callback=None):
    validation = validate_run_request(body)
    if not validation["ok"]:
        raise ValidationError(validation["toast_text"] or "Run validation failed.")

    # 1. Resolve inputs and options
    # 2. Construct processor / cancel bridge
    # 3. processor_ready_callback(processor or bridge)
    # 4. Run the legacy logic with progress + status wired
    # 5. Write the output workbook
    # 6. Return the result dict (status, summary, output_file, log_lines, mode)
```

## `_CancelBridge` Pattern

Tools that wrap legacy processors needing both a `CancellationToken` and a
`threading.Event` (BOM Compare, RefDes Extractor) use this bridge:

```python
# from backend/python/bom_compare/runtime.py
class _CancelBridge:
    """Bridges CancellationToken to threading.Event for BOM Compare functions."""

    def __init__(self) -> None:
        self.cancel = CancellationToken()
        self._event = threading.Event()

    @property
    def stop_event(self) -> threading.Event:
        return self._event

    def request_cancel(self) -> None:
        self.cancel.cancel()
        self._event.set()
```

Use `_CancelBridge` when the underlying logic was written against
`stop_event.is_set()` rather than `cancel.check()`. FMEA and Failure Rate
expose the `CancellationToken` directly because their processors already
use it.

## Progress Callback Wrapping

The sidecar contract is fixed:
`progress_callback(stage: str, message: str, percent: int, current: int | None, total: int | None)`.

Tool-internal progress callbacks are usually simpler (`(current, total)` or
`(fraction)`). Adapters wrap them:

```python
# from fmea/runtime.py — current/total style
def runtime_progress_callback(current: int, total: int) -> None:
    stage_label, percent = _progress_percent(current_stage_message, current, total)
    _emit_progress(progress_callback, stage=stage_label,
                   message=current_stage_message, percent=percent,
                   current=current, total=total)

# from failure_rate/runtime.py — fraction style
def logic_progress(fraction: float) -> None:
    percent = 10 + round(fraction * 75)
    emit_progress("Processing", f"Linking failure rates ({percent}%)...",
                  min(85, percent))
```

`PROGRESS_STAGE_WEIGHTS` tables in the runtime modules map stage messages
to (`start`, `span`, `display_label`) tuples, so a 0–100% value gets a
sensible bucket per stage.

## Debugging

### Drive the sidecar by hand

```bash
.venv/Scripts/python.exe backend/python/sidecar_main.py
```

Paste a single line of JSON and hit Enter:

```json
{"protocol_version":"0.1.0","id":"manual_001","kind":"command","request_id":"r1","run_id":null,"timestamp":"2026-04-06T00:00:00Z","payload":{"command":"health_check","body":{}}}
```

The response prints to stdout on its own line.

### Self-tests

```bash
.venv/Scripts/python.exe backend/python/sidecar_main.py --self-test
ReliabilityToolsDesktop.exe --self-test
ReliabilityToolsDesktop.exe --self-test-backend
```

`--self-test-backend` is the most useful smoke check — it spins up the
sidecar, sends a `health_check`, and prints the backend identity. Used by
the release pipeline as the final gate.

### Logs

- Python sidecar logs: `~/.reliability_tools/logs/` (override with
  `RELIABILITY_TOOLS_LOG_DIR`)
- Rust stderr forwarder: every line from the sidecar's stderr is prefixed
  with `[python-sidecar]` and printed to the desktop process stderr.
  In dev, that surfaces in the terminal running `tauri:dev`. In a packaged
  build, capture it by launching the exe from a console.
- Release pipeline logs: `logs/release_<timestamp>.log`

### Custom Python interpreter

Set `RELIABILITY_TOOLS_BACKEND_PYTHON` to point Tauri at a different Python
executable (useful when testing alternative builds). Set
`RELIABILITY_TOOLS_BACKEND_SCRIPT` to override the sidecar script path.

## Gotchas

- **Stdin write atomicity** — the Rust bridge holds the `ChildStdin` mutex
  for the entire envelope+newline+flush sequence. If you add a new write
  path, replicate the pattern. Releasing the lock between bytes will
  corrupt the NDJSON stream.
- **`CancellationError` inheritance chain** — `CancellationError ->
  InterruptedError -> OSError -> Exception`. Avoid bare
  `except OSError` in execution paths or you will swallow user cancellation.
- **stderr pipe deadlock** — never spawn the sidecar with `stderr=PIPE`
  unless you also drain it on a thread. Tests use
  `stderr=subprocess.DEVNULL`; the Rust bridge uses
  `spawn_stderr_logger`.
- **`_SidecarReader` pattern in tests** — one persistent reader per
  process keyed by `id(process)`. PIDs get recycled fast on Windows; do
  not key off `process.pid`.
- **Single active run** — the sidecar enforces `_active_run() is None`
  before accepting `execute_run`. Cancelling a run does not return a free
  slot until the background thread exits and clears `ACTIVE_RUN`.
- **Heartbeat vs. run events** — heartbeats have no `request_id` and no
  `run_id`. They are dropped by the stdout reader and only update the
  supervisor's last-seen timestamp.
- **Browser preview mode** — `npm run dev` runs without a backend.
  `isTauriRuntime()` checks `window.__TAURI_INTERNALS__` and
  `window.__TAURI__`; under Vite neither exists, so the client serves
  mock scenarios. Behavior differences between mock and real backend are
  caught in the desktop dev loop, not the browser preview.
