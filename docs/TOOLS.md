# Tools Guide

Plain-English reference for the five tools in Reliability Tools Desktop.
Written for reliability engineers who want to know what each tool does, what
it needs, and what it produces.

The app has one tab per tool along the 224 px left-hand rail. Every analysis
tool follows the same pattern: work through the numbered setup sections, then
use the persistent **Run** and **Validation** cards in the 320 px right rail.
Press Ctrl/Cmd+Enter to start when the visible tool is ready and focus is not
in an editable field. Progress also streams to the 30 px cross-tool log strip
at the bottom of the shell.

Domain acronyms used throughout: **FMEA** (Failure Mode and Effects Analysis),
**FMECA** (Failure Mode, Effects, and Criticality Analysis), **BOM** (Bill of
Materials), **HDA** (Hardware Design Assurance), **RefDes** (Reference
Designator).

---

## FMEA Generator

### What it does

Builds a piece-part FMEA workbook by combining a source that describes the
functional structure of the board (a grouping file, a BOM, or an existing
functional FMEA), a BOM that lists every part instance, and a failure-modes
library that gives the failure modes and their ratios for each part type.
The tool expands source rows to the piece-part level, attaches the correct
failure modes to every part, and writes an Excel workbook you can hand to a
reviewer.

### When to use it

- You have a completed grouping workbook and need to turn it into a
  piece-part FMEA for review.
- You need a fast first draft straight from the BOM before the grouping is
  finalized.
- You already have a functional FMEA and need to turn each circuit block
  into a set of piece-part rows.
- You already have an existing FMEA but parts have been added or removed and
  you need to bring it into sync with the latest BOM.

### Required inputs

- **BOM workbook** — an Excel file with one row per RefDes, listing the part
  number, description, and any other fields you want carried into the FMEA.
- **Failure Modes workbook** — a library of failure modes keyed by part type
  or part number, with the Failure Mode Ratio for each mode. Required for
  every FMEA workflow.
- **Grouping workbook** — required for the Grouping File workflow. An Excel
  file that defines functional groups and the RefDes ranges that belong to
  each group.
- **Functional FMEA workbook** — required for the Functional FMEA workflow.
  An existing functional FMEA with circuit-block rows whose RefDes column
  (e.g. `Failure Mode Causes (RefDes)`) lists the comma-separated RefDes
  for each block.

### Optional inputs

- **HDA workbook** — Hardware Design Assurance data. When provided, HDA
  fields are merged into the output rows so reviewers can see both sources
  side by side. See HDA Source Toggle below for how to supply HDA data.
- **Existing FMEA workbook** — required only for the Fill Gaps workflow.
  This is the FMEA you want to bring up to date.
- **CCA Prefix** — required only for the BOM-Only workflow. A short
  identifier (1–8 characters, matching `^[A-Z0-9][A-Z0-9-]{0,7}$`) used
  to generate FMEA IDs in the output. The field appears only when the
  `bom_only` workflow is selected.

### Workflows

Choose one before running.

- **Piece-Part from BOM Only** (`bom_only`) — a fast draft that
  skips the grouping file and builds an FMEA straight from the BOM and the
  failure-modes library. Best when the design is too early for a grouping
  file.
- **Piece-Part from Grouping File** (`piece_part_generate`) — the
  standard end-to-end workflow. Creates a piece-part FMEA from the
  circuit-block groups in a grouping workbook, combined with BOM and HDA
  data. Use this for the first full pass once grouping is stable.
- **Merge Functional FMEA** (`functional_to_piecepart`) —
  detects circuit-block rows in an existing functional FMEA, parses the
  comma-separated RefDes column on each circuit-block row, and expands them
  into piece-part rows beneath each block. The original functional rows are
  preserved as-is.
- **Merge Piece-Part FMEA** (`fill_gaps`) — takes an existing functional or
  piece-part FMEA and adds piece-part rows for any BOM components that are
  missing from it. With Preserve Formatting, blank generated values leave
  existing nonblank cells alone; different nonblank values update the output
  copy and are recorded on `Merge Changes`.

