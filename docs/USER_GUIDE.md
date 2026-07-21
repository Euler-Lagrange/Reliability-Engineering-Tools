# Reliability Tools Desktop — User Guide

**Version 1.3.0**

A practical manual for reliability engineers. It assumes you know FMEA, BOM,
and failure-rate concepts but have never opened this app.

Terms used throughout: **FMEA** (Failure Mode and Effects Analysis),
**BOM** (Bill of Materials), **RefDes** (Reference Designator, e.g. `R12`),
**FMR** (Failure Mode Ratio), **PU** (Part Usage), **CB** (Circuit Block),
**PP** (Piece-Part), **HDA** (Hardware Design Assurance).

---

## 1. Overview

Reliability Tools Desktop bundles five tools behind one window. You pick a tool
in the left sidebar (or `Ctrl+1`–`Ctrl+5`, `Ctrl+[` / `Ctrl+]`, or the command
palette `Ctrl+K`). Each tool loads Excel/PDF inputs, validates them, runs a
Python engine, and writes a styled `.xlsx` report.

| Tool | What it does | Inputs |
|------|--------------|--------|
| **FMEA Generator** | Builds or merges a piece-part FMEA workbook | Grouping / BOM / Failure Modes / Functional or existing FMEA / HDA |
| **BOM Comparison Tool** | Diffs grouping-vs-BOM, two BOMs, or two extraction outputs | Two workbooks |
| **Failure Rate Integration** | Links predicted failure rates onto FMEA failure modes | Prediction workbook + FMEA workbook |
| **RefDes Extractor** | Pulls reference designators out of an annotated schematic PDF | Schematic PDF (+ optional BOM / pinlist) |
| **Settings** | Themes, logs, backend health, RefDes prefix editor | — |

### Concepts common to every tool

- **Workflow and numbered setup sections.** The first section offers the
  workflow/mode choices. The rest of the numbered setup flow (inputs, mapping,
  and options) changes with your pick, and the 48 px topbar shows the active
  tool's current **Mode**.
- **Input rows with required markers.** Each 44 px row has a Browse button and
  (for Excel) a sheet dropdown. Required inputs carry a red `*`; the leading
  indicator changes from a hollow ring, to an active dot, to a green check when
  loaded. The app never seeds example paths into a real desktop run — empty
  required rows block the run rather than run against a fake path.
- **Column mapping.** Where a tool must find columns (RefDes, FMR, etc.), a
  mapping table pairs each canonical field with a dropdown of the *actual*
  headers read from your file. Required rows are marked. Every dropdown includes
  **— Do Not Map —**; choosing it on a *required* field blocks the run (it will
  not silently guess). Optional rows may be left unmapped and are auto-detected.
- **Persistent Run and Validation rail.** Every analysis tool keeps a 320 px
  right rail visible: **Run** shows readiness, Start/Cancel, live progress,
  phases, and the result; **Validation** shows the current validation messages.
  Press `Ctrl+Enter` (`Cmd+Enter` on macOS) to start only when the
  visible tool is ready and focus is not in an editable control. `Ctrl+R`
  (`Cmd+R`) opens the separate Review drawer for the larger sample and run
  summary.
- **Run log and backend health.** A 30 px cross-tool log strip at the bottom of
  the shell streams status and warnings and shows the backend status/mode on
  its right edge. It is shared — a run started in one tool keeps logging while
  you look at another. Full health diagnostics remain in Settings.
- **Output folder.** Every tool has an **Output Folder** picker. Default is
  *"alongside first input"* (the folder of your first loaded file). An unusable
  chosen folder does not fail the run; it falls back to that default with a
  warning.
- **One run at a time.** Only one run can execute across the whole app. Starting
  a second while one is live shows **"Another run is active"** and blocks before
  anything is sent.

---

## 2. FMEA Generator

Builds a piece-part FMEA from your design data, or merges new piece-part rows
into an existing FMEA. Start button: **Generate FMEA**.

### 2.1 Workflows (the "Mode" card)

