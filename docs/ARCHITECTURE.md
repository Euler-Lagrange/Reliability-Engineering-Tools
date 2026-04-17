# Architecture

Reliability Tools Desktop is a standalone Tauri application with three layers:

```
React frontend  ──invoke──▶  Rust bridge  ──NDJSON over stdio──▶  Python sidecar
       ▲                          │                                      │
       └──── backend://run-event ─┘◀──────── stdout reader ──────────────┘
              (Tauri events)
```

The frontend never speaks to Python directly. The Rust bridge owns one managed
sidecar session for the lifetime of the desktop window and brokers every
request, response, and streamed run event.

## Directory Tree

```
.
├── frontend/                   # React + TypeScript shell
│   ├── public/
│   │   └── fonts/              # Inter-Variable.woff2, JetBrainsMono-Variable.ttf
│   ├── src/
│   │   ├── app/                # AppShell, tool registry, types
│   │   ├── components/         # Shared UI (SectionCard, MappingTable, …)
│   │   │   └── primitives/     # Reusable building blocks (CommandPalette, ToggleChip, …)
│   │   ├── contracts/          # Zod schemas for sidecar payloads
│   │   ├── features/           # One directory per tool
│   │   ├── mocks/              # Browser-preview demo scenarios
│   │   ├── shared/             # backend/, errors/, hooks/, notifications/, theme/
│   │   ├── stores/             # Zustand stores
│   │   ├── theme/styles.css    # Single design-system source of truth
│   │   └── main.tsx            # React entry
│   ├── vite.config.ts
│   └── vitest.setup.ts
├── src-tauri/                  # Rust desktop host
│   ├── src/
│   │   ├── lib.rs              # Sidecar session, commands, supervisor
│   │   └── main.rs             # Tauri bootstrap
│   ├── tauri.conf.json
│   ├── Cargo.toml
│   └── capabilities/
├── backend/
│   ├── python/                 # Self-contained Python backend
│   │   ├── sidecar_main.py     # NDJSON entry point
│   │   ├── common/             # Shared utilities (logger, validation, …)
│   │   ├── shared/             # pre_run_validation
│   │   ├── fmea/               # FMEA tool: runtime + logic + template I/O
│   │   ├── bom_compare/        # BOM Compare tool
│   │   ├── failure_rate/       # Failure Rate linker
│   │   ├── refdes_extractor/   # RefDes extractor (with bom_loader, geometry)
│   │   └── refdes_test/        # Dark Star next-gen extraction engine
│   └── tests/
│       └── test_sidecar_main.py
├── contracts/
│   └── sidecar-protocol.md     # Wire format reference
├── scripts/
│   ├── build_sidecar.py        # PyInstaller bundling
│   ├── release.bat             # 10-step release pipeline (typecheck + security audit + tests + build + self-tests)
│   ├── bump-version.mjs        # Bump version across package.json / Cargo.toml / tauri.conf.json in lockstep
│   ├── tauri-msvc.cmd
│   └── tauri-runner.mjs
├── local_build/                # Output: ReliabilityToolsDesktop.exe + sidecar.exe
└── docs/                       # ARCHITECTURE, TESTING, DESIGN_SYSTEM, DEVELOPMENT
```

## Frontend Layer

The shell is built around a single `AppShell` component (`frontend/src/app/App.tsx`)
that hosts:

- **Tool registry** (`frontend/src/app/toolRegistry.tsx`) — declarative list of
  tool definitions with id, label, eyebrow, description, Phosphor icon, and a
  lazy-loaded React component. Adding a tool means appending one entry.
- **Active tool routing** — driven by `useShellStore.activeToolId`, not React Router.
- **Feature directories** (`frontend/src/features/{tool}/`) — each tool owns one
  `*Tool.tsx` component (e.g. `FmeaTool.tsx`, `BomCompareTool.tsx`,
  `FailureRateTool.tsx`, `RefDesExtractorTool.tsx`, `SettingsTool.tsx`).
