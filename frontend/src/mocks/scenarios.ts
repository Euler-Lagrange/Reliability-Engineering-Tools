import type {
  ColumnMappingRow,
  DemoScenario,
  FileRole,
  InputFileState,
  OutputStrategy,
  OutputStrategyId,
  ValidationMessage,
  WorkflowId,
  WorkflowOption,
} from "../app/types";

const sheets = (labels: string[]) =>
  labels.map((label) => ({ id: label.toLowerCase().replace(/\s+/g, "_"), label }));

const baseInputs: Record<string, InputFileState> = {
  grouping: {
    role: "grouping",
    label: "Grouping workbook",
    path: "DRIVE\\inputs\\NavUnit_Grouping_v6.xlsx",
    helper: "Circuit-block hierarchy and partition mapping.",
    status: "ready",
    sheets: sheets(["Grouping", "Partitions"]),
    selectedSheet: "Grouping",
    tag: "Loaded",
    isExample: true,
  },
  bom: {
    role: "bom",
    label: "BOM workbook",
    path: "DRIVE\\inputs\\NavUnit_BOM_enriched.xlsx",
    helper: "Primary piece-part source with usage and part metadata.",
    status: "ready",
    sheets: sheets(["Main BOM", "Exports"]),
    selectedSheet: "Main BOM",
    tag: "Auto-detected",
    isExample: true,
  },
  hda: {
    role: "hda",
    label: "HDA workbook",
    path: "DRIVE\\inputs\\NavUnit_HDA_reference.xlsx",
    helper: "Commodity enrichment and HDA coverage support.",
    status: "ready",
    sheets: sheets(["HDA Map", "Commodity"]),
    selectedSheet: "HDA Map",
    tag: "Optional",
    isExample: true,
  },
  failureModes: {
    role: "failureModes",
    label: "Failure modes workbook",
    path: "DRIVE\\inputs\\Failure_Modes_2026.xlsx",
    helper: "Normalized failure mode library and FMR defaults.",
    status: "ready",
    sheets: sheets(["Failure Modes", "Taxonomy"]),
    selectedSheet: "Failure Modes",
    tag: "Validated",
    isExample: true,
  },
  functionalFmea: {
    role: "functionalFmea",
    label: "Functional FMEA workbook",
    path: "DRIVE\\inputs\\NavUnit_Functional_FMEA.xlsx",
    helper: "Optional effect enrichment for generated circuit-block rows.",
    status: "ready",
    sheets: sheets(["Functional FMEA"]),
    selectedSheet: "Functional FMEA",
    tag: "Enrichment",
    isExample: true,
  },
  existingFmea: {
    role: "existingFmea",
    label: "Existing FMEA workbook",
    path: "DRIVE\\inputs\\Platform_FMEA_gap_fill.xlsx",
    helper: "Source workbook inspected for unresolved piece-part gaps.",
    status: "ready",
    sheets: sheets(["Piece-Part FMEA", "Functional FMEA"]),
    selectedSheet: "Piece-Part FMEA",
    tag: "Gap source",
    isExample: true,
  },
  targetWorkbook: {
    role: "targetWorkbook",
    label: "Target workbook",
    path: "DRIVE\\targets\\Customer_FMEA_Template.xlsx",
    helper: "Shown only for existing-workbook strategies. Output still writes to a copy.",
    status: "ready",
    sheets: sheets(["Template", "FMEA Sheet"]),
    selectedSheet: "FMEA Sheet",
    tag: "Planner-ready",
    isExample: true,
  },
};

const allPrototypeInputs = [
  baseInputs.grouping,
  baseInputs.bom,
  baseInputs.hda,
  baseInputs.failureModes,
  baseInputs.functionalFmea,
  baseInputs.existingFmea,
  baseInputs.targetWorkbook,
];

// Fix F1: the pre-Phase-5 7-row FMEA mapping fixture has been removed.
// FmeaTool.tsx now builds its mapping rows from `FMEA_COLUMN_METADATA`
// (see `features/fmea/mappingColumns.ts`) instead of reading
// `scenario.mappings`, so the FMEA demo scenarios supply an empty list
// for the required `DemoScenario.mappings` field. BOM Compare and
// Failure Rate scenarios still use their own tool-specific mapping
// fixtures (`bomCompareGroupMappings`, `failureRateMappings`).

const warningHeavyMessages: ValidationMessage[] = [
  {
    id: "warn-1",
    severity: "warning",
    area: "Failure Modes",
    title: "Failure mode ratio does not sum to 1.00 for 6 parts",
    detail: "Rows with partial FM coverage were kept in preview and flagged for operator review.",
  },
  {
    id: "warn-2",
    severity: "warning",
    area: "Piece-Part Merge",
    title: "Multi-RefDes source rows were excluded from enrichment",
    detail: "The generator preserved the legacy safety rule and rejected ambiguous rows.",
  },
  {
    id: "err-1",
    severity: "warning",
    area: "Target Workbook",
    title: "Protected sheet will be modified",
    detail: "The merge writes to a copy without the sheet password; review the protected-sheet warning and output workbook.",
  },
];