| Mode (card label) | When to pick it | Required inputs | Optional |
|-------------------|-----------------|-----------------|----------|
| **Merge Functional FMEA** | You have a functional-level FMEA and want it expanded to piece-part rows | Functional FMEA, BOM, Failure Modes | HDA, Grouping |
| **Merge Piece-Part FMEA** | You have an existing piece-part FMEA and want gaps filled / components unioned in | Existing FMEA, BOM, Failure Modes | HDA, Grouping |
| **Piece-Part from Grouping File** | Fresh build with the richest inputs | Grouping, BOM, Failure Modes | HDA |
| **Piece-Part from BOM Only** | Minimal build — just a BOM + failure modes under one CCA | BOM, Failure Modes (**+ CCA Identifier**) | HDA |

The two **Merge** modes are the only ones that show and use the effect columns
(Local / Next Higher / End Effect) and that require **Failure Mode Causes**.

### 2.2 Setup controls

- **Failure Modes Standard** — toggle **FMD-91** / **FMD-2016**. This drives the
  commodity-type labels used in mapping and failure-mode lookups. Switching it
  keeps any manual commodity-type mappings you made.
- **HDA source** — **Inline in BOM** (HDA taxonomy columns live in the BOM;
  default) or **Separate HDA file** (attach a dedicated HDA workbook). Choosing
  Separate without attaching a file blocks the run.
- **CCA Identifier** (BOM-Only mode only, required) — the prefix for generated
  FMEA-IDs; e.g. `PSU` produces `PSU-C200-A`. Allowed: 1–8 uppercase letters,
  digits, or hyphens.

### 2.3 Output strategy

| Strategy | Behavior |
|----------|----------|
| **New Workbook** | Fresh output workbook with all generator columns and summary sheets. Simplest to review, diff, and archive. |
| **Existing Workbook (Preserve Formatting)** | Writes into a new copy of the selected FMEA workbook; the original is never the output target. Blank generated cells do not replace existing nonblank cells. Different nonblank values do replace them and are listed on `Merge Changes`. New columns are appended at the far right. See the preservation limits below. |

Fresh-workbook filenames identify the workflow:
`PiecePartFMEA_Standard_<timestamp>.xlsx` (Grouping),
`PiecePartFMEA_BomOnly_<timestamp>.xlsx` (BOM Only),
`PiecePartFMEA_FromFunctional_<timestamp>.xlsx` (Merge Functional), and
`MergedFMEA_FillGaps_<timestamp>.xlsx` (Merge Piece-Part). Preserve-formatting
copies instead retain the selected target's stem as described below.

### 2.4 Column mapping

Rows are auto-detected from your headers; override any dropdown. Help text sits
behind each row's info icon.

| Column | Required | Notes |
|--------|----------|-------|
| FMEA-ID | Yes (hidden in BOM-Only) | Group FMEA-ID prefix, e.g. `PSU-C200`; combined with RefDes + suffix per row. In BOM-Only the CCA Identifier replaces it. |
| Part Number | Yes | Component identifier used for BOM/FMEA joins. It is auto-detected when possible, but a missing mapping or **— Do Not Map —** selection blocks every workflow. |
| Failure Mode Causes | Merge modes | Root-cause text. On circuit-block rows, a comma-separated RefDes list defines group membership. |
| Component Part Description | No | Human-readable part description; derived from the BOM if unmapped. |
| BAE HDA Commodity Level 1 / 2 | No | Commodity classification used for failure-mode lookup. |
| FMD-91/FMD-2016 Commodity Type 1 / 2 | No | Standard-specific type for failure-rate lookup. Label tracks the active standard. |
| Failure Mode | Yes | The mode being analyzed (Open, Short, Drift…). Cannot generate without it. |
| Failure Mode Ratio | Yes | Fraction of the failure rate for this mode (e.g. `0.43`). |
| Part Usage | No | Times the part appears. **Leave unmapped to auto-count.** If you map it and it disagrees with the computed count, the row is highlighted and flagged — see below. |
| FMEA Level | Derived | Not mappable. Header rows get `Circuit Block`; component rows get `Piece Part`. |
| Local / Next Higher / End Effect | No (merge only) | Component rows can inherit generated circuit-block effects. During Preserve Formatting, a generated blank leaves existing text unchanged; a different nonblank value replaces it and is audited on `Merge Changes`. |

