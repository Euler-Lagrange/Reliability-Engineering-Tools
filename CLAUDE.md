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
    primitives/         # Reusable low-level UI primitives
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
| FMEA Generator | `piece_part_generate`, `bom_only`, `functional_to_piecepart`, `fill_gaps` | `features/fmea/FmeaTool.tsx` | `fmea/runtime.py` |
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
npm test                 # Vitest (143 tests)

# Desktop (requires Rust toolchain)
npm run tauri:dev        # Dev mode with hot reload
npm run tauri:build:portable  # Release build → src-tauri/target/.../release/

# Python sidecar (use project venv)
.venv\Scripts\python.exe -m pytest backend/tests -v    # 101 backend tests (33 sidecar + 17 audit + 8 cancel bridge + 43 FMEA phase D)
.venv\Scripts\python.exe backend/python/sidecar_main.py --self-test

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
- `<GlobalLogPanel>` is mounted at the App shell level (not per-tool), so every tool automatically gets the cross-tool run log. Tools don't need to render it.
- `cancelError.ts` for cancel/abort error normalization
- `useBackendBusyReset` hook for clearing stale busy status
- `useCopyToClipboard` hook for clipboard operations

### File Picker
- `backendClient.openExcelFile()` for `.xlsx/.xls/.xlsm`
- `backendClient.openPdfFile()` for `.pdf`
- `backendClient.openDirectory()` for output folder selection
- After picking: `listSheets()` → `inspectInput()` for Excel; direct path set for PDF

## Python Import Policy

- All backend Python imports resolve from `backend/python/`. Python adds the
  script's parent directory to `sys.path` automatically when the sidecar is
  invoked as `python backend/python/sidecar_main.py`. The Rust bridge does
  **not** call `current_dir()` on the spawn — the import root comes from
  the script path, not the working directory.
- `common/` is a self-contained package — no external dependencies
- Tool packages import from `common` and from each other (e.g., `refdes_test` → `refdes_extractor`)
- **No manual `sys.path` manipulation in production code** — all imports are direct

## Security

The sidecar is offline / air-gapped and the policy is enforced statically by
`backend/python/common/security_audit.py`, which AST-walks every `.py` file
under `backend/python/` and reports:

1. Imports of network modules (`socket`, `urllib.request`, `http.client`,
   `requests`, `httpx`, ...). Pure-string helpers like `urllib.parse` are
   intentionally permitted.
2. Imports of database modules (`sqlite3`, `psycopg`, `pymongo`,
   `sqlalchemy`, ...).
3. `subprocess.*` calls whose statically-resolvable command head is not in
   the allowlist below.

**Subprocess allowlist:** `attrib`, `powershell`, `start`, `python`, `pythonw`.
The only command actually invoked today is `attrib` (in `common/utils.py`,
for OneDrive cloud-file detection and hydration); the rest are reserved for
vetted helpers.

The audit runs:

- As a regression test: `pytest backend/tests/test_security_audit.py`
- During the sidecar self-test: `python backend/python/sidecar_main.py --self-test`
- On demand from the CLI: `python -m common.security_audit --root backend/python --strict`
  (must be run with `backend/python` as the working directory so that
  `common` resolves as a top-level package)

## Testing

### Backend Tests (101 total)
- 33 sidecar integration tests in `test_sidecar_main.py`
- 17 security-audit tests in `test_security_audit.py` (synthetic positives + live tree scan)
- 8 cancel-bridge tests in `test_cancel_bridge.py`
- 43 FMEA Phase D tests in `test_fmea_phase_d.py`
- Sidecar tests are subprocess-based: spawn sidecar, send NDJSON commands, verify responses
- `stderr=subprocess.DEVNULL` to avoid Windows pipe buffer deadlock
- `SIDECAR_HEARTBEAT_INTERVAL=9999` suppresses heartbeats during tests
- `SIDECAR_LOG_LEVEL=CRITICAL` suppresses file logging
- `RELIABILITY_TOOLS_LOG_DIR` isolates log files per test session
- `pytest.importorskip("fitz")` for RefDes tests requiring PyMuPDF
- `backend/tests/conftest.py` installs a `sys.path` shim for in-process unit tests