/**
 * FMEA workflow options.
 *
 * Display order is deliberate (Phase 3): merge workflows first, generate
 * workflows second. The labels describe the user's mental model ("what am
 * I starting from?") rather than the legacy "workflow name" framing. The
 * backend workflow IDs are unchanged — they are a contract with
 * `fmea/runtime.py`. Only user-facing copy changes here.
 */
export const workflowOptions: WorkflowOption[] = [
  {
    id: "functional_to_piecepart",
    title: "Merge Functional FMEA",
    summary:
      "Expand a functional FMEA into piece-part rows using group-level union merge.",
    eyebrow: "Merge",
    badge: "Functional",
    badgeHint: "Starts from a functional-level FMEA source.",
    requiredRoles: ["functionalFmea", "bom", "failureModes"],
    optionalRoles: ["hda", "grouping"],
  },
  {
    id: "fill_gaps",
    title: "Merge Piece-Part FMEA",
    summary:
      "Bring forward an existing piece-part FMEA, union component lists, and fill gaps.",
    eyebrow: "Merge",
    badge: "Piece-Part",
    badgeHint: "Starts from an existing piece-part FMEA source.",
    requiredRoles: ["existingFmea", "bom", "failureModes"],
    optionalRoles: ["hda", "grouping"],
  },
  {
    id: "piece_part_generate",
    title: "Piece-Part from Grouping File",
    summary:
      "Build a new piece-part FMEA from a grouping workbook + BOM + failure modes.",
    eyebrow: "Generate",
    badge: "Balanced",
    badgeHint:
      "Full-input build: grouping workbook + BOM + failure modes give the richest output.",
    requiredRoles: ["grouping", "bom", "failureModes"],
    optionalRoles: ["hda"],
  },
  {
    id: "bom_only",
    title: "Piece-Part from BOM Only",
    summary:
      "Build a piece-part FMEA with just a BOM and failure modes. Requires a CCA prefix.",
    eyebrow: "Generate",
    badge: "Lean",
    badgeHint:
      "Minimal-input build: just a BOM + failure modes, grouped under one CCA identifier.",
    requiredRoles: ["bom", "failureModes"],
    optionalRoles: ["hda"],
  },
];

export const outputStrategies: OutputStrategy[] = [
  {
    id: "new_workbook_standard",
    title: "New Workbook",
    summary:
      "Generate a fresh output workbook with all generator columns and summary sheets. Simplest to review, diff, and archive — nothing is carried over.",
    badge: "Clean export",
  },
  {
    id: "existing_workbook_preserve_formatting",
    title: "Existing Workbook (Preserve Formatting)",
    summary:
      "Writes into a new copy of the selected FMEA. Blank generated cells keep existing text; real replacements are audited, and known workbook-feature limits are warned for review.",
    badge: "Review-aware",
  },
];

const previewRows = [
  {
    id: "p-1",
    refdes: "U14",
    failureMode: "Open circuit",
    localEffect: "Navigation card loses isolated power rail.",
    nextHigherEffect: "Guidance channel enters degraded mode.",
  },
  {
    id: "p-2",
    refdes: "C209",
    failureMode: "Capacitance drift high",
    localEffect: "Hold-up timing margin is reduced below nominal.",
    nextHigherEffect: "Warm restart sensitivity increases during transient load.",
  },
  {
    id: "p-3",
    refdes: "R882",
    failureMode: "Short circuit",
    localEffect: "Bias network collapses and downstream ADC saturates.",
    nextHigherEffect: "Mission computer flags invalid navigation telemetry.",
  },
];

const demoOutputPreview = {
  columns: ["RefDes", "Failure Mode", "Local Effect", "Next Higher Effect"],
  rows: previewRows.map((row) => [
    row.refdes,
    row.failureMode,
    row.localEffect,
    row.nextHigherEffect,
  ]),
  truncated: false,
  total_estimated: previewRows.length,
};

const successEvents = [
  {
    id: "event-1",
    title: "Resolve sheets and profile",
    detail: "Mapped workbook inputs against the selected column profile.",
    progress: 18,
    logs: [
      "Opened Grouping workbook — sheet 'Grouping' resolved.",
      "Opened BOM workbook — sheet 'Main BOM' (216 rows).",
    ],
  },
  {
    id: "event-2",
    title: "Normalize source columns",
    detail: "Applied canonical names and preserved manual overrides.",
    progress: 34,
    logs: ["Canonicalized 12 source columns (1 manual override preserved)."],
  },
  {
    id: "event-3",
    title: "Generate base rows",
    detail: "Built piece-part candidates and grouped them by canonical IDs.",
    progress: 58,
    logs: ["Generated 216 piece-part candidate rows across 34 canonical groups."],
  },
  {
    id: "event-4",
    title: "Apply enrichments",
    detail: "Copied safe effect fields from optional source FMEAs.",
    progress: 77,
    logs: ["Enriched 87 rows with effect fields from source FMEAs."],
  },
  {
    id: "event-5",
    title: "Plan workbook output",
    detail: "Prepared a formatting-preserved update plan against the selected template.",
    progress: 92,
    logs: ["Planned workbook output — 6 sheets, formatting preserved."],
  },
];