### Failure Modes Standard

Every FMEA workflow exposes a **FMD-91 vs FMD-2016** radio. The default is
FMD-2016. The selected standard drives the output column headers
(`FMD-91 Commodity Type 1/2` vs `FMD-2016 Commodity Type 1/2`), and if the
failure modes file has a `Standard` column, the tool uses it to filter the
library down to the matching standard.

### Output strategies

- **New Workbook** (`new_workbook_standard`) — writes a fresh workbook with
  all generator columns and summary sheets. Good for first-time generation.
- **Existing Workbook (Preserve Formatting)**
  (`existing_workbook_preserve_formatting`) — reads the selected functional or
  piece-part FMEA as a template and writes a separate merged copy. The original
  is never the output target. New columns are appended at the far right; known
  preservation limits are warned and listed below. This is the default strategy
  for the Fill Gaps workflow.

### HDA Source Toggle

When the workflow requires HDA data, you can choose between two modes:

- **Inline** — HDA data is embedded in the BOM file itself (the BOM columns
  include the HDA fields). No separate HDA input is needed.
- **Separate** — HDA data lives in a dedicated HDA workbook. When this mode
  is selected, an additional HDA file input slot appears so you can pick the
  standalone HDA file.

### Output Directory

By default the generated workbook is written to the same folder as the first
input file. You can override this by clicking the output directory picker,
which opens the OS folder dialog. The selected directory persists across tab
switches and app reloads.

New-workbook filenames expose the selected workflow:
`PiecePartFMEA_Standard_<timestamp>.xlsx`,
`PiecePartFMEA_BomOnly_<timestamp>.xlsx`,
`PiecePartFMEA_FromFunctional_<timestamp>.xlsx`, or
`MergedFMEA_FillGaps_<timestamp>.xlsx`. Preserve-formatting copies retain the
selected target's stem and use the collision-safe naming described below.

### Column Mapping Bulk Actions

The mapping table supports bulk operations alongside per-row dropdowns:

- **Part Number** — required in every FMEA workflow. An unresolved mapping or
  **— Do Not Map —** selection blocks validation instead of guessing.
- **Apply all suggestions** — auto-fills every mapping row with the
  backend's suggested column match from `inspect_input`.
- **Clear all mappings** — resets all mapping selections to empty.
- **Per-row help panels** — expand a row to see the column description and
  the kind of content the backend expects.

### Preserve-formatting safety and limits

- Blank generated values never overwrite existing nonblank cells. Numeric
  equivalents such as `1.0` and `"1"` count as unchanged. Every genuinely
  different nonblank replacement is written to `Merge Changes` with Excel row,
  RefDes, FMEA-ID, column, previous value, and new value.
- Row identity is never guessed. Ambiguity is reported; group-ID collisions and
  an unrecognizable header row or missing identity columns block output.
  Duplicate header labels warn, record `DUPLICATE_TEMPLATE_HEADER`, and use the
  last physical column.
- Existing columns stay in place and inserted rows use per-column styles.
  Merged ranges and custom row dimensions are rebased around insertions.
- Data-validation, conditional-formatting, table, formula, and hyperlink
  references below inserted rows are not rebased; `NOT_REBASED_FEATURES` warns
  reviewers. Rich text is flattened. Images and shapes are dropped with a
  warning, and drawings/charts require review.
- Protected sheets are modified without a password after a UI and run-log
  warning. `Template_Merge_Issues` also reports `AMBIGUOUS_IDENTITY`,
  `SHEET_NAME_CONFLICT`, and `NOT_REBASED_FEATURES` when applicable.
- Outputs use `<target>_Merged_<timestamp>.xlsx`; occupied names advance through
  ` (2)` to ` (99)` rather than replacing a previous output.

### BOM Inheritance