- **Shared services** (`frontend/src/shared/`):
  - `backend/client.ts` — typed wrapper around Tauri `invoke()` plus
    `isTauriRuntime()` browser-mock fallback.
  - `backend/runLifecycle.ts` — projects streamed run events into a
    per-tool timeline plus `RunMode` state. As of 0.4.2 the raw
    subscription to `backend://run-event` no longer lives here — it
    moved one layer up so a running job survives tool switches.
  - `backend/useBackendRunSubscription.ts` — shell-level hook (mounted
    in `App.tsx`) that owns the single subscription to
    `backend://run-event` and fans every ack / status / progress / log /
    terminal envelope into the run-lifecycle projector. Replaces the
    old `useGlobalLogSubscription`.
  - `backend/useBackendBootstrap.ts` — hook that performs the initial
    health check, runs the reconnect backoff chain, and reconciles the
    active run against the sidecar's `session_generation` on every
    reconnect: if the generation advanced, the stale run is cleared;
    otherwise the run is marked reconnected and resumes.
  - `backend/fileManager.ts` — cross-platform path helpers
    (`parentDirectoryForPath`, `OPEN_FOLDER_LABEL`) used by the
    `RunStatePanel` Open-folder affordance and the `OutputFolderPicker`.
  - `hooks/shortcutUtils.ts` — platform-aware shortcut helpers. Keyboard
    shortcuts use `Cmd` on macOS and `Ctrl` elsewhere, and are
    suppressed while focus is in an editable element so typing cannot
    swap tools by accident.
  - `notifications/NotificationCenter.tsx` — toast surface bound to
    `notificationStore`.
  - `theme/ThemeController.tsx` — applies `data-theme` attribute on `<html>`.
  - `errors/ErrorBoundary.tsx` — wraps each tool view.
- **Zustand stores** (`frontend/src/stores/`) — `shellStore`, `themeStore`,
  `notificationStore` (see State Management below).
- **Contracts** (`frontend/src/contracts/sidecar.ts`) — Zod schemas validate
  every payload received from Rust. Type drift between Rust/Python and the
  frontend fails loudly at the schema boundary, not deep inside a render.
- **Mocks** (`frontend/src/mocks/scenarios.ts`) — fully populated demo
  scenarios so the browser preview (`npm run dev`) works without a backend.
- **Primitives** (`frontend/src/components/primitives/`) — reusable
  building-block components extracted from tool surfaces: `CommandPalette`,
  `ToggleChip`, `OptionsField`, `ContextTabs`, `CheckboxField`,
  `OptionsSection`, `HoldButton`, `EmptyState`. The Command Palette
  (Ctrl+K) is mounted at the `AppShell` level and provides cross-tool
  navigation and action dispatch.

## Rust Bridge Layer

`src-tauri/src/lib.rs` is one file containing the entire bridge. Key types:

- **`ManagedSidecar`** — `Arc<Mutex<Child>>` plus `Arc<Mutex<ChildStdin>>`.
  One sidecar process per desktop window. Killed on window destroy. On
  Windows the struct also owns an `Option<JobObject>` — see *Windows
  process lifecycle* below.
- **`SessionShared`** — shared state across reader, supervisor, and command
  threads. Holds the pending-request registry, connection flag, app handle for
  emitting events, the last heartbeat timestamp, and a small
  `fatal_sidecar_detail` buffer that records the most recent error-level
  log line from the sidecar so `handle_disconnect` can merge it into the
  user-visible disconnect notification (see *Fatal-error detail merge*).
- **`SidecarState`** — Tauri-managed state. Owns the `ManagedSidecar` mutex
  and an `Arc<SessionShared>`.

### Command invocation

`SidecarState::send_command_wait(command_name, body, expected_kind)`:
1. Ensures a session exists (`ensure_session()` spawns one if needed).
2. Generates a `request_id`, registers an `mpsc::Sender` keyed by it.
3. Locks `ChildStdin`, writes the JSON envelope plus a single newline,
   flushes, then releases the lock.
4. Blocks on the matching `mpsc::Receiver` until the stdout reader thread
   delivers a response with that `request_id`.

### Stdin atomicity rule

