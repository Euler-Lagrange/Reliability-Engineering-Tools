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
  | "existing_workbook_best_effort"
  | "existing_workbook_preserve_formatting";
export type MappingStatus = "mapped" | "manual" | "attention";
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
  /**
   * When true, the workflow is shown in the UI but cannot be selected.
   * Used to preview "Coming soon" workflows whose backend hasn't
   * shipped yet — e.g. functional_to_piecepart before Phase D.
   */
  disabled?: boolean;
  /** Optional tooltip shown when the workflow is disabled. */
  disabledReason?: string;
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
  runSequence: {
    events: RunEventTemplate[];
    result: RunResult;
  };
}