When a grouping or functional source references a pin/variant RefDes such as
`U200-X` that does not exist in the BOM, the generator looks up the base
RefDes (`U200`) in the BOM and inherits its Part Number, Part Description,
HDA Commodity 1-2, and FMD Commodity 1-2 fields. Every inherited row is
recorded in a new **FMEA Gen New RefDes** sheet in the output workbook, listing
RefDes, Base RefDes, Usage fraction (e.g. `1/3`), Part Number, Part
Description, HDA Commodity 1-2, FMD Commodity 1-2, and Source Workflow. The
sheet has an explanatory banner at the top instructing reviewers to copy
the inherited rows into the BOM. Inherited variants do not trigger
false-positive Part Usage validation warnings.

### Output

An Excel workbook containing one row per piece-part failure mode, with every
mapped column from the BOM, HDA, and failure-modes library carried through.
The execution log records the row count, how many parts matched a failure
mode, and how many parts had no match.

The **Part Usage** column is resolved per part: an explicit, parseable value in
the BOM is used as-is; otherwise it is computed as `1/N`, where N is the number
of physical instances of the part (distinct RefDes sharing a usage-base — so a
part with five failure modes across two instances is `1/2`, not `1/5`). When the
instance count cannot be determined (no grouping/count source), the cell is left
**blank and flagged for verification** rather than defaulting to `1`, so a
multi-instance part is never silently reported as single-use.

### Review drawer (⌘R / Ctrl+R)

After running Validate, open the Review drawer from the topbar (or press
⌘R / Ctrl+R) to see a sample of the source rows this tool will process.
For FMEA that's the first 20 rows of the BOM workbook (or the functional
FMEA when the workflow is Merge Functional FMEA), mapped to
`RefDes / Part Number / Description` columns. Previews are capped at
20 rows and are skipped for source files larger than 10 MB.

### Limitations

- Fill Gaps can update an existing copied row when a generated nonblank value
  genuinely differs; inspect `Merge Changes` for every such replacement.
- Parts that are in the BOM but have no entry in the failure-modes library
  are reported as no-match and listed in the run summary.
- Preserve Formatting fails closed when it cannot identify the header row or
  the RefDes and Failure Mode identity columns. Unmapped generator columns are
  appended at the far right.

---

## BOM Compare

> Labeled **BOM Comparison Tool** in the app rail. Backend workflow IDs are
> `bom_compare_group`, `bom_compare_custom`, and `extraction_compare`.

### What it does

Compares two files and reports what is missing, extra, or mismatched. It has
three workflows: grouping coverage against a BOM, a generic delta between two
BOM-like files, and a fixed-schema comparison of two RefDes extraction
outputs.

### When to use it

- You want to verify that every RefDes in the BOM is covered by at least one
  functional group in the grouping workbook.
- You need to see what changed between two BOM revisions.
- You need to verify that an FMEA still matches the BOM it was derived from.

### Workflows

- **Group vs BOM** — checks whether every RefDes in the BOM is referenced in
  the grouping workbook, and whether every RefDes in the grouping workbook
  exists in the BOM.
- **Custom Compare** — generic delta between two files. Works on two BOMs,
  two FMEAs, or a BOM and an FMEA.
- **Extraction Compare** — diffs two RefDes-extraction output workbooks
  (rev A vs rev B of a schematic) and reports which components **appeared**,
  which **disappeared**, and which **moved** to a different group. Group
  identity ignores the `(Verified)`/`(Unverified)` split and skips
  `GROUP NOT DETECTED` gap rows, so verification-state changes and missing
  pages never read as false churn. UNGROUPED / PROVISIONAL are treated as
  named buckets — a component leaving UNGROUPED for a real group shows up as
  a move. This workflow has no column mapping (the extraction sheet schema is
  fixed) and no comparison options.

### Required inputs

- **Group vs BOM** — a grouping workbook and a BOM workbook.
- **Custom Compare** — any two Excel files with a RefDes column.
- **Extraction Compare** — two RefDes Extractor output workbooks (the sheet
  must carry the `Group` and `Failure Mode Causes` columns).

### Column mapping