The stdin lock must be held for the **entire** envelope-plus-newline write
sequence. Releasing between `write_all(payload)` and `write_all(b"\n")` would
allow another thread to interleave bytes and corrupt the NDJSON stream. The
write block in `send_command_wait` enforces this by performing all three
calls inside a single `MutexGuard` scope.

### Stdout reader thread

`spawn_stdout_reader` runs one dedicated thread per session. For each line:
- Parse JSON; on parse failure call `handle_disconnect`.
- For `ack` and `result` with a known `request_id`, resolve the pending sender.
- For `error` and `backend_error` with a known `request_id`, deliver `Err`.
- For `heartbeat`, call `record_heartbeat()`.
- For `ack | status | progress | log | result | backend_error | cancelled`
  with a `run_id`, emit the raw envelope on the `backend://run-event` Tauri
  event so the frontend can stream it.

### Heartbeat supervisor

`spawn_heartbeat_supervisor` wakes every `HEARTBEAT_CHECK_INTERVAL` (5 s).
If `heartbeat_overdue()` reports `last.elapsed() > HEARTBEAT_TIMEOUT` (15 s),
the supervisor calls `handle_disconnect`, which kills the child, fails every
pending request with the same message, and emits a session event.

### Windows process lifecycle (Job Objects)

On Windows the bridge wraps the spawned Python sidecar in a Win32 **Job
Object** with the `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` flag set (see the
`windows_job` module at the top of `src-tauri/src/lib.rs`). When the bridge
process exits — cleanly or via crash — Windows tears down the job, which
in turn terminates every process assigned to it. That guarantees the
sidecar is never orphaned, even if a Rust panic bypasses the
`on_window_event` `Destroyed` handler. macOS/Linux rely on their POSIX
parent-death signals instead and do not need the extra scaffolding.

### Fatal-error detail merge

When a fatal Python exception escapes the sidecar's top-level catch it
emits one last `log` envelope at `ERROR` level before the process dies
(see Crash Reporting below). The Rust bridge captures that line into
`SessionShared::fatal_sidecar_detail`; on the subsequent `handle_disconnect`
call it merges the detail into the user-visible message via
`merge_disconnect_message`, so the frontend sees e.g.
`Python sidecar closed stdout. Details: Unhandled exception:
RuntimeError: boom` rather than an opaque "connection lost." Unit tests
for the helper live alongside it in `lib.rs`.

### Session events

`backend://session` carries `{ kind, connected, backend, message }`. The
frontend bootstrap hook listens to it and triggers the reconnect backoff
when `connected` flips false.

### Tauri commands exposed to the frontend

| Command | Sidecar command | Returns |
|---------|-----------------|---------|
| `backend_session_status`     | (none — local state)  | `BackendSessionStatusResponse` |
| `backend_health_check`       | `health_check`        | `BackendHealthResponse` |
| `backend_list_sheets`        | `list_sheets`         | `SheetListResponse` |
| `backend_inspect_input`      | `inspect_input`       | `InputInspectionResponse` |
| `backend_analyze_template`   | `analyze_template`    | `TemplateAnalysisResponse` |
| `backend_validate_run`       | `validate_run`        | raw JSON |
| `backend_execute_run`        | `execute_run`         | `RunAcceptedResponse` (run_id) |
| `backend_cancel_run`         | `cancel_run`          | `CancelRunResponse` |
| `backend_read_flet_config`   | `read_flet_config`    | raw JSON |
| `reveal_in_file_manager`     | (none — local OS call) | `()` |

`reveal_in_file_manager` takes an absolute path string and spawns the
host OS file manager: `explorer.exe` on Windows, `open` on macOS,
`xdg-open` on Linux. Used by Settings › Logs "Open in Explorer" and the
per-tool `OutputFolderPicker`; zero new Cargo dependencies (no need for
`tauri-plugin-opener`). The command returns `Err` if the path does not
exist or the OS fails to spawn.

### Response enrichment

