# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.2] - 2026-04-07 — Reliability and Diagnostics

### Fixed

- **P0:** `_CancelBridge` in `bom_compare/runtime.py` and
  `refdes_extractor/runtime.py` now shares its underlying `threading.Event`
  with its `CancellationToken`, so cancelling a BOM Compare or RefDes run
  actually reaches the inner `stop_event.is_set()` checks. Previously the
  sidecar would emit `cancelling` but the run would continue to a `success`
  terminal because the bridge wired the two events independently.
- **P1:** `list_sheets` and the `execute_run` pre-ack `route_validate` call
  in `sidecar_main.py` are now wrapped in `try/except` and emit proper
  `error` envelopes instead of crashing the sidecar process when the user
  picks a moved/corrupt workbook or sends a malformed body. Added a
  defense-in-depth `handle_command` exception envelope to keep the sidecar
  alive on any unexpected exception.
- **P2:** FMEA, BOM Compare, Failure Rate, and RefDes tools now use a
  shared `useRoleRequestSequence` token to discard stale async results
  from `listSheets` / `inspectInput` / `analyzeTemplate`. A user rapidly
  changing inputs can no longer have older results overwrite newer state.
- **P2:** `mission_control` is now correctly classified as a dark theme,
  so its native form controls render with the right contrast.
- **P3:** `README.md` test counts and the broken
  `PHASED_MIGRATION_STATUS.md` reference are now correct.
- **P3:** `docs/DESIGN_SYSTEM.md` "default theme" description matches the
  ThemeController behaviour (the `data-theme` attribute is always set).

### Added

- **Global run store:** `frontend/src/stores/runStore.ts` (Zustand) holds
  the active backend run keyed by tool. The state survives tool switches,
  so a long-running FMEA run no longer disappears when the user opens
  Settings and returns. The hook reconciles against
  `backend_session_status` on reconnect, so the shell badge and the run
  panel can no longer disagree about backend liveness.
- **Backend tracebacks:** `backend_error` envelopes now carry optional
  `code` and `traceback` fields. The sidecar also streams every traceback
  line as an `error`-level `log` envelope so the run-log panel shows the
  trace inline.
- **Truncation indicator:** the run-log panel reports when earlier lines
  were dropped from the in-memory buffer (`truncatedLogCount`) and
  points to `~/.reliability_tools/logs/` for the full log.
- **Backend error block:** `RunStatePanel` renders the new error code as
  a chip and offers a "Show traceback" disclosure with a "Copy traceback"
  button when the backend supplies one.
- **Theme registry:** `frontend/src/shared/theme/themeRegistry.ts` is the
  single source of truth for theme metadata. The shell rail, Settings,
  ThemeController, and topbar chip all read from it. The rail now exposes
  the same theme list (in compact form) that Settings does.
- **New tests (~33 added):** BOM Compare cancel, RefDes cancel, cancel
  bridge unit tests (8), `list_sheets` missing/corrupt file, `execute_run`
  validator-raises, malformed-envelope survival, traceback assertion on
  `backend_error`, runLifecycle store survival across remount, runLifecycle
  reconnect/disconnect/log-truncation, role request sequence (5), theme
  registry consistency (10).

### Changed

- `frontend/src/shared/backend/runLifecycle.ts` is refactored to use the
  new `runStore` instead of local `useState`. Public API surface
  (`useBackendRunLifecycle`) is unchanged except for a new required
  `toolId` first argument so the hook can claim/release the global active
  run on behalf of its tool.
- `useBackendBootstrap` now mirrors backend disconnect/reconnect into
  `runStore` and calls `backend_session_status` on reconnect to clear any
  stale active run.
- `contracts/sidecar-protocol.md` documents the new `code` and `traceback`
  fields on `backend_error`.

## [0.2.1] - 2026-04-07 — Typography System

### Added

- Self-hosted Inter and JetBrains Mono variable fonts under `frontend/public/fonts/` (`40ca619`)
- Type scale tokens covering font sizes, weights, line heights, and letter spacing (`40ca619`)
- Mission Control theme variant alongside Light Precision and Dark Precision (`40ca619`)
- `backend/python/common/security_audit.py` — static AST audit for forbidden
  network/database imports and out-of-allowlist subprocess calls; wired into
  `sidecar_main.py --self-test` and exercised by `backend/tests/test_security_audit.py`
  (17 new tests)

### Changed

