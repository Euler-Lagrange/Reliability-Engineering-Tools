# Migration History

> **Migration completed on 2026-04-06.** This document preserves the phase
> history for reference. See `CHANGELOG.md` for per-commit detail and
> `ARCHITECTURE.md` for current architecture.

The Reliability Tools Desktop app was migrated from a Python/Flet
implementation to a Tauri (Rust + React + TypeScript) shell with a managed
Python sidecar. The migration ran in six phases followed by a standalone
repository restructure and a hardening pass.

## Phase 0: Adopt Prototype and Lock Architecture

**Goal:** Adopt the original Dark Star prototype as the foundation and
establish the new folder layout without disturbing the Flet codebase.

**Delivered:**

- `tauri_build/` created as a separate migration track
- Prototype adopted rather than rebuilt from scratch
- Desktop packaging scaffolding, release script, and docs baseline established
- Migration isolated from the Flet codebase (no shared imports or runtime
  coupling)

**Layout established:**

- `frontend/`, `src-tauri/`, `backend/python/`, `backend/tests/`
- `contracts/`, `docs/`, `scripts/`, `local_build/`, `logs/`

## Phase 1: Productionize the Shell Platform

**Goal:** Turn the prototype into a suite-ready desktop shell.

**Delivered:**

- Suite-style shell with tab-based navigation
- Theme system with `system`, `Light Precision`, and `Dark Precision`
- Tool icons and placeholder tabs for the full suite
- Notification infrastructure
- Keyboard shortcut scaffolding scoped to the active tool
- Shell state managed via Zustand stores
- Panel, tool, and app error boundaries
- Accessibility baseline

## Phase 2: Sidecar Foundation

**Goal:** Establish the Python sidecar contract and desktop bridge, replacing
per-action mocks with a real Rust-to-Python boundary.

**Delivered:**

- NDJSON sidecar protocol scaffold
- Managed Rust-held Python session with clean shutdown teardown
- Desktop bridge commands: `health_check`, `list_sheets`, `inspect_input`,
  `analyze_template`
- Backend self-test path in packaged builds
- Strict protocol validation at the frontend boundary

Phase 2 deliberately shipped as a synchronous request/response bridge;
heartbeat, streaming, and automatic reconnect were deferred to Phase 5.

## Phase 3: Real File Analysis Commands

**Goal:** Prove real workbook inspection and drive the mapping/review UI from
actual file metadata.

**Delivered:**

- Workbook browsing from the desktop app
- Real sheet enumeration via `list_sheets`
- Real workbook inspection via `inspect_input`
- Real template analysis via `analyze_template`
- Review UI fed by inspected/template metadata
- Stale-response handling when users change files quickly
- Browser-preview mode degraded safely

## Phase 4: Real FMEA Execution

**Goal:** Execute the first real migrated Dark Star backend path end-to-end
from the Tauri app.

**Delivered:**

- Frozen FMEA logic copied into the Tauri backend tree
- Shared pre-run validation helper copied into the Tauri backend tree
- Frozen template analyzer and writer copied into the Tauri backend tree
- `validate_run` command
- `execute_run` command supporting:
  - `piece_part_generate`
  - `bom_only`
  - `fill_gaps`
  - `new_workbook_standard`
  - `existing_workbook_preserve_formatting`
- Run panel surfaced real result metadata and backend log lines
- Phase 4B lifecycle plumbing across the stack:
  - Rust bridge separated request/response commands from streamed run events
  - Python sidecar returned `ack` with a real `run_id` and emitted streamed
    `status`, `progress`, `log`, and terminal events
  - Frontend gained shared backend event subscription and shared run-session
    state instead of FMEA-only plumbing
  - Shell disconnect became a shared backend concern
- Streamed progress/log/status events verified for the FMEA run path
- `cancel_run` path verified: cancellation propagated through
  `CancellationToken` to the processor
  - Removed `cancel.reset()` from `FMEAProcessor.process()` to prevent a race
    with `bind_processor()`
  - Same fix applied to `process_gaps()` for fill-gaps mode
- Fill-gaps execution wired via `process_gaps()`
- Template-preserved write path wired via `analyze_template()` +
  `write_template_preserved()`
- Desktop build verified with Rust 1.94.1 (portable artifact: 9.2 MB)
  *(Phase 4 snapshot — the final 0.2.0 release ships ~9 MB shell **plus**
  ~53 MB PyInstaller sidecar; see `CHANGELOG.md` 0.2.0.)*
- Protocol documentation updated to cover the streamed run contract

## Phase 5: Hardening and Heartbeat Supervision

**Goal:** Make the desktop app resilient enough for serious migration use.

**Delivered:**

- Heartbeat supervision: Python sidecar emitted heartbeat every 5 seconds,
  Rust bridge supervised with a 15-second timeout
- Automatic disconnect detection via heartbeat timeout, supplementing existing
  stdout-EOF detection
- Automatic frontend reconnection with exponential backoff (2s, 4s, 8s, 15s,
  30s)
- Backend regression tests for known failure patterns (missing columns,
  post-failure responsiveness, bogus cancel)
- Test infrastructure hardened: `stderr=DEVNULL`, single `_SidecarReader` per
  session, `id()` identity check on sidecar handles
- External GPT review fixes applied

## Phase 6: Full Suite Migration

**Goal:** Migrate the remaining tools and reach suite parity with the Flet
app.

**Delivered:**

- BOM Compare migration
- Failure Rate migration
- RefDes Extractor migration
- Settings/config parity
- `workflowId`-based routing through a single `execute_run` command
- Self-contained backend: all 12 `common/` modules and per-tool logic copied
  into `backend/python/`
- Per-tool characterization tests and parity review
- Shell complexity kept manageable as tools landed

## Post-Phase-6

### Standalone Repository Restructure

The migration track was lifted out of `Reliability_Eng_Tools_Dev/tauri_build/`
and promoted to its own repository at `Reliability_Eng_Tools/`. The release
script venv path was corrected for the new layout, and the README was
rewritten for the standalone Tauri app.

### External GPT Review Fixes

An external review identified threading and lifecycle issues in the sidecar
session management. Fixes landed: single `_SidecarReader` per session,
identity-based handle verification, and `stderr=DEVNULL` to prevent Windows
pipe deadlocks.

### Design System Cleanup

Stale `--color-*` tokens were removed, migration-era jargon was stripped from
UI copy, `--border-subtle` and `--font-mono` definitions were fixed, themes
were synced, and the tool rail was widened for domain-specific Phosphor icons.

### Typography System

Inter and JetBrains Mono variable fonts were self-hosted under
`frontend/public/fonts/` (the app is air-gapped and cannot fetch from CDNs).
A type scale token set was introduced, and a Phase 1D sweep replaced hardcoded
font properties across all CSS and components.

### Mission Control Theme

A Mission Control theme variant was added alongside the Precision themes,
providing a denser layout for run monitoring.

### PyInstaller Bundling

The Python sidecar was bundled as a 53 MB PyInstaller onefile executable,
enabling zero-install distribution for air-gapped end users. Cold-start
extraction takes approximately one second.

## Final Verification Snapshot

Verification at migration completion (2026-04-06):

- **Backend tests:** 27 passed (`backend/tests`)
- **Frontend tests:** 5 passed (`npm test`)
- **Flet regression tests:** 1153 passed (historical reference, Flet app
  remains frozen under its own repo)
- **Rust build:** 1.94.1, portable artifact verified
- **Typecheck:** `npm run typecheck` passed
- **Packaged sidecar:** self-test path verified