### 2.5 Output workbook

**Main "FMEA" sheet.** One row per failure mode. Row shading tells you the row
type: **Circuit Block** header rows (grey), **Piece Part** rows, **yellow** rows
that carry an FMR/Part-Usage validation flag, and **red** rows that matched no
failure mode. The Part Usage column is written as a fraction (e.g. `1/3`).

**Diagnostic sheets** appear only when they have content. Both output strategies
emit the same common diagnostics (preserve-formatting no longer drops them);
the merge audit sheets are preserve-only and are labeled below.

| Sheet | Meaning |
|-------|---------|
| `No_Matches` | RefDes with no failure-mode match (RefDes, PN, Reason). |
| `Missing_HDA` | Components with no HDA commodity found. |
| `Group_Missing_BOM` | Grouped RefDes absent from the BOM. |
| `BOM_Missing_Refs` | BOM rows whose RefDes cell could not be read. |
| `BOM_Duplicate_Refs` | RefDes appearing more than once in the BOM. |
| `Validation_Warnings` | FMR-sum and Part-Usage issues, each with a plain-language **Reason Code** (see table below). |
| `FMEA Gen New RefDes` | RefDes variants found in the source but not in the BOM, whose data was inherited from a matching base component. Columns: RefDes, Base RefDes, Usage, Part Number, Part Description, HDA/FMD commodities, Source Workflow, Notes. **The sheet banner says to review and copy these into your BOM.** |
| `Part Usage Diagnostics` | Rows where the mapped BOM Part Usage disagrees with the count the generator computed. Columns: RefDes, **Mapped Count**, **Computed Count**, **Diff** (Computed − Mapped). Banner explains: Mapped Count = `round(1 / usage)`. |
| `Merge Changes` *(preserve only)* | Audit of each nonblank replacement: Excel row, RefDes, FMEA-ID, column, previous value, and new value. |
| `Template_Merge_Issues` *(preserve only)* | Merge review items. Reason codes include `AMBIGUOUS_IDENTITY`, `NOT_REBASED_FEATURES`, `SHEET_NAME_CONFLICT`, and `DUPLICATE_TEMPLATE_HEADER`. |

**Preserve-Formatting merge rules and limits:**

- The original workbook is read as a template and remains unchanged. Output is
  a new `<target>_Merged_<timestamp>.xlsx` copy. If that name exists, the tool
  tries ` (2)` through ` (99)` instead of replacing an earlier output.
- Blank generated values never overwrite an existing nonblank cell. Numeric
  equivalents such as `1.0` and `"1"` are treated as unchanged. A genuinely
  different nonblank value overwrites the copied cell and is recorded on
  `Merge Changes`.
- Row identity is never guessed. Ambiguous matches are flagged; normalized
  group-ID collisions, an unrecognizable header row, and missing identity
  columns block output before workbook mutation. Duplicate header labels warn,
  record `DUPLICATE_TEMPLATE_HEADER`, and use the last physical column.
- Existing columns are not reordered. New generator columns are appended at
  the far right. Inserted rows copy each column's own piece-part style. Merged
  ranges and custom row dimensions are rebased around inserted rows.
- Data-validation, conditional-formatting, table, formula, and hyperlink
  references below an insertion are **not rebased**. The run warns and writes a
  `NOT_REBASED_FEATURES` review item when these features are present.
- Cell-level rich-text runs are flattened to plain text. Images and shapes are
  dropped with a warning; review all drawings and charts in the output.
- A protected sheet is modified without its password after a warning in the
  analysis card and run log.
