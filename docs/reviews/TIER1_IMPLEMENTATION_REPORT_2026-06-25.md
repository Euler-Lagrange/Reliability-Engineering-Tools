# Tier-1 Implementation Report — for Jacob (branch `fix/tier1-data-correctness`)

> **Status (2026-06-26):** merged to `main` as commit `66e507b`; the
> `fix/tier1-data-correctness` branch no longer exists (review with
> `git show 66e507b`). The 195/226/427 counts below are the point-in-time
> snapshot from when this report was written.

## Bottom line

9 of the 11 Tier-1 items are implemented, regression-tested, and adversarially QA'd. The full verification matrix is green:

- **Backend: 195 pytest** (was 176 — +19 new tests)
- **Frontend: 226 vitest** (unchanged — all changes are backend Python)
- **Typecheck: clean** · **Sidecar self-test + security audit: clean**

The work is on branch `fix/tier1-data-correctness` (off `main` @ 9cab706), **uncommitted** — I left it in the working tree for you to review and commit yourself, since you manage your own commits. 7 source files + 4 test files changed; the 3 pre-existing modified files (lockfile + 2 Tauri schemas — whitespace only) are untouched and not part of this work.

**Important:** the QA/QC pass caught a real bug *I had introduced* — a data-loss regression — plus two other gaps. I fixed all confirmed high/medium issues and re-verified. Details in the QA section below; I'm flagging it up front because it's exactly the kind of thing you'd want to know I caught and fixed rather than shipped.

---

## What changed (the 9 implemented items)

### Failure Rate Linker — `failure_rate/failure_rate_logic.py`
- **#2 Circuit/function-block roll-up (the feature you specified).** A block row (FMEA Level = Circuit/Function Block, or a multi-RefDes cause cell) now gets its failure rate as the **sum of its piece-part children's `Mode_FR`**, associated by shared **`FMEA-ID` prefix** (`CPU-001` owns `CPU-001-R201-A`), falling back to the block's listed RefDes when there's no `FMEA-ID` column. Block rows are **excluded from the `Function_FR` total** so part rates aren't double-counted. Reused the existing `common/fmea_utils.classify_fmea_rows` that BOM Compare already uses.
- **#8 Multi-RefDes cause cells** — handled by the same change (those cells *are* block rows; they now roll up instead of silently linking only the first RefDes).
- **#3 Silent prediction-FR `0.0`** — a non-numeric Failure Rate cell (`TBD`, `1.2 FIT`, a formula string, **or `inf`**) is now coerced to `0.0` **and flagged** in `Validation_Notes` + a log warning, instead of looking like a real zero-rate link.

### BOM Compare — `bom_compare/group_analysis.py`, `bom_compare/custom_compare.py`
- **#6 NaN/non-numeric ratio in the FMR check.** A blank ratio is now **skipped** (it no longer poisons the sum into a silent pass — the original bug); a non-numeric **text** ratio is **flagged**. Applied to both the group and custom paths.
- **#9 Loose base-match residual-digit guard.** Added `not other[len(key):].isdigit()` to the three previously-unguarded directions, so `R1` no longer falsely "covers" `R12` (a different component). `CPU`/`CPUA` (non-digit residual) still legitimately covered.

### Read layer — `common/utils.py`, `sidecar_main.py`
- **#10 Excel vs CSV NA-literal divergence.** Excel reads now use `keep_default_na=False, na_values=[""]` — literal `NA`/`N/A`/`NULL` text is preserved (was silently coerced to `NaN`, diverging from the CSV reader), while genuinely-empty cells still read as `NaN` (so no downstream `pd.notna()` guard changes behavior). Chose this surgical option over the broad one specifically to avoid blast radius.
- **#11 Duplicate header names.** `_finalize_headers` now dedupes with pandas' exact `.1`/`.2` scheme (verified byte-for-byte against `read_excel`, including the collision case where a literal `Name.1` already exists), so the mapping dropdown names match the column names the runtime binds — selecting the second `Part Number` no longer silently binds the first.

### FMEA Generator — `fmea/fmea_generator_logic.py`
- **#7 fill_gaps `1/1` guidance.** When there's no instance-count source (fill_gaps without a grouping file), the inherited `1/1` usage is now emitted **with a review note** ("best guess… verify") in the BOM_Additions sheet, instead of silently asserting single-instance usage. The stale comment claiming this path was unreachable was corrected.

### RefDes Extractor — `refdes_extractor/runtime.py`
- **#4 BOM load failure.** Per your choice, the run still continues, but a BOM-load failure now surfaces **prominently** — a `BOM cross-check FAILED` result title and a leading result note — instead of one easy-to-miss log line while every component is silently marked NOT IN BOM. The QA found a second silent path (a BOM that *loads but yields zero RefDes* — wrong sheet/blank column), which I also now surface the same way.

---

## The QA/QC pass — what it found and how I handled it

I ran a 38-agent adversarial review (5 area reviewers → independent skeptic verification → completeness critic). It confirmed **bom-compare and fmea were already clean and complete**, and found issues in the others. Every confirmed high/medium item was fixed and re-tested:

