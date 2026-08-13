# Design: "Create Unified BOM" for BOM Compare

**Date:** 2026-08-13
**Status:** Approved by user (brainstorming session); pending spec review
**Scope:** BOM Compare tool — Group and Custom workflows

## Problem

When comparing two BOMs, one is usually old and one is new. The comparison
report shows differences, but the user still has to hand-build the next
working BOM: apply the new BOM's updates, re-create manually-added suffix
rows (e.g. `U2000-1` … `U2000-10`, `J4-P1` … `J4-20` — the delivered BOMs
never contain these), and track what was added/removed for FMEA updates.

This feature makes the tool produce that merged document: a **Unified BOM**
tab in the compare output workbook that accepts the new BOM as authoritative,
carries the old BOM's manual data forward, and color-codes every row by what
happened to it.

## User-Facing Behavior

- New **"Create Unified BOM"** checkbox in the Options section.
  - Available in Group and Custom modes.
  - Disabled with an explanatory hint in Extraction Compare mode
    (wiring invariant #2).
- When checked, a **"Which file is the newer BOM?"** picker appears
  (explicit picker; two choices labeled with the file nicknames/role labels,
  default **File 2** — the BOM slot in Group mode, BOM B in Custom mode).
- The run produces one extra tab, **"Unified BOM"**, in the same compare
  output workbook. Everything else about the run is unchanged.

## Merge Semantics

### Backbone and ordering

- The **new** file's rows are the backbone, top to bottom, in original order.
  Every new-file row appears in the unified sheet.
- **Deletions are placed inline:** walking the old file top to bottom, each
  old-only row is inserted immediately after the nearest preceding old-file
  row that survived into the unified sheet (after its suffix-expansion block
  if it has one). Consecutive deletions stay together in old-file order.
  Deletions with no surviving anchor go at the top. Deterministic; reads
  like one continuous BOM.

### Columns

- Union of both files: the new file's columns in original order, then
  old-only columns appended (in old-file order), then three tool-authored
  columns at the far right: **Status**, **Source**, **Change Notes**.
- Column identity = case-insensitive exact header match (trimmed). In Custom
  mode, the user's configured column pairs (`compare_columns`) also count as
  identity; the unified column takes the new file's header.
- Columns that exist under different names in the two files both appear in
  the union — data is never lost; the user consolidates manually.

### Row matching

- Per-RefDes, using the existing normalization (`canonicalize_refdes`,
  base matching, `split_refdes_list` for multi-RefDes cells in grouping
  files). A multi-RefDes old row matches per token; carried data for a
  matched token comes from whichever old row contains that token.

### Conflict rule (rows in both files)

- Shared columns take the **new** file's value.
- Exception (a) — blank protection: if the new value is blank and the old
  value is not, the old value is kept and flagged
  (`kept old value; new was blank`).
- Exception (b) — carried suffix rows follow the uniform-column rule below.
- Old-only columns on matched rows are filled from the old file (general
  manual-data carry-forward, independent of the suffix feature).
- Value comparison is NaN-safe and string-normalized: trimmed,
  numeric-equivalent tolerant (`10` vs `10.0` is not a change).

## Suffix / Pin Carry-Forward

RefDes is the source of truth: same base RefDes ⇒ same physical thing.
Part-number match is **not** required for carry-forward.

When the old file has suffix rows for a base (`U2000-1` … `U2000-10`, or
pin-style `J4-P1` / `J4-20`) and the new file has only the bare RefDes
(`U2000`, `J4`):

- All old suffix rows are **carried forward** into the unified sheet, in
  old-file suffix order, immediately after the bare row's position.
- Pin-style notation is treated exactly like any other manual suffix here
  (no special-casing of `is_pin_notation` for the merge). Pin rows keep
  their existing behavior in the rest of the compare pipeline.
- Carried rows keep their old data. The new bare row's values overwrite a
  shared column only where **all** old suffix rows agree on that column's
  value (**uniform-column rule**): uniform columns (part number,
  description, commodity levels) are inherited from the base part and
  update; per-suffix columns (sheet number, section) vary row-to-row and
  are never touched. Every overwrite is flagged, e.g.
  `Part Number updated from "123-456" to "123-789" by new BOM`.
  Blank new values never overwrite.
- The bare new-file row is **kept**, marked **Superseded** (one consistent
  rule for pins and non-pins), with notes like
  `Superseded by 10 carried rows (J4-P1 … J4-20) — delete this row`.
  Nothing disappears silently; the user deletes bare rows after review.
- Reverse case (new file has suffixes, old has bare) needs no special
  handling: suffix rows are backbone rows and read as Added/Changed via
  normal matching.

## Status, Styling, Source, Change Notes

Row-level styling via the existing `common/excel_styles.py` palette
(identical hex values to Excel's Good/Bad/Neutral built-in styles):

| Status | Meaning | Style |
|---|---|---|
| `Added` | RefDes only in new file → add to FMEAs | green fill `C6EFCE`, dark green font `006100` |
| `Delete` | RefDes only in old file → remove | red fill `FFC7CE`, dark red font `9C0006` |
| `Superseded` | bare row replaced by its carried suffix/pin rows → delete after review | blue fill `BDD7EE`, dark blue font |
| `Changed` | in both, ≥1 value differs | yellow fill `FFEB9C`, dark yellow-brown font `9C5700` |
| `Carried` | suffix/pin rows pulled forward from old file | yellow (same as Changed) |
| *(blank)* | in both, identical | no fill |

- **Source** column (filterable): which file(s) the row came from. Values
  use the user's file nicknames when set, else "Old BOM" / "New BOM":
  `Both`, `New BOM only`, `Old BOM only`, `Old BOM (carried)`,
  `New BOM (superseded)`.
- **Change Notes** column: plain human-readable prose, semicolon-separated,
  exact values included:
  `Part Description changed from "RES 10K 1%" to "RES 10.5K 1%"; Commodity
  Level 2 changed from "Passive" to "Resistor"`. Carried rows explain the
  carry and any uniform-column updates. Deleted rows that came from a
  multi-RefDes old row note the original grouping. This column doubles as
  the merge's debug / data-error log.
- Sheet written with the extraction-compare pattern: `write_df_to_sheet` +
  `style_worksheet` with a `row_style_func`, autofilter on, frozen header.

## Backend Structure & Wiring

- **New module `backend/python/bom_compare/unified_bom.py`:**
  - `build_unified_bom(old_df, new_df, …) -> UnifiedBomResult` — pure merge
    logic returning the merged DataFrame, per-row status/style, notes, and
    counts. Testable in isolation.
  - `write_unified_bom_sheet(wb, result, presets)` — appends the styled tab
    to an already-open workbook (caller owns save lifecycle, like
    `write_extraction_compare_excel`).
- **Option keys** (wiring invariant #1 — read end-to-end with runtime tests):
  - `create_unified_bom: bool` (default `false`)
  - `unified_newer_file: "file1" | "file2"` (default `"file2"`)
  - Group runtime maps file1/file2 → grouping/bom; Custom maps → BOM A/B.
  - `validate_run_request` rejects an invalid `unified_newer_file` value at
    validate time (blocking validation error).
- Group and custom runtimes run the merge after their existing analysis and
  pass the result into their writers so the tab is added **before the single
  atomic save** — the existing write → verify → promote pattern is untouched.
  (The group writer `write_excel_report` and custom writer
  `write_bom_compare_excel` gain an optional unified-result parameter.)
- `ignore_dnp` is honored for status flags (a DNP-filtered old-only row is
  not emitted as a Delete), but every new-file row stays in the backbone
  regardless.
- **Run summary:** result notes gain a line like
  `Unified BOM: 412 rows — 12 added, 7 to delete, 23 changed, 10 carried
  forward, 2 superseded`. Only genuine data-integrity flags (blank-kept
  values, uniform-column overwrites on carried rows, duplicate RefDes in the
  new file) count toward `warning_count`; Added/Delete rows are the
  feature's point, not warnings.

## Frontend Wiring

- Add `create_unified_bom: false` to the options state object and an
  `OPTION_META` entry (label + hint) in `BomCompareTool.tsx` — the checkbox
  renders via the existing data-driven loop. Mode-gating disables it in
  extraction mode with a hint.
- The newer-file picker is a small dedicated control (not part of the
  checkbox loop), rendered only when the checkbox is checked, writing
  `unified_newer_file` into the options payload. Labels come from the file
  nicknames / role labels.
- No new workflow ID, no registry changes, no new subscription — the
  payload flows through the existing `buildRunRequest()` options object.
- Mock scenarios: group and custom demo `runSequence.result` fixtures gain
  the unified-BOM notes line so browser-preview reflects the feature.

## Edge Cases

- Duplicate RefDes in the new file: first row wins (matches existing compare
  behavior); later duplicates are kept, flagged in Change Notes, counted as
  warnings.
- Multi-RefDes backbone rows (grouping file as the newer file): status is
  the most severe across the row's tokens — `Changed` if any token changed,
  `Added` only if all tokens are new; Change Notes list per-token details.
- Old file has BOTH a bare row and suffix rows for the same base while the
  new file has only the bare row: the bare rows match normally (conflict
  rule applies), but supersession still wins — the new bare row is marked
  `Superseded` and the suffix rows are carried; notes mention both facts.
- Empty old or new frame: sheet still writes headers plus whatever side
  exists.
- NaN guards (`pd.notna`) before all string operations on cells (project
  invariant).
- Cancellation: merge runs under the existing `_CancelBridge`; cancel checks
  before the sheet write and before promote (existing pattern).

## Testing & Docs

- New `backend/tests/test_unified_bom.py`: column union/order, new-wins +
  blank-keep, uniform-column rule, suffix + pin carry-forward, superseded
  bare-row marking, inline deletion placement, statuses, Source values with
  and without nicknames, notes wording, duplicates, NaN guards, numeric
  equivalence, styled read-back of the written tab.
- `test_bom_compare_runtime.py` additions: both option keys read in group +
  custom paths, unified tab present in output workbook, validate-time
  rejection of a bad `unified_newer_file`, extraction path ignores the keys.
- `BomCompareTool.test.tsx` additions: checkbox renders, picker appears only
  when checked, payload carries both keys, disabled in extraction mode.
- Doc counts updated in CLAUDE.md (×2), README.md, docs/TESTING.md (×2) in
  the same commit (wiring invariant #10).

## Decisions Log (from brainstorming)

1. Scope: Group + Custom modes (not Extraction Compare).
2. Direction: explicit "which file is newer" picker, default File 2.
3. Bare rows with carried suffixes: kept and marked Superseded — one
   consistent rule for pins and non-pins (supersedes the earlier
   "replace silently" answer).
4. PN mismatch on carry-forward: RefDes is source of truth; carry anyway,
   stamp the new part number via the uniform-column rule, flag it.
5. Row order: new-BOM order with deletions placed inline.
6. Output: extra tab in the compare workbook (no standalone file).
7. Implementation: shared merge module + option (no new workflow ID).
8. User additions: pins included in carry-forward; Superseded gets its own
   color (blue); Source filter column added.