- `Template_Merge_Summary` counts matched/unmatched/new groups and
  updated/inserted/flagged rows, with a legend for the diagnostic flags below.
- In the merged sheet, the Diagnostic column may read:
  - **`NOT IN BOM - Review`** — this template row has no matching generated row;
    its RefDes is absent from the current BOM. Verify the part, then update the
    BOM or remove the stale row.
  - **`NEW - Added by generator`** — inserted for a RefDes present in the
    BOM/grouping data but missing from the template.

**Reason-code labels** (Validation_Warnings and Part Usage flags):

| You will read… | It means |
|----------------|----------|
| Part Usage Could Not Be Determined (No Instance Count Source) | Usage left **blank** because nothing could supply an instance count. Not defaulted to 1. |
| Part Usage Parse Failed and Was Replaced With the Instance Count (1/N) | The mapped usage value was unreadable; the generator substituted its own `1/N` count. |
| Part Usage Expected Value Mismatch *(…/Basic Validation/Inherited Variant)* | Mapped usage differs from the computed instance count. |
| Part Usage Value Above 1.0 / Is Zero or Negative | Usage outside the valid `0 < x ≤ 1` range. |
| Part Usage Inconsistent Across Duplicate Rows | The same RefDes carries different usage values. |
| Failure Mode Ratio Sum Mismatch | A part's FMRs do not sum to 1.0. |
| Failure Mode Ratio Missing for Piece-Part Rows | A PP row has no FMR. |
| Failure Mode Ratio and Part Usage Product Mismatch | `FMR × PU` does not reconcile. |
| Scope Mismatch: Circuit Block Only / Piece-Part Only / Unclassified Row Type Only | A RefDes was classified into only one scope where both were expected. |

### 2.6 What blocks a run

| Message | Fix |
|---------|-----|
| `Select required files: …` | Load the named input cards. |
| `Load current files and sheets for: …` | A file is picked but its sheet is not resolved yet. |
| `Missing required mappings: …` | Map the named required column(s). |
| `Required mappings cannot use 'Do Not Map': …` | A required column is set to — Do Not Map —. Pick a real column. |
| `Select FMD-91 or FMD-2016 before running.` | Choose a Failure Modes Standard. |
| `Enter a CCA identifier in the Workflow card before running BOM-Only mode.` | Fill the CCA Identifier field. |
| Separate-HDA block | You chose Separate HDA file but attached none. |
| Unsupported workflow/strategy toast | The chosen mode + output-strategy combination is not supported; the toast names the combo. |

---

## 3. BOM Comparison Tool

Three comparison styles, selected in the **Run Setup** card.

| Workflow (card) | Compares | Inputs | Mapping | Options |
|-----------------|----------|--------|---------|---------|
| **Group vs BOM** | A grouping sheet against a BOM (coverage, both directions) | Grouping workbook, BOM workbook | Group / RefDes / BOM RefDes / BOM description | All |
| **Custom Compare** | Two arbitrary BOMs by RefDes key | File 1, File 2 | File 1 RefDes, File 2 RefDes | Most (see below) |
| **Extraction Compare** | Two RefDes-extraction outputs (rev A vs rev B) | Extraction A (older), Extraction B (newer) | *none* | *none* |

**Optional display names.** Every BOM Compare input row includes a Display
name field. Use it when generic roles such as "File 1" or "Grouping" would be
ambiguous (for example, `Rev A`, `Supplier BOM`, or `CPU Grouping`). A name you
enter immediately appears in the associated mapping labels and travels into
the Excel report's Summary/source labels. Leave it blank to use the standard
role label in the UI and the canonical role or file-stem fallback in the
report. Display names do not change matching or file selection.

### 3.1 Options

Checkboxes in the **Options** card:

| Label | Default | Effect |
|-------|---------|--------|
| Loose prefix base match | off | Adds fuzzy prefix base coverage. Base-RefDes matching is *always* on; this is a no-op when **Exact match** is enabled. |
| Exact match | off | Compare RefDes tokens verbatim — no base-RefDes reduction. |
| Ignore DNP rows | on | Skip Do-Not-Populate parts before comparing. |
| Check Part Usage | on | Validate Part Usage against instance counts and add a warnings sheet. |
| Check Failure Mode Ratios | off | Verify each part's ratios sum to 1.0 and add a check sheet. |
| Treat PROV as covered | on | Treat `PROV` groups as covered. **Group vs BOM only** — disabled with a hint elsewhere. |

**Extraction Compare** reads none of these; every checkbox and the mapping card
are disabled/hidden in that mode (fixed-schema group diff).

**Custom Compare — Column Value Comparison.** Below Options, a picker diffs
specific *column values* (not just RefDes presence) for RefDes in both files.
Matching headers are auto-paired once both files are inspected; each pair takes a
rule (Text / Text exact / Numeric).

### 3.2 Output workbooks

**Group vs BOM** report sheets:

| Sheet | Content |
|-------|---------|
| `Summary` | Run timestamp, file names, and counts for each category below. |
| `Missing in BOM` | Grouped RefDes not in the BOM. Reason: `Exact token missing` / `Base RefDes missing`. |
| `BOM Not Grouped` | BOM RefDes not in the grouping file. Reason: `Exact token missing in Grouping` / `Not found in Grouping`. |
| `Warnings` | Low connector coverage and description notes. |
| `Duplicates` | RefDes duplicated in Grouping or BOM, with counts. |
| `Failure Mode Ratio Errors` | RefDes whose FMRs don't sum to 1.0, with a Status. |
| `Part Usage` | Part Usage warnings with Reason Code and Reason. |

**Custom Compare** report sheets: `Summary`, `Only In <File 1>`,
`Only In <File 2>`, `Differences`, `Duplicates`, `Part Usage`,
`Failure Mode Ratio Errors`, `Scope Warnings` — the same human naming scheme
as the Group vs BOM report (before 1.1.0 these used underscore names like
`Only_In_*`).

The FMEA-aware checks (`Scope Warnings`, composite duplicate identity) switch
on when a file's *name* contains FMEA/FMECA/piece-part **or** the file's
*content* carries a validated FMEA Level column with explicit Circuit Block /
Piece-Part rows — a renamed FMEA export is still recognized. The run log
records which signal triggered.

**Extraction Compare** report sheets:

| Sheet | Content |
|-------|---------|
| `Summary` | Component counts per revision, in-both, appeared, disappeared, moved. |
| `Appeared` | Components only in the newer extraction, with their group. |
| `Disappeared` | Components only in the older extraction, with their group. |
| `Moved Groups` | Components in both but whose group changed. |

Extraction Compare strips the `(Verified)`/`(Unverified)` suffix and skips
`GROUP NOT DETECTED` rows, so a verification-state change never reads as churn.
`UNGROUPED` and `PROVISIONAL` are kept as named buckets.

### 3.3 What blocks a run

| Message | Fix |
|---------|-----|
| `Select required files: …` / `Load current files and sheets for: …` | Load both workbooks and resolve their sheets. |
| `Missing required mappings: …` | Map the named RefDes/group column(s). |
| `Grouping file: the selected sheet has no data rows. Pick the sheet that contains the component groups.` | Choose the correct grouping sheet. |
| `BOM file: the selected sheet has no data rows. Pick the sheet that contains the BOM parts.` | Choose the correct BOM sheet. |
| `Input does not look like a RefDes extraction sheet: missing the 'Group' column …` | Extraction Compare needs actual RefDes-extraction outputs. |

---

## 4. Failure Rate Integration

Links predicted component failure rates onto FMEA failure modes and allocates a
per-mode rate. Start button: **Link Rates**.

### 4.1 Inputs and mapping

| Input | Required | Carries |
|-------|----------|---------|
| Prediction workbook | Yes | RefDes and predicted failure rate |
| FMEA workbook | Yes | Failure modes to receive the rates |