### Frontend Tests (143 total)
- Vitest + React Testing Library
- Browser-mock mode (no Tauri runtime needed)
- `src/app/App.test.tsx` — 10 tests
- `src/components/CustomSelect.test.tsx` — 1 test
- `src/components/MappingTable.test.tsx` — 10 tests
- `src/components/RunStatePanel.test.tsx` — 5 tests
- `src/components/GlobalLogPanel.resize.test.tsx` — 13 tests
- `src/components/primitives/CommandPalette.test.tsx` — 5 tests
- `src/components/primitives/HoldButton.test.tsx` — 5 tests
- `src/components/primitives/EmptyState.test.tsx` — 5 tests
- `src/features/fmea/FmeaTool.test.tsx` — 7 tests
- `src/features/fmea/mappingColumns.test.ts` — 21 tests
- `src/features/fmea/mappingAnalysis.test.ts` — 6 tests
- `src/shared/backend/runLifecycle.test.ts` — 8 tests
- `src/shared/backend/cancelError.test.ts` — 12 tests
- `src/shared/backend/client.cancelRun.test.ts` — 2 tests
- `src/shared/backend/useBackendBusyReset.test.ts` — 9 tests
- `src/shared/theme/themeRegistry.test.ts` — 10 tests
- `src/shared/hooks/useRoleRequestSequence.test.ts` — 5 tests
- `src/shared/hooks/useCopyToClipboard.test.ts` — 3 tests
- `src/stores/globalLogStore.test.ts` — 6 tests

## Critical Gotchas

- **Stdin write atomicity**: The Rust bridge writes payload+newline+flush under a single `stdin.lock()` — do NOT split into separate locks
- **CancellationError inheritance**: `CancellationError → InterruptedError → OSError → Exception` — always re-raise before `except Exception`
- **Heartbeat**: Python emits every 5s, Rust times out at 15s, frontend auto-reconnects with backoff
- **NaN guards**: Always `pd.notna(value)` before string operations on DataFrame cells
- **Single active run**: Only one `execute_run` at a time; second request is rejected

## Delegation Defaults — Use Skills and Agents Proactively

**Default to delegation, not direct work.** Skills and agents exist to keep responses focused, protect the main context window, and leverage specialized expertise. Reach for them automatically — do not wait for the user to ask.

### When to invoke Skills (via the Skill tool)

| Skill | Trigger — use automatically when... |
|-------|-------------------------------------|
| `code-review` | Before any commit, or when the user asks to "review" / "check" code |
| `quick-review` | For pre-commit lightweight checks on a small change |
| `git-workflow` | Writing commit messages, preparing releases, tagging versions |
| `release` | Running the full release pipeline or preparing a distribution |
| `testing-workflow` | Writing new tests, running pytest, adding test fixtures |
| `design-principles` | Building/modifying UI — especially theme, typography, component design |
| `simplify` | After finishing a feature — review changed code for reuse/quality opportunities |
| `debug-guide` | When troubleshooting runtime errors, test failures, or unexpected behavior |
| `update-config` | When the user asks to configure settings.json, hooks, or harness behavior |

### When to launch Agents (via the Agent tool)

| Agent | Trigger — use automatically when... |
|-------|-------------------------------------|
| `Explore` | Searching for code, answering "where is X", or unfamiliar area exploration. **Always prefer this over running multiple Grep/Glob calls serially.** |
| `Plan` | Designing implementation for any non-trivial task (>3 files or architectural decisions). **Never skip this for large features.** |
| `architect` | Complex multi-component designs, cross-layer refactors, or ADR work |
| `developer` | Delegating implementation of a well-specified feature with tests |
| `debugger` | Systematic debugging when the root cause is unclear after initial investigation |
| `quality-reviewer` | Reviewing code for security, data loss, performance issues |
| `technical-writer` | Any documentation creation/update — use multiple in parallel for large doc sweeps |
| `adr-writer` | Recording architecture decisions (see `docs/DECISIONS.md` for format) |

### Parallel Agent Patterns

- **Multiple independent explorations:** Launch 2-3 `Explore` agents in parallel in a single message with different focus areas
- **Large doc sweeps:** Launch multiple `technical-writer` agents with non-overlapping file sets
- **Research then implement:** `Plan` or `architect` first, then `developer` with the plan's output as its spec
- **Verify before acting:** `Explore` to verify claims, then act on verified findings — never trust GPT reviews or external reports without verification

### Anti-patterns to avoid

- **Running 5+ serial Grep/Glob/Read calls** when an Explore agent would do it in one pass
- **Writing implementation code directly for features >100 lines** when a `developer` agent could do it with tests
- **Designing large features without a Plan agent** — plans catch architectural issues that direct coding misses
- **Hand-writing commit messages** when `git-workflow` has the project conventions
- **Skipping pre-commit review** when `code-review` or `quick-review` exists
