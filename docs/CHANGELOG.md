# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.1] - 2026-04-13 — Inspection Caps, Session Generation, Writeability Guard

### Added

- **Worksheet inspection sampling caps:** `inspect_input` and
  `analyze_template` now bound header detection at 1 000 rows, column
  scanning at 100 columns, and data-row scanning at 20 000 rows. Results
  expose `rows_scanned`, `columns_scanned`, `row_cap_applied`,
  `column_cap_applied`, and `header_search_cap_applied` so the UI can
  warn on wide / long sheets. The FMEA analysis card surfaces the cap
  warning inline via `buildInspectionCapFragments()` /
  `buildInspectionCapWarning()` in `FmeaTool.tsx`.
- **Session generation tracking:** the Rust bridge now maintains a
  `session_generation` counter that increments on every sidecar respawn.
  The counter is echoed on the `execute_run` ack and on
  `backend_session_status`. The frontend reconciles this on reconnect
  and clears stale active runs when the bridge restarts the sidecar —
  previously, bridge-managed restarts left ghost runs in the store.
- **Output directory writeability pre-check:** FMEA runtime probes the
  resolved output directory for writeability via a tempfile before
  starting the workbook write. A read-only directory now falls back to
  the input-file parent with a warning, instead of failing late inside
  openpyxl.