The app auto-detects the RefDes column, the part number column, and other
common fields by matching header names against a synonym dictionary. If a
column is not detected, you can map it manually from a dropdown next to each
field.

Each input row also has an optional **Display name**. A typed name (for
example, `Rev A`, `Supplier BOM`, or `CPU Grouping`) replaces generic role
text in that file's mapping labels and flows into the Excel report's Summary
and source labels. Leave it blank to keep the normal role label in the UI and
the canonical role/file-stem fallback in the report. It does not change the
comparison data or matching rules.

### Output

A single Excel workbook with these sheets (any sheet with no rows is
omitted):

- **Only In \<File 1\>**, **Only In \<File 2\>** — RefDes present in one file
  but missing from the other.
- **Differences** — RefDes present in both, but with differing values in the
  columns you chose to compare. In Custom Compare a **Column Value Comparison**
  picker auto-pairs matching headers between the two files (the RefDes key is
  excluded) and lets you add/remove pairs and set a per-pair rule (Text / Text
  exact / Numeric). With no pair configured, Custom Compare reports RefDes
  presence/absence only.
- **Duplicates** — RefDes that appear more than once in either file, with the
  source file named per row.
- **Part Usage** — when the files carry Part Usage values, this sheet flags
  any RefDes whose Part Usage does not match the instance count. Each row
  names its **Source** file, and usage is additionally cross-checked against
  the *other* file's unique-instance count: a usage of `1/N` must agree with
  the instance count in **both** compared files. Disagreements surface as
  `PU_COUNT_MATCHES_THIS_FILE_ONLY`, `PU_COUNT_MATCHES_OTHER_FILE_ONLY`, or
  `PU_CROSS_COUNT_CONFLICT` reason codes (bases absent from one file's
  membership are skipped, not flagged).
- **Failure Mode Ratio Errors** — with the Check Failure Mode Ratios option,
  RefDes whose ratios don't sum to 1.0 (same sheet name as the group report).
  The check follows the strict FMR column (`Failure Mode Ratio` and close
  synonyms — a generic `Percentage` column never matches) to whichever file
  carries it, scanning both inputs, and each row names its **Source** file.
  When neither file has an FMR column the sheet says so in plain language
  instead of erroring.
- **Scope Warnings** — FMEA-aware sanity checks. Only populated when the
  comparison involves FMEA-like content. See below.

Extraction Compare writes its own four-sheet report instead
(`ExtractionCompare_<timestamp>.xlsx`): **Summary** (counts), **Appeared**,
**Disappeared**, and **Moved Groups** (component, group in rev A, group in
rev B).

### FMEA-aware mode

A file enters FMEA-aware mode through either signal: its *filename* looks
like an FMEA or FMECA (contains `FMEA`, `FMECA`, or `piecepart`) and the row
content supports it, **or** — regardless of the filename — its *content*
carries a validated FMEA Level column with explicit Circuit Block /
Piece-Part rows, so a renamed FMEA export is still recognized. The run log
records which signal triggered. When active, the comparison switches on a
few extra checks:

- Circuit-Block vs Piece-Part scope warnings — flags RefDes that only appear
  in Circuit Block rows, only in Piece-Part rows, or outside both.
- Composite duplicate detection — treats duplicates as a combination of
  RefDes plus FMEA ID plus Failure Mode, so the same RefDes with different
  failure modes does not trip a false duplicate.

### Review drawer (⌘R / Ctrl+R)

After running Validate, open the Review drawer from the topbar (or press
⌘R / Ctrl+R) to see a sample of the primary BOM's first 20 rows mapped to
`RefDes / Part Number / Description` columns. It's a quick sanity check
that the tool parsed the workbook you expected. Previews are capped at
20 rows and skipped for files larger than 10 MB.

### Limitations

- Comparisons are cell-value based. Formatting and formulas are ignored.
- The Custom Compare workflow does not understand semantic equivalences (for
  example, `C-1206-0.1UF` vs `0.1UF 1206 CAP`). If your BOMs use different
  part number conventions, clean them up first.