const failureEvents = [
  {
    id: "event-f1",
    title: "Resolve sheets and profile",
    detail: "Loaded target workbook metadata and planned the update scope.",
    progress: 20,
    logs: ["Opened target workbook — 6 sheets, 2 protected."],
  },
  {
    id: "event-f2",
    title: "Generate gap rows",
    detail: "Detected missing piece-part rows from the existing FMEA workbook.",
    progress: 47,
    logs: ["Detected 14 missing piece-part rows."],
  },
  {
    id: "event-f3",
    title: "Inspect workbook constraints",
    detail: "Template analysis found a protected sheet that the output copy will modify without a password.",
    progress: 71,
    logs: [
      "BLOCKED: protected sheet 'FMEA' would be modified without a password.",
    ],
  },
];

export const demoScenarios: DemoScenario[] = [
  {
    id: "piece-part-generate",
    label: "Piece-Part Generate",
    description: "Default modern flow with functional enrichment enabled and a clean new-workbook export.",
    workflowId: "piece_part_generate",
    outputStrategyId: "new_workbook_standard",
    inputs: allPrototypeInputs,
    mappings: [],
    validations: [
      {
        id: "v-1",
        severity: "info",
        area: "Preview",
        // Demo copy must describe the DEMO, not claim live state — a "92%
        // auto-mapped" chip beside a mapping table showing 10 unmapped
        // fields read as a contradiction.
        title: "Example preview seeded",
        detail:
          "Preview rows below come from the demo scenario. Live mapping status appears under Column Mapping.",
      },
    ],
    previewRows,
    outputPreview: demoOutputPreview,
    runSequence: {
      events: successEvents,
      result: {
        status: "success",
        title: "Prototype run completed",
        summary: "216 output rows were planned with one manual column review still visible in the UI.",
        // Workflow-stem contract (2026-07-20): PiecePartFMEA_* for every
        // generation workflow — MergedFMEA_* belongs to fill_gaps only.
        outputFile: "PiecePartFMEA_Standard_20260403_101200.xlsx",
        primaryMetric: "216 planned rows",
        // Must agree with the staged mapping table (10 mapped · 1 derived
        // · 1 unmapped) — a "92% auto-mapped" chip beside an unmapped
        // required row read as a contradiction.
        secondaryMetric: "10 of 12 auto-mapped",
        notes: ["No backend work was executed.", "Workbook output is illustrative only."],
      },
    },
  },
  {
    id: "fill-gaps",
    label: "Fill Gaps",
    description: "Delta-oriented scenario that reads an existing FMEA and targets only missing piece-part rows.",
    workflowId: "fill_gaps",
    outputStrategyId: "new_workbook_standard",
    inputs: allPrototypeInputs,
    mappings: [],
    validations: [
      {
        id: "v-2",
        severity: "warning",
        area: "Gap Detection",
        title: "14 missing piece-part rows detected",
        detail: "Preview is restricted to gap-generated rows and keeps circuit-block provenance notes.",
      },
    ],
    previewRows,
    runSequence: {
      events: successEvents,
      result: {
        status: "success",
        title: "Gap-fill simulation completed",
        summary: "14 missing rows were identified and merged into a new workbook plan.",
        // MergedFMEA_FillGaps_* is the fill_gaps new-workbook stem
        // (workflow-stem contract 2026-07-20; the in-app User Guide
        // documents the same names).
        outputFile: "MergedFMEA_FillGaps_20260403_103500.xlsx",
        primaryMetric: "14 gap rows",
        secondaryMetric: "2 workbook notes",
        notes: ["New-workbook merge shown.", "No file was written."],
      },
    },
  },
  {
    id: "preserve-formatting",
    label: "Preserve Formatting",
    description: "Formatting-preserved strategy with both enrichment sources enabled and template planning emphasized.",
    workflowId: "piece_part_generate",
    outputStrategyId: "existing_workbook_preserve_formatting",
    inputs: allPrototypeInputs,
    mappings: [],
    validations: [
      {
        id: "v-3",
        severity: "info",
        area: "Planner",
        title: "Workbook constraints included in merge review",
        detail: "The generator keeps the target explicit and reports features that need review after row insertion.",
      },
    ],
    previewRows,
    runSequence: {
      events: successEvents,
      result: {
        status: "success",
        title: "Formatting-preserved plan ready",
        summary: "The simulated merge wrote a reviewable workbook copy and surfaced its protected-sheet warning.",
        outputFile: "Customer_FMEA_Merged_20260403_110800.xlsx",
        primaryMetric: "1 protected sheet",
        secondaryMetric: "Changes audited",
        notes: ["Planner/executor behavior is simulated.", "The original target remains unchanged; the copy is the output."],
      },
    },
  },
  {
    id: "warning-heavy",
    label: "Warning Heavy",
    description: "Stress case for validation density, manual review, and high-visibility diagnostic messaging.",
    // Reachable slot: BOM-Only mode + Existing Workbook strategy. Every
    // fixture must map to a (workflow, strategy) pair the UI can select
    // — this one was previously shadowed by preserve-formatting.
    workflowId: "bom_only",
    outputStrategyId: "existing_workbook_preserve_formatting",
    inputs: allPrototypeInputs,
    mappings: [],
    validations: warningHeavyMessages,
    previewRows,
    runSequence: {
      events: failureEvents,
      result: {
        status: "failure",
        title: "Planner review required",
        summary: "The prototype paused after detecting a workbook region that should block automated insertion.",
        outputFile: "No output generated",
        primaryMetric: "1 blocking workbook constraint",
        secondaryMetric: "3 surfaced diagnostics",
        notes: ["This is an intentional prototype failure path.", "The UI is designed to keep the operator oriented."],
      },
    },
  },
  {
    id: "success-run",
    label: "Success Run",
    description: "Focused run-state demo that ends in a successful workbook plan summary.",
    // Reachable slot: Merge Functional mode + Existing Workbook strategy
    // (previously shadowed by preserve-formatting).
    workflowId: "functional_to_piecepart",
    outputStrategyId: "existing_workbook_preserve_formatting",
    inputs: allPrototypeInputs,
    mappings: [],
    validations: [
      {
        id: "v-4",
        severity: "info",
        area: "Run State",
        title: "Run panel is fixture-driven",
        detail: "Use this scenario to evaluate the timeline, progress, and completion summary.",
      },
    ],
    previewRows,
    runSequence: {
      events: successEvents,
      result: {
        status: "success",
        title: "Workbook plan simulation finished",
        summary: "The generator reached a review-ready state with clean completion messaging and output metadata.",
        outputFile: "Customer_FMEA_Merged_20260403_113100.xlsx",
        primaryMetric: "5 timeline stages",
        secondaryMetric: "100% run completion",
        notes: ["No backend call occurred.", "This fixture exists only to evaluate UX."],
      },
    },
  },
  {
    id: "failure-run",
    label: "Failure Run",
    description: "Focused run-state demo that ends in a planner failure and operator-facing recovery guidance.",
    workflowId: "fill_gaps",
    outputStrategyId: "existing_workbook_preserve_formatting",
    inputs: allPrototypeInputs,
    mappings: [],
    validations: warningHeavyMessages,
    previewRows,
    runSequence: {
      events: failureEvents,
      result: {
        status: "failure",
        title: "Formatting-preserved run stopped",
        summary: "Planner hit a workbook constraint and surfaced the stop reason without losing operator context.",
        outputFile: "No output generated",
        primaryMetric: "71% progress before stop",
        secondaryMetric: "Recovery path visible",
        notes: ["Failure mode is intentional.", "Use this fixture to judge the exception experience."],
      },
    },
  },
  {
    id: "functional-to-piecepart",
    label: "Merge Functional",
    description: "Functional-level FMEA expanded into piece-part rows via group-level union merge.",
    workflowId: "functional_to_piecepart",
    outputStrategyId: "new_workbook_standard",
    inputs: allPrototypeInputs,
    mappings: [],
    validations: [
      {
        id: "v-5",
        severity: "info",
        area: "Preview",
        title: "Example preview seeded",
        detail:
          "Preview rows below come from the demo scenario. Live mapping status appears under Column Mapping.",
      },
    ],
    previewRows,
    runSequence: {
      events: successEvents,
      result: {
        status: "success",
        title: "Functional expansion completed",
        summary: "Functional-level rows were expanded into piece-part rows using group-level union merge.",
        outputFile: "PiecePartFMEA_FromFunctional_20260403_104900.xlsx",
        primaryMetric: "182 planned rows",
        secondaryMetric: "24 functions expanded",
        notes: ["No backend work was executed.", "Workbook output is illustrative only."],
      },
    },
  },
  {
    id: "bom-only",
    label: "BOM Only",
    description: "Minimal piece-part build from just a BOM and failure modes under one CCA identifier.",
    workflowId: "bom_only",
    outputStrategyId: "new_workbook_standard",
    inputs: allPrototypeInputs,
    mappings: [],
    validations: [
      {
        id: "v-6",
        severity: "info",
        area: "Preview",
        title: "Example preview seeded",
        detail:
          "Preview rows below come from the demo scenario. Live mapping status appears under Column Mapping.",
      },
    ],
    previewRows,
    runSequence: {
      events: successEvents,
      result: {
        status: "success",
        title: "BOM-only build completed",
        summary: "Piece-part rows were generated for a single CCA from the BOM and failure-modes inputs.",
        outputFile: "PiecePartFMEA_BomOnly_20260403_105900.xlsx",
        primaryMetric: "148 planned rows",
        secondaryMetric: "1 CCA prefix",
        notes: [
          "FMEA-IDs use the CCA identifier you entered as their prefix.",
          "No backend work was executed.",
        ],
      },
    },
  },
];