- **Column provenance in mapping dropdowns:** duplicate columns that
  appear in multiple visible roles (e.g. BOM + HDA) are merged into one
  option labeled with their source workbooks (e.g. "Part Number - BOM
  workbook and HDA workbook"), via the new `optionLabels` field on
  `AggregatedMappingSource` and `ColumnMappingRow`.

### Changed

- **Demo scenarios** no longer reference the removed "Existing Workbook
  (Best Effort)" output strategy; the `fill_gaps` demo scenario now uses
  "Existing Workbook (Preserve Formatting)".
- **Rust session cleanup** consolidated into `kill_managed_session()` /
  `disconnect_managed_session()` helpers; `ManagedSidecar::kill()` now
  calls `.wait()` for proper child-process reaping;
  `handle_disconnect()` resets `last_heartbeat` to avoid stale state
  after reconnect.

### Tests

- **Backend total: 101 → 106.** New in `test_sidecar_main.py` (33 → 37):
  row-cap metadata, column-cap metadata, sparse-sheet row cap by
  physical rows, header-search-cap fatal error. New in
  `test_fmea_phase_d.py` (43 → 44): unwritable output directory falls
  back with warning.
- **Frontend total: 143 → 148 across 20 test files.** New file:
  `FmeaTool.inspection.test.tsx` (2 tests — sheet-selection
  interactivity during background aggregation, cap-warning display).
  `MappingTable.test.tsx` 10 → 11 (source-aware option labels).
  `mappingAnalysis.test.ts` 6 → 7 (multi-source provenance merging).
  `runLifecycle.test.ts` 8 → 9 (session-generation reconciliation on
  reconnect).
- **Grand total: 244 → 254.**

## [0.4.0] - 2026-04-10 — FMEA Mapping Analysis, Command Palette, Phase D Backend

### Added

- **Command Palette** (`Ctrl+K`): global keyboard-driven command launcher
  with fuzzy search across tools, themes, and actions. Implemented as a new
  UI primitive in `components/primitives/CommandPalette.tsx`.
- **FMEA column mapping analysis** (`mappingColumns.ts`,
  `mappingAnalysis.ts`): canonical column metadata registry, header
  normalization (case/whitespace/synonym folding), column deduplication,
  and source aggregation for automatic mapping suggestions.
- **MappingTable toolbar:** bulk **Apply all suggestions** and **Clear all
  mappings** buttons, plus per-row contextual help panels explaining each
  column's purpose.
- **Output directory picker:** explicit `outputDirectory` parameter with OS
  directory dialog via `openDirectory()` API, persisted via Zustand persist
  middleware in `shellStore`.
- **CCA prefix validation:** BOM-Only mode now requires a CCA prefix,
  validated against the format `^[A-Z0-9][A-Z0-9-]{0,7}$`.
- **Part Usage diagnostics:** mapping mismatch detection between BOM Part
  Usage and actual instance count, surfaced as validation warnings.
- **FMD standard templating refactor:** `_build_column_overrides()` and
  `FRONTEND_TO_BACKEND_MAPPING` bridge frontend canonical names to backend
  column keys, replacing the ad-hoc translation layer.
- **8 new UI primitives** (`components/primitives/`): `CommandPalette`,
  `ToggleChip`, `OptionsField`, `ContextTabs`, `CheckboxField`,
  `OptionsSection`, `HoldButton`, `EmptyState`.
- **Cancel error normalization** (`cancelError.ts`): shared utility for
  Tauri cancel/abort error detection and normalization across all tools.
- **Backend busy reset hook** (`useBackendBusyReset.ts`): auto-resets shell
  store backend status on run completion, preventing stuck busy states.
- **Copy to clipboard hook** (`useCopyToClipboard.ts`): reusable hook for
  clipboard write with success/error feedback.
- **3 new themes:** Kraft Paper (warm paper/graphite), Forest Depth (deep
  pine/moss dark), Graphite Dawn (soft charcoal/ivory).
- **HDA source toggle** with workflow-aware role handling for conditional
  file inputs.
- **GlobalLogPanel resizable:** drag handle for panel height adjustment
  with `localStorage` persistence.
- **Tauri file drop handling:** native drag-drop with path notification for
  file input cards.

### Changed

- **FmeaTool.tsx major refactor:** mapping rows, HDA source toggle,
  workflow-aware file roles, CCA prefix input, output directory picker,
  and bulk mapping actions integrated into the tool layout.
- **MappingTable toolbar** expanded with apply-all, clear-all actions and
  contextual help panels per mapping row.
- **Shell store persistence** via Zustand `persist` middleware — FMEA output
  directory and other shell state survive page reloads.
- **Column mapping refactor** in `fmea/runtime.py`:
  `_build_column_overrides()` translates frontend mappings to flat canonical
  keys and nested per-file-type buckets, replacing the previous direct
  key passthrough.

### Fixed

- **Backend busy state** no longer sticks after run completion — the
  `useBackendBusyReset` hook clears the shell store flag on terminal events.
- **Cancel errors from Tauri dialog dismissals** normalized via
  `cancelError.ts` instead of surfacing as unhandled exceptions.

### Tests

- **Backend total: 101** (33 sidecar + 17 audit + 8 cancel bridge + 43
  Phase D).
- **Backend FMEA Phase D:** expanded from 12 to 43 tests — CCA prefix
  (A6), output directory (A7), Part Usage diagnostics (A8), column override
  translation, union merge diagnostics, Failure Mode Causes mapping,
  invalid output directory fallback.
- **Frontend total: 143** across 19 test files.
- **13 new frontend test files** (~101 tests): `FmeaTool` (7),
  `MappingTable` (10), `RunStatePanel` (5), `GlobalLogPanel.resize` (13),
  `mappingColumns` (21), `mappingAnalysis` (6), `cancelError` (12),
  `client.cancelRun` (2), `useBackendBusyReset` (9),
  `useCopyToClipboard` (3), `HoldButton` (5), `EmptyState` (5),
  `CommandPalette` (5).
- **`App.test.tsx`** expanded from 4 to 10 tests.
- **Grand total: 244 tests** (101 backend + 143 frontend).

## [0.3.0] - 2026-04-08 — FMEA Workflow Restructure, BOM Inheritance, Global Run Log

### Added

- **Functional-to-Piece-Part workflow** (`functional_to_piecepart`): a new
  primary FMEA workflow that detects circuit-block rows in an existing
  functional FMEA, parses the comma-separated RefDes column (e.g.
  `Failure Mode Causes (RefDes)`) on each block, and expands them into
  piece-part rows beneath each block. The original functional rows are
  preserved as-is.
- **Failure Modes Standard selector:** every FMEA workflow now exposes a
  **FMD-91 vs FMD-2016** radio (default: FMD-2016). The selection drives
  the output column headers (`FMD-91 Commodity Type 1/2` vs
  `FMD-2016 Commodity Type 1/2`) and, if the failure modes file carries a
  `Standard` column, filters the library to the matching standard.
- **BOM Inheritance + BOM_Additions sheet:** when a grouping or functional
  source references a pin/variant RefDes (e.g. `U200-X`) that does not
  exist in the BOM, the generator now looks up the base RefDes (`U200`)
  and inherits Part Number, Part Description, HDA Commodity 1-2, and FMD
  Commodity 1-2. Every inherited row is recorded in a new
  **BOM_Additions** sheet in the output workbook, with columns RefDes,
  Base RefDes, Usage fraction, Part Number, Part Description, HDA
  Commodity 1-2, FMD Commodity 1-2, and Source Workflow. The sheet opens
  with an explanatory banner row telling reviewers to copy the inherited
  rows into their BOM.
- **Merge Column Scope picker** for the Fill Gaps workflow: a new panel
  that defaults to "Merge All Columns" and can switch to "Select Columns
  to Merge", where a checkbox list of detected template columns controls
  exactly which generator columns are written into the preserved
  template.
- **Global Run Log Console** (Phase B): a new cross-tool run log panel
  docked at the bottom of the app shell. Persistent across tool switches,
  filterable ("All tools" vs "Current tool only"), exportable as a `.log`
  snapshot, collapsible via a header chevron, and backed by a 5000-entry
  in-memory ring buffer. The canonical full log still lives on disk at
  `~/.reliability_tools/logs/`.
- **Design system tokens** (Phase G): spacing tokens `--space-1..8`
  (4/8/12/16/20/24/32/48 px); border-radius tokens `--radius-xs`,
  `--radius-sm`, `--radius-md`, `--radius-lg`, `--radius-xl`,
  `--radius-pill`; shadow tokens `--shadow-popover`,
  `--shadow-focus-ring`, `--shadow-rail-active`, `--shadow-toast` (with
  per-theme overrides for dark themes); and `--text-on-accent` for
  primary button text.
- **Memory guard** on `process_functional_to_piecepart`: warns above
  100k input rows and hard-fails above 1M output rows.

### Changed

- **FMEA workflow restructure:** the tool now exposes four primary
  workflows with clean names — **Generate Piece-Part from BOM Only**
  (`bom_only`), **Generate Piece-Part from Grouping File**
  (`piece_part_generate`), **Generate Piece-Part from Functional FMEA**
  (`functional_to_piecepart`), and **Fill Gaps (Advanced)** (`fill_gaps`).
  Every FMEA workflow now requires a failure modes file.
- **Fill Gaps default output strategy** now auto-sets to "Existing
  Workbook (Preserve Formatting)" when the user selects the Fill Gaps
  workflow. The preserve-formatting path — previously blocked by a legacy
  validation — is fully functional for fill_gaps runs.
- **Output strategy wording:**
  - "New Workbook (Standard)" is now "New Workbook" — writes a fresh
    workbook with all generator columns and summary sheets.
  - "Preserve Original Template" is now "Existing Workbook (Preserve
    Formatting)" — writes new piece-part rows directly into the selected
    functional or piece-part FMEA workbook, appending any new columns at
    the very end of the sheet and preserving all existing rows, data,
    formatting, fonts, and column widths.
