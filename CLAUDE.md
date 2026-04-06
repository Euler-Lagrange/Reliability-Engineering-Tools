# CLAUDE.md — Reliability Tools Desktop (Tauri)

> This is a standalone Tauri desktop application. No dependency on any legacy/Flet codebase.

## Project Identity

**Stack:** Tauri 2.x (Rust) + React 19 (TypeScript) + Python sidecar (pandas, openpyxl, PyMuPDF)
**Entry:** `frontend/src/main.tsx` (React) | `src-tauri/src/lib.rs` (Rust) | `backend/python/sidecar_main.py` (Python)
**Build:** `npm run tauri:build:portable` | `scripts/release.bat`

## Architecture

```
frontend/src/           # React + TypeScript UI
  app/                  # Shell, tool registry, types
  features/             # Tool components (one dir per tool)
  components/           # Shared UI components
  shared/               # Backend client, theme, errors, hooks
  stores/               # Zustand state (shell, theme, notifications)
  contracts/            # Zod schemas for sidecar protocol
  mocks/                # Browser-preview demo data

src-tauri/src/          # Rust desktop bridge
  lib.rs                # Managed sidecar session, Tauri commands, heartbeat supervisor

backend/python/         # Python sidecar (NDJSON over stdio)
  sidecar_main.py       # Protocol handler, command routing, heartbeat
  common/               # Self-contained shared utilities (12 modules)
  fmea/                 # FMEA generator logic + runtime adapter
  bom_compare/          # BOM comparison logic + runtime adapter
  failure_rate/         # Failure rate linker logic + runtime adapter
  refdes_extractor/     # RefDes extraction logic + runtime adapter (PyMuPDF)
  refdes_test/          # NextGen extraction engine + shared constants
  shared/               # Pre-run validation helpers

backend/tests/          # Sidecar integration tests (subprocess-based)
contracts/              # Protocol documentation (sidecar-protocol.md)
```

## Tools (All Active)

| Tool | Workflow IDs | Frontend | Runtime |
|------|-------------|----------|---------|
| FMEA Generator | `piece_part_generate`, `bom_only`, `fill_gaps` | `features/fmea/FmeaTool.tsx` | `fmea/runtime.py` |
| BOM Compare | `bom_compare_group`, `bom_compare_custom` | `features/bom-compare/BomCompareTool.tsx` | `bom_compare/runtime.py` |
| Failure Rate | `failure_rate_link` | `features/failure-rate/FailureRateTool.tsx` | `failure_rate/runtime.py` |
| RefDes Extractor | `refdes_extract` | `features/refdes-extractor/RefDesExtractorTool.tsx` | `refdes_extractor/runtime.py` |
| Settings | — (frontend-only) | `features/settings/SettingsTool.tsx` | — |

## Sidecar Protocol

NDJSON over stdio. Commands: `health_check`, `list_sheets`, `inspect_input`, `analyze_template`, `validate_run`, `execute_run`, `cancel_run`, `read_flet_config`.

- `validate_run` and `execute_run` route by `workflowId` to tool-specific runtime adapters
- `execute_run` returns `ack` immediately, then streams `status`/`progress`/`log` events, then a terminal `result`/`cancelled`/`backend_error`
- Heartbeat emitted every 5s by Python, supervised by Rust (15s timeout)
- See `contracts/sidecar-protocol.md` for full spec

## Dev Commands

```bash
# Frontend
npm run dev              # Vite dev server (browser preview mode)
npm run build            # Production build
npm run typecheck        # TypeScript type checking
npm test                 # Vitest (5 tests)

# Desktop (requires Rust toolchain)
npm run tauri:dev        # Dev mode with hot reload
npm run tauri:build:portable  # Release build → src-tauri/target/.../release/

# Python sidecar (use project venv)
..\.venv\Scripts\python.exe -m pytest backend/tests -v    # 27 integration tests
..\.venv\Scripts\python.exe backend/python/sidecar_main.py --self-test

# Full release
scripts/release.bat
```

## Key Patterns

### Adding a New Tool
1. Create `backend/python/{tool}/runtime.py` with `validate_run_request()` and `execute_run_request()`
2. Add workflow routing in `sidecar_main.py` (`route_validate` / `route_execute`)
3. Create `frontend/src/features/{tool}/{Tool}Tool.tsx`
4. Register in `frontend/src/app/toolRegistry.tsx`
5. Add mock scenarios in `frontend/src/mocks/scenarios.ts`
6. Add types to `frontend/src/app/types.ts`

### Runtime Adapter Pattern
Each tool's `runtime.py` follows the same structure:
- `validate_run_request(body) -> dict` — check required files, mappings, options
- `execute_run_request(body, *, log_callback, status_callback, progress_callback, processor_ready_callback) -> dict` — load files, run logic, write output, return result metadata
- Uses `_CancelBridge` for cancellation (CancellationToken + threading.Event)
- Uses `shared/pre_run_validation.py` for input validation

### Frontend Tool Pattern
Each tool component uses:
- `useBackendRunLifecycle` hook for run session state
- `InputGrid` for file inputs with sheet selection
- `MappingTable` for column mapping (optional)
- `RunStatePanel` for execution progress and results
- `SectionCard` for layout sections
- Mock scenarios for browser-preview mode

### File Picker
- `backendClient.openExcelFile()` for `.xlsx/.xls/.xlsm`
- `backendClient.openPdfFile()` for `.pdf`
- After picking: `listSheets()` → `inspectInput()` for Excel; direct path set for PDF

## Python Import Policy

- All backend Python imports resolve from `backend/python/` (the sidecar CWD)
- `common/` is a self-contained package — no external dependencies
- Tool packages import from `common` and from each other (e.g., `refdes_test` → `refdes_extractor`)
- **No `sys.path` manipulation** — all imports are direct

## Security

- Offline/air-gapped — no network imports in Python backend
- `common/security_audit.py` blocks network/database/unauthorized subprocess imports
- Subprocess allowlist: `attrib`, `powershell`, `start`, `python`, `pythonw`

## Testing

### Backend Tests (27 integration tests)
- Subprocess-based: spawn sidecar, send NDJSON commands, verify responses
- `stderr=subprocess.DEVNULL` to avoid Windows pipe buffer deadlock
- `SIDECAR_HEARTBEAT_INTERVAL=9999` suppresses heartbeats during tests
- `SIDECAR_LOG_LEVEL=CRITICAL` suppresses file logging
- `RELIABILITY_TOOLS_LOG_DIR` isolates log files per test session
- `pytest.importorskip("fitz")` for RefDes tests requiring PyMuPDF

### Frontend Tests (5 component tests)
- Vitest + React Testing Library
- Browser-mock mode (no Tauri runtime needed)

## Critical Gotchas

- **Stdin write atomicity**: The Rust bridge writes payload+newline+flush under a single `stdin.lock()` — do NOT split into separate locks
- **CancellationError inheritance**: `CancellationError → InterruptedError → OSError → Exception` — always re-raise before `except Exception`
- **Heartbeat**: Python emits every 5s, Rust times out at 15s, frontend auto-reconnects with backoff
- **NaN guards**: Always `pd.notna(value)` before string operations on DataFrame cells
- **Single active run**: Only one `execute_run` at a time; second request is rejected
