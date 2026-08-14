# Known Residuals, Pending Verification, and Audit Lenses

> **Living document.** This is the single place future audits (human or agent)
> should check before re-flagging something as a finding. Every item here is
> either deliberately accepted, informational, or pending verification on a
> machine with real technical data. Historical plan/review documents for
> completed work are deleted once finished — their surviving knowledge lands
> here. Last consolidated: v1.3.0 (2026-07-21), during the documentation
> sweep — every entry below was re-verified against the v1.3.0 code at that
> point. (Previous consolidation: v1.1.0, 2026-07-14, after the
> external-review remediation Waves 1–4 + Wave R.)

## Pending verification (requires real technical data — not on the dev machine)

First real-data pass should exercise:

- **FMEA preserve-formatting merge** against a genuine hand-maintained FMEA:
  confirm the blank-guard leaves hand-authored Local/Next/End Effect text
  intact, real replacements land on the `Merge Changes` audit sheet, ambiguous
  rows are flagged rather than guessed, and the output lands as
  `<target>_Merged_<timestamp>.xlsx`.
- **Failure Rate** run whose BOM text contains standalone "CB"/"PP"/"PU"
  tokens — must pass through unmodified (expander is scoped to tool-authored
  columns).
- **RefDes piece-part** run with the geometry-subprocess option ON in the
  **packaged** build (`freeze_support` path).
- **RefDes DIG-418 incident closure**: re-run the affected schematic PDF;
  previously-vanished groups should now appear (recovered labels / UNGROUPED
  rows / range-summary gap rows). Check the run log for
  `annotation extraction timed out` to pin the original trigger; dense sheets
  may warrant raising the new Advanced "Annotation page timeout (s)" option.
- **Desktop-only UI surfaces** not coverable by browser-preview tests: real
  run toasts, the RefDes prefix editor round-trip, per-workflow onboarding
  EmptyStates on the desktop runtime.

## Accepted residuals and deliberate non-fixes

Do not re-flag these without new evidence; each was examined and accepted.

### Cross-cutting / process lifetime

- **Windows Job Object pre-assignment window**: an external force-kill of the
  bridge between `spawn()` (CREATE_SUSPENDED) and `AssignProcessToJobObject`
  can leave one suspended, never-scheduled `python.exe` (inert orphan).
  Eliminating it requires `PROC_THREAD_ATTRIBUTE_JOB_LIST` process creation —
  deferred. Full discussion in `docs/ARCHITECTURE.md`. (The CLAUDE.md gotcha
  now carries a matching caveat — reconciled 2026-07-21.)
