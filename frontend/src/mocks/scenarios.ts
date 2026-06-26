import type {
  ColumnMappingRow,
  DemoScenario,
  FileRole,
  InputFileState,
  OutputStrategy,
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
    detail: "Dark Star preserved the legacy safety rule and rejected ambiguous rows.",
  },
  {
    id: "err-1",
    severity: "error",
    area: "Target Workbook",
    title: "Protected footer region collides with planned inserts",
    detail: "Planner would require workbook review before formatting-preserved output can continue.",
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
    requiredRoles: ["bom", "failureModes"],
    optionalRoles: ["hda"],
  },
];

export const outputStrategies: OutputStrategy[] = [
  {
    id: "new_workbook_standard",
    title: "New Workbook",
    summary: "Generate a fresh output workbook with all generator columns and summary sheets.",
    badge: "Clean export",
  },
  {
    id: "existing_workbook_preserve_formatting",
    title: "Existing Workbook (Preserve Formatting)",
    summary:
      "Writes the new piece-part rows directly into the selected functional or piece-part FMEA workbook. Any new columns are appended at the very end of the sheet. All existing rows, data, formatting, fonts, and column widths are preserved.",
    badge: "High trust",
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
    detail: "Mapped workbook inputs against the selected Dark Star column profile.",
    progress: 18,
  },
  {
    id: "event-2",
    title: "Normalize source columns",
    detail: "Applied canonical names and preserved manual overrides.",
    progress: 34,
  },
  {
    id: "event-3",
    title: "Generate base rows",
    detail: "Built piece-part candidates and grouped them by canonical IDs.",
    progress: 58,
  },
  {
    id: "event-4",
    title: "Apply enrichments",
    detail: "Copied safe effect fields from optional source FMEAs.",
    progress: 77,
  },
  {
    id: "event-5",
    title: "Plan workbook output",
    detail: "Prepared a formatting-preserved update plan against the selected template.",
    progress: 92,
  },
];

const failureEvents = [
  {
    id: "event-f1",
    title: "Resolve sheets and profile",
    detail: "Loaded target workbook metadata and planned the update scope.",
    progress: 20,
  },
  {
    id: "event-f2",
    title: "Generate gap rows",
    detail: "Detected missing piece-part rows from the existing FMEA workbook.",
    progress: 47,
  },
  {
    id: "event-f3",
    title: "Inspect workbook constraints",
    detail: "Planner found a protected footer region under the insertion boundary.",
    progress: 71,
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
        title: "92% of canonical columns auto-mapped",
        detail: "Only operator-sensitive fields remain in manual review status.",
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
        outputFile: "DarkStar_PiecePart_20260403_1012.xlsx",
        primaryMetric: "216 planned rows",
        secondaryMetric: "92% auto-mapped",
        notes: ["No backend work was executed.", "Workbook output is illustrative only."],
      },
    },
  },
  {
    id: "fill-gaps",
    label: "Fill Gaps",
    description: "Delta-oriented scenario that reads an existing FMEA and targets only missing piece-part rows.",
    workflowId: "fill_gaps",
    outputStrategyId: "existing_workbook_preserve_formatting",
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
        summary: "14 missing rows were identified and staged into a workbook copy plan.",
        outputFile: "DarkStar_GapFill_20260403_1035.xlsx",
        primaryMetric: "14 gap rows",
        secondaryMetric: "2 workbook notes",
        notes: ["Preserve-formatting path shown.", "No file was written."],
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
        title: "Merged-header region preserved in workbook plan",
        detail: "Dark Star keeps the target workbook explicit and shows planner confidence before execution.",
      },
    ],
    previewRows,
    runSequence: {
      events: successEvents,
      result: {
        status: "success",
        title: "Formatting-preserved plan ready",
        summary: "Planner isolated 4 protected regions and still staged all row updates into a workbook copy.",
        outputFile: "DarkStar_PreserveFmt_20260403_1108.xlsx",
        primaryMetric: "4 protected regions",
        secondaryMetric: "0 unsafe overwrites",
        notes: ["Planner/executor behavior is simulated.", "Target workbook remains read-only in this prototype."],
      },
    },
  },
  {
    id: "warning-heavy",
    label: "Warning Heavy",
    description: "Stress case for validation density, manual review, and high-visibility diagnostic messaging.",
    workflowId: "piece_part_generate",
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
    workflowId: "piece_part_generate",
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
        summary: "Dark Star reached a review-ready state with clean completion messaging and output metadata.",
        outputFile: "DarkStar_RunSuccess_20260403_1131.xlsx",
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
];

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
};

