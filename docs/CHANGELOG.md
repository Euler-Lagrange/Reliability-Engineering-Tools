# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Continuous integration** — new `.github/workflows/ci.yml` runs on every
  push/PR to `main` (windows-latest, the only supported target): frontend
  typecheck ×2 + Vitest, version-consistency check, backend pytest, sidecar
  self-test + security audit, and Rust `cargo check` + `cargo test`. Catches
  the cross-machine drift that the pinned deps and lockfiles guard against.
  (Tier-3 #23.)
- **Test coverage (Tier-3 #28)** — closed the cheap test gaps: the FMEA
  execute payload's option keys are now asserted in `toolRunDispatch` (guards
  the `hdaSource`-drop bug class); a new `App.shellHooks` test fails if the
  shell-level backend bootstrap / run-subscription hooks are ever deleted from
  `App`; and a registry-wide `scenarios` completeness test guards the Custom
  Compare zero-file-slots regression (Wiring Invariant #4). +4 frontend tests.
  (The fourth gap — a regression test for the success-toast race #10 — already
  shipped with that fix.)
- **Pinned Python dependencies** — new `requirements.txt` (runtime: pandas,
  openpyxl, PyMuPDF) and `requirements-dev.txt` (adds pytest, pyinstaller),
  pinned to the tested-green set so both dev machines and the build host
  resolve identical versions (closes the cross-machine version drift). README
  and DEVELOPMENT setup now install from them, and the `pip install` line that
  silently omitted pyinstaller is fixed. (Tier-3 #22, #27.)
- **BOM Compare — Custom column-value diff** — Custom Compare now diffs column
  *values* (not just RefDes presence/absence) for RefDes present in both files,
  via a column-pair picker that auto-pairs matching headers (RefDes key
  excluded) and supports a per-pair rule (Text / Text exact / Numeric). Sent as
  `options.compare_columns`; previously a custom compare always reported
  "0 differences" on values because no control sent them.
- **RefDes Extractor — BOM coverage reverse-diff** — with a BOM loaded, the
  extractor emits three sheets: `Coverage Summary`, `BOM Not Grouped` (BOM
  RefDes not cleanly grouped, split Not Extracted / Extracted-Ungrouped /
  Extracted-Provisional and enriched with Part Number + Description from the
  BOM), and `Extracted Not In BOM`. Component-level matching; failure-isolated
  so a coverage defect can never lose the extraction output.

### Changed

- **Persisted prefs are versioned + migrated (Decision E)** — the theme and
  shell Zustand stores now carry a persist `version` and a `migrate` hook, so a
  stale or invalid persisted value (a removed theme id, a wrong-typed output
  directory) is sanitized on rehydrate instead of restored verbatim. +7 tests.
- **analyze_template guarded against OOM (Decision C)** — the template-analysis
  command opens the whole workbook (`read_only=False`) for merged-cell and
  freeze-pane inspection, so a pathologically large template could exhaust
  memory. It now rejects a file over 50 MB with a clear error before loading,
  via a shared `ensure_file_size_within` helper. +3 tests.
- **OneDrive detection prefers the OneDrive env vars (Decision A)** — cloud-file
  detection/hydration now checks the `%OneDrive%` / `%OneDriveCommercial%` /
  `%OneDriveConsumer%` roots first (normalized directory-boundary match),
  falling back to the historical `"onedrive"` substring heuristic. This
  correctly detects OneDrive mounted at a non-standard location and avoids a
  false hit on a folder merely named "onedrive". +5 tests.

### Fixed

- **Run-event envelope parse guarded (Tier-2 #21)** — the run-event listener's
  envelope `sidecarRunEventSchema.parse` had no try/catch (unlike the guarded
  inner result parse), so a schema drift — plausible on the two-machine build
  setup where a newer sidecar outruns an older bundled frontend — would throw
  in the Tauri listener, drop a terminal event, and strand the run in "running"
  forever. The parse is now guarded: on failure it logs and forwards the raw
  payload so the subscription's own result guard can still drive the run to a
  terminal state.
- **Pinlist failures surfaced (Tier-2 #20)** — when per-page pinlist
  pin-qualification fails, the page's qualified-pin set is emptied; that
  failure was logged only to the rotating file log, so the output looked
  complete while silently having no qualified pins for the page. It is now also
  emitted on the streamed run log with the page number and cause. +1 test.
- **Output folder honored in preserve mode + validated up front (Tier-2 #18,
  #19)** — FMEA preserve-formatting mode now writes the merged workbook to the
  chosen output folder instead of silently landing it next to the template
  (#18). And an unusable explicit output folder is now flagged as a warning at
  *validate* time across all four tools (FMEA, BOM Compare, Failure Rate,
  RefDes) via the shared `output_directory_validation` helper — instead of
  passing validation green and then silently relocating the output at execute
  time (#19). +6 backend tests.
- **Bounded command replies (Tier-2 #15)** — a command whose file I/O stalls on
  a dead/slow network path (a stale `\\server\share` existence check can block
  the OS call 30-120s) no longer hangs the UI with zero feedback. The bridge's
  awaited reply now uses a bounded `recv_timeout` (default 60s,
  `RELIABILITY_TOOLS_COMMAND_TIMEOUT_SECS`) and returns an actionable
  "check the path" error instead of blocking forever — the heartbeat runs on
  its own Python thread, so the 15s supervisor never caught this. (The Python
  command loop still processes commands inline, so a stuck check self-recovers
  on the OS timeout; the UI is now responsive with feedback throughout.)
  +2 cargo tests.
- **Bounded sidecar startup + release-safe resolution (Tier-2 #14, decision
  D)** — the `ready` handshake is now read on a worker thread with a BOUNDED
  wait (default 60s, `RELIABILITY_TOOLS_READY_TIMEOUT_SECS`); a sidecar that
  stalls during import (cold-disk `import fitz`, AV scan of the PyInstaller
  bootloader) no longer hangs the whole bootstrap forever with no watchdog
  active. Separately, release-build resource resolution is now **exe-adjacent
  only** (dev keeps the ancestor walk), so a stray parent-directory `.venv` or
  `backend/` can no longer be bound. +5 cargo tests.
- **Sidecar stdout resilience (Tier-2 #13)** — a single unparseable line on the
  sidecar's stdout (e.g. a stray write to fd 1 from a C extension like PyMuPDF
  or openpyxl) no longer tears down the whole session and fails every pending
  request. The Rust stdout reader now skips-and-continues on a non-JSON line
  (matching the Python command loop, which already does), while EOF and real
  read errors stay fatal and the 15s heartbeat supervisor still catches a truly
  dead sidecar. +3 cargo tests.
- **Backend-error surfacing at folder/reveal sites (Tier-3 #26)** — the seven
  folder-picker / reveal-in-folder catch blocks (FMEA ×2, BOM Compare, Failure
  Rate, RefDes, Settings, and the shared `OutputFolderPicker`) used the banned
  `error instanceof Error ? … : <generic>` ternary, which discarded the real
  message on Tauri's raw-string rejections and showed only a generic fallback.
  All now route through `describeBackendError` (Wiring Invariant #5), so a
  native-dialog error surfaces its actual text. +2 regression tests on the
  shared picker.
- **Security-audit blind spots (Tier-3 #25)** — the static audit now catches
  command execution through an aliased or bare import (`import subprocess as
  sp`, `from subprocess import run`) and via `os.system` / `os.popen` /
  `os.startfile`, plus `ctypes` native imports — all previously invisible to
  the `subprocess.<name>`-only matcher. The command allowlist (`attrib`) is
  unchanged. CLAUDE.md's "enforced statically" wording is softened to reflect
  that this is a regression net against accidental introductions, not an
  adversarial sandbox (dynamic `importlib`/`eval` escapes remain out of scope
  by design).
- **Release gate hardening (Tier-3 #24)** — `scripts/release.bat` now runs the
  packaged self-tests against the build output and only promotes the exe to
  `local_build` **after** they pass, so a failed release can no longer clobber
  the last-good artifact teammates pull from that path. Added `version:check`
  and `cargo test` to the gate (previously only `cargo check` ran and version
  consistency across manifests was never verified). Separately, the
  previously-untagged **v0.4.6** release is now tagged at its version-bump
  commit.
- **Tier-1 data-correctness** — circuit/function-block failure-rate roll-up in
  the Failure Rate linker; BOM-Compare blank-ratio FMR poisoning + loose
  base-match residual-digit guard; Excel/CSV `NA`-literal read parity and
  duplicate-header dedup; FMEA fill-gaps `1/1` usage flagged as a best-guess;
  RefDes BOM-load failure surfaced prominently instead of a silent "all
  unverified".
- **Part Usage (Tier-1 #1)** — Part Usage is no longer silently defaulted to
  `1`. The FMEA Generator now derives it as `1/N` from the part's instance
  count (N = distinct RefDes sharing a usage-base; explicit BOM values still
  win) and leaves the cell **blank + flagged** (`PU_GUESSED_NO_COUNT_SOURCE`)
  when the count is unknown — fixing the overstatement where multi-instance
  parts got `1`. The Failure Rate linker now leaves `Mode_FR` **blank +
  flagged** when usage is a genuine gap (incl. an uncached `=1/N` formula cell)
  on a real-rate row instead of overstating with `1.0`; the circuit-block
  roll-up skips blank children and flags the block as possibly understated.
- **Tier-2 run-lifecycle** — the success toast + "saved to…" message is no
  longer lost on every successful run (#10); a late `cancelling` no longer
  strands the UI in "Cancelling…" (#11); a new toast behind 5 sticky errors no
  longer self-evicts (#12); switching workflow/strategy mid-run no longer
  orphans the backend job (#16); browsing after a finished run no longer lets
  the "Inspecting…" busy chip be wiped (#17).

### Removed

- Deleted the dead `refdes_extractor/bom_verifier.py` (zero callers); the BOM
  cross-check is computed fresh in the engine's own normalized space.

## [0.4.6] - 2026-06-04 — Holistic Review Cleanup

### Holistic review cleanup

- **Dead code removed (~470 verified lines)** — deleted the unused
  `PlaceholderTool` and `ScenarioRail` React components and their CSS,
  the Flet-era Python helpers (`add_recent_file` / `get_recent_files`,
  `GUILogHandler` / `log_session_*`), and unreferenced FMEA / failure-rate
  symbols. No runtime behavior changed.
- **Shared desktop run controller** — extracted
  `frontend/src/shared/backend/useDesktopRunController.ts`; the FMEA, BOM
  Compare, Failure Rate, and RefDes Extractor tools now share one
  run-lifecycle hook instead of four near-identical copies (−527 lines of
  duplication).
- **Defensive run-result parse guard** — `execute_run` result parsing now
  guards malformed/partial terminal payloads instead of assuming a
  well-formed shape.
- **RefDes pin-label collision fix** — `_disambiguate_pin_mapping` now
  resolves the multi-candidate path (body-center-in-rect → overlap →
  nearest-body), which was previously unreachable because an exact
  `(page, label)` dict let the last-written mapping win.
- **FMEA-ID bijective suffix** — FMEA row IDs use a bijective overflow suffix
  (A..Z, AA..AZ, ...) so suffixes past 26 failure modes are consistent, replacing
  the old inconsistent `Z{idx}` scheme.
- **BOM / OneDrive parity** — BOM Compare and the OneDrive cloud-file
  hydration path were brought back into parity with the other tools.
- **Tests** — +56 backend tests (now **176**: adds
  `test_failure_rate_logic.py` ×12, `test_extraction_engine.py` ×6,
  `test_bom_compare_logic.py` ×21, `test_bom_compare_runtime.py` ×7,
  `test_failure_rate_runtime.py` ×2, and eight more FMEA Phase D cases),
  +3 frontend tests inside existing suites, and new regression suites for
  the input-visibility, interaction-state, file-loading, and wiring fixes
  below (`BomCompareTool.test.tsx`, `RefDesExtractorTool.test.tsx`,
  `FailureRateTool.test.tsx`, `App.keepalive.test.tsx`,
  `deriveMappingRows.test.ts`, `NumberField.test.tsx`, plus added FMEA
  and cancel-error cases — now **226** across 33 files).
- **Doc fixes** — corrected the NextGen extraction-engine docstrings
  (the `refdes_test` engine is the default production backend, not a
  test-only / experimental path), `docs/DEVELOPMENT.md`, `release.bat`,
  and a stale `vite.config` comment. tsc-emitted `vite.config.js/.d.ts`
  and `vitest.setup.js/.d.ts` artifacts are now gitignored.

### Fixed

- **BOM Compare Custom Compare had no file inputs** — switching to the
  `bom_compare_custom` workflow rendered an empty Input Files card (and
  dispatched zero inputs) because `bomCompareDemoScenarios` only contained
  the group scenario, so the workflow-switch fallback re-seeded the input
  slots without the `bomA`/`bomB` roles. Added the missing custom-compare
  scenario plus a regression suite
  (`frontend/src/features/bom-compare/BomCompareTool.test.tsx`).
- **Pristine EmptyState never yielded after loading a real file** — the
  browse handlers in BOM Compare, Failure Rate, and RefDes Extractor never
  cleared `isExample`, so `isPristine` stayed true after a real workbook
  /PDF was picked and the EmptyState kept covering the input grid — the
  remaining file slots and sheet pickers were unreachable in the desktop
  app. Browsing now sets `isExample: false` on the loaded slot.
- **RefDes piece-part mode had no pinlist picker** — `refdesInputs.pinlist`
  existed in the mocks but was never seeded into the demo scenario, so the
  piece-part role filter (`pdf`/`bom`/`pinlist`) found no pinlist slot to
  render. The pinlist is now seeded (hidden in functional mode), and
  switching extraction mode counts as engagement so the grid (with the
  pinlist slot) replaces the pristine EmptyState.
- **Switching tools destroyed all loaded inputs** — the shell rendered only
  the active tool, so switching tools (sidebar, `Ctrl+1..5`, `Ctrl+[`/`]`,
  command palette) unmounted the outgoing tool and discarded every loaded
  file, sheet selection, and manual column mapping. `App.tsx` is now a
  keep-alive shell: tools mount on first visit and stay mounted behind a
  `[hidden]` pane. This also fixes the cascade bugs — terminal run toasts
  now fire even when the run's tool is not the active one, the live Run
  panel survives a switch-away-and-back, and the FMEA/BOM Compare
  mount-reset no longer orphans an in-flight run on re-entry.
- **FMEA: changing Output Strategy wiped manual column mappings** — the
  workflow/strategy reset effect cleared `mappingOverrides` (and run state)
  on `outputStrategyId` changes even though strategy never alters the
  mapping rows. The reset is now split: full reset on workflow change only;
  strategy changes reset run-presentation state but preserve mappings and
  validations.
- **FMEA: toggling FMD-91 ↔ FMD-2016 dropped Commodity Type mappings** —
  overrides are keyed by canonical labels and the two Commodity Type rows
  have standard-specific labels, so the toggle orphaned the user's mapping
  (and the run payload silently lost it). `migrateFmdOverrides` now remaps
  the dynamic keys when the standard changes.
- **BOM Compare: workflow round-trip discarded loaded files** — switching
  group ↔ custom re-seeded the input slots from the demo scenario every
  time. A per-workflow cache now stashes and restores each workflow's
  inputs, mapping overrides, and validations within the session.
- **Stale validation cards after changing inputs** — BOM Compare and
  Failure Rate kept showing the previous validation results after the user
  browsed a different file or changed a sheet; both now clear the
  validation list when an input changes.
- **RefDes: pristine empty-state covered a loaded pinlist** — loading only
  a pinlist in piece-part mode and toggling back to functional re-triggered
  the pristine EmptyState because the check ignored hidden inputs; it now
  evaluates all input slots. The adaptive-geometry checkbox is also
  disabled (with a hint) while geometry analysis is off, since the backend
  ignores it on that path.
- **BOM Compare Group dropped the entire BOM as DNP (wrong output)** — the
  frontend never sends `dnp_regex`, the runtime adapter defaulted it to
  `""`, and `re.compile("")` matches everything, so with `ignore_dnp`
  enabled every BOM row was skipped and every group run reported all
  RefDes missing. The adapter now falls back to `DEFAULT_DNP_REGEX` (with
  defense-in-depth in `_compile_patterns`), and the sidecar group-compare
  test asserts a zero-missing fixture.
- **Example demo paths leaked into real desktop runs** — BOM Compare,
  Failure Rate, and RefDes seeded their input slots with fake
  `DRIVE\inputs\...` example paths that passed backend validation and then
  crashed mid-run (`FileNotFoundError`, raw `fitz` error) or silently
  degraded output (RefDes "no BOM provided"). All three tools now seed
  empty slots in desktop mode via a shared `emptyInputsFromScenario`
  (FMEA's existing pattern), so un-loaded required slots block at
  validate time with the precise "Select required files" message; empty
  slots also no longer show green "Loaded" chips.
- **Double-click Start wiped the live run's UI** — the Start button is
  not disabled during the validate round-trip, so a second click launched
  a second execute that the sidecar rejected; the rejection handler then
  cleared the FIRST (live) run's session, dropping its events, result,
  and toast. `handleStartRun` is now re-entrancy-guarded in all four
  tools, and the failure path skips the session reset when a live run it
  does not own is active.
- **Do-Not-Map on a required column crashed at execute** — BOM Compare and
  Failure Rate accepted the `__do_not_map__` sentinel through validation
  (it reads as a non-empty mapping) and then failed mid-run with a
  cryptic "column '__do_not_map__' not found". Both runtimes now report
  it through the `invalid_do_not_map` validation branch up front; the
  sentinel constant is shared from `shared/pre_run_validation.py`.
- **Backend error messages were discarded by the frontend** — Tauri v2
  rejects commands with a raw string, so every non-cancel catch's
  `instanceof Error` check replaced the sidecar's real message
  ("Could not locate a non-empty header row...", "Another backend run is
  already active...") with generic fallbacks. All backend-invoke catches
  now route through a shared `describeBackendError` (generalized from the
  cancel-path normalizer), so input cards and toasts show the real cause.
- **FMEA stale validation cards** — FMEA now clears the Preview tab's
  validation cards when a file is browsed or a sheet changes (parity with
  the BOM Compare / Failure Rate fix), and prunes manual mapping
  overrides whose column no longer exists in the re-inspected workbook
  (previously the table displayed the stale pick while the backend
  silently auto-detected a different column; the backend now also logs a
  WARNING when it discards an override).
- **Mapping dropdowns now reflect the real workbook** — BOM Compare and
  Failure Rate mapping rows were static demo fixtures; on real files the
  dropdowns offered columns that didn't exist and mismatches surfaced
  only as execute-time errors. Rows are now derived from the inspected
  headers per role (exact-match auto-fill, attention state on no match),
  falling back to the fixtures until a file is inspected.
- **All six BOM Compare option checkboxes now drive real behavior** — a
  192-element interactive-wiring audit found "base match" was dead in
  both workflows (the backend read only the never-sent
  `loose_base_match`) and four options were silently ignored in Custom
  Compare. The `base_match` wire key now maps to the real loose
  base-match behavior (frontend default flipped to off so default runs
  are byte-identical), and the custom path honors `exact_match`,
  `ignore_dnp`, `check_fmr` (new `Failure_Mode_Ratio` warnings sheet),
  and loose base matching with group-path semantics.
  `treat_prov_as_covered` is provably inapplicable to a two-BOM compare
  (no group-name column) and is now disabled with a hint in custom mode.
- **FMEA HDA source flag is now authoritative** — the toggle's
  `hdaSource` payload was read by nothing; selecting "Separate HDA file"
  without attaching one silently fell back to inline detection. The
  backend now blocks `separate` with no HDA workbook at validate time
  (`missing_separate_hda`) and ignores stray HDA paths when `inline` is
  selected. Legacy clients without the flag keep path-presence behavior.
- **RefDes numeric tuning options got UI** — geometry batch size, max
  pin-label length, and provenance distance were honored by the backend
  but frozen at defaults with no controls. Added a `NumberField`
  primitive and three Options fields (geometry batch size disabled while
  geometry analysis is off).
- **Dead UI code removed** — ToggleChip's unused checkbox mode + `name`
  prop, RunStatePanel's unused `revealOutputLabel` prop, and
  WorkflowSelector's unreachable disabled-card branch (plus the stale
  pre-Phase-D `WorkflowOption.disabled` fields).
- Synced the streamed `execute_run` ack contract: Rust now enriches the
  run-event ack with `session_generation`, matching the frontend Zod
  schema and protocol docs.
- Aligned `inspect_input.header_rows_scanned` across Python, Rust,
  frontend schemas/types, tests, and protocol docs.
- Updated `read_flet_config` frontend schema to accept `null` namespace
  entries, matching Python and the protocol contract.
- Removed stale frontend output strategy and reconnect helper surfaces.

### Changed

- Release pipeline is now 12 steps with separate production and test
  TypeScript checks, locked Cargo checking, backend audit/tests, frontend
  tests, builds, and packaged self-tests.
- `npm run version:check` now includes lockfile package versions, so stale
  `package-lock.json` / `Cargo.lock` metadata cannot pass unnoticed.
- Browser-preview mock data now seeds a real `output_preview` sample for
  the Review drawer.

## [0.4.5] - 2026-04-22 — Design Handoff: Review Drawer + Preview Protocol

Additive refresh distilled from the `design_handoff_reliability_tools/`
package — no tokens renamed, no components replaced, no breaking protocol
changes. Introduces an optional `output_preview` field on `validate_run`
and a shell-level review surface that consumes it.

### Added

- **`output_preview` field on `validate_run` response** — a best-effort
  sample of **source/input rows mapped into review-friendly columns** (not
  a simulation of the eventual output workbook). Capped at 20 rows; inputs
  larger than 10 MB are skipped; emitted only after successful validation.
  Documented in `contracts/sidecar-protocol.md`.
- **Shared preview helper** (`backend/python/shared/output_preview.py`,
  new): `build_preview_from_file`, `build_preview_from_dataframe`, and the
  `PREVIEW_ROW_CAP = 20` / `PREVIEW_FILE_SIZE_LIMIT_BYTES = 10 MB`
  constants. All four runtime adapters import from here — one preview
  shape across the whole suite.
- **Runtime adapters attach `output_preview` on success**:
  - `backend/python/fmea/runtime.py` — samples the BOM, or the functional
    FMEA for `functional_to_piecepart`.
  - `backend/python/bom_compare/runtime.py` — samples the primary BOM.
  - `backend/python/failure_rate/runtime.py` — samples the prediction
    workbook.
  - `backend/python/refdes_extractor/runtime.py` — samples the optional
    BOM workbook when one is provided; no preview is emitted when the run
    is PDF-only.
- **Review drawer** (`frontend/src/components/ContextDrawer.tsx`, new): a
  right-anchored overlay toggled by `Ctrl/Cmd+R` that shows the active
  tool's run summary (phase / stage / progress / timestamps) above the
  `output_preview` table. Not modal — no backdrop, no focus steal, and
  `inert` when closed so the underlying tool stays keyboard-reachable.
  Escape dismisses. A matching `Review` button in the topbar toggles
  `shellStore.contextOpen` via `toggleContext`.
- **`previewStore`** (`frontend/src/stores/previewStore.ts`, new): Zustand
  store keyed by `ToolId` that holds the last `output_preview` per tool.
  Every tool's `validate_run` handler writes into it, which is how the
  shell-level `ContextDrawer` renders the active tool's preview without
  owning the active tool.
- **`Ctrl/Cmd+R` drawer binding**
  (`frontend/src/shared/hooks/useAppShortcuts.ts`): new platform-aware
  binding wired next to the existing Command Palette (`Ctrl+K`) shortcut.
- **`SectionCard` `variant` prop**: accepts `"outlined" | "divided" |
  "bare"` and defaults to `"outlined"`. Every existing call site remains
  unchanged unless it explicitly opts in.
- **`[data-selected="true"]` selector** added globally alongside the
  existing `data-active` selector. `StrategySelector`, `WorkflowSelector`,
  `ToggleChip`, and the Settings theme tiles now emit both attributes so
  selection styling works through either naming convention.
- **New CSS tokens** in `frontend/src/theme/styles.css`:
  `--section-surface-primary`, `--section-surface-muted`,
  `--section-surface-decoration`; the gap scale `--gap-inline` /
  `--gap-group` / `--gap-section` / `--gap-page`; and two larger type
  steps `--text-xxl: 28px` / `--text-3xl: 32px`.
- **Pill vocabulary split**: three distinct utility classes —
  `.badge-state` (with `good` / `warn` / `bad` / `idle` variants),
  `.tag-category`, and `.kbd-shortcut` — each with semantics for a
  different use (status vs. classification vs. keyboard hint). The old
  `.status-chip` is retained as a legacy alias so the 12 existing call
  sites keep working without migration.
- **`InputGrid` step indicators**: every `.input-card` now emits
  `data-state="pending|active|loaded"` with an accompanying step-number
  or checkmark badge. Pure CSS progressive disclosure — every control
  stays in the DOM, only the badge and card styling change.
- **6 new frontend tests**: 4 in a new `ContextDrawer.test.tsx` covering
  open/close, focus behavior, and preview rendering; 2 new drawer-shortcut
  cases added to `useAppShortcuts.test.tsx`.

### Changed

- **App rail widened 144px → 244px** with an icon-next-to-label layout
  (`frontend/src/app/AppShell.module.css`). The responsive fallback
  breakpoint bumped 1180px → 1280px: below 1280px the rail reverts to
  the previous 144px stacked layout, so narrow windows are unaffected.
- **FMEA / BOM Compare / Failure Rate / RefDes "Review Panel"
  SectionCards** now use `variant="divided"`, matching the new visual
  vocabulary for secondary review surfaces.
- **FMEA first SectionCard renamed**: "Piece-Part FMEA Generation
  Options" → "Generation Options". Principle C — the card heading was
  shadowing the topbar H1 and repeating the tool's name.
- **Topbar H1** moved from `--text-2xl` (24px) to the new
  `--text-xxl` (28px), giving the tool title more presence against the
  widened rail.
- **`GlobalLogPanel` status dot** is now derived from
  `runStore.activeRun.phase` — idle / pulsing accent / green / amber /
  red — so the dot reflects actual run state instead of a static color.
  The collapsed-panel count text contrast was bumped, and the drag-handle
  hit area grew from 6px to 10px so it is easier to grab.

### Protocol

- **`validate_run` response** gains one optional field,
  `output_preview`, alongside the existing `ok` / `reason_code` /
  `toast_text` / `validations` / `mode`. The field is omitted when
  validation fails, when the input exceeds `PREVIEW_FILE_SIZE_LIMIT_BYTES`
  (10 MB), or when a workflow has no natural preview source (e.g.
  RefDes Extractor with no BOM). Row count is capped at
  `PREVIEW_ROW_CAP` (20). Full schema in `contracts/sidecar-protocol.md`.

### Known Limitations

Documented here so they are visible, not hidden:

- **No `.status-chip` migration** across the 12 existing call sites —
  the new pill vocabulary is additive; the legacy class is still live.
- **No `--gap-*` call-site migration** — the new gap tokens are defined
  as aliases and are ready for adoption, but no existing spacing has been
  swapped over yet.
- **Hero-metric utility is unused** — the class is available, but no
  surface applies it today.
- **No topbar redesign** beyond the new `Review` button.
- **RefDes Extractor emits no preview** when the user runs PDF-only
  (no BOM workbook provided). This is intentional — a RefDes-extraction
  run without a BOM has no tabular source to sample.

### Tests

- **Backend 110 → 115 (+5).** Five new preview tests in
  `backend/tests/test_sidecar_main.py` cover the preview shape, row cap,
  file-size skip, per-workflow runtime attachment, and the optional-field
  contract. Sidecar self-test and security audit still clean.
- **Frontend 153 → 159 (+6) across 23 → 24 test files.** New file:
  `ContextDrawer.test.tsx` (4 tests — open/close, focus behavior,
  preview table render). `useAppShortcuts.test.tsx` grew +2 for the
  drawer binding.
- **Grand total: 263 → 274.**

## [0.4.4] - 2026-04-17 — release.bat cargo-check MSVC env

### Fixed

- **`scripts/release.bat` step 3 (`cargo check`) now finds `link.exe`**
  (`scripts/cargo-runner.mjs`, `scripts/cargo-msvc.cmd` — both new). The
  0.4.3 hardening added a bare `cargo check --quiet` call that assumed
  MSVC was on the parent shell's `PATH`. On a fresh shell (the exact
  environment `release.bat` spawns itself into) it isn't, so the step
  died with `error: linker 'link.exe' not found` before reaching the
  full Tauri build. The fix mirrors the existing `tauri-runner.mjs` /
  `tauri-msvc.cmd` pair: `cargo-runner.mjs` resolves `vswhere` (with a
  hardcoded VS 2022 BuildTools fallback when `vswhere` can't be spawned)
  and delegates to `cargo-msvc.cmd`, which calls `vcvars64.bat` /
  `VsDevCmd.bat` before invoking `cargo`. Step 3 now routes through
  `npm run cargo:check`.

### Added

- **`npm run cargo:check`** — run Rust typecheck with the MSVC
  environment set up. Equivalent to `cargo check --manifest-path
  src-tauri/Cargo.toml --quiet` but works on a cold shell.

## [0.4.3] - 2026-04-17 — v0.4.2 Build Fix + QC Pass

### Fixed

- **Rust build on Windows**: v0.4.2 shipped a `WindowsJobObject` type
  that failed every Tauri `Send + Sync + 'static` bound and imported a
  `windows-sys` symbol gated behind a missing feature, producing 83
  compile errors on the first `scripts/release.bat` run. Fix:
  - `src-tauri/Cargo.toml` now enables the `Win32_Security` feature on
    `windows-sys` so `CreateJobObjectW` resolves.
  - `WindowsJobObject` has explicit `unsafe impl Send + Sync` with a
    safety comment (kernel HANDLE, only shared through
    `Arc<Mutex<Option<ManagedSidecar>>>`).
  - Null-handle checks use `HANDLE::is_null()` instead of comparing a
    `*mut c_void` to the integer `0`.
- **FMEA preserve-template temp-file leak** (`backend/python/fmea/runtime.py`):
  if `write_template_preserved()` raised mid-write, the temp
  `<stem>.<hex>.part<suffix>` file leaked because the exception
  propagated past the cleanup try/except. Merged the two blocks so the
  temp is removed on any failure.
- **Windows Job Object startup race** (`src-tauri/src/lib.rs`): two
  orphan-the-sidecar windows in `spawn_managed_sidecar`:
  - (B2) `WindowsJobObject::create()` failing after `Command::spawn()`
    had already returned a live child.
  - (B3) The bridge panicking between `spawn()` and
    `AssignProcessToJobObject`, leaving the child running outside any
    job.
  Fix: create the Job Object BEFORE spawning, spawn the child with
  `CREATE_SUSPENDED`, assign to the job, then call `NtResumeProcess`
  (declared via a direct `extern "system"` from `ntdll`) so the child
  never executes a single scheduler tick outside the job. Failures on
  `assign_child` or `resume_child` now kill the (still-suspended) child
  before returning the error.
- **Stale "sidecar crashed" detail surfacing on unrelated disconnects**
  (`src-tauri/src/lib.rs`): the bridge was capturing every error-level
  log envelope into `fatal_sidecar_detail`, so a routine runtime error
  logged 30 s before an unrelated heartbeat timeout got quoted into the
  next "sidecar closed stdout" message. Now only the explicit crash
  envelopes emitted by the Python excepthooks (`Unhandled exception:…` /
  `Unhandled thread exception…`) are captured.
- **`useBackendBootstrap` dead branch**
  (`frontend/src/shared/backend/useBackendBootstrap.ts`): the
  old reconnect-resume branch was unreachable because every reconnect
  spawns a fresh sidecar, which always bumps `session_generation`.
  Replaced the `sessionStatus()` round-trip with an unconditional
  `clearActiveRun()` on reconnect — simpler and matches the only path
  the Rust bridge actually exercises.
- **`useBackendRunSubscription` dependency-array lint nit**
  (`frontend/src/shared/backend/useBackendRunSubscription.ts`): removed
  `handleRunEvent` from the `useEffect` deps (it's a
  `useEffectEvent` return value, stable by design) with a comment
  pointing at React's rules-of-hooks guidance.

### Changed

- **Release pipeline hardened to 11 steps**: `scripts/release.bat` now
  runs `cargo check --quiet` on the Rust bridge as step 3 (right after
  frontend typecheck) so a broken Rust build fails in ~30 s instead of
  surviving to the 3-minute `tauri:build:portable` step 8. Includes a
  dedicated `:cargo_check_failed` error label.
- **README** now advertises the 11-step release pipeline.

### Known Issues (for follow-up, likely v0.4.4)

Issues surfaced by the post-release debugger + quality-reviewer sweep
but intentionally deferred to keep v0.4.3 focused on the build break:

- **`reveal_in_file_manager` accepts any path** (`src-tauri/src/lib.rs`):
  a crafted UNC path (e.g. `\\attacker\bait`) handed to the command
  would trigger an SMB connection and leak the user's NTLM hash. Needs
  an absolute-path + UNC-allowlist gate.
- **Crash dumps have no rate limit or redaction**
  (`backend/python/common/logger.py`, `src-tauri/src/lib.rs`): a panic
  loop can fill the disk, and tracebacks may include proprietary BOM /
  customer part numbers that then end up in `~/.reliability_tools/logs/crashes/`.
- **Notification store evicts oldest error when five errors visible**
  (`frontend/src/stores/notificationStore.ts`): burst of five distinct
  errors + a sixth loses actionable information silently. Coalesce into
  a "+N more" summary or raise the cap for error tone.
- **First `status` event can race `ack` response**
  (`frontend/src/shared/backend/useBackendRunSubscription.ts`): the very
  first stage/message from a freshly-started run may arrive before
  `activeRun` is seeded and get dropped. Buffer-and-flush keyed by
  `run_id`.
- **`atomic_finalize` on OneDrive placeholders** (`backend/python/common/utils.py`):
  `os.replace` onto a cloud-only destination can fail mid-sync; consider
  pre-hydrating the target when OneDrive is detected.
- **Naive OneDrive path hint** (`common/utils.py`): the
  `"onedrive" in str(path).lower()` check matches unrelated folder names
  like `OneDrive_backup`, potentially running `attrib +P` and waiting up
  to 15 s against a dead network share.

### Tests

- Backend **110 → 110** (unchanged).
- Frontend **153 → 153** (unchanged — the fixes are either pure
  refactors or Rust-only).
- Full 11-step release pipeline is now the authoritative release gate
  and must pass before any `v0.4.X` tag.

## [0.4.2] - 2026-04-16 — Hardening, Crash Reporting, CSP, Cross-Tool Output Picker

### Added

- **Content Security Policy** (production builds): `tauri.conf.json`
  now sets `app.security.csp` to `default-src 'self' ipc:; script-src
  'self'; style-src 'self' 'unsafe-inline'; object-src 'none';
  base-uri 'self'; frame-ancestors 'none'` (full directive in
  `docs/ARCHITECTURE.md › Security Surface`). Dev mode is unaffected —
  CSP only applies to packaged release builds.
- **Crash reporting** — three independent capture paths write
  timestamped files into `~/.reliability_tools/logs/crashes/`:
  - **Python**: `sidecar_main._install_crash_hooks()` wires
    `sys.excepthook` AND `threading.excepthook`, skipping
    `KeyboardInterrupt`/`SystemExit`, and emits a last-gasp `log`
    envelope so the Rust bridge surfaces a notification before the
    sidecar exits. Backed by new `common.logger.write_crash_dump()`.
  - **Rust**: `install_rust_panic_hook()` in `src-tauri/src/lib.rs`
    chains after the default panic printer. Uses `USERPROFILE`/`HOME`
    directly — zero new Cargo dependencies.
  - **Frontend**: `shared/errors/installGlobalErrorHandlers.ts`
    catches `window.error` and `unhandledrejection` (neither caught by
    `ErrorBoundary`) and pushes a toast via `useNotificationStore`.
    Installed in `main.tsx` before the React root mounts.
- **Cross-tool output-folder picker**: new reusable
  `OutputFolderPicker` component under
  `frontend/src/components/`. BOM Compare, Failure Rate, and RefDes
  Extractor now surface the same picker UI the FMEA tool already had,
  with per-tool persistence in `shellStore` (`bomCompareOutputDirectory`,
  `failureRateOutputDirectory`, `refdesExtractorOutputDirectory`).
- **Backend honors `outputDirectory` for every tool**: the BOM
  Compare, Failure Rate, and RefDes Extractor runtimes now call the new
  `common.utils.validate_explicit_output_directory()` helper. Missing
  or unwritable directories fall back to the input-parent heuristic
  with a warning streamed via the run log.
- **`reveal_in_file_manager` Tauri command** (`src-tauri/src/lib.rs`):
  opens a path in the host OS file manager (`explorer.exe` on Windows,
  `open` on macOS, `xdg-open` on Linux). Wired into Settings › Logs
  "Open in Explorer" and `OutputFolderPicker`. Zero new Cargo deps.
- **`health_check` reports `log_directory`**: the Python sidecar now
  returns its resolved log directory (`~/.reliability_tools/logs/` or
  `$RELIABILITY_TOOLS_LOG_DIR`) on every `health_check`. Settings ›
  Logs swaps the placeholder for the real path on first successful
  check.
- **Global notification "Dismiss all" action**: new `dismissAll` on
  `useNotificationStore` with a matching button in `NotificationCenter`.
- **`__APP_VERSION__` compile-time constant**: `frontend/vite.config.ts`
  reads the repo-root `package.json` and defines `__APP_VERSION__` so
  Settings › About displays the live version instead of a hand-typed
  string. Declaration lives in `frontend/src/vite-env.d.ts`.
- **Version bumper** (`scripts/bump-version.mjs`): single-command
  update across `package.json`, `src-tauri/Cargo.toml`, and
  `src-tauri/tauri.conf.json`, with `patch | minor | major | x.y.z` or
  `--check` modes. Exposed as `npm run version:bump` / `npm run
  version:check`.
- **Release pipeline hardening** (`scripts/release.bat`): now a
  10-step pipeline that adds explicit frontend typecheck (step 2) and
  `python -m common.security_audit --strict` (step 3) before the
  existing backend/frontend test and build steps, each with its own
  fast-fail error label.
- **Windows Job Object sidecar lifecycle** (`src-tauri/src/lib.rs`,
  new `windows_job` module): the Rust bridge creates a Job Object with
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` and assigns the Python sidecar
  to it on spawn. If the bridge process is killed (or crashes without
  clean shutdown), Windows reaps the sidecar automatically instead of
  leaving an orphaned `python.exe` running. macOS/Linux are unaffected
  — they already inherit POSIX parent-death cleanup. Zero new Cargo
  dependencies; the module uses `windows-sys` types already pulled in
  transitively by Tauri.
- **"Open folder" affordance on successful runs**
  (`frontend/src/components/RunStatePanel.tsx`): when a run result
  includes an `outputFile`, the panel now renders an "Open folder"
  button that invokes the `reveal_in_file_manager` Tauri command on
  the containing directory. Wired into every tool via a shared
  `parentDirectoryForPath` helper in the new
  `frontend/src/shared/backend/fileManager.ts` module.

### Changed

- **Subprocess allowlist narrowed**: `common/security_audit.py`'s
  `SUBPROCESS_ALLOWLIST` shrank from `{"attrib", "powershell", "start",
  "python", "pythonw"}` to just `{"attrib"}` (the only command actually
  invoked today, in `common/utils.py` for OneDrive hydration). Adding
  any new subprocess call requires explicitly extending the allowlist
  and updating `CLAUDE.md` / `docs/ARCHITECTURE.md`.
- **Settings › About "Shell version"** now tracks `__APP_VERSION__`
  from `package.json` instead of the stale hand-typed `0.2.2`.
- **Text contrast**: `--text-faint` tightened across the Default,
  Signal Slate, and Midnight Blue themes to meet WCAG AA against each
  theme's surface tokens.
- **Fatal-sidecar detail merged into disconnect messages**
  (`src-tauri/src/lib.rs`, new `merge_disconnect_message` helper +
  `fatal_sidecar_detail` field on `SessionShared`): the bridge now
  captures the most recent error-level log line emitted by the
  sidecar and appends it to the user-visible disconnect notification.
  Users now see `Python sidecar closed stdout. Details: Unhandled
  exception: RuntimeError: …` instead of an opaque "connection lost."
- **Platform-aware keyboard shortcuts**
  (`frontend/src/shared/hooks/shortcutUtils.ts` + `useAppShortcuts.ts`):
  navigation and command-palette shortcuts use `Cmd` on macOS and
  `Ctrl` everywhere else, and are suppressed while focus is in a text
  input, textarea, or `contenteditable` region so typing never
  accidentally swaps tools. Shortcut labels in the UI follow the
  same platform convention.
- **Shell-level run-event subscription**
  (`frontend/src/shared/backend/useBackendRunSubscription.ts`, new):
  subscription for `status` / `progress` / `log` / terminal events
  moved out of per-tool hooks and into the App shell, so a running
  job now survives switching between tools. `runLifecycle.ts` shrank
  by ~123 lines; `useGlobalLogSubscription.ts` was deleted
  (superseded). Per-tool hooks focus only on local session
  projection.
- **Notification toast dedup and 5-slot cap**
  (`frontend/src/stores/notificationStore.ts`): identical toasts
  (same `tone` / `title` / `detail`) increment a `count` and
  re-arm the auto-dismiss timer instead of stacking; the visible
  stack is capped at `MAX_VISIBLE_NOTIFICATIONS = 5` (FIFO eviction
  of the oldest non-error toast when exceeded). Prevents backend
  error bursts from burying the rest of the UI.

### Fixed

- **Atomic-write temp file naming** (`common.utils.atomic_write_path`):
  generated temp paths now preserve the target suffix
  (`<stem>.<hex>.part<suffix>` instead of `<name>.<hex>.part`), so
  `openpyxl`'s post-write `verify_excel_readable()` — which sniffs
  format from the file extension — accepts the temp file during atomic
  finalize. Before the fix, any FMEA run that exercised the
  post-write verification failed with `Post-write verification failed
  for ... .part; workbook did not open.`.
- **HoldButton double-invocation**: removed redundant
  `onMouseDown`/`onTouchStart` handlers that could fire alongside
  `onPointerDown` on platforms that dispatch both; a
  `gestureActiveRef` guard now prevents a second `beginHold` call
  inside the same gesture. Also added `aria-modal="true"`, focus
  capture on open, focus restoration on close, and an `onCancel`
  handler for Escape on the confirmation dialog.
- **Error toasts announce as alerts**: `NotificationCenter` now
  renders `role="alert"` on error-tone `<article>` elements so screen
  readers pick them up as assertive live regions.
- **FMEA demo data in desktop mode**: the FMEA tool no longer
  pre-populates demo inputs when launched in desktop-bridge mode — the
  demo scenario is scoped to `browser-mock` (`IS_BROWSER_MOCK`) and
  desktop users start with empty inputs.
- **ADR-002 terminology** (`docs/DECISIONS.md`): clarified that `id`
  identifies every envelope uniquely, `request_id` correlates a
  request/response pair, and `run_id` correlates a long-running run.
- **`CLAUDE.md` stdin-atomicity wording**: disambiguated between
  Rust's `Mutex<ChildStdin>` guard and `io::Stdin::lock()` to prevent
  readers from confusing the two.
- **`docs/ARCHITECTURE.md` stale line numbers**: replaced hardcoded
  `src-tauri/src/lib.rs` line references with a grep instruction so
  the doc survives unrelated refactors.
- **`list_sheets` now hydrates OneDrive placeholders**
  (`backend/python/sidecar_main.py`): the handler calls
  `ensure_file_available()` before `openpyxl.load_workbook()`, so
  cloud-only OneDrive placeholders are materialised on demand instead
  of failing with an opaque `openpyxl` I/O error. Matches the
  behaviour already in place for every run command.

### Tests

- **Backend total: 106 → 110.** Four new tests in `test_cancel_bridge.py`
  cover the Failure Rate path: `FMEALinkerLogic.cancel` is a
  `CancellationToken`; `logic.cancel.cancel()` sets the flag; the
  sidecar's `ActiveRun.bind_processor(logic)` plus `request_cancel()`
  propagates cancellation; and the race where cancel arrives *before*
  the processor is bound is latched and replayed on bind.
- **Frontend total: 148 → 153** across **20 → 23** test files. Three
  new suites landed with the shell-level subscription / shortcut
  rework:
  - `useBackendBootstrap.test.ts` — bootstrap + session-generation
    reconciliation on reconnect.
  - `useBackendRunSubscription.test.ts` — shell-level run-event
    subscription lifecycle.
  - `useAppShortcuts.test.tsx` — platform-aware shortcut routing
    and editable-field guards.
  `RunStatePanel.test.tsx` also grew to cover the new Open-folder
  affordance. `installGlobalErrorHandlers` is exercised indirectly
  through the existing notification-store suites.
- **Grand total: 254 → 263.**

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
  `runLifecycle.test.ts` 8 → 9 (disconnect and reconnect-clearing
  coverage).
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