| Mapping row | Required | Notes |
|-------------|----------|-------|
| Prediction: RefDes column | Yes | Key for the join. |
| Prediction: failure rate column | Yes | The predicted rate. |
| FMEA: failure mode causes | Yes | RefDes source on the FMEA side. |
| FMEA: failure mode ratio | Yes | FMR per mode. |
| FMEA: part usage | Yes | Usage per row. |
| FMEA: function column | No | Optional — enables function/circuit-block failure-rate roll-up. |

### 4.2 Options

- **Failure rate unit** — Per hour / Per million hours / Per billion hours.
- **Validate FMR sums (sum to 1.0)** — flag parts whose ratios don't total 1.0.

### 4.3 Output

The linked FMEA gains **`Mode_FR`** (per-mode rate = part rate × FMR × usage),
**`Function_FR`** (roll-up total when a Function column is mapped), and a
**`Validation_Notes`** column. The internal `Validation_RefDes` column is not
exported.

**Validation_Notes vocabulary:**

| Note | Meaning |
|------|---------|
| `RefDes not in Prediction` | No prediction row matched this RefDes. |
| `Prediction FR unparseable (treated as 0.0)` | The prediction rate cell could not be read. |
| `Part Usage missing — Mode_FR left blank; verify` | Genuine Part-Usage gap on a real-rate row. `Mode_FR` is **blank** (not overstated to 1.0). Review the usage. |
| `Invalid Usage (…, defaulted 1.0)` / `Invalid Ratio (…, defaulted 1.0)` | A malformed usage/ratio value; substituted 1.0. |
| `Failure Mode Ratio Sum … does not equal 1.0` | The part's FMRs don't sum to 1.0. |
| `Circuit-block roll-up of N piece-part row(s); …` | Informational: the block FR is the sum of its children. May add "…may be understated" when blank children were skipped. |
| `Block roll-up of N listed component(s); …` | Informational: block FR rolled up from a listed component set. |

Roll-up notes are **informational only** — they are amber, do not inflate the
warning count, and are not repeated on the Validation Warnings triage sheet.

Blocking messages mirror the shared set (`Select required files…`,
`Load current files and sheets for…`, `Missing required mappings…`,
`Required mappings cannot use 'Do Not Map'…`).

---

## 5. RefDes Extractor

Pulls reference designators out of an annotated schematic PDF and (optionally)
cross-checks them against a BOM. Start button on the Run panel.

### 5.1 Inputs

| Input | Required | Notes |
|-------|----------|-------|
| Schematic PDF | Yes | Annotated schematic with component group boxes. |
| BOM workbook | No | Enables the BOM cross-check and coverage sheets. |
| Pinlist file | No | Piece-part pin qualification. Pin data usually already lives in the BOM. |

### 5.2 Options

- **Extraction mode** — **Functional** groups components by schematic annotation
  boxes; **Piece-Part** additionally qualifies individual pins (uses a pinlist if
  provided).
- **Backend** — **Auto (recommended)** runs the NextGen engine and falls back to
  Legacy only on error. Force **NextGen only** / **Legacy only** for
  troubleshooting.
- **Enable geometry analysis** — use vector geometry (bodies, pins, wires) to
  qualify and parent pins. Off = annotation-text-only.
- **Adaptive geometry (smart page gating)** — run full geometry only on pages
  that need it. Requires geometry analysis (disabled otherwise).
- **Geometry batch size**, **Max pin label length**, **Provenance distance** —
  primary tuning.
- **Advanced controls** (collapsed) — geometry subprocess isolation, geometry
  batch timeout (s), checkpoint between batches, pin assignment threshold (pt),
  RefDes search radius (pt), adaptive orphan threshold / ratio / max pages, and
  pinlist-prefers-annotation, plus the per-page annotation timeout. Each has a
  hover tooltip; defaults are safe.

All 17 options are type/range-checked before the run; a bad value blocks with
`Invalid extraction option(s): …`.

### 5.3 Output workbook

