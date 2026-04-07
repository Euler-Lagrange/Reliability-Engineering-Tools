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

Builds a piece-part FMEA workbook by combining three inputs: a grouping file
that defines the functional groups on the board, a BOM that lists every part
instance, and a failure-modes library that gives the failure modes and their
ratios for each part type. The tool expands grouping rows to the piece-part
level, attaches the correct failure modes to every part, and writes an Excel
workbook you can hand to a reviewer.

### When to use it

- You have a completed grouping workbook and need to turn it into a
  piece-part FMEA for review.
- You need a fast first draft straight from the BOM before the grouping is
  finalized.
- You already have an existing FMEA but parts have been added or removed and
  you need to bring it into sync with the latest BOM.

### Required inputs

- **Grouping workbook** — an Excel file that defines functional groups and
  the RefDes ranges that belong to each group.
- **BOM workbook** — an Excel file with one row per RefDes, listing the part
  number, description, and any other fields you want carried into the FMEA.
- **Failure Modes workbook** — a library of failure modes keyed by part type
  or part number, with the Failure Mode Ratio for each mode.

### Optional inputs

- **HDA workbook** — Hardware Design Assurance data. When provided, HDA
  fields are merged into the output rows so reviewers can see both sources
  side by side.
- **Existing FMEA workbook** — required only for the Fill Gaps workflow.
  This is the FMEA you want to bring up to date.

### Workflows

Choose one before running.

- **Generate Piece-Part** — the standard end-to-end workflow. Expands every
  grouping row down to the piece-part level, attaches failure modes from the
  library, and writes a complete workbook. Use this for the first full pass.
- **BOM-Only Generate** — a fast draft that skips the grouping file and
  builds an FMEA straight from the BOM and the failure-modes library. Useful
  early in the project before grouping is stable.
- **Fill Gaps** — takes an existing FMEA workbook and only adds rows for
  parts that are new since the last pass. Existing rows are left untouched.
  Use this to keep an FMEA in sync with BOM churn without re-reviewing
  previously signed-off content.

### Output strategies

- **New Workbook (Standard)** — writes a clean, freshly formatted Excel file.
  Good for first-time generation and for anyone who does not need to match an
  existing template.
- **Preserve Original Template** — when you point at an existing FMEA
  workbook, the tool merges the generated rows into the template while
  keeping your column widths, merged headers, freeze panes, cell formatting,
  and any conditional formatting you set up. Use this when your team has a
  locked-down FMEA template.

### Enrichment toggles

- **Functional FMEA** — adds functional-level failure-mode rows on top of
  the piece-part rows.
- **Piece-Part FMEA** — controls whether piece-part rows are expanded.

Both can be enabled together for a combined Functional and Piece-Part FMEA.

### Output

An Excel workbook containing one row per piece-part failure mode, with every
mapped column from the BOM, HDA, and failure-modes library carried through.
The execution log records the row count, how many parts matched a failure
mode, and how many parts had no match.

### Limitations

- Fill Gaps does not rewrite or re-score existing rows; it only adds new ones.
- Parts that are in the BOM but have no entry in the failure-modes library
  are reported as no-match and listed in the run summary.
- Preserve Original Template requires that the template sheet already has
  the column headers you plan to use.

---

## BOM Compare

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
- **Differences** — RefDes present in both, but with differing field values
  (for example, part number or description).
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

### Limitations

- Comparisons are cell-value based. Formatting and formulas are ignored.
- The Custom Compare workflow does not understand semantic equivalences (for
  example, `C-1206-0.1UF` vs `0.1UF 1206 CAP`). If your BOMs use different
  part number conventions, clean them up first.
- The display table in the UI is limited to the first 100 rows per category;
  the full result is always available in the Excel output.

---

## Failure Rate

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

- **Auto** — the default. The tool picks the best engine based on the PDF.
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

- **Theme selection** — choose from seven themes. Each theme has a distinct
  visual personality (light and dark variants, plus a few color accents).
  Your selection persists between sessions.
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