- The display table in the UI is limited to the first 100 rows per category;
  the full result is always available in the Excel output.

---

## Failure Rate

> Labeled **Failure Rate Integration** in the app rail. Backend workflow ID
> is still `failure_rate_link`.

### What it does

Links prediction failure rates to FMEA failure modes. You supply a prediction
workbook (with per-RefDes failure rates) and an FMEA workbook (with RefDes,
failure-mode causes, Failure Mode Ratio, and Part Usage). The tool matches
them by RefDes and writes a merged workbook with a Mode_FR column showing
the failure rate for every failure mode.

### When to use it

- You have a reliability prediction (per RefDes) and an FMEA (per failure
  mode) and need a workbook that ties the two together.
- You want to verify that the Failure Mode Ratios in your FMEA sum to 1.0
  per instance.

### Required inputs

- **Prediction workbook** — one row per RefDes with a numeric failure rate.
- **FMEA workbook** — one row per failure mode, with RefDes, the cause
  column, the Failure Mode Ratio, and the Part Usage.

### Column mapping

You map six columns in total. Five are required:

| Mapping | What it is |
|---------|------------|
| `pred_ref` | RefDes column in the prediction workbook |
| `pred_fr` | Failure rate column in the prediction workbook |
| `fmea_cause` | Cause column in the FMEA workbook |
| `fmea_ratio` | Failure Mode Ratio column in the FMEA workbook |
| `fmea_usage` | Part Usage column in the FMEA workbook |

One is optional:

| Mapping | What it is |
|---------|------------|
| `fmea_func` | Functional identifier column in the FMEA workbook |

### Options

- **Unit mode** — tells the tool what unit the prediction failure rate is in.
  Three choices:
  - **Per hour** — the raw value is used as-is.
  - **Per million hours** — the value is divided by 1,000,000.
  - **Per billion hours** — the value is divided by 1,000,000,000.
- **Validate Failure Mode Ratio sums** — when enabled, the tool checks that
  the sum of all Failure Mode Ratios per RefDes instance equals 1.0 within a
  tolerance of 0.1 percent. Rows where the sum is off are listed in the run
  summary so you can fix the FMEA before shipping.

### Output

A merged Excel workbook containing every row from the FMEA with a new
Mode_FR column (the failure rate for that specific failure mode, computed as
prediction failure rate times Failure Mode Ratio times Part Usage). If the
Failure Mode Ratio validator is on, a warnings sheet lists any instances
where the sums are out of tolerance.

When a row's Part Usage is a genuine gap — blank, or an uncached `=1/N` formula
cell that reads as no value — on a part that has a real failure rate, `Mode_FR`
is left **blank** (not defaulted to `1.0`, which would overstate it) and the row
is flagged in `Validation_Notes`. Circuit-block roll-ups skip such blank
children and note that the block failure rate may be understated.

### Review drawer (⌘R / Ctrl+R)

After running Validate, open the Review drawer from the topbar (or press
⌘R / Ctrl+R) to see a sample of the prediction workbook's first 20 rows
mapped to `RefDes / Failure Rate / Description` columns. The sample
previews the FR values about to be merged into the FMEA. Previews are
capped at 20 rows and skipped for files larger than 10 MB.

### Limitations

- The tool matches by RefDes only. If your prediction uses a different
  naming convention than your FMEA (for example, `R1` vs `R-1`), normalize
  the names first.
- The computation assumes one prediction failure rate per RefDes. Multiple
  predictions for the same RefDes are not merged.

---

## RefDes Extractor

### What it does

Reads an annotated schematic PDF and pulls out every Reference Designator it
finds, grouped by the functional blocks drawn on the schematic. Supports a
functional mode (RefDes only) and a piece-part mode (RefDes plus pins). It
can also verify the extracted list against a BOM.

### When to use it

- You need to build a grouping file from a schematic PDF without typing
  every RefDes by hand.
- You need to check whether a schematic covers every RefDes in the BOM.
- You are working on a piece-part FMEA and need a pin-level RefDes list.

