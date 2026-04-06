# Tauri Migration Handoff

This file is the durable handoff record for the `tauri_build` migration track. It summarizes:

- the full phased migration plan
- which phases are complete vs partial
- what code review should focus on for each phase
- what remains before the Tauri app can replace the Flet app

The current Flet app under `src/` remains frozen and untouched by this migration work.

## Current Snapshot

Status as of `2026-04-06`:

- `Phase 0` complete
- `Phase 1` complete
- `Phase 2` complete
- `Phase 3` complete
- `Phase 4` complete (expanded: fill-gaps + template-preserve + desktop build verified)
- `Phase 5` in progress (heartbeat supervision landed)
- `Phase 6` not started

Current portable desktop artifact:

- `tauri_build/local_build/ReliabilityToolsDesktop.exe`

Latest verification (`2026-04-06`):

- `npm run typecheck` passed
- `npm test` passed (5/5)
- `..\.venv\Scripts\python.exe -m pytest backend\tests -v` passed (18/18)
- `npm run tauri:build:portable` passed (Rust 1.94.1 installed, build verified)
- `..\.venv\Scripts\python.exe -m pytest tests/ -q` passed (1153/1153 — no Flet regressions)

## Phase Plan

### Phase 0: Adopt Prototype and Lock Architecture

Goal:

- adopt the original Dark Star prototype into `tauri_build`
- establish the new folder layout and migration boundary
- leave Python/Flet untouched

Planned deliverables:

- `frontend/`
- `src-tauri/`
- `backend/python/`
- `backend/tests/`
- `contracts/`
- `docs/`
- `scripts/`
- `local_build/`
- `logs/`

Status:

- complete

What was completed:

- `tauri_build` created as the separate migration track
- old prototype adopted instead of rebuilding from zero
- desktop packaging, release script, and docs baseline established
- migration kept isolated from the Flet codebase

Code review focus:

- confirm no imports or runtime coupling accidentally point back into Tauri from the Flet app
- confirm folder boundaries are clean and intentional
- confirm release flow matches the current Python app philosophy
- confirm prototype-only code was either removed from shell paths or clearly contained

Key files to review:

- `tauri_build/README.md`
- `tauri_build/docs/ARCHITECTURE.md`
- `tauri_build/docs/MIGRATION_PLAN.md`
- `tauri_build/scripts/release.bat`

### Phase 1: Productionize the Shell Platform

Goal:

- turn the prototype into a suite-ready desktop shell
- add themes, icons, navigation, error boundaries, and shell infrastructure

Status:

- complete

What was completed:

- suite-style shell with tab-based navigation
- theme system with `system`, `Light Precision`, and `Dark Precision`
- tool icons and shell placeholder tabs
- notification system
- keyboard shortcut infrastructure
- shell state via Zustand
- panel/tool/app error boundaries
- improved UI accessibility baseline

Code review focus:

- verify shell state ownership is clean and not duplicated across components
- verify theme tokens are consistent across light/dark themes
- verify navigation icon active states remain legible and restrained
- verify error boundaries fail safely without blank-screen failure modes
- verify keyboard shortcut scoping only affects the active tool

Key files to review:

- `tauri_build/frontend/src/app/App.tsx`
- `tauri_build/frontend/src/app/toolRegistry.tsx`
- `tauri_build/frontend/src/shared/theme/ThemeController.tsx`
- `tauri_build/frontend/src/stores/shellStore.ts`
- `tauri_build/frontend/src/stores/themeStore.ts`
- `tauri_build/frontend/src/shared/errors/ErrorBoundary.tsx`

### Phase 2: Sidecar Foundation

Goal:

- establish the Python sidecar contract and desktop bridge
- replace per-action mock/backend assumptions with a real Rust-to-Python boundary

Status:

- complete for the current foundation

What was completed:

- NDJSON sidecar protocol scaffold
- managed Rust-held Python session
- desktop bridge commands for:
  - `health_check`
  - `list_sheets`
  - `inspect_input`
  - `analyze_template`
- backend self-test path in packaged builds

Important limitation:

- this is still a synchronous request/response bridge
- heartbeat, streamed progress/log events, disconnect recovery, and safe restart policy are not done yet

Code review focus:

- verify request correlation is correct and stable
- verify the managed sidecar session tears down cleanly on app shutdown
- verify stderr handling is safe and does not block stdout protocol flow
- verify protocol validation is strict enough at the frontend boundary
- verify no UI path assumes streaming behavior that does not yet exist

