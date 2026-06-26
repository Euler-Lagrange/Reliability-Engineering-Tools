import type { OutputPreview } from "../contracts/sidecar";

export type WorkflowId =
  | "piece_part_generate"
  | "bom_only"
  | "functional_to_piecepart"
  | "fill_gaps"
  | "bom_compare_group"
  | "bom_compare_custom"
  | "failure_rate_link"
  | "refdes_extract";
export type FileRole =
  | "grouping"
  | "bom"
  | "hda"
  | "failureModes"
  | "functionalFmea"
  | "existingFmea"
  | "targetWorkbook"
  | "bomA"
  | "bomB"
  | "prediction"
  | "fmea"
  | "pdf"
  | "pinlist";
export type FileStatus = "ready" | "attention" | "optional";
export type OutputStrategyId =
  | "new_workbook_standard"
  | "existing_workbook_preserve_formatting";
export type MappingStatus = "mapped" | "manual" | "attention" | "derived" | "not_mapped";
export type MappingOrigin = "mapped" | "derived" | "merge_only";

/**
 * Sentinel value the mapping UI sends when the user explicitly chooses
 * "— Do Not Map —" for a column. The backend receives this as-is and
 * decides whether to hard-error (for `required: true` rows) or derive
 * the value from another source. Do NOT compare raw header strings to
 * this value — real workbook headers never start with double underscores.
 */
export const DO_NOT_MAP_VALUE = "__do_not_map__";
export const DO_NOT_MAP_LABEL = "— Do Not Map —";

/**
 * Per-column comparison rule for Custom BOM Compare value diffs (Tier-1 #5).
 * These exact strings are matched loosely by the backend's `values_differ`
 * (`bom_compare/custom_compare.py`): "Numeric" -> numeric tolerance compare,
 * "...exact..." -> case-sensitive text, otherwise case-insensitive text. Do
 * NOT change the wording without updating that matcher.
 */
export type CompareRule = "Text (ignore case)" | "Text (exact)" | "Numeric";

/**
 * One column-value comparison pair for Custom BOM Compare. The frontend sends
 * an array of these as `options.compare_columns`; the runtime adapter
 * (`bom_compare/runtime.py` `_run_custom_compare`) converts each to a
 * `(col_a, col_b, rule)` tuple for `compare_two_boms`.
 */
export interface ComparePair {
  col_a: string;
  col_b: string;
  rule: CompareRule;
}
export type ValidationSeverity = "info" | "warning" | "error";
export type RunEventStatus = "completed" | "active" | "pending";
export type RunMode = "idle" | "starting" | "running" | "cancelling" | "success" | "failure" | "cancelled" | "disconnected";

export interface WorkflowOption {
  id: WorkflowId;
  title: string;
  summary: string;
  eyebrow: string;
  badge: string;
  /**
   * Input roles that MUST be supplied before this workflow will validate.
   * Must match the backend's `_required_roles()` in `fmea/runtime.py`
   * exactly — if the two drift, the UI will either block the user
   * unnecessarily or let them submit broken runs.
   */
  requiredRoles?: FileRole[];
  /**
   * Input roles that are shown in the UI and passed to the backend if
   * loaded, but NOT required for validation. Examples: HDA for every
   * FMEA workflow, grouping for fill_gaps.
   */
  optionalRoles?: FileRole[];
}

export interface SheetOption {
  id: string;
  label: string;
}

export interface InputFileState {
  role: FileRole;
  label: string;
  path: string;
  helper: string;
  status: FileStatus;
  sheets: SheetOption[];
  selectedSheet: string;
  tag: string;
  source?: "mock" | "desktop-bridge";
  isResolvingSheets?: boolean;
  isAnalyzing?: boolean;
  resolutionError?: string | null;
  /** Mock/demo placeholder path that should be visually marked as an example. */
  isExample?: boolean;
}

export interface OutputStrategy {
  id: OutputStrategyId;
  title: string;
  summary: string;
  badge: string;
}

export interface ColumnMappingRow {
  canonical: string;
  mappedTo: string;
  status: MappingStatus;
  recommendation: string;
  options: string[];
  /**
   * Optional display-label overrides keyed by the raw option value.
   * The backend still receives the raw option string; this only affects
   * how the dropdown presents provenance to the user.
   */
  optionLabels?: Record<string, string>;
  /**
   * Stylized long-form "About this column" body text. When present, the
   * MappingTable renders an `(i)` info button next to the canonical label
   * that expands an inline accent-bordered help panel. When undefined, the
   * info button is not rendered (backward-compatible with tools that
   * haven't authored help text yet).
   */
  help?: string;
  /**
   * Drives status chip colour and visibility logic downstream. `derived`
   * columns (like FMEA Level) render as read-only informational rows in
   * the mapping table. `merge_only` columns are hidden in non-merge modes.
   */
  origin?: MappingOrigin;
  /**
   * If true, the row is a critical column: selecting "— Do Not Map —"
   * should cause the backend to raise a validation error rather than
   * silently derive a value.
   */
  required?: boolean;
}

export interface ValidationMessage {
  id: string;
  severity: ValidationSeverity;
  area: string;
  title: string;
  detail: string;
}

export interface AnalysisContextCard {
  id: string;
  eyebrow: string;
  title: string;
  detail: string;
  metrics: string[];
}

export interface PreviewRow {
  id: string;
  refdes: string;
  failureMode: string;
  localEffect: string;
  nextHigherEffect: string;
}

export interface InputInspection {
  role: FileRole;
  path: string;
  sheet: string;
  headerRow: number;
  rowCount: number;
  columns: string[];
  previewRows: Array<Record<string, string>>;
  rowsScanned: number;
  columnsScanned: number;
  headerRowsScanned?: number;
  rowCapApplied: boolean;
  columnCapApplied: boolean;
  headerSearchCapApplied: boolean;
  mode: "browser-mock" | "desktop-bridge";
}

export interface TemplateAnalysis {
  role: FileRole;
  path: string;
  sheet: string;
  headerRow: number;
  columns: string[];
  mergedRangeCount: number;
  freezePanes: string | null;
  protectedSheet: boolean;
  rowsScanned: number;
  headerRowsScanned?: number;
  columnsScanned: number;
  rowCapApplied: boolean;
  columnCapApplied: boolean;
  headerSearchCapApplied: boolean;
  mode: "browser-mock" | "desktop-bridge";
}

export interface RunEventTemplate {
  id: string;
  title: string;
  detail: string;
  progress: number;
}

export interface RunEvent extends RunEventTemplate {
  status: RunEventStatus;
}

export interface RunResult {
  status: "success" | "failure";
  title: string;
  summary: string;
  outputFile: string;
  primaryMetric: string;
  secondaryMetric: string;
  notes: string[];
}

export interface DemoScenario {
  id: string;
  label: string;
  description: string;
  workflowId: WorkflowId;
  outputStrategyId: OutputStrategyId;
  inputs: InputFileState[];
  mappings: ColumnMappingRow[];
  validations: ValidationMessage[];
  previewRows: PreviewRow[];
  outputPreview?: OutputPreview;
  runSequence: {
    events: RunEventTemplate[];
    result: RunResult;
  };
}