export const bomCompareWorkflowOptions: WorkflowOption[] = [
  {
    id: "bom_compare_group",
    title: "Group vs BOM",
    summary: "Compare grouping file against BOM to find missing and extra RefDes.",
    eyebrow: "Standard",
    badge: "Coverage",
  },
  {
    id: "bom_compare_custom",
    title: "Custom Compare",
    summary: "Compare two arbitrary BOMs to find differences by RefDes key.",
    eyebrow: "Flexible",
    badge: "Delta",
  },
];

export const bomCompareGroupMappings: ColumnMappingRow[] = [
  {
    canonical: "grouping_group_col",
    mappedTo: "Component Group",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Component Group", "Group", "Circuit Block"],
  },
  {
    canonical: "grouping_refdes_col",
    mappedTo: "Reference Designator",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Reference Designator", "RefDes", "Ref Des"],
  },
  {
    canonical: "bom_refdes_col",
    mappedTo: "Reference Designator",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Reference Designator", "RefDes", "Ref Des"],
  },
  {
    canonical: "bom_desc_col",
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
    mappedTo: "Reference Designator",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Reference Designator", "RefDes"],
  },
  {
    canonical: "refdes_col_b",
    mappedTo: "Reference Designator",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Reference Designator", "RefDes"],
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
        title: "Ready to run",
        detail: "All inputs loaded and mapped.",
      },
    ],
    previewRows: [],
    runSequence: {
      events: [
        { id: "bc-1", title: "Read input files", detail: "Loading grouping and BOM workbooks.", progress: 15 },
        { id: "bc-2", title: "Run comparison", detail: "Comparing RefDes coverage between files.", progress: 60 },
        { id: "bc-3", title: "Write report", detail: "Writing Excel comparison report.", progress: 100 },
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
        title: "Ready to run",
        detail: "Both BOMs loaded and RefDes columns mapped.",
      },
    ],
    previewRows: [],
    runSequence: {
      events: [
        { id: "bcc-1", title: "Read input files", detail: "Loading both BOM workbooks.", progress: 15 },
        { id: "bcc-2", title: "Run comparison", detail: "Diffing RefDes keys between File 1 and File 2.", progress: 60 },
        { id: "bcc-3", title: "Write report", detail: "Writing Excel comparison report.", progress: 100 },
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

export const failureRateMappings: ColumnMappingRow[] = [
  {
    canonical: "pred_ref",
    mappedTo: "Reference Designator",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Reference Designator", "Component", "RefDes"],
  },
  {
    canonical: "pred_fr",
    mappedTo: "Failure Rate",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Failure Rate", "FR", "Lambda"],
  },
  {
    canonical: "fmea_cause",
    mappedTo: "Failure Mode Causes",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Failure Mode Causes", "Failure Cause", "Cause"],
  },
  {
    canonical: "fmea_ratio",
    mappedTo: "Failure Mode Ratio",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Failure Mode Ratio", "FMR", "Ratio"],
  },
  {
    canonical: "fmea_usage",
    mappedTo: "Part Usage",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Part Usage", "Usage", "Quantity"],
  },
  {
    canonical: "fmea_func",
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
        title: "Ready to run",
        detail: "All inputs loaded and mapped.",
      },
    ],
    previewRows: [],
    runSequence: {
      events: [
        { id: "fr-1", title: "Load input files", detail: "Loading prediction and FMEA workbooks.", progress: 10 },
        { id: "fr-2", title: "Link failure rates", detail: "Matching prediction rates to FMEA failure modes.", progress: 70 },
        { id: "fr-3", title: "Write report", detail: "Writing Excel output with linked rates.", progress: 100 },
      ],
      result: {
        status: "success",
        title: "Failure rate linking complete",
        summary: "1500 FMEA rows linked with prediction failure rates.",
        outputFile: "DRIVE\\outputs\\FailureRate_Link_20260406.xlsx",
        primaryMetric: "1500 rows",
        secondaryMetric: "12 warnings",
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
    validations: [{ id: "ready", severity: "info", area: "Run State", title: "Ready to run", detail: "PDF loaded and ready for extraction." }],
    previewRows: [],
    runSequence: {
      events: [
        { id: "rd-1", title: "Load input files", detail: "Loading BOM and pinlist.", progress: 8 },
        { id: "rd-2", title: "Open PDF", detail: "Extracting annotations from schematic.", progress: 18 },
        { id: "rd-3", title: "Extract components", detail: "Running adaptive geometry extraction.", progress: 90 },
        { id: "rd-4", title: "Write report", detail: "Writing Excel results.", progress: 100 },
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
