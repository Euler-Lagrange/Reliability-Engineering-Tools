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
| BOM Compare | `bom_compare_group`, `bom_compare_custom`, `extraction_compare` | `features/bom-compare/BomCompareTool.tsx` | `bom_compare/runtime.py` |
| Failure Rate | `failure_rate_link` | `features/failure-rate/FailureRateTool.tsx` | `failure_rate/runtime.py` |
| RefDes Extractor | `refdes_extract` | `features/refdes-extractor/RefDesExtractorTool.tsx` | `refdes_extractor/runtime.py` |
| Settings | — (frontend-only) | `features/settings/SettingsTool.tsx` | — |

## Sidecar Protocol

NDJSON over stdio. Commands: `health_check`, `list_sheets`, `inspect_input`, `analyze_template`, `validate_run`, `execute_run`, `cancel_run`, `read_flet_config`, `read_refdes_prefixes`, `write_refdes_prefixes`.

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
npm run typecheck:tests  # TypeScript type checking for Vitest files
npm test                 # Vitest (275 tests)

# Desktop (requires Rust toolchain)
npm run tauri:dev        # Dev mode with hot reload
npm run tauri:build:portable  # Release build → src-tauri/target/.../release/
npm run cargo:test       # Rust bridge unit tests via the repo runner

# Python sidecar (use project venv)
.venv\Scripts\python.exe -m pytest backend/tests -v    # 329 backend tests (48 sidecar + 27 audit + 12 cancel bridge + 10 output-directory helper + 58 FMEA phase D + 24 failure-rate logic + 15 RefDes extraction-engine + 31 BOM-compare logic + 9 BOM-compare runtime + 7 extraction-compare + 2 failure-rate runtime + 6 read-layer + 19 RefDes BOM-coverage + 6 BOM-loader + 5 OneDrive detection + 3 file-size guard + 3 crash-dump + 8 NextGen engine + 24 RefDes runtime + 12 validation-notes)
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

The sidecar is offline / air-gapped. `backend/python/common/security_audit.py`
AST-walks every `.py` file under `backend/python/` as a **static regression net
against accidental introductions** (not an adversarial sandbox — see the scope
note below) and reports:

1. Imports of network modules (`socket`, `urllib.request`, `http.client`,
   `requests`, `httpx`, ...). Pure-string helpers like `urllib.parse` are
   intentionally permitted.
2. Imports of database modules (`sqlite3`, `psycopg`, `pymongo`,
   `sqlalchemy`, ...).
3. Imports of native-code modules (`ctypes`) — arbitrary DLL calls that would
   bypass every other rule here.
4. Command execution whose statically-resolvable command head is not in the
   allowlist below. This covers `subprocess.*` under any import form
   (`import subprocess`, `import subprocess as sp`, `from subprocess import
   run`) and `os.system` / `os.popen` (same allowlist); `os.startfile` is
   flagged on any use.

**Subprocess allowlist:** `attrib` (only). The list is intentionally
minimal — the only command invoked today is `attrib` (in
`common/utils.py`, for OneDrive cloud-file detection and hydration).
Extending the allowlist requires adding the command here AND updating
`SUBPROCESS_ALLOWLIST` in `common/security_audit.py`.

**Scope:** the audit resolves command heads and import names *statically*. It
deliberately does **not** chase dynamic escapes — `importlib.import_module("soc"
+ "ket")`, `eval`, or a module rebound to a local variable — which are out of
scope by design (the sidecar is in-house and non-adversarial). It catches the
accidental `import requests` / stray `subprocess.run(["curl", ...])`, not a
determined bypass.

The audit runs:

- As a regression test: `pytest backend/tests/test_security_audit.py`
- During the sidecar self-test: `python backend/python/sidecar_main.py --self-test`
- On demand from the CLI: `python -m common.security_audit --root backend/python --strict`
  (must be run with `backend/python` as the working directory so that
  `common` resolves as a top-level package)

## Testing