/**
 * Resolve the FMEA demo scenario for a (workflow, output-strategy)
 * pair. Every pair the UI can select maps to exactly one fixture, so
 * the browser-mock replay shows workflow-correct events, result copy,
 * and output-filename stems (the workflow-stem contract) instead of
 * replaying `demoScenarios[0]` for every mode.
 */
export function resolveFmeaDemoScenario(
  workflowId: WorkflowId,
  outputStrategyId: OutputStrategyId,
): DemoScenario {
  return (
    demoScenarios.find(
      (scenario) =>
        scenario.workflowId === workflowId &&
        scenario.outputStrategyId === outputStrategyId,
    ) ??
    demoScenarios.find((scenario) => scenario.workflowId === workflowId) ??
    demoScenarios[0]
  );
}

export const bomCompareInputs: Record<string, InputFileState> = {
  grouping: {
    role: "grouping",
    label: "Grouping workbook",
    path: "DRIVE\\inputs\\NavUnit_Grouping.xlsx",
    helper: "Circuit-block grouping hierarchy.",
    status: "ready",
    sheets: sheets(["Grouping"]),
    selectedSheet: "Grouping",
    tag: "Loaded",
    isExample: true,
  },
  bom: {
    role: "bom",
    label: "BOM workbook",
    path: "DRIVE\\inputs\\NavUnit_BOM.xlsx",
    helper: "Bill of materials with RefDes and descriptions.",
    status: "ready",
    sheets: sheets(["Main BOM"]),
    selectedSheet: "Main BOM",
    tag: "Auto-detected",
    isExample: true,
  },
  bomA: {
    role: "bomA",
    label: "File 1",
    path: "DRIVE\\inputs\\PSU_Parts_List.xlsx",
    helper: "First BOM for comparison.",
    status: "ready",
    sheets: sheets(["Sheet1"]),
    selectedSheet: "Sheet1",
    tag: "Loaded",
    isExample: true,
  },
  bomB: {
    role: "bomB",
    label: "File 2",
    path: "DRIVE\\inputs\\PSU_FMEA.xlsx",
    helper: "Second BOM for comparison.",
    status: "ready",
    sheets: sheets(["Sheet1"]),
    selectedSheet: "Sheet1",
    tag: "Loaded",
    isExample: true,
  },
  extractionA: {
    role: "extractionA",
    label: "Extraction A (older)",
    path: "DRIVE\\outputs\\RefDesExtract_revA.xlsx",
    helper: "RefDes extraction output from the earlier schematic revision.",
    status: "ready",
    sheets: sheets(["RefDes Extraction"]),
    selectedSheet: "RefDes Extraction",
    tag: "Loaded",
    isExample: true,
  },
  extractionB: {
    role: "extractionB",
    label: "Extraction B (newer)",
    path: "DRIVE\\outputs\\RefDesExtract_revB.xlsx",
    helper: "RefDes extraction output from the newer schematic revision.",
    status: "ready",
    sheets: sheets(["RefDes Extraction"]),
    selectedSheet: "RefDes Extraction",
    tag: "Loaded",
    isExample: true,
  },
};