- Phase 1D sweep replaced hardcoded font properties across all CSS and components (`938c6eb`)
- Monospace references unified through the `--font-mono` token (`938c6eb`)
- Manifest versions in `package.json`, `src-tauri/tauri.conf.json`, and
  `src-tauri/Cargo.toml` bumped from `0.1.0` to `0.2.1` to match released
  documentation
- Documentation accuracy sweep across `CLAUDE.md`, `docs/ARCHITECTURE.md`,
  `docs/DECISIONS.md` (ADR-008), `docs/TESTING.md`, `docs/MIGRATION_PLAN.md`,
  and `docs/MIGRATION_HISTORY.md`

## [0.2.0] - 2026-04-06 — Standalone Repo and Zero-Install Distribution

### Added

- PyInstaller sidecar bundling for zero-install distribution (53 MB onefile, ~1s cold start) (`8e5b61a`)
- Domain-specific Phosphor icons for each tool in the app rail (`dbf3706`)
- Standalone repository README for the Tauri app (`35a8b30`)

### Changed

- Project lifted out of `Reliability_Eng_Tools_Dev/tauri_build/` and promoted to its own repo (`045bbca`)
- Release script venv path updated for the standalone repo layout (`570b4a2`)
- Tool rail widened to accommodate domain icons (`6781f42`)

### Fixed

- `--border-subtle` and `--font-mono` token definitions corrected (`6781f42`)
- Stale `--color-*` tokens removed and themes resynced (`6781f42`)

### Removed

- Migration-era jargon stripped from UI copy (`6781f42`)

## [0.1.5] — Phase 6: Full Suite Migration

### Added

- BOM Compare tool migrated to the Tauri app
- Failure Rate tool migrated to the Tauri app
- RefDes Extractor tool migrated to the Tauri app
- Settings tool with config parity
- `workflowId`-based routing through a single `execute_run` command
- All 12 `common/` modules and per-tool logic copied into `backend/python/` for a self-contained backend
- Per-tool characterization tests

## [0.1.4] — Phase 5: Hardening and Heartbeat

### Added

- Heartbeat supervision: Python sidecar emits every 5s, Rust bridge times out at 15s
- Automatic frontend reconnection with exponential backoff (2s, 4s, 8s, 15s, 30s)
- Backend regression tests for missing columns, post-failure responsiveness, and bogus cancel

### Changed

- Test infrastructure hardened: `stderr=DEVNULL`, single `_SidecarReader` per session, `id()` identity check on handles

### Fixed

- External GPT review findings on sidecar session lifecycle addressed

## [0.1.3] — Phase 4: Real FMEA Execution

### Added

- `validate_run` command
- `execute_run` command supporting `piece_part_generate`, `bom_only`, `fill_gaps`, `new_workbook_standard`, and `existing_workbook_preserve_formatting`
- Streamed `ack`, `status`, `progress`, `log`, and terminal events correlated by `run_id`
- Shared frontend run-session state and backend event subscription
- `cancel_run` path propagating through `CancellationToken`
- Template-preserved write path via `analyze_template()` + `write_template_preserved()`
- Fill-gaps execution via `process_gaps()`

### Fixed

- Removed `cancel.reset()` in `FMEAProcessor.process()` to prevent race with `bind_processor()`
- Same `cancel.reset()` removal applied to `process_gaps()` for fill-gaps mode

## [0.1.2] — Phase 3: Real File Analysis

### Added

- `list_sheets` command for real sheet enumeration
- `inspect_input` command for real workbook inspection
- `analyze_template` command for real template analysis
- Review UI driven by inspected and template metadata
- Stale-response handling for fast file changes

## [0.1.1] — Phase 2: Sidecar Foundation

### Added

- NDJSON sidecar protocol
- Managed Rust-held Python session with clean shutdown teardown
- Desktop bridge commands: `health_check`, `list_sheets`, `inspect_input`, `analyze_template`
- Backend self-test path in packaged builds

## [0.1.0] — Phases 0 and 1: Prototype Adoption and Shell Platform

### Added

- Dark Star prototype adopted as the Tauri app foundation
- Folder layout: `frontend/`, `src-tauri/`, `backend/python/`, `backend/tests/`, `contracts/`, `docs/`, `scripts/`
- Suite-style shell with tab-based navigation
- Theme system with `system`, Light Precision, and Dark Precision
- Notification infrastructure
- Keyboard shortcut scaffolding scoped to the active tool
- Zustand shell and theme stores
- Panel, tool, and app error boundaries
- Radix-based select control replacing the hand-rolled version