### Required inputs

- **Schematic PDF** — an annotated schematic. Works best when functional
  groups are visibly outlined or boxed on the page.

### Optional inputs

- **BOM workbook** — used to cross-check the extracted RefDes against a known
  part list. When provided, the run adds three coverage sheets — **Coverage
  Summary**, **BOM Not Grouped**, and **Extracted Not In BOM** — reconciling the
  extracted RefDes against the BOM (the run summary also reports verified /
  unverified group counts).
- **Pinlist file** — always optional; the picker only appears in Piece-Part
  mode. Piece-part pin data is usually already in the BOM, so a separate
  pinlist is rarely needed. A CSV or single-column list of `RefDes-Pin` pairs
  (for example, `U1-3`, `J2-10`).

### Extraction modes

- **Functional** — extracts RefDes only. Good for building a grouping file.
- **Piece-Part** — extracts RefDes plus pin information by combining the
  PDF annotations with your pinlist. Good for piece-part FMEAs where
  failure modes are pin-specific.

### Backend routing

The tool has two internal extraction engines: NextGen (the newer engine with
adaptive geometry analysis) and Legacy (the original rule-based engine).
Choose:

- **Auto** — the default. Runs NextGen first; Legacy is used only as an
  exception fallback if NextGen fails.
- **NextGen only** — force the newer engine. Use this if you hit an edge
  case where Legacy returns noisy results.
- **Legacy only** — force the older engine. Use this for documents that
  were known to work well with the legacy path before NextGen was added.

### Options

- **Geometry analysis** — when on, the tool looks at the drawn shapes on
  each page (boxes, rectangles, lines) to figure out which RefDes belong to
  which functional group. When off, grouping falls back to text proximity
  only.
- **Adaptive geometry** — runs full geometry analysis only on the pages that
  need it (those left with many unqualified pins), instead of every page —
  faster on large documents.
- **Batch size** — how many pages the geometry engine processes at once.
  Default is 10. Lower this if you run into memory issues on very dense
  schematics.
- **Max pin label length** — the maximum number of characters a pin label
  can have before it is treated as noise. Default is 4.
- **PROV distance** — the maximum distance (in PDF points) that a pin label
  can sit from its RefDes and still be attached to it.
- **Advanced controls** — a collapsed section exposing the remaining engine
  tuning parameters (geometry subprocess / batch timeout / checkpoint,
  pin-assignment threshold, RefDes search radius, the adaptive-orphan
  thresholds, pinlist-prefers-annotation, and the per-page annotation timeout).
  Defaults are tuned for typical schematics; each control has a hover tooltip
  explaining what it does, and all 17 options are type/range-validated at run
  time.

### Output

A styled Excel workbook (Aptos Narrow, frozen header row, auto-filter,
content-sized columns, zebra banding) containing:

- **Groups sheet** — one row per functional group, with the group name, the
  page it appeared on, and a comma-separated list of RefDes.
- **Failure Mode Cause column** — a pre-formatted list of RefDes suitable
  for pasting into the FMEA as a failure-mode cause.
- **Component counts** — per-group and total RefDes counts.
- **Page index** — which PDF page each group was extracted from.
- **Validation Notes column** — extraction-quality reason notes with row
  highlighting: a component landing in a second (third, …) group gets an
  ordinal note naming where it was first seen (amber row), populated
  Unverified rows get an explicit "Not found in BOM: …" note (grey row),
  and sequence-gap placeholder rows are explained (yellow row).

When the default NextGen engine runs, two diagnostics sheets are also
written (they are omitted on a legacy-engine fallback, which does not
collect diagnostics):

- **Component Detail** — one row per extracted component: its group, every
  page it was seen on, the geometry engine's pin-assignment confidence where
  a pin mapping was chosen, the assignment source (`geometry`,
  `pinlist-cluster`, `parent-refdes`, `box-text`, `unqualified`), and an
  `ambiguous (N candidates)` flag when the parent was chosen among
  alternatives. Ambiguous components also get a Validation Notes entry on
  the main sheet pointing here.