export const bomCompareWorkflowOptions: WorkflowOption[] = [
  {
    id: "bom_compare_group",
    title: "Group vs BOM",
    summary: "Compare grouping file against BOM to find missing and extra RefDes.",
    eyebrow: "Standard",
    badge: "Coverage",
    badgeHint: "Checks that every grouped RefDes is covered by the BOM, both directions.",
  },
  {
    id: "bom_compare_custom",
    title: "Custom Compare",
    summary: "Compare two arbitrary BOMs to find differences by RefDes key.",
    eyebrow: "Flexible",
    badge: "Delta",
    badgeHint: "Direct row-level differences between any two BOMs.",
  },
  {
    id: "extraction_compare",
    title: "Extraction Compare",
    summary: "Diff two RefDes extraction outputs: appeared, disappeared, and moved groups.",
    eyebrow: "Revision",
    badge: "Drift",
    badgeHint: "Tracks components that appeared, disappeared, or moved between schematic revisions.",
  },
];

// displayLabel = what the operator reads; canonical = the backend payload
// contract (never rename it — execute payloads and deriveMappingRows key on it).
export const bomCompareGroupMappings: ColumnMappingRow[] = [
  {
    canonical: "grouping_group_col",
    displayLabel: "Group column — Grouping file",
    mappedTo: "Component Group",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Component Group", "Group", "Circuit Block"],
    required: true,
  },
  {
    canonical: "grouping_refdes_col",
    displayLabel: "RefDes column — Grouping file",
    mappedTo: "Reference Designator",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Reference Designator", "RefDes", "Ref Des"],
    required: true,
  },
  {
    canonical: "bom_refdes_col",
    displayLabel: "RefDes column — BOM file",
    mappedTo: "Reference Designator",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Reference Designator", "RefDes", "Ref Des"],
    required: true,
  },
  {
    canonical: "bom_desc_col",
    displayLabel: "Description column — BOM file",
    mappedTo: "Description",
    status: "mapped",
    recommendation: "Optional",
    options: ["Description", "Part Description"],
  },
];

