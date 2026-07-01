# Tools Guide

Plain-English reference for the five tools in Reliability Tools Desktop.
Written for reliability engineers who want to know what each tool does, what
it needs, and what it produces.

The app has one tab per tool along the left-hand rail. Every tool follows the
same pattern: pick your input files, map the columns if the app cannot detect
them automatically, set any options, and click **Run**. Progress appears in
the execution log at the bottom of the tab.

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

- **Generate Piece-Part from BOM Only** (`bom_only`) — a fast draft that
  skips the grouping file and builds an FMEA straight from the BOM and the
  failure-modes library. Best when the design is too early for a grouping
  file.
- **Generate Piece-Part from Grouping File** (`piece_part_generate`) — the
  standard end-to-end workflow. Creates a piece-part FMEA from the
  circuit-block groups in a grouping workbook, combined with BOM and HDA
  data. Use this for the first full pass once grouping is stable.
- **Generate Piece-Part from Functional FMEA** (`functional_to_piecepart`) —
  detects circuit-block rows in an existing functional FMEA, parses the
  comma-separated RefDes column on each circuit-block row, and expands them
  into piece-part rows beneath each block. The original functional rows are
  preserved as-is.
- **Fill Gaps (Advanced)** (`fill_gaps`) — takes an existing functional or
  piece-part FMEA and adds piece-part rows for any BOM components that are
  missing from it. Any new columns are appended at the very end of the
  sheet. All existing rows, data, formatting, fonts, and column widths are
  preserved when the preserve-formatting output strategy is used.

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
  (`existing_workbook_preserve_formatting`) — writes new piece-part rows
  directly into the selected functional or piece-part FMEA workbook. Any
  new columns are appended at the very end of the sheet. All existing rows,
  data, formatting, fonts, and column widths are preserved. This is the
  default strategy for the Fill Gaps workflow.

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

### Column Mapping Bulk Actions

The mapping table supports bulk operations alongside per-row dropdowns:

- **Apply all suggestions** — auto-fills every mapping row with the
  backend's suggested column match from `inspect_input`.
- **Clear all mappings** — resets all mapping selections to empty.
- **Per-row help panels** — expand a row to see the column description and
  the kind of content the backend expects.

### Merge Column Scope (Fill Gaps only)

When the Fill Gaps workflow is selected, a **Merge Column Scope** picker
appears with two modes:

- **Merge All Columns** (default) — every generated column is written into
  the target workbook.
- **Select Columns to Merge** — shows a checkbox list of the template
  columns detected by the analyzer. Only checked columns are written.

The scope only applies to Fill Gaps runs; switching to any other workflow
clears the column selection.

### BOM Inheritance

When a grouping or functional source references a pin/variant RefDes such as
`U200-X` that does not exist in the BOM, the generator looks up the base
RefDes (`U200`) in the BOM and inherits its Part Number, Part Description,
HDA Commodity 1-2, and FMD Commodity 1-2 fields. Every inherited row is
recorded in a new **BOM_Additions** sheet in the output workbook, listing
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
FMEA when the workflow is Merge Functional → Piece-Part), mapped to
`RefDes / Part Number / Description` columns. Previews are capped at
20 rows and are skipped for source files larger than 10 MB.

### Limitations

- Fill Gaps does not rewrite or re-score existing rows; it only adds new ones.
- Parts that are in the BOM but have no entry in the failure-modes library
  are reported as no-match and listed in the run summary.
- Existing Workbook (Preserve Formatting) requires that the template sheet
  already has the column headers you plan to use.

---

## BOM Compare

> Labeled **Cross Compare** in the app rail. Backend workflow IDs are still
> `bom_compare_group` and `bom_compare_custom`.

### What it does

Compares two files and reports what is missing, extra, or mismatched. It has
two workflows: one for checking grouping coverage against a BOM, and one for
diffing two arbitrary BOMs (or BOM-like files such as FMEAs).

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

### Required inputs

- **Group vs BOM** — a grouping workbook and a BOM workbook.
- **Custom Compare** — any two Excel files with a RefDes column.

### Column mapping

The app auto-detects the RefDes column, the part number column, and other
common fields by matching header names against a synonym dictionary. If a
column is not detected, you can map it manually from a dropdown next to each
field.

### Output

A single Excel workbook with these sheets (any sheet with no rows is
omitted):

- **Only_In_A** — RefDes present in the first file but missing from the second.
- **Only_In_B** — RefDes present in the second file but missing from the first.
- **Differences** — RefDes present in both, but with differing values in the
  columns you chose to compare. In Custom Compare a **Column Value Comparison**
  picker auto-pairs matching headers between the two files (the RefDes key is
  excluded) and lets you add/remove pairs and set a per-pair rule (Text / Text
  exact / Numeric). With no pair configured, Custom Compare reports RefDes
  presence/absence only.
- **Duplicates_A**, **Duplicates_B** — RefDes that appear more than once in
  either file.
- **Part_Usage_Warnings** — when the files carry Part Usage values, this
  sheet flags any RefDes whose Part Usage does not match the instance count.
- **Scope_Warnings** — FMEA-aware sanity checks. Only populated when the
  comparison involves FMEA-like content. See below.

### FMEA-aware mode

The tool inspects both filenames. If either file looks like an FMEA or FMECA
(for example, the filename contains `FMEA`, `FMECA`, or `piecepart`), and the
row content supports it, the comparison switches on a few extra checks:

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

- **BOM workbook** — used to verify the extracted RefDes against a known
  part list. When provided, the run summary reports matched, missing, and
  extra counts.
- **Pinlist file** — required only for Piece-Part mode. A CSV or single-
  column list of `RefDes-Pin` pairs (for example, `U1-3`, `J2-10`).

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
- **Adaptive geometry** — lets the tool try up to four progressively more
  aggressive passes of geometry analysis per page when the first pass leaves
  too many RefDes ungrouped.
- **Batch size** — how many pages the geometry engine processes at once.
  Default is 10. Lower this if you run into memory issues on very dense
  schematics.
- **Max pin label length** — the maximum number of characters a pin label
  can have before it is treated as noise. Default is 4.
- **PROV distance** — the maximum distance (in PDF points) that a pin label
  can sit from its RefDes and still be attached to it.

### Output

An Excel workbook containing:

- **Groups sheet** — one row per functional group, with the group name, the
  page it appeared on, and a comma-separated list of RefDes.
- **Failure Mode Cause column** — a pre-formatted list of RefDes suitable
  for pasting into the FMEA as a failure-mode cause.
- **Component counts** — per-group and total RefDes counts.
- **Page index** — which PDF page each group was extracted from.

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
- Piece-Part mode requires a pinlist. Without one, pin information cannot
  be reconstructed.

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
run in FMEA Generator, switch to Cross Compare, and still watch the FMEA
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
- **Ring buffer** — the in-memory buffer holds the most recent 5000
  entries. Older lines are dropped from memory but the canonical full log
  is always written to disk under `~/.reliability_tools/logs/`.
