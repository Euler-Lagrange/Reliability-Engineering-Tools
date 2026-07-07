# Stability Sweep — 2026-07-06/07 (v0.4.7 + v0.4.8)

> **v0.4.8 addendum (final-day sweep, commit `e3cced6`):** a fourth audit
> wave covered the layers never deep-dived (backend `common/` + `shared/`,
> frontend components/primitives/stores/hooks) plus the deferred backlog.
> Headline fixes: the BOM Compare group-report expander was rewriting user
> text (same corruption class as the 0.4.7 Failure Rate fix — now scoped to
> Reason/Status); `detect_column` no longer crashes on numeric Excel
> headers; NaN cells can no longer become a phantom "NAN" RefDes; a
> cross-tool run guard stops one tool's start from clobbering another
> tool's live run; command palette/selector/copy-button accessibility; and
> the long-standing vitest under-load flake was root-caused (RTL
> asyncUtilTimeout 1000ms vs cold lazy-chunk imports) and fixed. Suite:
> **378 backend / 295 frontend / 17 Rust = 690**, day-diff QA verdict PASS
> with zero findings. Remaining known-open: the live in-browser UX pass
> was blocked (no Chrome on this machine) — worth doing once Chrome +
> the Claude extension are available; the dev server workflow is
> `npm run dev` → localhost:5173.

Session handoff for the FMEA deep dive + all-tools stability sweep. Written so
any future session (or reviewer) can see what was done, how it was verified,
and what deliberately remains.

## What shipped (commit series `cde301d..v0.4.7`)

| Commit | Batch | Content |
|--------|-------|---------|
| `b7722d2` | FMEA 1 | Preserve-mode diagnostic-sheet parity (`build_summary_frames`), `_style_hint` leak, `invalid_do_not_map` required-mapping gate + MappingTable marker |
| `f23cc3e` | FMEA 2 | Truthful diagnostics language: `PU_PARSE_REPLACED_WITH_COUNT` split, `PU_INHERITED_MISMATCH` label, REASON_CODE_LABELS lockstep test, sheet legend banners, named unsupported-combo toast, files-first FMC gate |
| `112eb8f` | FMEA 3 | Removed phantom `columnSelection`, warning counts in RunResult + toast, Required input chips, mode-aware FMC marker, M9 demo-validation desktop leak (the "state survived restart" mystery — nothing actually persists except output folders/theme/CCA prefix/log height) |
| `6fa7d3f` | FMEA 4 | `FileAccessError` for all post-write verification, negative Part Usage as data-quality warning, NaN-safe template append, dead exports removed, protocol doc sync |
| `c3fb1f4` | Sweep 5 | Failure Rate output-text corruption fix (expander ran on EVERY column), `Validation_RefDes` leak, informational roll-up notes excluded from warnings; RefDes verified-group metrics require components, checkpoint control wired + flipped opt-in + write-failure guard; sidecar `multiprocessing.freeze_support()`; custom FMR sheet translation |
| `fa57eb2` | Sweep 6 | Friendly empty-sheet ValidationErrors with UI labels, truthful base-match label+hint, Component Detail legend banner, corrupt prefix-config warning surface + `.tmp` cleanup, protocol-layer ValidationErrors, display-label blocked-run messages, dead `backendStatus` write removed |

Every batch: failing test written first, full suites run, independent
QA-review agent, doc counts synced in the same commit. Cross-batch integration
audit after the FMEA series: PASS.

## Verification state at release

- 373 backend / 281 frontend / 17 Rust = **671 tests green**
- `npm run typecheck` + `typecheck:tests` clean
- `common.security_audit --strict` clean; sidecar `--self-test` OK
- Full `release.bat` pipeline (typechecks, cargo check/test, audit, suites,
  PyInstaller sidecar, portable Tauri build, packaged self-tests) run for
  v0.4.7 — see the release commit/tag for the result
- NOT verified on this machine: real-data runs (no tech data allowed here).
  First real-data pass should exercise: an FMEA preserve-formatting run
  (diagnostic sheets + banners), a Failure Rate run whose BOM text contains
  standalone "CB"/"PP"/"PU" tokens (must pass through unmodified), and a
  RefDes piece-part run with the geometry-subprocess option ON in the
  packaged build (freeze_support fix).

## Known/accepted items (deliberate non-fixes)

- `common/utils.py` read-layer raw `IOError`s — pre-existing, different
  semantics from the write-path class that was fixed; change only with a
  caller audit.
- `build_summary_frames` logs the BOM_Additions rename note as a side effect
  — single call site per run today; documented in Batch-1 QA.
- Component Detail / New-RefDes / Part Usage Diagnostics banner sheets freeze
  the banner row, not the header (matches pre-existing FMEA precedent; re-pin
  with `freeze_panes="A3"` if it ever bothers users).
- Vitest full-suite occasionally flakes 1-3 tests (usually
  `App.keepalive.test.tsx`) when the machine is under heavy load; every flake
  passes in isolation and on quiet re-runs. Known issue since 0.4.6.
- `docs/TESTING.md` line ~260 mentions the removed `resolveSheetInspections`
  symbol inside an accurate removal note.

## Where to pick up

- Follow-ups listed in `project_fmea_deep_dive_2026-07` and
  `project_holistic_review_execution` memory files.
- The four deep-dive audit lenses (dropped diagnostics, internal-column
  leaks, cryptic tokens, misleading labels, phantom options, asserts on user
  data, NaN writes, demo-content leaks, generic messages) have now been
  applied to ALL four tools — future features should be reviewed against the
  same list (see CLAUDE.md Wiring Invariants).