- **Stale stdout reader buffered frames**: generation-guarded teardown stops an
  old reader from killing a successor session, but a stale reader can still
  process already-buffered frames (heartbeat/fatal-detail refresh, or a frame
  enriched with the successor's generation) before hitting EOF. Retiring stale
  readers from all frame processing needs a separate event-session identity
  design.
- **Execute-timeout head-of-line**: synchronous sidecar commands
  (`list_sheets`/`inspect_input`) run on the single stdin thread; Browse is
  disabled during live runs to protect cancel latency, but pre-ack validation
  of a run on a slow network path can still exceed the bridge timeout — the
  frontend treats that as acceptance-unknown and the late ack auto-attaches.
  Moving sync commands to an executor thread was considered and deferred.
- **Cross-instance output-name race**: name allocation is collision-proof
  (` (2)`…` (99)`) within one app instance, but two independent instances
  writing the same stem in the same wall-clock second can race between
  free-name selection and `os.replace` promotion — last writer wins (atomic,
  no corruption). Exclusive-create reservation at finalize deferred as
  practically negligible for a single-user desktop tool.
- **Start from a pristine tool**: the Start button sits outside the onboarding
  EmptyState gate on all four tools; backend validation blocks the run.
  Disabling Start until the first file loads would be tidier — cosmetic.

### Python sidecar

- `sidecar_main._parse_log_level` recognizes embedded `" WARNING:"` text but
  not the leading `"WARNING:"` form, so several streamed warning lines
  classify as INFO in the UI log.
- **Legacy `.xls` tests pin BIFF8, not BIFF5** (accepted 2026-07-21): the
  xlwt-generated fixtures are BIFF8 (Excel 97–2003, i.e. every real-world
  old `.xls`). Genuine Excel-5.0/95 BIFF5 files are untested and expected to
  stay that way — no such files exist in the user's workflow, `xlrd` handles
  BIFF5–BIFF8 with the same reader at runtime, and the failure mode would be
  a loud read error, never silently wrong data.
- `common/utils.py` read-layer raw `IOError`s — pre-existing, different
  semantics from the fixed write-path class; change only with a caller audit.
- `build_summary_frames` logs the BOM_Additions rename note as a side effect —
  single call site per run today.
- **Mixed-mode PROVISIONAL formatter gap** (both RefDes engines, pre-existing):
  the bucket's mode is fixed at creation while functional prov writes to
  `unverified` and piece-part prov writes to `tokens` unconditionally — in a
  doc mixing both modes, whichever kind lands second is invisible in the
  PROVISIONAL row.
- **Direct RefDes engine API ownership**: the desktop runtime guards
  `doc.close()` against surviving word-extraction threads, but direct
  legacy/NextGen entry points that own their own fitz document still leave
  closure to a context manager; a separate lifecycle design is needed for
  direct-API callers.
- `detect_groups_from_drawings` keeps an unbounded direct word-read default
  for compatibility; the sole in-repo production caller supplies the bounded
  reader, but a future direct caller could omit it.
- **Numeric-equivalence merge rule** (informational): textually distinct but
  numerically equal generated strings ("1e3" vs "1000", "007" vs 7) count as
  unchanged — the user's existing cell wins, no audit row. Always the
  preserve-user direction; expected under the decided semantics.
- **PyMuPDF fixture trap**: `set_info(content="")` silently no-ops — simulate
  empty-`/Contents` annotations another way in tests.

### Frontend / docs

- Component Detail / New-RefDes / Part Usage Diagnostics banner sheets freeze
  the banner row, not the header (matches pre-existing FMEA precedent).
- Vitest full-suite occasionally flakes 1–3 tests (usually
  `App.keepalive.test.tsx`) under heavy machine load; every flake passes in
  isolation. Root-caused 2026-07 (cold lazy-chunk imports vs the RTL default
  timeout); mitigated in `vitest.setup.ts`, residual under extreme load.
- FMEA's onboarding EmptyState is desktop-only by design — the browser-mock
  preview deliberately stages a working demo instead.

### Unified BOM (2026-08-13)

- **J2 — inline delete anchoring can interleave rows**: deletions carried
  from one old row can land between backbone rows when the old- and
  new-file orders diverge — deterministic and spec-sanctioned, not a bug.
- **J3 — silent old-blank-to-new-value fill**: when an old cell is blank and
  the new file supplies a value, the merged cell shows the new value with
  no Changed note — the value is correct and no old data was lost; pinned
  by `test_old_blank_filled_by_new_value_is_silent`.
- **J5 — 200-row cancel-check stride**: the merge checks cancellation every
  200 rows vs. the repo's usual 50 elsewhere — sub-millisecond impact at
  measured scale, left as-is.
- **J7 — DNP-marked old SUFFIX rows still carry into the unified tab**:
  preserving manual suffix/pin rows outranks DNP filtering here — the
  unified tab is not DNP-clean the way compare tabs are.
- **J8 — a value change on a superseded base reports twice**: once on the
  bare row, once on each carried row — compare-tab metrics and unified
  counts describe the same reality from different angles, not a
  double-count bug.
- **F-A — the unified tab matches full canonical tokens**: a suffix→suffix
  rename reads as Delete+Added, where default base-matching compare tabs
  read "in both" — deliberate: the merge document must show physical row
  changes, not base-token continuity.

## Reusable audit lenses

Applied to all four tools during the 2026-07 deep dives; review future
features against the same list:

dropped diagnostics · internal-column leaks · cryptic tokens · misleading
labels · phantom options · asserts on user data · NaN writes · demo-content
leaks · generic messages

Plus the wiring invariants in `CLAUDE.md` (every control wired end-to-end,
disabled-with-hint, no demo content in desktop state, lockstep two-definition
couplings, doc counts honest).