Key files to review:

- `tauri_build/src-tauri/src/lib.rs`
- `tauri_build/backend/python/sidecar_main.py`
- `tauri_build/contracts/sidecar-protocol.md`
- `tauri_build/frontend/src/contracts/sidecar.ts`
- `tauri_build/frontend/src/shared/backend/client.ts`

### Phase 3: Real File Analysis Commands

Goal:

- prove real workbook inspection before attempting full execution
- drive the mapping/review UI from real file metadata

Status:

- complete

What was completed:

- workbook browsing from the desktop app
- real sheet enumeration
- real workbook inspection
- real template analysis
- review UI fed by inspected/template metadata

Code review focus:

- verify stale-response handling when users change files quickly
- verify sheet-selection behavior stays correct when inputs change
- verify workbook analysis results are reflected in the mapping UI consistently
- verify error states surface clearly and do not leave stale analysis in place
- verify browser-preview mode still degrades safely

Key files to review:

- `tauri_build/frontend/src/features/fmea/FmeaTool.tsx`
- `tauri_build/frontend/src/components/InputGrid.tsx`
- `tauri_build/frontend/src/components/ValidationPreview.tsx`
- `tauri_build/backend/tests/test_sidecar_main.py`

### Phase 4: Real FMEA Execution Slice

Goal:

- execute a first real migrated Dark Star backend path from the Tauri app

Target long-term deliverables:

- backend validation
- run execution
- progress/log/result handling
- output workbook generation
- eventually template-preserved write path and fill-gaps parity

Status:

- complete (lifecycle refactor verified 2026-04-06)

What is complete now:

- copied frozen FMEA logic into the Tauri backend tree
- copied shared pre-run validation helper into the Tauri backend tree
- copied frozen template analyzer and writer into the Tauri backend tree
- added `validate_run`
- added a first real `execute_run`
- Dark Star can now perform:
  - `piece_part_generate`
  - `bom_only`
  - `fill_gaps`
  - `new_workbook_standard`
  - `existing_workbook_preserve_formatting`
- run panel now shows real result metadata and backend log lines
- shared Phase 4B lifecycle plumbing is now wired across the stack:
  - Rust bridge now separates request/response commands from streamed run events
  - Python sidecar now returns `ack` with a real `run_id` and emits streamed `status`, `progress`, `log`, and terminal events
  - frontend now has shared backend event subscription and shared run-session state instead of FMEA-only desktop-run plumbing
  - shell disconnect state is now surfaced as a shared backend/session concern instead of a tool-local concern
- real streamed progress/log/status events verified for the migrated FMEA run path
- `cancel_run` path verified: cancellation propagates through `CancellationToken` to the processor
  - fix: removed `cancel.reset()` in Tauri copy of `FMEAProcessor.process()` to prevent race with `bind_processor()`
  - fix: same `cancel.reset()` removal applied to `process_gaps()` for fill-gaps mode
- shared frontend lifecycle state verified as generic for future tool migrations
- Rust-side disconnect fanout and sidecar-session event emission wired
- fill-gaps execution wired: `process_gaps()` invoked for `fill_gaps` workflow with adapted progress callbacks
- template-preserved write path wired: `analyze_template()` + `write_template_preserved()` used for `existing_workbook_preserve_formatting` strategy
- backend tests fully green (13/13) including cancel, busy streaming, fill-gaps, and template-preserve cases
- desktop build verified with Rust 1.94.1 (portable artifact: 9.2 MB)
- protocol documentation updated to cover the streamed run contract

Remaining deliberate limits:

- no heartbeat supervision yet
- no restart policy or automatic mid-run recovery yet
- no multi-run queueing; only one active long-running backend task is intended right now

Code review focus:

- verify copied frozen logic is isolated and not mutating legacy code
- verify runtime adapter builds the correct legacy input contract
- verify the shared Rust sidecar manager correctly routes request/response traffic separately from run-stream traffic
- verify streamed `ack` / `status` / `progress` / `log` / terminal events remain correlated to the correct `run_id`
- verify the new shared frontend run-session model is generic enough for future tool migrations and not Dark Star-specific
- verify run validation blocks unsupported paths cleanly
- verify output paths are safe and predictable
- verify frontend run-state transitions do not regress into stale or misleading states
- verify execution logs and results reflect real backend state rather than leftover demo assumptions
- verify cancel and disconnect states fail honestly and preserve useful run diagnostics
- verify unsupported paths fail honestly instead of silently downgrading