### Backend Tests (329 total)
- 48 sidecar integration tests in `test_sidecar_main.py` (incl. the RefDes BOM-coverage sheet emission, the extraction_compare validate/execute pair, and the refdes-prefix read/write round-trip with HOME isolated to tmp_path)
- 27 security-audit tests in `test_security_audit.py` (synthetic positives + live tree scan; incl. subprocess via alias/from-import, os.system/popen/startfile, and ctypes native-import detection)
- 12 cancel-bridge tests in `test_cancel_bridge.py` (BOM Compare + RefDes bridges plus Failure Rate `FMEALinkerLogic.cancel` binding through `ActiveRun`)
- 10 output-directory helper tests in `test_output_directory_helpers.py` (incl. Tier-2 #18 preserve-mode output path honoring the chosen folder, and #19 validate-time output-directory warning + the shared `output_directory_validation` helper)
- 58 FMEA Phase D tests in `test_fmea_phase_d.py` (incl. the hdaSource contract, fill_gaps no-count-source flagging, and Tier-1 Part Usage compute-or-blank+flag: instance-count 1/N derivation counting distinct physical instances not occurrences, blank+PU_GUESSED flag, explicit-value preservation)
- 24 Failure-Rate logic tests in `test_failure_rate_logic.py` (incl. circuit-block roll-up, leaf-block preservation, prediction-FR coercion flagging, and Tier-1 genuine-gap Part Usage: blank usage with real FR → NaN Mode_FR, formula-cell-as-NaN, unmatched-RefDes zero preserved, roll-up skips blank child, all-gap-children block blanks to NaN)
- 15 RefDes extraction-engine tests in `test_extraction_engine.py` (pin-disambiguation, Tier-2 #20 pinlist-failure streaming, and the geometry RefDes-check prefix-allowlist alignment (#6) + `pin_assignment_threshold` key + cap-hit warning)
- 31 BOM-compare logic tests in `test_bom_compare_logic.py` (incl. custom-path option semantics, residual-digit guard, non-numeric FMR flagging, per-column value-diff contract, and Tier-4 FMR-key canonicalization against invisible-char RefDes)
- 9 BOM-compare runtime tests in `test_bom_compare_runtime.py` (dnp_regex default, Do-Not-Map sentinel validation, custom option wiring, compare_columns forwarding)
- 7 extraction-compare tests in `test_extraction_compare.py` (rev-to-rev differ: appeared/disappeared/moved buckets, (Verified)/(Unverified) suffix + gap-row normalization against phantom churn, UNGROUPED as a named bucket, styled 4-sheet report read-back)
- 2 Failure-Rate runtime tests in `test_failure_rate_runtime.py` (Do-Not-Map sentinel validation)
- 6 read-layer tests in `test_read_layer.py` (Excel/CSV NA-literal parity, duplicate-header dedup matching pandas)
- 19 RefDes BOM-coverage tests in `test_coverage_report.py` (reverse-diff buckets: Not Extracted / Extracted-Ungrouped / Extracted-Provisional, component-level normalization, deterministic collapse of same-base BOM rows, unparented-pin rejection, multi-row page/group union, NaN-cell guards, BOM enrichment, summary counts, sheet writer)
- 6 BOM-loader tests in `test_bom_loader.py` (opt-in Part Number / Description capture keyed to the normalized RefDes, Description-over-Name precedence, pin-style rows count as their base component)
- 5 OneDrive-detection tests in `test_onedrive_detection.py` (Decision A: env-var-first OneDrive path detection with directory-boundary match + substring fallback)
- 3 file-size guard tests in `test_file_guards.py` (Decision C: `ensure_file_size_within` caps the full analyze_template load against OOM)
- 3 crash-dump tests in `test_crash_dump.py` (Decision B: review-before-sharing banner + embedded-value truncation)
- 8 NextGen-engine tests in `test_nextgen_engine.py` (default engine: pinlist-failure streamed to the run log; word-extraction-timeout surfacing; pin-token verification against pin-level BOM entries incl. the Verified-row formatting; diagnostics accumulator: None is a no-op, token-diag merge skips None fields, pinned orphan-disposition vocabulary, token-pages fold with mode-suffix strip)
- 24 RefDes-runtime tests in `test_refdes_runtime.py` (output DataFrame drops internal `_is_gap`/`_row_style` columns and renames to Title Case display headers; blocking type/range validation of all 16 engine options at validate time, incl. the 0-valid adaptive-orphan threshold and a config-field lockstep guard)
- 12 validation-notes tests in `test_validation_notes.py` (cross-group duplicate ordinals by page order, V/U split never self-flags, not-in-BOM notes gated on a provided BOM, gap-row notes, ambiguous-token notes + warning style, Component Detail / Orphan Pins sheet read-back incl. skip-when-empty, styled-workbook read-back: Aptos Narrow, frozen header, header fill, duplicate-row amber highlight)
- Sidecar tests are subprocess-based: spawn sidecar, send NDJSON commands, verify responses
- `stderr=subprocess.DEVNULL` to avoid Windows pipe buffer deadlock
- `SIDECAR_HEARTBEAT_INTERVAL=9999` suppresses heartbeats during tests
- `SIDECAR_LOG_LEVEL=CRITICAL` suppresses file logging
- `RELIABILITY_TOOLS_LOG_DIR` isolates log files per test session
- `pytest.importorskip("fitz")` for RefDes tests requiring PyMuPDF
- `backend/tests/conftest.py` installs a `sys.path` shim for in-process unit tests

### Frontend Tests (275 total across 41 test files)
- Vitest + React Testing Library
- Browser-mock mode (no Tauri runtime needed)
- `src/app/App.test.tsx`
- `src/app/App.keepalive.test.tsx` (new in 0.4.6)
- `src/app/App.shellHooks.test.tsx` (new — Tier-3 #28 shell-hook install guard)
- `src/components/ContextDrawer.test.tsx` (new in 0.4.5)
- `src/components/CustomSelect.test.tsx`
- `src/components/MappingTable.test.tsx`
- `src/components/RunStatePanel.test.tsx` (now covers the Open-folder affordance)
- `src/components/ValidationPreview.test.tsx` (new — compact 2-column preview, EmptyState, Full-preview drawer affordance)
- `src/components/OutputFolderPicker.test.tsx` (new — Tier-3 #26 backend-error surfacing)
- `src/components/GlobalLogPanel.resize.test.tsx`
- `src/components/primitives/CommandPalette.test.tsx`
- `src/components/primitives/HoldButton.test.tsx`
- `src/components/primitives/EmptyState.test.tsx`
- `src/components/primitives/NumberField.test.tsx` (new in 0.4.6)
- `src/contracts/sidecar.test.ts`
- `src/features/bom-compare/BomCompareTool.test.tsx` (new in 0.4.6; incl. Extraction Compare slots + hidden mapping card)
- `src/features/failure-rate/FailureRateTool.test.tsx` (new in 0.4.6)
- `src/features/refdes-extractor/RefDesExtractorTool.test.tsx` (new in 0.4.6)
- `src/features/fmea/FmeaTool.test.tsx`
- `src/features/fmea/FmeaTool.inspection.test.tsx`
- `src/features/fmea/mappingColumns.test.ts`
- `src/features/fmea/mappingAnalysis.test.ts`
- `src/features/settings/SettingsTool.test.tsx` (new — RefDes prefix editor: load/add/remove/save, client-side validation, browser-mode guard)
- `src/features/toolRunDispatch.test.tsx` (now covers the FMEA payload keys + the extraction_compare no-mappings/no-options payload)
- `src/mocks/scenarios.test.ts` (new — Tier-3 #28 scenario completeness)
- `src/shared/backend/runLifecycle.test.ts` (now covers the terminal-status guard)
- `src/shared/backend/useDesktopRunController.test.ts` (new — success-toast two-event ordering)
- `src/shared/backend/cancelError.test.ts`
- `src/shared/backend/client.cancelRun.test.ts`
- `src/shared/backend/client.runEvents.test.ts`
- `src/shared/backend/useBackendBusyReset.test.ts`
- `src/shared/backend/useBackendBootstrap.test.ts` (new in 0.4.2)
- `src/shared/backend/useBackendRunSubscription.test.ts` (new in 0.4.2)
- `src/shared/hooks/useAppShortcuts.test.tsx` (new in 0.4.2)
- `src/shared/hooks/useRoleRequestSequence.test.ts`
- `src/shared/hooks/useCopyToClipboard.test.ts`
- `src/shared/mapping/deriveMappingRows.test.ts` (new in 0.4.6)
- `src/shared/theme/themeRegistry.test.ts`
- `src/stores/globalLogStore.test.ts`
- `src/stores/notificationStore.test.ts` (new — toast eviction never drops the incoming)
- `src/stores/storeMigrations.test.ts` (new — Decision E persist version/migration)

Run `npx vitest run --config frontend/vite.config.ts --reporter=default` to
see individual counts per file — the suite totals 275 tests and changes
whenever a suite gains or loses cases.

## Critical Gotchas

- **Stdin write atomicity**: The Rust bridge writes payload+newline+flush under a single `Mutex<ChildStdin>` guard (one `lock()` call, not three) — do NOT split into separate locks, or NDJSON frames from concurrent commands will interleave
- **CancellationError inheritance**: `CancellationError → InterruptedError → OSError → Exception` — always re-raise before `except Exception`
- **Heartbeat**: Python emits every 5s, Rust times out at 15s, frontend auto-reconnects with backoff
- **NaN guards**: Always `pd.notna(value)` before string operations on DataFrame cells
- **Single active run**: Only one `execute_run` at a time; second request is rejected
- **Atomic write temp-path extension**: `common/utils.atomic_write_path()` returns `<stem>.<hex>.part<suffix>` so the temp file keeps its `.xlsx` extension. Do NOT rename to drop the suffix — `openpyxl`'s post-write `verify_excel_readable()` sniffs format from the suffix and will reject extension-less temps.
- **Windows Job Object owns the sidecar**: on Windows the Rust bridge creates a `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` job and assigns the spawned `python.exe` to it (`windows_job` module in `src-tauri/src/lib.rs`). When the bridge process dies, Windows reaps the sidecar automatically. Do NOT remove the assignment — without it a Rust panic that bypasses `on_window_event` orphans a live sidecar process.
- **Shell-level run subscription**: `useBackendRunSubscription` is mounted once in `App.tsx` and owns the subscription to `backend://run-event`. Per-tool hooks (`useBackendRunLifecycle`) project events into local state but do NOT subscribe directly. If you need a new stream subscription, add it next to `useBackendRunSubscription` at the shell level — do not subscribe inside a tool component or you will miss events during tool switches.
- **Keep-alive tool shell**: `App.tsx` mounts each tool on first visit and keeps it mounted afterwards, hiding inactive tools behind a `[hidden]` pane. Tool-local state (loaded files, sheet selections, mapping overrides) deliberately survives tool switches — do NOT revert to a single `<ActiveToolComponent />` render or add a `key` to tool panes, both of which remount tools and destroy loaded inputs.

## Wiring Invariants — Anti-Tech-Debt Rules

Every one of these rules exists because its violation shipped a real bug
(found and fixed in the 0.4.6 audits). Violating them recreates known tech
debt. When adding or reviewing UI/option/backend code, check the change
against this list.

1. **Every interactive control must be wired end-to-end.** A control's
   handler → state → consumer chain must terminate in something real: a
   backend reader, a store, a render branch, or an OS call. Never add an
   option key to a tool's `options` state without the matching reader in
   that tool's `runtime.py` (and a runtime test proving it) — `base_match`
   and `hdaSource` were sent for months while the backend read neither.
   The inverse also holds: a backend option with no UI control must either
   get a control or be removed from the frontend payload.
2. **If a control is inert in a particular mode, disable it with a hint —
   never render it silently ignored.** Pattern: RefDes adaptive-geometry
   checkbox, BOM Compare `treat_prov_as_covered` in custom mode
   (`disabled` + `hint` on `CheckboxField`).
3. **Never seed example/mock paths into desktop state.** Desktop-bridge
   seeding goes through `emptyInputsFromScenario` (shared in
   `useDesktopRunController.ts`); `cloneInputs(scenario.inputs)` is for
   browser-mock only. Example `DRIVE\inputs\...` paths pass backend
   validation and then crash mid-run with paths the user never typed.
4. **Mock scenario data is load-bearing.** Every workflow needs a
   `DemoScenario` whose `inputs` cover ALL of that workflow's roles —
   a missing scenario/role rendered Custom Compare with zero file slots.
   When adding a workflow, add its scenario (or a role-complete superset
   like FMEA's `allPrototypeInputs`) in the same change.
5. **All backend-invoke `catch` blocks use `describeBackendError`**
   (`shared/backend/cancelError.ts`). Tauri v2 rejects with raw strings;
   `error instanceof Error ? error.message : fallback` silently discards
   every real sidecar message. Never reintroduce that ternary.
6. **`DO_NOT_MAP_VALUE` has exactly two definitions** that must stay in
   lockstep: `frontend/src/app/types.ts` and
   `backend/python/shared/pre_run_validation.py` (`DO_NOT_MAP_SENTINEL`,
   re-exported by `fmea/runtime.py`). Backends must reject the sentinel on
   REQUIRED mappings at validate time (`invalid_do_not_map`), not crash at
   execute.
7. **Mapping rows derive from real inspected headers** via
   `shared/mapping/deriveMappingRows.ts` (BOM Compare, Failure Rate) or
   `buildFmeaMappingRows` (FMEA). The static fixture rows in
   `mocks/scenarios.ts` are the fallback for un-inspected roles only —
   never the live dropdown source for a loaded file.
8. **`handleStartRun` is re-entrancy-guarded** (`isStartingRef`) in every
   tool, and failed-start cleanup goes through `resetSessionUnlessLive` so
   it can never clobber a live run's session. Keep both when touching run
   dispatch.
9. **When stashing input state across a context switch** (e.g. BOM
   Compare's per-workflow cache), sanitize in-flight busy flags
   (`isResolvingSheets`/`isAnalyzing`) and bump the per-role request
   tokens — a verbatim stash restores a permanently-stuck slot whose
   orphaned continuation can never clear it.
10. **Keep doc counts honest.** Test counts live in CLAUDE.md (twice),
    README.md, and docs/TESTING.md (two tables). If a suite gains or loses
    cases, update all of them in the same commit — drift between them was
    a recurring QA finding.

## Crash Dumps

Unhandled exceptions on either side of the bridge write a timestamped
file under `~/.reliability_tools/logs/crashes/` (or
`$RELIABILITY_TOOLS_LOG_DIR/crashes/`). Each dump opens with a
review-before-sharing banner and truncates any embedded value (Decision B) —
a crash can echo a BOM / part value into an exception / panic message:

- **Python** — `sidecar_main._install_crash_hooks()` installs
  `sys.excepthook` AND `threading.excepthook`, skipping `KeyboardInterrupt`
  / `SystemExit`. Files are `crash_sidecar_*.log` / `crash_thread_*.log`.
  The hook also emits one last `log` envelope on stdout so the Rust
  bridge surfaces a notification before the process dies. See
  `common/logger.write_crash_dump()`.
- **Rust** — `install_rust_panic_hook()` in `src-tauri/src/lib.rs` chains
  on top of the default panic printer and writes `crash_rust_*.log`. Zero
  new Cargo dependencies (uses `USERPROFILE` / `HOME` directly).
- **Frontend** — `shared/errors/installGlobalErrorHandlers.ts` catches
  `window.error` and `unhandledrejection` (neither caught by
  `ErrorBoundary`), logs to `console.error`, and surfaces an error toast
  via `useNotificationStore`. Installed in `main.tsx` before React mounts.

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