### Fixed — HIGH
1. **Data-loss regression I introduced (failure-rate).** A block row with *no* matched children had its real rate **overwritten with 0.0**, and the self-check logged "OK" — so a block-only functional FMEA (a valid input) would have had every rate silently wiped. **Fixed:** a childless block is now treated as a leaf — a multi-RefDes leaf sums its listed components' λ (no phantom first-RefDes rate), a single-RefDes leaf keeps its computed rate, and leaf blocks are counted in the function total. New tests pin both.
2. **Prediction FR `inf` propagation (failure-rate).** `inf` / `1e999` slipped past the non-numeric flag and propagated as infinity into every downstream number. **Fixed:** non-finite values are now flagged and zeroed like other unparseable cells. New test.
3. **Header-dedup collision (read-layer).** My first dedup diverged from pandas (and self-duplicated) when a literal `Name.1` already existed. **Fixed:** collision-aware algorithm verified to match `read_excel` exactly. New tests.

### Fixed — MEDIUM
4. **FMR over-flagging (bom-compare).** My first FMR fix flagged a RefDes that summed to 1.0 if it had any blank continuation row. **Fixed:** blank ratios are skipped silently (the sum-check still catches genuinely short sums); only non-numeric text is flagged. Updated + added tests for both paths.
5. **`Function_FR` consistency (failure-rate).** Fixed so a function is one consistent total for all its rows even when it mixes a block+children with unrelated ungrouped piece-parts. New test.
6. **Empty-but-successful BOM load (refdes)** — surfaced as a soft failure (see #4 above).
7. **Test-coverage gaps** the QA flagged — added group-path FMR test, zero-child/inf/mixed-function failure-rate tests, header-collision tests, and the loose-match positive-branch test.

### Consciously deferred or documented (with rationale)
- **Success toast still green when BOM cross-check fails (refdes, MEDIUM).** The result-panel title and leading note do surface it, but the corner toast stays success-toned. Fixing the toast tone is a **frontend** change, so I've folded it into the deferred frontend work (with #5) rather than touch the frontend in this backend-only branch.
- **`#N/A` Excel-error sentinel (read-layer, LOW).** openpyxl nulls `#N/A` at the cell level regardless of `na_values`, so it still reads `NaN` from `.xlsx`. Left as-is — `#N/A` is a genuine Excel *error*, not user text; documented as a known limitation.
- **Broadened text preservation (read-layer, LOW/split).** `keep_default_na=False` also preserves tokens like `None`/`NULL`/`<NA>` as text. For RefDes/part/description cells that's arguably correct, it matches the CSV reader, and the RefDes BOM loader has a second guard. Kept intentionally rather than narrowing to a whitelist (which would re-diverge from CSV). **Flagging for your call.**
- **`CB`-in-description misclassification (failure-rate).** A piece-part row with "CB" in a description could be misclassified as a block by the shared classifier's row-scan fallback. The data-loss fix above **neutralizes the numeric harm** (such a row is now a leaf that keeps its rate and stays counted). The upstream classifier heuristic is pre-existing and out of Tier-1 scope.
- **RefDes runtime test for #4** needs a synthetic PDF fixture (no harness exists for `execute_run_request`); deferred as a test gap. The behavior itself is implemented; only the automated runtime test is pending.

---

## Test summary

| Suite | Before | After | New |
|---|---|---|---|
| failure-rate logic | 12 | 19 | +7 (circuit-block roll-up, leaf-block preservation, listed-RefDes fallback, prediction-FR text + inf flagging, mixed-function consistency) |
| BOM-compare logic | 21 | 26 | +5 (residual-digit guard ×2, non-numeric FMR ×2, non-digit-residual coverage) |
| FMEA phase D | 52 | 53 | +1 (fill_gaps no-count-source flagging) |
| read-layer (new file) | 0 | 6 | +6 (NA-literal parity ×2, header dedup ×4 incl. collision) |
| **Backend total** | **176** | **195** | **+19** |
| Frontend | 226 | 226 | unchanged |

Doc counts synced in `CLAUDE.md` (×2), `README.md`, and `docs/TESTING.md` (table + total → 427), per wiring invariant #10.

---

## Not done this round (and why)
- **#5 Custom BOM-Compare column picker** — you chose "build the UI." It's a net-new **frontend** feature (the backend already supports it), so I scoped it for its own focused build with a design-principles pass rather than rush a UI at the tail of this backend session. Ready to build next.
- **#1 FMEA-gen blank-usage default** — left intentional: a blank usage = 1 instance is often legitimate for single-instance parts, and flagging every one would be noise. The high-impact case (Failure Rate `Mode_FR`) already flags it. **Your call** whether you want the FMEA-gen side flagged too.

## How to review
```
git -C C:\reliability_eng_tools diff main...fix/tier1-data-correctness -- backend/ CLAUDE.md README.md docs/
```
Branch: `fix/tier1-data-correctness`. When you're happy, commit/squash it however you like. The two open questions for you: the broadened-text-preservation choice (read-layer), and whether to flag the FMEA-gen blank-usage default (#1).
```
```