Key files to review:

- `tauri_build/backend/python/fmea/fmea_generator_logic.py`
- `tauri_build/backend/python/fmea/fmea_template_analyzer.py`
- `tauri_build/backend/python/fmea/fmea_template_writer.py`
- `tauri_build/backend/python/fmea/runtime.py`
- `tauri_build/backend/python/shared/pre_run_validation.py`
- `tauri_build/backend/python/sidecar_main.py`
- `tauri_build/frontend/src/features/fmea/FmeaTool.tsx`
- `tauri_build/frontend/src/components/RunStatePanel.tsx`
- `tauri_build/backend/tests/test_sidecar_main.py`

### Phase 5: Hardening, Release Readiness, and Config Migration

Goal:

- make the desktop app resilient enough for serious migration use

Status:

- in progress

What is complete now:

- heartbeat supervision: Python sidecar emits heartbeat every 5s, Rust bridge supervises with 15s timeout
- automatic disconnect detection via heartbeat timeout (supplements existing stdout-EOF detection)
- automatic frontend reconnection with exponential backoff (2s, 4s, 8s, 15s, 30s)
- backend regression tests for known failure patterns (missing columns, post-failure responsiveness, bogus cancel)

Major work still needed:

- production-hardening of the new cancellation semantics
- config migration from Flet into Tauri namespace
- stronger accessibility coverage
- stronger security audit coverage
- offline build hardening
- code-signing/deployment hardening

Code review focus when implemented:

- verify stuck-running and stale-result regressions are covered by tests
- verify logs persist across failures
- verify sidecar crash states are visible and recoverable
- verify config migration never mutates Flet config files
- verify release pipeline covers backend, frontend, packaged shell, and packaged backend
- verify accessibility does not regress under dense UI states

Expected review targets:

- `tauri_build/src-tauri/src/lib.rs`
- `tauri_build/frontend/src/shared/backend/*`
- `tauri_build/frontend/src/stores/*`
- `tauri_build/scripts/release.bat`
- `tauri_build/docs/TESTING.md`

### Phase 6: Expand the Suite and Retire Flet Only When Ready

Goal:

- migrate remaining tools one by one
- retire Flet only after parity and release confidence exist

Status:

- not started

Major work still needed:

- BOM Compare migration
- Failure Rate migration
- RefDes Extractor migration
- settings/config parity
- per-tool characterization tests and parity review

Code review focus when implemented:

- verify each tool is migrated as a self-contained slice
- verify no tool-specific shortcuts or config state leak across tool boundaries
- verify each tool gets explicit parity criteria
- verify shell complexity stays manageable as more tools land

## What Needs Immediate Next Work

Items 1-2 from the previous plan are complete. Rust installed, desktop build verified,
fill-gaps and template-preserve execution paths wired and tested. The next steps are:

1. Smoke-test the packaged artifact with a real FMEA run and cancel
   - the `.exe` was rebuilt but has not been manually exercised with real files

2. Add regression coverage for known Flet-era failures
   - cancel race conditions, stale event handling, missing column errors

3. Begin Phase 5 hardening
   - heartbeat and backend health monitoring
   - disconnect/restart behavior
   - config migration from Flet into Tauri namespace

4. Begin Phase 6 tool expansion
   - BOM Compare migration (logic decomposition already complete in Flet codebase)
   - Failure Rate migration

## Review Priority Order

If a fresh reviewer is short on time, review in this order:

1. `Phase 4`
2. `Phase 2`
3. `Phase 1`
4. `Phase 3`
5. `Phase 0`

Reason:

- `Phase 4` contains the newest and highest-risk behavioral work
- `Phase 2` contains the desktop/backend contract and lifecycle assumptions
- `Phase 1` defines the shell architecture everything else depends on

## Known Truths for the Next Chat

- The Flet app is still the production reference.
- `tauri_build` is the active migration track.
- Phase 4 is feature-complete: standard, BOM-only, fill-gaps, new-workbook, and template-preserved paths all wired and tested.
- Rust 1.94.1 is installed; desktop builds work.
- 18 backend integration tests, 5 frontend tests, 1153 Flet tests all green.
- Phase 5 heartbeat supervision is landed. Next hard problems: config migration, security audit, accessibility.
- Do not modify the frozen Flet implementation to advance the Tauri migration.