- **Tool rail labels** (Phase G): "FMEA" -> "FMEA Generator", "Compare"
  -> "Cross Compare", "Rates" -> "Failure Rate Integration", "RefDes" ->
  "RefDes Extractor". Backend workflow IDs are unchanged.
- **Consistent `:focus-visible`** styles are now applied across all
  interactive elements; hardcoded pixel values throughout the CSS have
  been replaced with the new spacing tokens; Column Mapping dropdown
  widths were widened (previously cramped).
- **Phase 0 unfreezing:** 9 frozen Python modules were unfrozen to allow
  the sprint work: `refdes_extractor_logic`, `pinlist_parenting`,
  `group_detection`, `extraction_engine`, `geometry_analyzer`,
  `bom_verifier`, `fmea_generator_logic`, `fmea_template_writer`, and
  `fmea_template_analyzer`. `# FROZEN -- Do not modify this file.`
  headers were replaced with dated relaxation notes.

### Fixed

- **P0:** `dialog:allow-open` capability added to
  `src-tauri/capabilities/default.json`. Without it, the Browse button on
  every input card silently failed in the desktop build.
- **P0:** FMD-91 + Existing Workbook (Preserve Formatting) no longer
  silently drops FMD commodity columns. The template analyzer and writer
  are now parametrized by the selected FMD standard.
- **P0:** `columnSelection` state no longer leaks across workflows.
  Switching away from Fill Gaps resets the column picker state, and the
  backend only applies the column filter for Fill Gaps runs.
- **P0:** the Fill Gaps default-strategy `useEffect` no longer fights a
  user's manual output-strategy selection. It only flips on the
  transition into `fill_gaps`.
- **P1:** inherited BOM variants are no longer double-flagged as "Part
  Usage mismatch" validation warnings. The expected Part Usage is now
  computed against the source-derived variant count rather than the BOM
  instance count.
- **P1:** `process_functional_to_piecepart` column detection for group
  stub metadata (`FMEA-ID`, `Function Description`, `Schematic Page`)
  now uses the shared synonym lookup helper instead of hardcoded header
  names.
- **P1:** legacy `enrichments: { functional: true }` payloads are now
  rejected with a hard `ValidationError` instead of silently ignored.

### Removed

- **Enrichment toggles (Functional FMEA + Piece-Part FMEA):** the old
  enrichment grafting system is gone. Functional FMEA is now its own
  primary workflow (`functional_to_piecepart`); piece-part enrichment
  was dropped entirely.
- **Phase H1 dead-code cleanup:** ~825 lines of dead enrichment merge
  code removed from `fmea_generator_logic.py` (2319 -> 1494 lines).
  Deleted `MergeSourceSpec`, `MergeIssue`, and `MergeResult` dataclasses;
  `FUNCTIONAL_MERGE_SPEC` and `PIECEPART_MERGE_SPEC` constants; and 18
  dead methods including `_apply_functional_merge`,
  `_apply_piecepart_merge`, and `_build_merge_summary_sheets`. The
  corresponding "Applying Piece-Part effect merge..." stage weight was
  dropped from `runtime.py`.
- **Phase H2 type cleanup:** the vestigial `enrichments` field was
  removed from `DemoScenario`, `RunRequestBody`, 9 `scenarios.ts`
  literals, and the `EMPTY_ENRICHMENTS` constant in `FmeaTool.tsx`, plus
  the BOM Compare, Failure Rate, and RefDes tool components.
- **Phase H3:** `piecePartFmea` removed from the `FileRole` type union.

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