// Custom Compare example headers. These are load-bearing (Wiring Invariant
// #4/#7): they back both the mapping dropdowns and — once a file is inspected
// in the desktop app — the ColumnPairPicker's value-diff column choices. The
// two files share "Part Number", "Description", and "Quantity" headers so the
// auto-pair heuristic (case-insensitive header match, excluding the RefDes
// key) has matching pairs to seed; "Reference Designator" is the key and is
// intentionally excluded from value diffs.
export const bomCompareCustomColumns = [
  "Reference Designator",
  "Part Number",
  "Description",
  "Quantity",
];

export const bomCompareCustomMappings: ColumnMappingRow[] = [
  {
    canonical: "refdes_col_a",
    displayLabel: "RefDes column — File 1",
    mappedTo: "Reference Designator",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Reference Designator", "RefDes"],
    required: true,
  },
  {
    canonical: "refdes_col_b",
    displayLabel: "RefDes column — File 2",
    mappedTo: "Reference Designator",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Reference Designator", "RefDes"],
    required: true,
  },
];

export const bomCompareDemoScenarios: DemoScenario[] = [
  {
    id: "bom-compare-group",
    label: "BOM Compare - Group vs BOM",
    description: "Standard group coverage check.",
    workflowId: "bom_compare_group",
    outputStrategyId: "new_workbook_standard",
    inputs: [bomCompareInputs.grouping, bomCompareInputs.bom],
    mappings: bomCompareGroupMappings,
    validations: [
      {
        id: "ready",
        severity: "info",
        area: "Run State",
        title: "Example data staged",
        detail: "A demo grouping + BOM pair is pre-wired. Browse for real files to replace it.",
      },
    ],
    previewRows: [],
    runSequence: {
      events: [
        {
          id: "bc-1",
          title: "Read input files",
          detail: "Loading grouping and BOM workbooks.",
          progress: 15,
          logs: ["Loaded grouping workbook (34 groups) and BOM (216 rows)."],
        },
        {
          id: "bc-2",
          title: "Run comparison",
          detail: "Comparing RefDes coverage between files.",
          progress: 60,
          logs: ["Compared 216 base RefDes — 3 missing in BOM, 1 extra."],
        },
        {
          id: "bc-3",
          title: "Write report",
          detail: "Writing Excel comparison report.",
          progress: 100,
          logs: ["Wrote comparison report — 4 sheets."],
        },
      ],
      result: {
        status: "success",
        title: "BOM comparison complete",
        summary: "3 missing in BOM, 1 extra in BOM.",
        outputFile: "DRIVE\\outputs\\BomCompare_Group_20260406.xlsx",
        primaryMetric: "3 missing",
        secondaryMetric: "1 warning",
        notes: ["Group vs BOM mode: compared grouping against BOM."],
      },
    },
  },
  {
    id: "bom-compare-custom",
    label: "BOM Compare - Custom Compare",
    description: "Direct two-BOM delta by RefDes key.",
    workflowId: "bom_compare_custom",
    outputStrategyId: "new_workbook_standard",
    inputs: [bomCompareInputs.bomA, bomCompareInputs.bomB],
    mappings: bomCompareCustomMappings,
    validations: [
      {
        id: "ready",
        severity: "info",
        area: "Run State",
        title: "Example data staged",
        detail: "A demo BOM pair is pre-wired with RefDes columns mapped.",
      },
    ],
    previewRows: [],
    runSequence: {
      events: [
        {
          id: "bcc-1",
          title: "Read input files",
          detail: "Loading both BOM workbooks.",
          progress: 15,
          logs: ["Loaded File 1 (198 rows) and File 2 (203 rows)."],
        },
        {
          id: "bcc-2",
          title: "Run comparison",
          detail: "Diffing RefDes keys between File 1 and File 2.",
          progress: 60,
          logs: ["Diffed RefDes keys — 5 only in File 1, 2 only in File 2."],
        },
        {
          id: "bcc-3",
          title: "Write report",
          detail: "Writing Excel comparison report.",
          progress: 100,
          logs: ["Wrote comparison report — 3 sheets."],
        },
      ],
      result: {
        status: "success",
        title: "BOM comparison complete",
        summary: "5 only in File 1, 2 only in File 2.",
        outputFile: "DRIVE\\outputs\\BomCompare_Custom_20260406.xlsx",
        primaryMetric: "7 differences",
        secondaryMetric: "0 warnings",
        notes: ["Custom mode: compared two BOMs directly by RefDes key."],
      },
    },
  },
  {
    id: "extraction-compare",
    label: "Extraction Compare - Rev A vs Rev B",
    description: "Diff two RefDes extraction outputs across schematic revisions.",
    workflowId: "extraction_compare",
    outputStrategyId: "new_workbook_standard",
    inputs: [bomCompareInputs.extractionA, bomCompareInputs.extractionB],
    mappings: [],
    validations: [
      {
        id: "ready",
        severity: "info",
        area: "Run State",
        title: "Example data staged",
        detail: "A demo extraction pair (rev A / rev B) is pre-wired. Browse for real outputs to replace it.",
      },
    ],
    previewRows: [],
    runSequence: {
      events: [
        {
          id: "exc-1",
          title: "Read input files",
          detail: "Loading both extraction workbooks.",
          progress: 15,
          logs: ["Loaded rev A (244 components) and rev B (246 components)."],
        },
        {
          id: "exc-2",
          title: "Compare extractions",
          detail: "Diffing component groups between revisions.",
          progress: 60,
          logs: ["Diffed groups — 3 appeared, 1 disappeared, 2 moved."],
        },
        {
          id: "exc-3",
          title: "Write report",
          detail: "Writing Excel comparison report.",
          progress: 100,
          logs: ["Wrote extraction-compare report — 4 sheets."],
        },
      ],
      result: {
        status: "success",
        title: "Extraction comparison complete",
        summary: "3 appeared, 1 disappeared, 2 moved groups (240 unchanged).",
        outputFile: "DRIVE\\outputs\\ExtractionCompare_20260406.xlsx",
        primaryMetric: "6 changes",
        secondaryMetric: "2 moved groups, 240 in both",
        notes: ["Compared RefDesExtract_revA against RefDesExtract_revB."],
      },
    },
  },
];