**Main `RefDes Extraction` sheet** — columns: Group, Failure Mode Causes,
Component Count, Pages, Validation Notes. When a BOM is loaded, each group is
emitted as **two** rows: **`X (Verified)`** (components found in the BOM) and
**`X (Unverified)`** (components not in the BOM). Without a BOM, everything is
Unverified. `GROUP NOT DETECTED` marks an expected group missing from the
schematic.

**`Component Detail`** — per-component provenance. Columns: Component, Group,
Pages, Confidence, Source, Flags. A row 1 legend explains the **Source**
vocabulary and the **Confidence** = 0–1 heuristic score:

| Source value | Meaning |
|--------------|---------|
| `geometry` | Pin-to-body geometric match. |
| `parent-refdes` | Inherited from the parent RefDes token. |
| `box-text` | Text found inside the component outline. |
| `pinlist-cluster` | Grouped via the pin list. |
| `unqualified` | No geometric confirmation. |

The **Flags** cell reads `ambiguous (N candidates)` when the parent was chosen
among alternatives; those components also get a Validation Notes entry.

**`Orphan Pins`** — every pin dropped before output. Columns: Pin, Page, Group,
Disposition, Detail. **Disposition** values:

| Disposition | Meaning |
|-------------|---------|
| `suppressed-passive` | Dropped as a passive-component pin. |
| `pinlist-drop` / `pinlist-filtered` | Removed during pinlist qualification. |
| `excluded` | Excluded by a rule. |
| `passive-prefix` | Pin belonged to a passive-prefix token. |
| `box-contains-body` | Resolved into a containing box body. |

**BOM coverage sheets** (only when a BOM is loaded):

| Sheet | Content |
|-------|---------|
| `Coverage Summary` | Counts: BOM components, grouped, not grouped (split), extracted-not-in-BOM. |
| `BOM Not Grouped` | BOM RefDes that never landed in a real group. Columns: RefDes, Part Number, Description, **Status**, Pages. Status = `Not Extracted` (never seen on the schematic), `Extracted-Ungrouped`, or `Extracted-Provisional`. |
| `Extracted Not In BOM` | RefDes pulled off the schematic but absent from the BOM. Columns: RefDes, Group, Pages. |

**Validation Notes** on the main sheet include the sequence-gap note, a
cross-group duplicate note, the `assigned ambiguously (N candidates)` note, and
`Not found in BOM: …`.

### 5.4 What blocks a run

| Message | Fix |
|---------|-----|
| `Load required files: …` | Load the Schematic PDF (and any other required slot). |
| `PyMuPDF (fitz) is not installed. PDF extraction requires this dependency.` | Reinstall / repair the app build — the PDF engine is missing. |
| `Invalid extraction option(s): …` | Fix the flagged advanced option value. |

If the BOM fails to load, the run still completes but the result title reads
**"RefDes extraction complete - BOM cross-check FAILED"** and every component is
marked NOT IN BOM — re-run with a usable BOM.

---

## 6. Settings

| Card | What it holds |
|------|---------------|
| **Theme** | 11 themes (System, Light Precision, Dark Precision, Signal Slate, Midnight Blue, High Contrast, Synthwave, Mission Control, Kraft Paper, Forest Depth, Graphite Dawn). Selection is immediate and remembered. |
| **Logs** | The sidecar log directory (default `~/.reliability_tools/logs/`) with **Copy path** and **Open folder** buttons. |
| **Backend Diagnostics** | **Run health check** — reports backend name, protocol version, and ping latency. |
| **RefDes Prefixes** | Edit the custom RefDes prefix list. |
| **About** | App name, platform, shell version, protocol version. |

### RefDes Prefixes editor

Custom prefixes extend the IEEE-315 defaults the extractor uses to recognize
reference designators (`U7`, `R12`, …). The card lists the defaults (with a
**Show all** expander) and your custom prefixes as removable chips.

- Add a prefix in the input (**e.g. PS**) and click **Add**. Validation:
  1–5 letters A–Z. A token already in the defaults is rejected as
  "Already covered".