Every typed Tauri command in the table above constructs its response struct
with `mode: "desktop-bridge".to_string()` set explicitly (see
`src-tauri/src/lib.rs` — the `mode` field is hard-wired in each
`backend_*` handler; grep for `"desktop-bridge".to_string()` to find the
current call sites). The Python sidecar itself
only sets `mode` on the `execute_run` ack and the `cancel_run` result;
every other command relies on the Rust layer to add it before the response
crosses the bridge. The Zod schemas in `frontend/src/contracts/` therefore
validate the **enriched** Rust output, not the raw Python payload — keep
this in mind when adding new commands so the schema and the Rust handler
stay in sync.

## Python Sidecar Layer

`backend/python/sidecar_main.py` is a single-file dispatcher with no framework.

- **Entry point** — `main()` reads `--self-test` and exits, otherwise calls
  `iter_messages()` which emits a `ready` envelope, starts the heartbeat
  thread, and reads stdin lines forever.
- **Envelope** — `Envelope` dataclass formats every outbound line with
  `protocol_version`, generated `id`, `kind`, optional `request_id`/`run_id`,
  ISO timestamp, and the `payload` dict. `EMIT_LOCK` serializes writes.
- **Commands** — `handle_command()` is a flat if/elif over `payload.command`:
  `health_check`, `list_sheets`, `inspect_input`, `analyze_template`,
  `validate_run`, `execute_run`, `cancel_run`, `read_flet_config`.
- **Routing** — `route_validate(body)` and `route_execute(body, **kwargs)`
  inspect `body["workflowId"]` and dispatch to the correct runtime adapter:
  - `BOM_COMPARE_WORKFLOWS` → `bom_compare.runtime`
  - `FAILURE_RATE_WORKFLOWS` → `failure_rate.runtime`
  - `REFDES_WORKFLOWS` → `refdes_extractor.runtime`
  - everything else → `fmea.runtime`
- **Runtime adapters** — `{tool}/runtime.py` translate sidecar request bodies
  into the legacy logic-module call shape, run them, and translate results
  back into protocol payloads. They never reach into Tauri or Rust types.
- **`ActiveRun`** — single-run guard. `execute_run` rejects with an error if
  `_active_run()` is not None. Holds the run id, request id, the bound
  processor (for cancellation), and a `threading.Event` for cancellation
  intent received before the processor is bound.
- **Heartbeat thread** — `_heartbeat_loop` emits one `heartbeat` envelope
  every `HEARTBEAT_INTERVAL` seconds (default 5, override with
  `SIDECAR_HEARTBEAT_INTERVAL`). Tests set this to `9999` to silence it.

## Sidecar Protocol Lifecycle

The protocol has two distinct correlation modes:

| Mode | Field | Used by |
|------|-------|---------|
| Request/response | `request_id` | Synchronous commands (health_check, list_sheets, inspect_input, analyze_template, validate_run, cancel_run) |
| Streamed run | `run_id` | Long-running executions started by `execute_run` |

### Synchronous commands

```
frontend → invoke → Rust → command{request_id} → Python
                                                    ↓
frontend ← deserialize ← Rust ← result{request_id} ← Python
```

### Streamed runs

```
frontend → invoke → Rust → command{request_id} → Python
                                                    ↓
frontend ← run-event ← Rust ← ack{request_id, run_id} ← Python (registers ActiveRun)
                                ↓
                              status / progress / log envelopes
                                ↓
                              result | cancelled | backend_error (terminal)
```

The `ack` envelope is the only message correlated by both `request_id` and
`run_id`. After it lands the Rust bridge resolves the pending request and
forwards every subsequent run-tagged envelope as a Tauri event.

Full payload schemas live in `contracts/sidecar-protocol.md`.

## Heartbeat Supervision

| Layer | Behavior |
|-------|----------|
| Python | `_heartbeat_loop` emits a `heartbeat` envelope every 5 s. |
| Rust   | Records every heartbeat. Supervisor wakes every 5 s and calls `handle_disconnect` if `last_heartbeat` is older than 15 s. |
| Frontend | `useBackendBootstrap` listens for `backend://session` disconnects and runs a reconnect backoff: 2 s → 4 s → 8 s → 15 s → 30 s, then surfaces a permanent error notification. On every successful reconnect it reconciles the active run against the sidecar's `session_generation` (bumped → clear stale run; match → mark reconnected). |