export const failureRateInputs: Record<string, InputFileState> = {
  prediction: {
    role: "prediction",
    label: "Prediction workbook",
    path: "DRIVE\\inputs\\Prediction_Report.xlsx",
    helper: "Failure rate prediction data with RefDes and rates.",
    status: "ready",
    sheets: sheets(["Predictions"]),
    selectedSheet: "Predictions",
    tag: "Loaded",
    isExample: true,
  },
  fmea: {
    role: "fmea",
    label: "FMEA workbook",
    path: "DRIVE\\inputs\\System_FMEA.xlsx",
    helper: "FMEA failure modes for rate linking.",
    status: "ready",
    sheets: sheets(["FMEA"]),
    selectedSheet: "FMEA",
    tag: "Loaded",
    isExample: true,
  },
};

// displayLabel = what the operator reads; canonical = the backend payload
// contract (never rename it — execute payloads and deriveMappingRows key on it).
export const failureRateMappings: ColumnMappingRow[] = [
  {
    canonical: "pred_ref",
    displayLabel: "Prediction: RefDes column",
    mappedTo: "Reference Designator",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Reference Designator", "Component", "RefDes"],
    required: true,
  },
  {
    canonical: "pred_fr",
    displayLabel: "Prediction: failure rate column",
    mappedTo: "Failure Rate",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Failure Rate", "FR", "Lambda"],
    required: true,
  },
  {
    canonical: "fmea_cause",
    displayLabel: "FMEA: failure mode causes",
    mappedTo: "Failure Mode Causes",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Failure Mode Causes", "Failure Cause", "Cause"],
    required: true,
  },
  {
    canonical: "fmea_ratio",
    displayLabel: "FMEA: failure mode ratio",
    mappedTo: "Failure Mode Ratio",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Failure Mode Ratio", "FMR", "Ratio"],
    required: true,
  },
  {
    canonical: "fmea_usage",
    displayLabel: "FMEA: part usage",
    mappedTo: "Part Usage",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Part Usage", "Usage", "Quantity"],
    required: true,
  },
  {
    canonical: "fmea_func",
    displayLabel: "FMEA: function column",
    mappedTo: "",
    status: "attention",
    recommendation: "Optional. Select a Function column for FR rollup.",
    options: ["Function"],
  },
];