- Click **Save prefixes**. A note reminds you: **changes apply after the app
  restarts** (recognition patterns compile at startup).
- **Corrupt config:** if `~/.refdes_extractor_config.json` is present but
  unreadable, a warning banner appears —
  *"Your saved prefix file could not be read (invalid JSON); showing defaults.
  Saving will overwrite it."* — instead of silently resetting. If the initial
  load fails (e.g. backend still reconnecting), a **Retry** button reloads it.
- Desktop-only: the editor is inert in browser preview.

---

## 7. Troubleshooting

**Run blocked (validation).** The Start button turns the validation result into
a toast and highlighted cards. The exact sentence tells you what to fix — see
the per-tool "What blocks a run" tables above. The common family:

| Reason | Meaning |
|--------|---------|
| `Select required files: …` | A required input card is empty. |
| `Load current files and sheets for: …` | A file is picked but its sheet isn't resolved. |
| `Missing required mappings: …` | A required column is unmapped. |
| `Required mappings cannot use 'Do Not Map': …` | A required column is set to — Do Not Map —. |
| `Another run is active` | A run is live in some tool; wait for it or cancel it. |

**Backend disconnected.** The Python sidecar sends a heartbeat every 5 s; if it
stops, the app reports the disconnect (with the sidecar's last error, when
known) and auto-reconnects with backoff. A live run does not survive a full
disconnect — re-run once reconnected. You can confirm health under
**Settings → Backend Diagnostics → Run health check**.

**Crash reporting.** Unhandled Python exceptions and Rust panics write
timestamped files under `~/.reliability_tools/logs/crashes/`. Those files open
with a **review-before-sharing banner** and truncate embedded values because a
crash can echo BOM/part data — read a dump before sending it on. The Python
writer prunes the shared `crash_*.log` backlog to the newest 20 when it writes a
dump. Frontend `window.error` / unhandled-promise failures do **not** write a
disk file today; they go to `console.error` and an in-app notification.

**"N warning(s) captured in the output workbook."** A run that *succeeded* but
produced warnings shows this instead of a bare file path. It is not a failure —
the workbook was written; open it and check the diagnostic/validation sheets for
the N flagged rows.

---

## 8. FAQ

**Why is `Mode_FR` blank for some rows?**
Because Part Usage was a genuine gap (blank / unreadable, including an uncached
`=1/N` formula cell) on a row that *does* have a real predicted rate. The tool
leaves `Mode_FR` blank and flags it rather than overstating it as `× 1.0`. Fill
in the usage and re-run. The Validation Note reads
*"Part Usage missing — Mode_FR left blank; verify"*.

**Why did my RefDes group come out `(Unverified)`?**
A group splits into `(Verified)` / `(Unverified)` by whether each component was
found in the loaded BOM. If you ran without a BOM, *everything* is Unverified. If
you loaded a BOM but the result title says "BOM cross-check FAILED", the BOM
didn't load (bad sheet or no recognizable RefDes column) — fix the BOM input and
re-run.

**What does a roll-up note in Failure Rate mean?**
It is informational, not a warning. A circuit/function block's failure rate is
the **sum of its children's `Mode_FR`**. The note records how many rows rolled
up. If it adds "…may be understated," some children had blank usage and were
skipped from the sum — verify those parts.

**Why did a hyphenated designator become a pin, not a range?**
In RefDes extraction a hyphen denotes a *pin*, not a range: a pinlist entry like
`U92-2` means component `U92`, pin `2`. The extractor never expands `U92-2` into
`U92 … U2`. (Page-range parsing, e.g. for the pinlist's own page column, is a
separate mechanism.)

**Where do my outputs go?**
To the **Output Folder** you set, or — by default — the folder of your first
loaded input. If the chosen folder is unwritable, the run saves next to the first
input and logs a warning.

**Do settings changes apply immediately?**
Themes yes. RefDes prefix changes require an **app restart** (the recognition
patterns compile once at startup).