## Tool Wiring Matrix

| Tool | Workflow IDs | Frontend component | Runtime adapter | Logic module |
|------|--------------|--------------------|-----------------|--------------|
| FMEA | `piece_part_generate`, `bom_only`, `functional_to_piecepart`, `fill_gaps` | `frontend/src/features/fmea/FmeaTool.tsx` | `fmea/runtime.py` | `fmea/fmea_generator_logic.py` (+ template analyzer/writer) |
| BOM Compare | `bom_compare_group`, `bom_compare_custom` | `frontend/src/features/bom-compare/BomCompareTool.tsx` | `bom_compare/runtime.py` | `bom_compare/bom_compare_logic.py`, `custom_compare.py` |
| Failure Rate | `failure_rate_link` | `frontend/src/features/failure-rate/FailureRateTool.tsx` | `failure_rate/runtime.py` | `failure_rate/failure_rate_logic.py` |
| RefDes Extractor | `refdes_extract` | `frontend/src/features/refdes-extractor/RefDesExtractorTool.tsx` | `refdes_extractor/runtime.py` | `refdes_test/refdes_test_logic.py` (+ `refdes_extractor/extraction_engine.py`) |
| Settings | (none) | `frontend/src/features/settings/SettingsTool.tsx` | (none) | (none) |

## Runtime Adapter Pattern

Every runtime module exposes the same two functions:

```python
def validate_run_request(body: dict[str, Any]) -> dict[str, Any]: ...

def execute_run_request(
    body: dict[str, Any],
    *,
    log_callback: Callable[[str], None] | None = None,
    status_callback: Callable[[str, str, str], None] | None = None,
    progress_callback: Callable[[str, str, int, int | None, int | None], None] | None = None,
    processor_ready_callback: Callable[[Any], None] | None = None,
) -> dict[str, Any]: ...
```

`validate_run_request` returns `{ ok, reason_code, toast_text, validations,
mode }`. It must be safe to call without any side effects — `execute_run`
in `sidecar_main.py` calls it before accepting a run.

`execute_run_request` is invoked from a background thread spawned by
`_run_in_background`. The four callbacks are wired by the sidecar to emit
`log`, `status`, and `progress` envelopes scoped to the active `run_id`.

### Cancellation

| Adapter | Cancellation surface |
|---------|----------------------|
| `fmea/runtime.py`, `failure_rate/runtime.py` | The processor exposes a `cancel` `CancellationToken` directly. `processor_ready_callback` hands the processor to `ActiveRun.bind_processor`, which calls `processor.cancel.cancel()` when cancellation is requested. |
| `bom_compare/runtime.py`, `refdes_extractor/runtime.py` | `_CancelBridge` wraps a `CancellationToken` plus a `threading.Event` (legacy logic uses `stop_event`). `request_cancel()` sets both. The bridge is exposed through `processor_ready_callback`. |

The progress callback signature is fixed:
`(stage: str, message: str, percent: int, current: int | None, total: int | None)`.
Adapters wrap their tool-internal progress functions to match.

### `shared/pre_run_validation`

All four runtimes call `validate_pre_run_state(...)` from
`shared/pre_run_validation.py` for required-file, sheet-loaded, and column-mapping
checks. It returns a `ValidationResult` that the runtime then translates into
the protocol's `validations` array.

## State Management

| Store | File | Persisted | Purpose |
|-------|------|-----------|---------|
| `useShellStore` | `frontend/src/stores/shellStore.ts` | yes (`zustand/middleware.persist`, key `reliability-tools-tauri-shell`) | active tool id, backend status/mode/message, last health-check timestamp, and per-tool `{fmea,bomCompare,failureRate,refdesExtractor}OutputDirectory: string \| null` |
| `useThemeStore` | `frontend/src/stores/themeStore.ts` | yes (`zustand/middleware.persist`, key `reliability-tools-tauri-theme`) | `mode: "system" \| ThemeId` |
| `useNotificationStore` | `frontend/src/stores/notificationStore.ts` | no | toast list with `push` / `dismiss` / `dismissAll` |