export const failureRateDemoScenarios: DemoScenario[] = [
  {
    id: "failure-rate-link",
    label: "Failure Rate Link",
    description: "Link prediction failure rates to FMEA failure modes.",
    workflowId: "failure_rate_link",
    outputStrategyId: "new_workbook_standard",
    inputs: [failureRateInputs.prediction, failureRateInputs.fmea],
    mappings: failureRateMappings,
    validations: [
      {
        id: "ready",
        severity: "info",
        area: "Run State",
        title: "Example data staged",
        detail: "A demo prediction + FMEA pair is pre-wired. Mapping status lives in Column Mapping.",
      },
    ],
    previewRows: [],
    runSequence: {
      events: [
        {
          id: "fr-1",
          title: "Load input files",
          detail: "Loading prediction and FMEA workbooks.",
          progress: 10,
          logs: ["Loaded prediction (1512 rows) and FMEA (1500 rows)."],
        },
        {
          id: "fr-2",
          title: "Link failure rates",
          detail: "Matching prediction rates to FMEA failure modes.",
          progress: 70,
          logs: ["Linked 1500 rows — 12 rows carried data-quality warnings."],
        },
        {
          id: "fr-3",
          title: "Write report",
          detail: "Writing Excel output with linked rates.",
          progress: 100,
          logs: ["Wrote linked-rate workbook."],
        },
      ],
      result: {
        status: "success",
        title: "Failure rate linking complete",
        summary: "1500 FMEA rows linked with prediction failure rates.",
        outputFile: "DRIVE\\outputs\\FailureRate_Link_20260406.xlsx",
        primaryMetric: "1500 rows",
        secondaryMetric: "12 warnings",
        // Drives the warning-qualified success toast, mirroring the
        // desktop controller's warning_count handling.
        warningCount: 12,
        notes: ["Failure rate linking mode: matched prediction rates to FMEA failure modes."],
      },
    },
  },
];

export const refdesInputs: Record<string, InputFileState> = {
  pdf: {
    role: "pdf" as FileRole,
    label: "Schematic PDF",
    path: "DRIVE\\inputs\\NavUnit_Schematic_v3.pdf",
    helper: "Annotated schematic PDF with component group boxes.",
    status: "ready",
    sheets: [],
    selectedSheet: "",
    tag: "Loaded",
    isExample: true,
  },
  bom: {
    role: "bom",
    label: "BOM workbook (optional)",
    path: "DRIVE\\inputs\\NavUnit_BOM.xlsx",
    helper: "Optional BOM for RefDes verification.",
    status: "ready",
    sheets: sheets(["Main BOM"]),
    selectedSheet: "Main BOM",
    tag: "Optional",
    isExample: true,
  },
  pinlist: {
    role: "pinlist" as FileRole,
    label: "Pinlist file (optional)",
    path: "",
    helper: "Optional pinlist for piece-part pin qualification.",
    status: "optional",
    sheets: [],
    selectedSheet: "",
    tag: "Not loaded",
    // Untouched empty slot still counts as pristine until the user browses.
    isExample: true,
  },
};

export const refdesDemoScenarios: DemoScenario[] = [
  {
    id: "refdes-extract",
    label: "RefDes Extraction",
    description: "Extract RefDes from annotated schematic PDF.",
    workflowId: "refdes_extract" as WorkflowId,
    outputStrategyId: "new_workbook_standard",
    // Pinlist must be seeded even though it only renders in piece_part
    // mode — the tool filters inputStates by inputRoles, so a missing
    // entry here would silently drop the pinlist picker.
    inputs: [refdesInputs.pdf, refdesInputs.bom, refdesInputs.pinlist],
    mappings: [],
    validations: [{ id: "ready", severity: "info", area: "Run State", title: "Example data staged", detail: "A demo schematic + BOM pair is pre-wired for extraction." }],
    previewRows: [],
    runSequence: {
      events: [
        {
          id: "rd-1",
          title: "Load input files",
          detail: "Loading BOM and pinlist.",
          progress: 8,
          logs: ["Loaded BOM — 251 component rows."],
        },
        {
          id: "rd-2",
          title: "Open PDF",
          detail: "Extracting annotations from schematic.",
          progress: 18,
          logs: ["Opened schematic PDF — 42 pages, 12 group boxes."],
        },
        {
          id: "rd-3",
          title: "Extract components",
          detail: "Running adaptive geometry extraction.",
          progress: 90,
          logs: ["Extracted 245 components (10 groups verified, 2 unverified)."],
        },
        {
          id: "rd-4",
          title: "Write report",
          detail: "Writing Excel results.",
          progress: 100,
          logs: ["Wrote extraction workbook — 5 sheets."],
        },
      ],
      result: {
        status: "success" as const,
        title: "RefDes extraction complete",
        summary: "245 components extracted from 12 groups.",
        outputFile: "DRIVE\\outputs\\RefDesExtract_20260406.xlsx",
        primaryMetric: "10 verified groups",
        secondaryMetric: "2 unverified, 245 total components",
        notes: [
          "Backend: nextgen.",
          "Extraction mode: functional.",
          "BOM coverage: 6 BOM component(s) not grouped (4 never extracted), 3 extracted not in BOM — see the 'Coverage Summary', 'BOM Not Grouped', and 'Extracted Not In BOM' sheets.",
        ],
      },
    },
  },
];
