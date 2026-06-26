# RefDes Extractor — BOM Coverage Reverse-Diff (2026-06-25)

**Feature build report.** Adds the two reconciliation directions the RefDes
Extractor was missing, plus two settled decisions from the same session.

## What was built

The RefDes Extractor already labels every *extracted* component
`(Verified)`/`(Unverified)` against the BOM. This change adds the inverse so an
engineer can fully reconcile a board against its schematic:

- **BOM Not Grouped** — RefDes in the BOM that never landed in a real extracted
  group, split by `Status`: **Not Extracted** (never seen on the schematic) vs
  **Extracted-Ungrouped** / **Extracted-Provisional** (seen, but not cleanly
  grouped). Enriched with **Part Number + Description + Pages** carried from the
  BOM itself.
- **Extracted Not In BOM** — RefDes pulled off the schematic that aren't in the
  BOM (the existing `(Unverified)` set, surfaced explicitly).
- **Coverage Summary** — counts for all of the above.

Three new sheets are appended to the existing `RefDes Extraction` workbook, and
a one-line coverage note is added to the run result. The feature is **gated on a
non-empty, successfully-loaded BOM** (with no BOM the diff is degenerate; a
failed BOM load already shows the prominent `BOM CROSS-CHECK FAILED` notice).

### Design decisions
- **Coverage is component-level.** Both BOM and extracted RefDes normalize
  through `common.refdes_utils.get_usage_base_refdes`, so instance/pin suffixes
  collapse to base (`U200-1`/`U200-2` both cover BOM `U200`; `J1-4` covers `J1`).
  This is what makes BOM-base vs schematic-pin matching work. Same-base BOM rows
  are merged deterministically (sorted display, unioned pages, first non-blank
  meta) — never an arbitrary set-iteration winner.
- **Enrichment is Level B (BOM columns), not HDA.** The missed parts are in the
  BOM by definition, so Part#/Description come free from the BOM. HDA (a
  part-number→commodity-taxonomy lookup, keyed by PN not RefDes) was scoped out
  as an optional Level-C follow-on; the BOM-loader gained an opt-in
  `include_component_metadata` flag for the Part#/Description capture.
- **Computed fresh, in the engine's own normalized space.** The confirmed-dead
  `bom_verifier.py` (zero callers — verified) was **deleted** rather than
  revived, to avoid a second normalization drifting from the engine's.
- **Coverage is on the extraction critical path but can never harm it.** Both
  `build_coverage` and the sheet write are wrapped so any defect degrades to
  "no coverage sheets" — the primary extraction workbook is always saved.

## Files changed
- `backend/python/refdes_extractor/coverage_report.py` — **new**, pure
  `build_coverage()` + `write_coverage_sheets()`.
- `backend/python/refdes_extractor/bom_loader.py` — opt-in Part#/Description
  capture (`include_component_metadata`), Description-over-Name precedence.
- `backend/python/refdes_extractor/runtime.py` — BOM-meta load, gated coverage
  compute + sheet write (both failure-guarded), coverage note.
- `backend/python/refdes_extractor/bom_verifier.py` — **deleted** (dead).
- `scripts/build_sidecar.py` — hidden-import: drop `bom_verifier`, add
  `coverage_report`.
- `backend/tests/test_coverage_report.py` (**new**, 17),
  `test_bom_loader.py` (**new**, 5), `test_sidecar_main.py` (+1 end-to-end).
- `frontend/src/mocks/scenarios.ts` — mock result coverage note.
- Doc counts: `CLAUDE.md` (×2), `README.md`, `docs/TESTING.md`.

## Adversarial review + fixes
A 3-lens review (correctness / wiring / bug-hunt) ran on the diff. Wiring was
clean; the other lenses found four real issues, all fixed with tests before
the fix (TDD):
1. **HIGH** — coverage failure could unlink the temp file and lose the entire
   extraction. Fixed: compute + write are both failure-guarded; the main
   workbook always saves.
2. **MEDIUM** — same-usage-base BOM rows collapsed non-deterministically
   (set-iteration winner) and dropped pages/meta. Fixed: deterministic merge.
3. **MEDIUM** — `Name` (generic) shadowed a real `Description` column. Fixed:
   curated Description-first priority list, locally (global synonym table
   untouched).
4. **MEDIUM** — `str(nan)` leaked a phantom `NAN` RefDes. Fixed: NaN-safe cell
   stringification + mixed-type page-sort guard.

## Adversarial QA/QC pass (second review)
A deeper 5-dimension QA/QC pass (finders that *ran* `build_coverage` to
reproduce defects, each finding then independently refuted-or-confirmed) found
two more real defects plus two cleanups; two candidate findings were **refuted**
as unreachable in production:
1. **Confirmed (important)** — in **piece-part** mode the engines emit unparented
   pins as the literal token `PIN-{text}`, which `get_usage_base_refdes` collapses
   to the base `PIN`, producing one phantom "PIN" row and inflating the
   over-extraction count. Fixed: `_norm` now rejects any base without a digit (a
   real RefDes is prefix+number), mirroring nextgen's own `_extract_base_refdes`.
2. **Confirmed** — the "Extracted Not In BOM" side used first-seen `setdefault`,
   dropping later rows' pages/group for a token spanning multiple rows
   (asymmetric with the now-unioned BOM side). Fixed: union pages + prefer a real
   group over PROVISIONAL/UNGROUPED.
3. **Cleanups** — NaN-safe `group` cell read for parity; docstring + test note
   that `Extracted-Ungrouped` only arises under the legacy fallback backend
   (default NextGen discards non-annotation words → they show as Not Extracted).
4. **Refuted (no change)** — phantom `123`/`NET1` tokens (engine gates all tokens
   through `REFDES_RE` first) and same-base BOM-row provenance mixing (the loader
   drops hyphenated forms, so each base maps to exactly one entry in production).

## Verification (Python 3.14, this laptop)
- Backend **220** pytest · Frontend **226** vitest · Typecheck clean ·
  Sidecar self-test + security audit clean.

## Parking lot (not in this change)
- **Decision 1 — Part Usage (settled, not yet implemented):** leave Part Usage
  **blank** when it can't be counted from a data file; **flag the counting
  method for verification** when the count comes from anything other than a BOM
  or HDA file. FMEA-generator change; do next. (Decision 2 — read-layer text
  preservation — was "keep current," no code.)
- **HDA Level-C enrichment** — optional commodity-taxonomy columns on the
  coverage sheets; clean additive follow-on if wanted.
- **RefDes success-toast tone** — still green when a BOM cross-check fails;
  bundled with the separate Custom-BOM-Compare frontend item in the prior
  handoff.