`shellStore` uses `partialize` to persist only the four per-tool output
directories; transient fields (backend status, mode, message) are
excluded so they do not survive a reload with stale values. The shared
`OutputFolderPicker` primitive (`frontend/src/components/OutputFolderPicker.tsx`)
is how every tool exposes the picker — consumers pass the corresponding
`{tool}OutputDirectory` slice through its `value` / `onChange` props.

Tool-local state lives inside each `*Tool.tsx` via `useState` and is not
hoisted into a store. Run lifecycle is owned by `useBackendRunLifecycle`
in `shared/backend/runLifecycle.ts`.

## Security Surface

- **Content Security Policy** (since 0.4.2) — `src-tauri/tauri.conf.json`
  sets `app.security.csp` to a conservative production policy:
  `default-src 'self' ipc: http://ipc.localhost; script-src 'self';
  style-src 'self' 'unsafe-inline'; img-src 'self' asset:
  http://asset.localhost data: blob:; font-src 'self' data:; connect-src
  'self' ipc: http://ipc.localhost; object-src 'none'; base-uri 'self';
  frame-ancestors 'none'`. CSP only applies to packaged release builds —
  Vite serves HTML directly in dev so the Vite HMR pipeline is unaffected.
  If a new tool needs a different source (external SVG, wasm eval, ...),
  relax the relevant directive here — do NOT weaken `default-src`.
- **Subprocess audit** — `common/security_audit.py` AST-walks every
  sidecar `.py` file, rejecting network/database imports and subprocess
  calls outside an explicit allowlist (currently just `attrib`). Runs
  from `sidecar_main.py --self-test`, from `pytest`, and from
  `release.bat` step 3 via `python -m common.security_audit --strict`.
- **Offline invariant** — the Python backend has no network stack. Every
  artifact exchange between frontend and backend goes through file paths
  on the local disk. Adding a network import will fail the security audit
  at build time.

## Crash Reporting

Three independent crash-capture paths write into the same
`<log_dir>/crashes/` directory so a user can zip one folder to share.

| Layer | Hook | Output |
|-------|------|--------|
| Python | `sidecar_main._install_crash_hooks()` installs `sys.excepthook` AND `threading.excepthook` (skipping `KeyboardInterrupt` / `SystemExit`) | `crash_sidecar_<ts>.log`, `crash_thread_<ts>.log` |
| Rust   | `install_rust_panic_hook()` chains after the default printer | `crash_rust_<ts>.log` |
| Frontend | `shared/errors/installGlobalErrorHandlers.ts` catches `window.error` + `unhandledrejection` | `console.error` + notification toast (no disk file today) |

The Python hook also emits one last-gasp `log` envelope on stdout so the
Rust bridge can surface a notification before the sidecar process exits.
Both Python and Rust hooks share the same directory resolution rule
(`RELIABILITY_TOOLS_LOG_DIR` env var > `~/.reliability_tools/logs`).

## Design Decisions and Trade-offs

These are brief pointers; the full ADR text lives in `docs/DECISIONS.md`.

- **NDJSON over stdio** — one JSON object per line, no framing protocol,
  no length prefixes. Easy to debug with a manual stdin paste, easy to
  capture with `tee`. Trade-off: no zero-copy binary payloads, every
  artifact crosses as a file path.
- **Sidecar over embedded Python** — Tauri does not embed CPython. Running
  Python out-of-process means we can ship the same backend code as the
  legacy Flet build, isolate crashes from the desktop UI, and use a
  conventional `.venv` in development.
- **PyInstaller bundling** — `scripts/build_sidecar.py` produces a single
  `reliability-tools-sidecar.exe`. Rust prefers the bundled exe at runtime
  and falls back to `.venv/Scripts/python.exe + sidecar_main.py` in dev.
- **Managed single-session sidecar** — one process for the lifetime of the
  window. Avoids per-command spawn cost and lets the Python side maintain
  warm caches. The single-active-run guard makes the model honest.
- **Single active run** — only one `execute_run` may be in flight at a time.
  Concurrency is bounded inside the run by Python threads, not by stacking
  runs. Simplifies cancellation, progress routing, and the UI state machine.