- **Orphan Pins** — every pin dropped before reaching the output rows, with
  its page, group, disposition (`pinlist-filtered`, `excluded`,
  `pinlist-drop`, `suppressed-passive`, `passive-prefix`,
  `box-contains-body`), and a human-readable reason. Use this to audit why
  an expected pin is missing from a group.

When a BOM workbook is loaded, three BOM-coverage sheets are also written:

- **Coverage Summary** — counts of BOM components, how many were grouped, how
  many weren't, and how many extracted RefDes are absent from the BOM.
- **BOM Not Grouped** — BOM RefDes that didn't land in a clean group, each
  tagged Not Extracted / Extracted-Ungrouped / Extracted-Provisional and
  enriched with the BOM's Part Number and Description.
- **Extracted Not In BOM** — RefDes pulled off the schematic that are not in the
  BOM.

### Review drawer (⌘R / Ctrl+R)

After running Validate, open the Review drawer from the topbar (or press
⌘R / Ctrl+R) to see a sample of the optional BOM workbook — the first 20
rows mapped to `RefDes / Part Number / Description` columns. This helps
confirm the extractor will be validated against the expected designators.
No preview is shown when no BOM is provided (previewing the PDF itself
would require running the extractor). Previews are capped at 20 rows and
skipped for files larger than 10 MB.

### Limitations

- Extraction quality depends heavily on how the PDF was produced. Raster
  (scanned) PDFs do not work — the engine needs embedded text.
- Hand-drawn annotations and rotated text are not always recognized.
- Piece-Part pin qualification works from the PDF geometry; an optional
  pinlist can refine it but is not required (piece-part data usually comes
  from the BOM).

---

## Settings

### What it does

Central place for theme, backend health, and application info. This tab
does not produce files or run any analysis.

### Sections

- **Theme selection** — choose from 10 visual themes (light and dark
  variants, plus a few color accents), plus a **System** option that follows
  your OS preference. Your selection persists between sessions.
- **Backend health check** — click the health-check button to ping the
  Python backend and confirm it responds. The result shows the backend
  version and the protocol version.
- **Connection status** — a live indicator showing whether the backend is
  connected, reconnecting, or disconnected. If it disconnects, the app
  attempts to reconnect automatically.
- **RefDes prefixes** — view the IEEE-315 default prefix list and maintain
  custom prefixes (1-5 letters) that extend it for the RefDes Extractor and
  its BOM/pinlist matching. Saved to `~/.refdes_extractor_config.json`;
  because the extraction engines compile their recognition patterns at
  startup, changes apply after the app restarts. Desktop-only (browser
  preview shows a hint instead).
- **Application info** — shows the app version and the protocol version in
  use. Useful when filing a bug report.

### When to use it

- After a fresh install, to pick a theme.
- When something feels off and you want to confirm the backend is still up.
- When asked for a version by whoever is triaging an issue.

---

## Cross-Tool Run Log

### What it does

A cross-tool run log panel is docked at the bottom of the app shell and is
visible from every tool tab. It aggregates `log`, `status`, `progress`, and
terminal events from every run in the current session, so you can start a
run in FMEA Generator, switch to the BOM Comparison Tool, and still watch the FMEA
run finish in the log.

### Features

- **Persistent across tool switches** — the log is owned by the app shell,
  not the individual tool tab, so switching tools does not reset it.
- **Filter** — toggle between "All tools" and "Current tool only" to narrow
  the log to the active tab.
- **Export** — click Export to download a `.log` snapshot of the current
  buffer.
- **Collapsible** — the header chevron collapses the panel when you need
  screen space.
- **Backend health** — the right side of the strip shows a 6 px status dot,
  backend state word, and current bridge mode. Detailed health checks remain
  under Settings.
- **Ring buffer** — the in-memory buffer holds the most recent 5000
  entries. Older lines are dropped from memory but the canonical full log
  is always written to disk under `~/.reliability_tools/logs/`.
