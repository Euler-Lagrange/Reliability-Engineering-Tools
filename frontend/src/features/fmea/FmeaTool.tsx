import { startTransition, useEffect, useMemo, useRef, useState } from "react";
import {
  FILE_INSPECTION_PAUSED_REASON,
  InputGrid,
} from "../../components/InputGrid";
import { MappingTable } from "../../components/MappingTable";
import { RunStatePanel } from "../../components/RunStatePanel";
import { SectionCard } from "../../components/SectionCard";
import { StrategySelector } from "../../components/StrategySelector";
import { ValidationPreview } from "../../components/ValidationPreview";
import { WorkflowSelector } from "../../components/WorkflowSelector";
import { ContextTabs } from "../../components/primitives/ContextTabs";
import { EmptyState } from "../../components/primitives/EmptyState";
import { OptionsField } from "../../components/primitives/OptionsField";
import { ToggleChip } from "../../components/primitives/ToggleChip";
import { FolderOpen, TreeStructure } from "@phosphor-icons/react";
import { demoScenarios, outputStrategies, workflowOptions } from "../../mocks/scenarios";
import type {
  AnalysisContextCard,
  ColumnMappingRow,
  FileRole,
  InputInspection,
  InputFileState,
  MappingStatus,
  OutputStrategyId,
  RunEventTemplate,
  RunMode,
  TemplateAnalysis,
  ValidationMessage,
  WorkflowId,
} from "../../app/types";
import { DO_NOT_MAP_VALUE } from "../../app/types";
import { FMEA_COLUMN_METADATA, migrateFmdOverrides, resolveColumnLabel } from "./mappingColumns";
import {
  buildAggregatedMappingSource,
  buildWorkbookColumnUnion,
  normalizeHeader,
  shouldShowTargetWorkbook,
} from "./mappingAnalysis";
import {
  backendClient,
  type InspectInputResult,
  type RunRequestBody,
} from "../../shared/backend/client";
import { describeBackendError } from "../../shared/backend/cancelError";
import { parentDirectoryForPath } from "../../shared/backend/fileManager";
import { LIVE_PHASES } from "../../shared/backend/runLifecycle";
import {
  buildTimeline,
  cloneInputs,
  emptyInputsFromScenario,
  useDesktopRunController,
} from "../../shared/backend/useDesktopRunController";
import { ErrorBoundary } from "../../shared/errors/ErrorBoundary";
import { useRoleRequestSequence } from "../../shared/hooks/useRoleRequestSequence";
import { useNotificationStore } from "../../stores/notificationStore";
import { usePreviewStore } from "../../stores/previewStore";
import { useRunStore } from "../../stores/runStore";
import { useShellStore } from "../../stores/shellStore";

const baseScenario = demoScenarios[0];
const fmeaRunEvents: RunEventTemplate[] = [
  {
    id: "fmea-validate",
    title: "Validate run state",
    detail: "Checking required files and confirming the selected workflow is ready.",
    progress: 18,
  },
  {
    id: "fmea-generate",
    title: "Generate FMEA rows",
    detail: "Building FMEA workbook rows from input sources.",
    progress: 64,
  },
  {
    id: "fmea-write",
    title: "Write workbook",
    detail: "Writing output workbook and returning the artifact path.",
    progress: 100,
  },
];

type HdaSource = "inline" | "separate";

/**
 * Phase 3 role visibility matrix. The display order returned here determines
 * the order of file cards inside the Inputs SectionCard. When `hdaSource`
 * is `"inline"` the `hda` role is omitted entirely; the backend still
 * resolves HDA data from BOM columns via `_resolve_hda_dataframe()`.
 *
 * Only the roles specific to each workflow mode are returned. Output-only
 * roles such as `targetWorkbook` are rendered separately in the Outputs
 * section and only added to the run payload when the selected strategy
 * requires them.
 */
function getVisibleRoles(workflowId: WorkflowId, hdaSource: HdaSource): FileRole[] {
  const hda: FileRole[] = hdaSource === "separate" ? ["hda"] : [];
  switch (workflowId) {
    case "functional_to_piecepart":
      return ["functionalFmea", "bom", "failureModes", ...hda, "grouping"];
    case "fill_gaps":
      return ["existingFmea", "bom", "failureModes", ...hda, "grouping"];
    case "piece_part_generate":
      return ["grouping", "bom", "failureModes", ...hda];
    case "bom_only":
      return ["bom", "failureModes", ...hda];
    default: {
      // Non-FMEA workflow IDs shouldn't reach this helper, but if they do
      // fall back to the shared workflowOptions metadata for safety.
      const workflow = workflowOptions.find((option) => option.id === workflowId);
      return [
        ...(workflow?.requiredRoles ?? []),
        ...(workflow?.optionalRoles ?? []),
      ];
    }
  }
}

/**
 * Roles the backend's `_required_roles` blocks validation on, per workflow.
 * Drives the "Required" chip on unloaded input cards — keep in lockstep
 * with `backend/python/fmea/runtime.py`.
 */
const FMEA_REQUIRED_ROLES: Partial<Record<WorkflowId, FileRole[]>> = {
  piece_part_generate: ["grouping", "bom", "failureModes"],
  bom_only: ["bom", "failureModes"],
  functional_to_piecepart: ["functionalFmea", "bom", "failureModes"],
  fill_gaps: ["existingFmea", "bom", "failureModes"],
};

function buildWorkflowInputs(
  inputs: InputFileState[],
  workflowId: WorkflowId,
  hdaSource: HdaSource,
) {
  const requiredRoles = new Set<FileRole>(FMEA_REQUIRED_ROLES[workflowId] ?? []);
  // Explicitly choosing a separate HDA file makes the hda role blocking
  // (backend reason_code missing_separate_hda).
  if (hdaSource === "separate") {
    requiredRoles.add("hda");
  }
  return getVisibleRoles(workflowId, hdaSource)
    .map((role) => inputs.find((input) => input.role === role))
    .filter((input): input is InputFileState => Boolean(input))
    .map((input) => ({ ...input, required: requiredRoles.has(input.role) }));
}

function buildOutputInputs(inputs: InputFileState[], outputStrategyId: OutputStrategyId) {
  if (!shouldShowTargetWorkbook(outputStrategyId)) {
    return [];
  }

  const targetWorkbook = inputs.find((input) => input.role === "targetWorkbook");
  // The preserve-formatting strategy cannot run without its template.
  return targetWorkbook ? [{ ...targetWorkbook, required: true }] : [];
}

function buildRunRequest(
  workflowId: WorkflowId,
  outputStrategyId: OutputStrategyId,
  visibleInputs: InputFileState[],
  mappingRows: ColumnMappingRow[],
  mappingOverrides: Record<string, string>,
  failureModesStandard: "FMD-91" | "FMD-2016",
  options: {
    ccaPrefix: string | null;
    outputDirectory: string | null;
    hdaSource: HdaSource;
  },
): RunRequestBody {
  const toolOptions: Record<string, unknown> = {
    failureModesStandard,
    hdaSource: options.hdaSource,
  };

  // Phase 3: CCA prefix is ONLY sent for BOM-Only runs. In every other
  // mode the backend derives the prefix from the grouping / functional /
  // existing FMEA source file, and leaking a stale user-entered prefix
  // into those runs would produce a wrong FMEA-ID.
  if (workflowId === "bom_only" && options.ccaPrefix) {
    toolOptions.ccaPrefix = options.ccaPrefix;
  }

  return {
    workflowId,
    outputStrategyId,
    inputs: visibleInputs.map((input) => ({
      role: input.role,
      label: input.label,
      path: input.path,
      selectedSheet: input.selectedSheet,
      source: input.source,
      isResolvingSheets: input.isResolvingSheets,
      isAnalyzing: input.isAnalyzing,
      resolutionError: input.resolutionError,
      sheets: input.sheets,
    })),
    mappings: mappingRows.map((row) => ({
      canonical: row.canonical,
      mappedTo: mappingOverrides[row.canonical] ?? row.mappedTo,
      status: mappingOverrides[row.canonical] ? "manual" : row.status,
    })),
    options: toolOptions,
    // Top-level outputDirectory: Phase 4 backend will honor this when
    // present, else fall back to the first-input-file-parent heuristic.
    // Phase 3 plumbs the field; no-op on the current backend.
    outputDirectory: options.outputDirectory,
  };
}

/**
 * Strip a CCA prefix candidate to the allowed character set.
 * A-Z, 0-9, hyphen; max 8 characters. Input is upper-cased first.
 */
function sanitizeCcaPrefix(raw: string): string {
  return raw.toUpperCase().replace(/[^A-Z0-9-]/g, "").slice(0, 8);
}

const CCA_PREFIX_PATTERN = /^[A-Z0-9][A-Z0-9-]{0,7}$/;
const CCA_PREFIX_STORAGE_KEY = "fmea.lastCcaPrefix";

function readStoredCcaPrefix(): string {
  if (typeof window === "undefined") {
    return "";
  }
  try {
    const stored = window.localStorage.getItem(CCA_PREFIX_STORAGE_KEY);
    return stored ? sanitizeCcaPrefix(stored) : "";
  } catch {
    return "";
  }
}

// Family 1 fix: FMEA's local `emptyInputsFromScenario` was promoted verbatim
// (modulo two confirmed-cosmetic bugs it carried) to the shared
// `useDesktopRunController` module so all four tools seed empty desktop slots
// identically. The shared helper additionally (a) sets a neutral
// `optional`/"Not loaded" status+tag instead of inheriting the scenario's
// green `ready`/"Loaded" chip — FMEA's local copy showed loaded-looking chips
// on empty desktop cards — and (b) keeps `isExample: true` (the local copy set
// `false`); FMEA reads neither flag (no isPristine/EmptyState here, and
// InputGrid's example styling needs a non-empty path), so the change is inert
// for FMEA and correct for the three tools whose isPristine gate needs it.

// Evaluate once at module load; `backendClient.runtimeMode` is fixed per
// session (the bridge cannot switch runtime modes after boot).
const IS_BROWSER_MOCK = backendClient.runtimeMode === "browser-mock";
const initialInputs: InputFileState[] = IS_BROWSER_MOCK
  ? cloneInputs(demoScenarios[0].inputs)
  : emptyInputsFromScenario(demoScenarios[0].inputs);
const initialValidations: ValidationMessage[] = IS_BROWSER_MOCK
  ? demoScenarios[0].validations
  : [];
const initialRunTemplates: RunEventTemplate[] = IS_BROWSER_MOCK
  ? demoScenarios[0].runSequence.events
  : fmeaRunEvents;
// UX findings 2026-07-07 #5: browser-mock demo columns. Without these the
// demo staged LOADED files but every mapping row read "Not mapped" (plus an
// amber unmapped badge and a "TBD" hero metric) — inconsistent with the BOM
// Compare / Failure Rate demos, whose fixtures stage mapped rows. Headers
// match the canonical labels so every visible row exact-matches. Desktop
// seeds {} — real inspection is the only column source there (mirrors BOM
// Compare's seedColumnsForWorkflow pattern).
const DEMO_WORKBOOK_COLUMNS: Partial<Record<FileRole, string[]>> = IS_BROWSER_MOCK
  ? {
      grouping: [
        "FMEA-ID",
        "Failure Mode Causes",
        "Function Description",
        "Schematic Page",
      ],
      bom: [
        "Component Part Description",
        "Part Usage",
        "BAE HDA Commodity Level 1",
        "BAE HDA Commodity Level 2",
        "FMD-2016 Commodity Type 1",
        "FMD-2016 Commodity Type 2",
      ],
      failureModes: ["Failure Mode", "Failure Mode Ratio"],
    }
  : {};

/**
 * Phase 5: Build the FMEA mapping rows from the canonical metadata.
 *
 * Rows are filtered per workflow (BOM-Only hides FMEA-ID; non-merge modes
 * hide Local/Next Higher/End Effect). The FMD Commodity Type rows get
 * their label swapped to track the active FMD standard. When the user
 * has loaded a workbook, each row's dropdown options include every
 * inspected column and the row auto-maps to an exact header match. When
 * no workbook has been inspected, rows render with the inspected-column
 * list empty (CustomSelect will still offer the "— Do Not Map —" sentinel
 * from MappingTable).
 *
 * The `origin`, `required`, and `help` fields flow straight through from
 * `FMEA_COLUMN_METADATA` — this is the single source of truth Phase 5
 * wires into the expandable help panel.
 */
function buildFmeaMappingRows(
  workflowId: WorkflowId,
  fmdStandard: "FMD-91" | "FMD-2016",
  inspectedColumns: string[],
  sourceLabel: string | null,
  optionLabels: Record<string, string>,
): ColumnMappingRow[] {
  const exactMap = new Map(
    inspectedColumns.map((column) => [normalizeHeader(column), column] as const),
  );

  return FMEA_COLUMN_METADATA.filter((meta) => meta.isVisibleInMode(workflowId)).map(
    (meta) => {
      const canonical = resolveColumnLabel(meta, fmdStandard);
      const exactMatch = exactMap.get(normalizeHeader(canonical));
      const options = Array.from(
        new Set(exactMatch ? [exactMatch, ...inspectedColumns] : [...inspectedColumns]),
      );

      let mappedTo = "";
      let status: MappingStatus = meta.origin === "derived" ? "derived" : "not_mapped";
      let recommendation =
        meta.origin === "derived"
          ? "Generated automatically from BOM and grouping data."
          : "No column mapped yet.";

      if (meta.origin !== "derived" && exactMatch) {
        mappedTo = exactMatch;
        status = "mapped";
        recommendation = sourceLabel
          ? `Exact header found in ${sourceLabel}.`
          : "Exact header found in inspected workbook.";
      }

      return {
        canonical,
        mappedTo,
        status,
        recommendation,
        options,
        optionLabels,
        help: meta.help,
        origin: meta.origin,
        // "Failure Mode Causes" is static `required: false` in the metadata
        // (it is optional outside merges), but the backend hard-blocks the
        // merge workflows without it (missing_failure_mode_causes_mapping) —
        // show the marker exactly where the gate exists.
        required:
          meta.required ||
          (meta.canonical === "Failure Mode Causes" &&
            (workflowId === "fill_gaps" || workflowId === "functional_to_piecepart")),
      };
    },
  );
}

function buildInspectionCapFragments(scan: {
  rowsScanned: number;
  columnsScanned: number;
  rowCapApplied: boolean;
  columnCapApplied: boolean;
}) {
  const fragments: string[] = [];
  if (scan.rowCapApplied) {
    fragments.push(`first ${scan.rowsScanned.toLocaleString()} data rows`);
  }
  if (scan.columnCapApplied) {
    fragments.push(`first ${scan.columnsScanned.toLocaleString()} columns`);
  }
  return fragments;
}

function buildInspectionCapWarning(
  inspection: InputInspection | null,
  roleLabel: string | null,
): ValidationMessage | null {
  if (!inspection) {
    return null;
  }

  const fragments = buildInspectionCapFragments(inspection);
  if (fragments.length === 0) {
    return null;
  }

  return {
    id: `inspection-cap-${inspection.role}-${inspection.sheet}`,
    severity: "warning",
    area: roleLabel ?? inspection.role,
    title: "Workbook inspection capped",
    detail: `Mapping suggestions for ${inspection.sheet} were built from the ${fragments.join(" and ")} to keep the desktop bridge responsive.`,
  };
}

function buildAnalysisCards(
  inspection: InputInspection | null,
  template: TemplateAnalysis | null,
): AnalysisContextCard[] {
  const cards: AnalysisContextCard[] = [];

  if (inspection) {
    cards.push({
      id: `inspection-${inspection.role}`,
      eyebrow: "Input inspection",
      title: `${inspection.sheet} inspected`,
      detail:
        buildInspectionCapFragments(inspection).length > 0
          ? `${inspection.columns.length} headers were found in the selected input workbook. Inspection was capped to ${buildInspectionCapFragments(inspection).join(" and ")}.`
          : `${inspection.columns.length} headers were found in the selected input workbook.`,
      metrics: [
        `Header row ${inspection.headerRow}`,
        `${inspection.rowCount} data rows`,
        ...(inspection.rowCapApplied ? [`Scanned ${inspection.rowsScanned.toLocaleString()} rows`] : []),
        ...(inspection.columnCapApplied ? [`Scanned ${inspection.columnsScanned} columns`] : []),
      ],
    });
  }

  if (template) {
    cards.push({
      id: `template-${template.role}`,
      eyebrow: "Template analysis",
      title: `${template.sheet} analyzed`,
      detail: `${template.columns.length} template columns are available for mapping review.`,
      metrics: [
        `Header row ${template.headerRow}`,
        `${template.mergedRangeCount} merged ranges`,
        template.freezePanes ? `Freeze ${template.freezePanes}` : "No freeze panes",
        ...(template.columnCapApplied ? [`Scanned ${template.columnsScanned} columns`] : []),
      ],
      warning: template.protectedSheet
        ? "Sheet is protected — the merge will modify it without the password."
        : undefined,
    });
  }

  return cards;
}

function failureModesHintForStandard(failureModesStandard: "FMD-91" | "FMD-2016") {
  return failureModesStandard === "FMD-91"
    ? "Uses the FMD-91 commodity labels in column mapping and failure-mode lookups."
    : "Uses the FMD-2016 commodity labels in column mapping and failure-mode lookups.";
}

export function FmeaTool() {
  const [workflowId, setWorkflowId] = useState<WorkflowId>(baseScenario.workflowId);
  const [outputStrategyId, setOutputStrategyId] = useState<OutputStrategyId>(baseScenario.outputStrategyId);
  const [failureModesStandard, setFailureModesStandard] = useState<"FMD-91" | "FMD-2016">("FMD-2016");
  // Phase 3: HDA source selector (inline vs separate file). Default inline
  // mirrors the legacy backend behavior where HDA columns live in the BOM.
  const [hdaSource, setHdaSource] = useState<HdaSource>("inline");
  // Phase 3: CCA identifier input — only meaningful in BOM-Only mode but
  // persisted so switching modes + coming back doesn't clear it.
  const [ccaPrefix, setCcaPrefix] = useState<string>(() => readStoredCcaPrefix());
  const [ccaPrefixTouched, setCcaPrefixTouched] = useState<boolean>(false);
  // In desktop mode we start with empty files, empty validations, and the
  // real FMEA run-event timeline. In browser-mock mode we seed with the
  // demo scenario so the preview is populated. See `IS_BROWSER_MOCK`.
  const [inputStates, setInputStates] = useState<InputFileState[]>(() =>
    IS_BROWSER_MOCK ? cloneInputs(baseScenario.inputs) : initialInputs,
  );
  const [validations, setValidations] = useState<ValidationMessage[]>(initialValidations);
  const [inputInspections, setInputInspections] = useState<Partial<Record<FileRole, InputInspection>>>({});
  const [workbookColumnsByRole, setWorkbookColumnsByRole] = useState<Partial<Record<FileRole, string[]>>>(DEMO_WORKBOOK_COLUMNS);
  const [templateAnalyses, setTemplateAnalyses] = useState<Partial<Record<FileRole, TemplateAnalysis>>>({});
  const [mappingOverrides, setMappingOverrides] = useState<Record<string, string>>({});
  const [runMode, setRunMode] = useState<RunMode>("idle");
  const [runIndex, setRunIndex] = useState(-1);
  const [runTemplates, setRunTemplates] = useState<RunEventTemplate[]>(initialRunTemplates);
  const [runResult, setRunResult] = useState<typeof baseScenario.runSequence.result | null>(null);
  const [runLogLines, setRunLogLines] = useState<string[]>([]);
  const [cancelledNotice, setCancelledNotice] = useState<string | null>(null);
  const [contextView, setContextView] = useState<"preview" | "run">("preview");
  const contextHeadingRef = useRef<HTMLHeadingElement | null>(null);
  // Fix 2 (Family 2): re-entrancy guard for the desktop run pipeline. Held
  // for the whole validate→execute window so a double-click on Start can't
  // launch a second run whose rejection (single-active-run guard) would clear
  // the first, live run's session.
  const isStartingRef = useRef(false);
  const setBackendState = useShellStore((state) => state.setBackendState);
  const fmeaOutputDirectory = useShellStore((state) => state.fmeaOutputDirectory);
  const setFmeaOutputDirectory = useShellStore((state) => state.setFmeaOutputDirectory);
  const pushNotification = useNotificationStore((state) => state.push);
  const setPreview = usePreviewStore((state) => state.setPreview);

  const timeline = useMemo(() => buildTimeline(runMode, runIndex, runTemplates), [runIndex, runMode, runTemplates]);
  const progress =
    runMode === "running" && runIndex >= 0
      ? runTemplates[runIndex]?.progress ?? 0
      : runResult
        ? 100
        : 0;

  const {
    beginAcceptedRun,
    resetSession: resetDesktopRunSession,
    resetSessionUnlessLive: resetDesktopRunSessionUnlessLive,
    handleExecuteRunDispatchError,
    armTerminalHandler,
    cancel: cancelDesktopRun,
    guardCrossToolRun,
    panelRunMode,
    panelTimeline,
    panelProgress,
    panelRunResult,
    panelLogLines,
    panelCancelledNotice,
    panelRunId,
    panelStatusMessage,
    panelTruncatedLogCount,
    panelErrorCode,
    panelErrorTraceback,
  } = useDesktopRunController("dark_star_fmea", {
    successMessage: (outputFile) => `Generated workbook at ${outputFile}.`,
    successTitle: "FMEA generated",
    failureTitle: "FMEA run failed",
    cancelledTitle: "FMEA run cancelled",
    mockRunMode: runMode,
    mockTimeline: timeline,
    mockProgress: progress,
    mockRunResult: runResult,
    mockLogLines: runLogLines,
    mockCancelledNotice: cancelledNotice,
  });
  const activeRun = useRunStore((state) => state.activeRun);
  const storedRunIsLive =
    !!activeRun && LIVE_PHASES.some((phase) => phase === activeRun.phase);
  const owningRunIsLive =
    LIVE_PHASES.some((phase) => phase === panelRunMode) ||
    (storedRunIsLive && activeRun.toolId === "dark_star_fmea");
  const anyRunIsLive = owningRunIsLive || storedRunIsLive;
  const fileInspectionDisabledReason = anyRunIsLive
    ? FILE_INSPECTION_PAUSED_REASON
    : undefined;

  // Onboarding EmptyState (user decision 2026-07-13) — DESKTOP ONLY. The
  // browser-mock preview deliberately stages a full demo (UX fix #5 seeded
  // the demo mapping columns so the preview shows a working tool), so the
  // pristine gate applies to the desktop runtime alone. Pristine is
  // mode-INdependent: the four modes share their input slots, so the first
  // real file browsed in ANY mode (including the target workbook) is
  // engagement and exits permanently — mode switches never resurrect the
  // panel (mirrors RefDes' mode-toggle semantics).
  const isPristine =
    !IS_BROWSER_MOCK &&
    inputStates.every((input) => input.isExample === true) &&
    panelRunMode === "idle";

  const PRISTINE_BROWSE_LABELS: Partial<Record<FileRole, string>> = {
    grouping: "Browse for grouping file",
    bom: "Browse for BOM",
    functionalFmea: "Browse for functional FMEA",
    existingFmea: "Browse for existing FMEA",
  };
  const pristineBrowseRole: FileRole =
    (FMEA_REQUIRED_ROLES[workflowId] ?? ["bom"])[0];
  const pristineBrowseLabel =
    PRISTINE_BROWSE_LABELS[pristineBrowseRole] ?? "Browse for source workbook";

  const handleLoadExample = () => {
    pushNotification({
      tone: "info",
      title: "Example files coming soon",
      detail:
        "Bundled example workbooks aren't shipping yet. For now, browse to a real workbook.",
    });
  };
  // Per-role token used to discard stale async sheet/inspect/analyze results
  // when the user changes the input under a still-resolving operation.
  const fileRequestSeq = useRoleRequestSequence<FileRole>();

  useEffect(() => {
    if (IS_BROWSER_MOCK) {
      setPreview("dark_star_fmea", baseScenario.outputPreview ?? null);
    }
  }, [setPreview]);

  // Full reset on workflow-mode change. A mode switch can change which
  // mapping rows are visible (BOM-Only hides FMEA-ID; non-merge modes hide
  // the merge-only effect rows), so clearing mapping overrides and
  // validations here is correct — they may no longer apply to the new mode.
  useEffect(() => {
    startTransition(() => {
      setValidations(initialValidations);
      setMappingOverrides({});
      // Fix B2: inspection / analysis state is keyed by FileRole and is
      // NOT workflow-specific, so the previous
      // clear-on-mode-switch was overly aggressive: the loaded files
      // stayed in inputStates (InputGrid rendered them as loaded), but
      // the mapping table lost its inspected columns and every row fell
      // back to "not mapped". Now we preserve the role-keyed maps and let the
      // per-role resolution flow handle inspection updates naturally.
      //
      // Fix R2-M4 (deferred): we intentionally do NOT clear
      // inputInspections/workbookColumnsByRole/templateAnalyses on
      // workflow change. Hidden-role data is harmless because the active
      // workflow only reads visible roles. Stale data for hidden
      // roles is harmless. If the user modifies a file externally and
      // returns to this mode, re-picking the file in the InputCard
      // triggers a fresh inspection and writes the new data over the
      // stale entry, so no staleness can leak into a run.
      setRunMode("idle");
      setRunIndex(-1);
      setRunTemplates(initialRunTemplates);
      setRunResult(null);
      setRunLogLines([]);
      setCancelledNotice(null);
      setContextView("preview");
      armTerminalHandler();
      // Fix #16: guard the reset so switching workflow MID-RUN doesn't clobber a
      // live run (which would orphan the backend job). Idle/terminal still reset.
      resetDesktopRunSessionUnlessLive();
    });
  }, [workflowId]);

  // Fix B-Strategy: changing the output strategy never changes which
  // mapping rows are visible — `isVisibleInMode` keys only on `workflowId`,
  // not on the strategy. The previous effect lumped `outputStrategyId` into
  // the full-reset deps above, so a strategy change unconditionally wiped
  // `mappingOverrides` (and validations), silently discarding the user's
  // manual mapping work which `buildRunRequest` then reverted. This
  // dedicated effect resets ONLY run-presentation state on a strategy
  // change and intentionally does NOT touch `setMappingOverrides` or
  // `setValidations`. (Like the effect above, it also fires once on mount —
  // React always runs effects on mount — which matches prior behavior.)
  useEffect(() => {
    startTransition(() => {
      setRunMode("idle");
      setRunIndex(-1);
      setRunResult(null);
      setRunLogLines([]);
      setCancelledNotice(null);
      setContextView("preview");
      armTerminalHandler();
      // Fix #16: guard the reset so switching strategy MID-RUN doesn't clobber a
      // live run (which would orphan the backend job). Idle/terminal still reset.
      resetDesktopRunSessionUnlessLive();
    });
  }, [outputStrategyId]);

  useEffect(() => {
    contextHeadingRef.current?.focus();
  }, [contextView]);

  useEffect(() => {
    if (backendClient.runtimeMode !== "browser-mock") {
      return;
    }

    if (runMode !== "running") {
      return;
    }

    const events = runTemplates;

    if (runIndex >= events.length - 1) {
      const resultTimer = window.setTimeout(() => {
        setRunResult(baseScenario.runSequence.result);
        setRunMode(baseScenario.runSequence.result.status);
      }, 520);

      return () => window.clearTimeout(resultTimer);
    }

    const timer = window.setTimeout(() => {
      setRunIndex((current) => current + 1);
    }, 520);

    return () => window.clearTimeout(timer);
  }, [runIndex, runMode, runTemplates]);

  const workflowInputs = useMemo(
    () => buildWorkflowInputs(inputStates, workflowId, hdaSource),
    [inputStates, workflowId, hdaSource],
  );
  const outputInputs = useMemo(
    () => buildOutputInputs(inputStates, outputStrategyId),
    [inputStates, outputStrategyId],
  );
  const runInputs = useMemo(
    () => [...workflowInputs, ...outputInputs],
    [workflowInputs, outputInputs],
  );
  const preferredAnalysisRole = workflowInputs.find((input) => input.source === "desktop-bridge")?.role ?? null;
  const activeInspection = preferredAnalysisRole ? inputInspections[preferredAnalysisRole] ?? null : null;
  const activeTemplateAnalysis = outputInputs.some((input) => input.role === "targetWorkbook")
    ? templateAnalyses.targetWorkbook ?? null
    : null;
  const aggregatedMappingSource = useMemo(
    () => buildAggregatedMappingSource(workflowInputs, workbookColumnsByRole),
    [workflowInputs, workbookColumnsByRole],
  );
  const inspectedColumns = aggregatedMappingSource.columns;
  const inspectedSourceLabel = aggregatedMappingSource.sourceLabelText;

  // Family 3 fix: prune orphaned manual mapping overrides. `mappingOverrides`
  // survives file/sheet changes, so an override pointing at a column ("Foo")
  // that the newly-inspected workbook no longer exposes would leave the
  // MappingTable still showing "Foo" while the backend silently discards it
  // and auto-detects (`map_columns` honours an override only when
  // `overrides[std] in df.columns`). Drop every override whose target column
  // is no longer in the inspected set — but keep DO_NOT_MAP sentinels (an
  // explicit unmap, not a column reference) and never prune while no file has
  // been inspected yet (empty set), where dropping would clobber overrides the
  // user set against options that simply haven't loaded. `inspectedColumns`
  // is the union across every visible role, which is exactly the membership
  // set every mapping row's dropdown draws from, so this is the right check.
  useEffect(() => {
    if (inspectedColumns.length === 0) {
      return;
    }
    const allowed = new Set(inspectedColumns);
    setMappingOverrides((current) => {
      let changed = false;
      const next: Record<string, string> = {};
      for (const [canonical, value] of Object.entries(current)) {
        if (value === DO_NOT_MAP_VALUE || allowed.has(value)) {
          next[canonical] = value;
        } else {
          changed = true;
        }
      }
      // Return the same reference when nothing was pruned so we don't trigger
      // a needless re-render (and never loop on this effect).
      return changed ? next : current;
    });
  }, [inspectedColumns]);

  const effectiveMappings = useMemo(
    () =>
      buildFmeaMappingRows(
        workflowId,
        failureModesStandard,
        inspectedColumns,
        inspectedSourceLabel,
        aggregatedMappingSource.optionLabels,
      ),
    [workflowId, failureModesStandard, inspectedColumns, inspectedSourceLabel, aggregatedMappingSource.optionLabels],
  );
  const analysisCards = useMemo(
    () => buildAnalysisCards(activeInspection, activeTemplateAnalysis),
    [activeInspection, activeTemplateAnalysis],
  );
  const activeInspectionRoleLabel =
    (workflowInputs.find((input) => input.role === activeInspection?.role) ?? outputInputs.find((input) => input.role === activeInspection?.role))
      ?.label ?? null;
  const inspectionCapWarning = useMemo(
    () => buildInspectionCapWarning(activeInspection, activeInspectionRoleLabel),
    [activeInspection, activeInspectionRoleLabel],
  );
  const previewValidations = useMemo(
    () => (inspectionCapWarning ? [inspectionCapWarning, ...validations] : validations),
    [inspectionCapWarning, validations],
  );

  async function handleRevealOutput(path: string) {
    try {
      await backendClient.revealInFileManager(parentDirectoryForPath(path));
    } catch (error) {
      const detail = describeBackendError(error, "Failed to open output folder");
      pushNotification({ tone: "error", title: "Open output folder failed", detail });
    }
  }

  const mappingCoverage =
    inspectedColumns.length > 0 && effectiveMappings.length > 0
      ? Math.round(
          (effectiveMappings.filter((row) => row.status === "mapped").length / effectiveMappings.length) * 100,
        )
      : null;
  // "—" (not "TBD") before any inspection: a literal TBD in the hero
  // metric reads as unfinished UI (UX findings 2026-07-07 #2).
  const mappingCoverageLabel = mappingCoverage === null ? "—" : `${mappingCoverage}%`;

  const activeWorkflow = workflowOptions.find((workflow) => workflow.id === workflowId) ?? workflowOptions[0];

  // Phase 3 (A6): BOM-Only mode gates on a non-empty CCA identifier
  // that matches the pattern backend Phase 4 will also enforce.
  const isBomOnly = workflowId === "bom_only";
  const ccaPrefixValid = CCA_PREFIX_PATTERN.test(ccaPrefix);
  const ccaPrefixError =
    isBomOnly && ccaPrefixTouched && !ccaPrefixValid
      ? "Enter 1–8 uppercase letters, digits, or hyphens (e.g. PSU)."
      : null;
  const bomOnlyBlockedReason =
    isBomOnly && !ccaPrefixValid
      ? "Enter a CCA identifier in the Workflow card before running BOM-Only mode."
      : null;

  const handleCcaPrefixChange = (raw: string) => {
    const sanitized = sanitizeCcaPrefix(raw);
    setCcaPrefix(sanitized);
    setCcaPrefixTouched(true);
    try {
      if (typeof window !== "undefined") {
        window.localStorage.setItem(CCA_PREFIX_STORAGE_KEY, sanitized);
      }
    } catch {
      // localStorage quota / privacy mode — drop silently, the in-memory
      // state is still authoritative for the current session.
    }
  };

  // Phase 3 (A7): output folder picker. On the browser preview we surface
  // a gentle notification instead of silently failing — the plugin dialog
  // is a no-op in that runtime.
  const handleBrowseOutputDirectory = async () => {
    if (backendClient.runtimeMode !== "desktop-bridge") {
      pushNotification({
        tone: "info",
        title: "Desktop runtime required",
        detail: "Picking an output folder uses the native OS dialog — run the Tauri desktop shell to set a real path.",
      });
      return;
    }

    try {
      const picked = await backendClient.openDirectory(fmeaOutputDirectory ?? undefined);
      if (picked) {
        setFmeaOutputDirectory(picked);
      }
    } catch (error) {
      const detail = describeBackendError(error, "Unknown folder picker failure");
      pushNotification({
        tone: "error",
        title: "Folder picker failed",
        detail,
      });
    }
  };

  const handleClearOutputDirectory = () => {
    setFmeaOutputDirectory(null);
  };

  async function indexRemainingWorkbookSheets(
    role: FileRole,
    path: string,
    selectedSheet: string,
    workbookSheets: string[],
    token: number,
  ) {
    const remainingSheets = workbookSheets.filter((sheetName) => !!sheetName && sheetName !== selectedSheet);
    if (remainingSheets.length === 0) {
      return;
    }

    const successfulInspections: InspectInputResult[] = [];
    const skippedSheets: string[] = [];

    for (const sheetName of remainingSheets) {
      try {
        const inspection = await backendClient.inspectInput(path, sheetName, role);
        if (!fileRequestSeq.isCurrent(role, token)) {
          return;
        }
        successfulInspections.push(inspection);
      } catch {
        if (!fileRequestSeq.isCurrent(role, token)) {
          return;
        }
        skippedSheets.push(sheetName);
      }
    }

    if (!fileRequestSeq.isCurrent(role, token) || successfulInspections.length === 0) {
      return;
    }

    let nextColumns: string[] = [];
    setWorkbookColumnsByRole((current) => {
      nextColumns = buildWorkbookColumnUnion([
        current[role] ?? [],
        ...successfulInspections.map((inspection) => inspection.columns),
      ]);
      return {
        ...current,
        [role]: nextColumns,
      };
    });

    const mode = successfulInspections[successfulInspections.length - 1]?.mode ?? "desktop-bridge";
    const skippedDetail =
      skippedSheets.length > 0
        ? ` Skipped ${skippedSheets.length} non-tabular sheet${skippedSheets.length === 1 ? "" : "s"}.`
        : "";

    setBackendState({
      backendStatus: "ready",
      backendMode: mode,
      backendMessage: `Indexed ${nextColumns.length} unique header${nextColumns.length === 1 ? "" : "s"} across ${successfulInspections.length + 1} readable sheet${successfulInspections.length === 0 ? "" : "s"} for ${role}.${skippedDetail}`,
      lastBackendCheckAt: new Date().toISOString(),
    });
  }

  async function inspectRole(role: FileRole, path: string, sheet: string, workbookSheets?: string[]) {
    if (!sheet) {
      return;
    }

    // Stale-safe: bump the per-role sequence and capture the token. After
    // every await, abort if a newer request has started for this role.
    const token = fileRequestSeq.begin(role);

    setInputStates((current) =>
      current.map((input) =>
        input.role === role
          ? {
              ...input,
              isAnalyzing: true,
              resolutionError: null,
              tag: "Analyzing",
            }
          : input,
      ),
    );

    try {
      if (role === "targetWorkbook" && shouldShowTargetWorkbook(outputStrategyId)) {
        const template = await backendClient.analyzeTemplate(path, sheet, role);
        if (!fileRequestSeq.isCurrent(role, token)) return;
        setInputStates((current) =>
          current.map((input) =>
            input.role === role ? { ...input, isAnalyzing: false, tag: "Analyzed" } : input,
          ),
        );
        setTemplateAnalyses((current) => ({
          ...current,
          [role]: {
            role,
            path: template.path,
            sheet: template.sheet,
            headerRow: template.header_row,
            columns: template.columns,
            mergedRangeCount: template.merged_range_count,
            freezePanes: template.freeze_panes,
            protectedSheet: template.protected_sheet,
            rowsScanned: template.rows_scanned,
            headerRowsScanned: template.header_rows_scanned,
            columnsScanned: template.columns_scanned,
            rowCapApplied: template.row_cap_applied,
            columnCapApplied: template.column_cap_applied,
            headerSearchCapApplied: template.header_search_cap_applied,
            mode: template.mode,
          },
        }));
        setBackendState({
          backendStatus: "ready",
          backendMode: template.mode,
          backendMessage: `Analyzed template sheet ${template.sheet}.`,
          lastBackendCheckAt: new Date().toISOString(),
        });
      } else {
        const selectedInspection = await backendClient.inspectInput(path, sheet, role);
        if (!fileRequestSeq.isCurrent(role, token)) return;
        const workbookColumns = buildWorkbookColumnUnion([selectedInspection.columns]);
        setInputStates((current) =>
          current.map((input) =>
            input.role === role ? { ...input, isAnalyzing: false, tag: "Analyzed" } : input,
          ),
        );
        setInputInspections((current) => ({
          ...current,
          [role]: {
            role,
            path: selectedInspection.path,
            sheet: selectedInspection.sheet,
            headerRow: selectedInspection.header_row,
            rowCount: selectedInspection.row_count,
            columns: selectedInspection.columns,
            previewRows: selectedInspection.preview_rows,
            rowsScanned: selectedInspection.rows_scanned,
            headerRowsScanned: selectedInspection.header_rows_scanned,
            columnsScanned: selectedInspection.columns_scanned,
            rowCapApplied: selectedInspection.row_cap_applied,
            columnCapApplied: selectedInspection.column_cap_applied,
            headerSearchCapApplied: selectedInspection.header_search_cap_applied,
            mode: selectedInspection.mode,
          },
        }));
        setWorkbookColumnsByRole((current) => ({
          ...current,
          [role]: workbookColumns,
        }));
        setBackendState({
          backendStatus: "ready",
          backendMode: selectedInspection.mode,
          backendMessage: `Inspected ${selectedInspection.sheet} and indexed ${workbookColumns.length} unique header${workbookColumns.length === 1 ? "" : "s"} from the selected sheet.`,
          lastBackendCheckAt: new Date().toISOString(),
        });
        void indexRemainingWorkbookSheets(
          role,
          path,
          selectedInspection.sheet,
          Array.from(new Set(workbookSheets ?? [])),
          token,
        );
      }
    } catch (error) {
      if (!fileRequestSeq.isCurrent(role, token)) return;
      const detail = describeBackendError(error, "Unknown workbook analysis failure");
      setInputStates((current) =>
        current.map((input) =>
          input.role === role
            ? {
                ...input,
                isAnalyzing: false,
                resolutionError: detail,
                tag: "Review needed",
              }
            : input,
        ),
      );
      setBackendState({
        backendStatus: "error",
        backendMessage: detail,
        lastBackendCheckAt: new Date().toISOString(),
      });
      pushNotification({
        tone: "error",
        title: role === "targetWorkbook" ? "Template analysis failed" : "Workbook inspection failed",
        detail,
      });
    }
  }

  async function handleBrowse(role: FileRole) {
    const pickedPath = await backendClient.openExcelFile();

    if (!pickedPath) {
      if (backendClient.runtimeMode !== "desktop-bridge") {
        pushNotification({
          tone: "info",
          title: "Browser preview active",
          detail: "Run the Tauri desktop shell to browse a real workbook and load sheets from Python.",
        });
      }
      return;
    }

    // Stale-safe: a fresh browse for this role obsoletes any in-flight
    // listSheets/inspect/analyze for the same role.
    const token = fileRequestSeq.begin(role);

    setInputStates((current) =>
      current.map((input) =>
        input.role === role
          ? {
              ...input,
              path: pickedPath,
              source: "desktop-bridge",
              // A real file replaces the seeded placeholder — clears the
              // pristine EmptyState so the full input grid renders. FMEA
              // never read this flag before the onboarding panel existed.
              isExample: false,
              isResolvingSheets: true,
              resolutionError: null,
              tag: "Inspecting",
            }
          : input,
      ),
    );
    setInputInspections((current) => {
      const next = { ...current };
      delete next[role];
      return next;
    });
    setWorkbookColumnsByRole((current) => {
      const next = { ...current };
      delete next[role];
      return next;
    });
    setTemplateAnalyses((current) => {
      const next = { ...current };
      delete next[role];
      return next;
    });
    // Fix 2: a new file invalidates the previous validate_run result — clear
    // the stale validation cards (including the backend "ready-to-run" info
    // card) so the Preview tab no longer describes the OLD file/sheet. Guarded
    // by the early return above, so browser-mock demo cards are never wiped.
    setValidations([]);
    // Fix #17: clear a lingering terminal run before flipping to busy, else
    // useBackendBusyReset (terminal phase + busy) instantly wipes this
    // "Inspecting..." chip. Guarded so a live sibling run survives.
    resetDesktopRunSessionUnlessLive();
    setBackendState({
      backendStatus: "busy",
      backendMessage: `Inspecting workbook for ${role}...`,
    });

    try {
      const result = await backendClient.listSheets(pickedPath);
      if (!fileRequestSeq.isCurrent(role, token)) return;
      setInputStates((current) =>
        current.map((input) =>
          input.role === role
            ? {
                ...input,
                path: result.path,
                sheets: result.sheets.map((sheet) => ({
                  id: sheet.toLowerCase().replace(/\s+/g, "_"),
                  label: sheet,
                })),
                selectedSheet: result.sheets[0] ?? "",
                source: "desktop-bridge",
                isResolvingSheets: false,
                isAnalyzing: false,
                resolutionError: result.sheets.length > 0 ? null : "No sheets were found in the selected workbook.",
                tag: result.sheets.length > 0 ? "Desktop" : "Empty workbook",
              }
            : input,
        ),
      );
      setBackendState({
        backendStatus: "ready",
        backendMode: result.mode,
        backendMessage: `Loaded ${result.sheets.length} sheet${result.sheets.length === 1 ? "" : "s"} from ${role}.`,
        lastBackendCheckAt: new Date().toISOString(),
      });
      if (result.sheets[0]) {
        await inspectRole(role, result.path, result.sheets[0], result.sheets);
      }
    } catch (error) {
      if (!fileRequestSeq.isCurrent(role, token)) return;
      const detail = describeBackendError(error, "Unknown sheet inspection failure");
      setInputStates((current) =>
        current.map((input) =>
          input.role === role
            ? {
                ...input,
                source: backendClient.runtimeMode === "desktop-bridge" ? "desktop-bridge" : input.source,
                isResolvingSheets: false,
                isAnalyzing: false,
                resolutionError: detail,
                tag: "Review needed",
              }
            : input,
        ),
      );
      setBackendState({
        backendStatus: "error",
        backendMessage: detail,
        lastBackendCheckAt: new Date().toISOString(),
      });
      pushNotification({
        tone: "error",
        title: "Workbook inspection failed",
        detail,
      });
    }
  }

  function handleSheetChange(role: FileRole, selectedSheet: string) {
    let nextPath = "";
    let nextSheets: string[] = [];
    setInputStates((current) =>
      current.map((input) => {
        if (input.role !== role) {
          return input;
        }

        nextPath = input.path;
        nextSheets = input.sheets.map((sheetOption) => sheetOption.label);
        return {
          ...input,
          selectedSheet,
        };
      }),
    );

    if (backendClient.runtimeMode === "desktop-bridge" && nextPath) {
      // Fix 2: a sheet change re-inspects the workbook, invalidating the prior
      // validate_run result — clear the stale validation cards so the Preview
      // tab does not describe the previously-selected sheet. Kept on the
      // desktop-bridge path so browser-mock demo cards are never wiped.
      setValidations([]);
      void inspectRole(role, nextPath, selectedSheet, nextSheets);
    }
  }

  async function handleStartRun() {
    // Phase 3 (A6): frontend-side BOM-Only CCA prefix gate. Mark the
    // field as touched so the inline error renders, and short-circuit
    // before we even build the request.
    if (isBomOnly && !ccaPrefixValid) {
      setCcaPrefixTouched(true);
      pushNotification({
        tone: "warning",
        title: "CCA identifier required",
        detail: "Enter a CCA identifier in the Workflow card before running BOM-Only mode.",
      });
      return;
    }

    if (backendClient.runtimeMode !== "desktop-bridge") {
      setRunTemplates(baseScenario.runSequence.events);
      setRunLogLines([]);
      setCancelledNotice(null);
      setRunResult(null);
      setContextView("run");
      setRunMode("running");
      setRunIndex(0);
      return;
    }

    // Cross-tool guard: another tool's live run must not be clobbered by
    // this start's rejection path — toast and bail before sending anything.
    if (guardCrossToolRun()) {
      return;
    }

    // Fix 2 (Family 2): re-entrancy guard. The Start button is not disabled
    // during the async validate→execute window, so a fast double-click could
    // fire a second pipeline; the second executeRun is rejected by Python's
    // single-active-run guard and its catch used to wipe the FIRST, live run.
    // Swallow the re-entrant call here.
    if (isStartingRef.current) {
      return;
    }
    isStartingRef.current = true;

    const runRequest = buildRunRequest(
      workflowId,
      outputStrategyId,
      runInputs,
      effectiveMappings,
      mappingOverrides,
      failureModesStandard,
      {
        ccaPrefix: isBomOnly ? ccaPrefix : null,
        outputDirectory: fmeaOutputDirectory,
        hdaSource,
      },
    );

    // Fix R2-C1: clear any stale active run from a previous run BEFORE flipping
    // the busy chip. If the previous run's phase is still "success"/"cancelled"/
    // "failure" when we flip backendStatus to "busy", useBackendBusyReset will
    // see (terminal phase + busy) and instantly clear the busy chip, making the
    // "Validating..." message flicker away on every second run.
    resetDesktopRunSession();

    setContextView("run");
    setRunLogLines([]);
    setRunResult(null);
    setCancelledNotice(null);
    setBackendState({
      backendStatus: "busy",
      backendMessage: "Validating run configuration...",
    });

    try {
      const validation = await backendClient.validateRun(runRequest);
      setValidations(validation.validations);
      // Phase 4: publish output_preview to the shared store so the
      // Review drawer can render the sampled rows. Clearing on failure
      // prevents a stale preview from lingering after an input change.
      setPreview("dark_star_fmea", validation.output_preview ?? null);

      if (!validation.ok) {
        setRunMode("idle");
        setRunIndex(-1);
        setRunTemplates(fmeaRunEvents);
        setContextView("preview");
        resetDesktopRunSession();
        setBackendState({
          backendStatus: "ready",
          backendMode: validation.mode,
          backendMessage: validation.toast_text,
          lastBackendCheckAt: new Date().toISOString(),
        });
        pushNotification({
          tone: "warning",
          title: "Run blocked",
          detail: validation.toast_text,
        });
        return;
      }

      setRunTemplates(fmeaRunEvents);
      setBackendState({
        backendStatus: "busy",
        backendMode: validation.mode,
        backendMessage: "Generating FMEA workbook...",
      });

      armTerminalHandler();
      beginAcceptedRun(await backendClient.executeRun(runRequest));
    } catch (error) {
      if (handleExecuteRunDispatchError(error)) {
        return;
      }
      const detail = describeBackendError(error, "Unknown backend execution failure");
      // Fix 2 (Family 2): guarded reset — must not clobber a live sibling run.
      resetDesktopRunSessionUnlessLive();
      setContextView("preview");
      setBackendState({
        backendStatus: "error",
        backendMessage: detail,
        lastBackendCheckAt: new Date().toISOString(),
      });
      pushNotification({
        tone: "error",
        title: "FMEA run failed",
        detail,
      });
    } finally {
      // Release the re-entrancy guard once the validate→execute window has
      // closed. A run accepted in this window is owned by the run store and
      // survives.
      isStartingRef.current = false;
    }
  }

  const getDisabledSheetReason = (input: InputFileState) => {
    if (input.isResolvingSheets) {
      return "Loading sheets from the desktop bridge…";
    }
    if (input.sheets.length === 0) {
      return "Waiting for workbook…";
    }
    return undefined;
  };

  return (
    <div className="tool-workspace">
      {/* No per-tool banner: the shell topbar is the single title block
          (title + description + backend-mode chip live there). */}
      <section className="workspace-grid workspace-grid--single">
        <div className="workspace-grid__main">
          <SectionCard
            className="section-card--compact"
            step={1}
            title="Generation Options"
            eyebrow="Configuration"
            description="Choose the generation path, confirm the standards in play, and load the source workbooks this mode needs."
            actions={
              <div className="header-metrics">
                <span className="header-metric">
                  <span>Mode</span>
                  <strong>{activeWorkflow.title}</strong>
                </span>
                <span className="header-metric">
                  <span>Auto-mapped</span>
                  {/* The one hero metric for this tool (design-system
                      .hero-metric, shipped 0.4.5, first adopted here). */}
                  <strong className="hero-metric">{mappingCoverageLabel}</strong>
                </span>
              </div>
            }
          >
            <div className="setup-grid">
              <div className="setup-block setup-block--full">
                <OptionsField
                  label="Mode"
                  hint="Choose the starting point that best matches your source data."
                >
                  <WorkflowSelector
                    workflows={workflowOptions}
                    selectedWorkflowId={workflowId}
                    onSelect={setWorkflowId}
                    disabled={owningRunIsLive}
                  />
                </OptionsField>
              </div>

              <div className="setup-block">
                <OptionsField
                  label="Failure Modes Standard"
                  hint={failureModesHintForStandard(failureModesStandard)}
                >
                  <ToggleChip<"FMD-91" | "FMD-2016">
                    ariaLabel="Failure modes standard"
                    value={failureModesStandard}
                    onChange={(next) => {
                      const nextStandard = next as "FMD-91" | "FMD-2016";
                      // Fix B-FMD: the FMD Commodity Type rows carry a
                      // dynamic canonical label keyed by the active
                      // standard, and mappingOverrides is keyed by that
                      // resolved label. Toggling the standard rebuilds
                      // those rows under the other standard's key, so we
                      // must migrate any manual overrides to the new keys
                      // or they orphan and the UI silently reverts.
                      setMappingOverrides((current) =>
                        migrateFmdOverrides(current, failureModesStandard, nextStandard),
                      );
                      setFailureModesStandard(nextStandard);
                    }}
                    options={[
                      { value: "FMD-91", label: "FMD-91" },
                      { value: "FMD-2016", label: "FMD-2016" },
                    ]}
                  />
                </OptionsField>
              </div>

              <div className="setup-block">
                <OptionsField
                  label="HDA source"
                  hint="Where the HDA taxonomy columns live — inline in the BOM or a separate workbook."
                >
                  <ToggleChip<HdaSource>
                    ariaLabel="HDA source"
                    value={hdaSource}
                    onChange={(next) => setHdaSource(next as HdaSource)}
                    options={[
                      // Short first label so both chips sit side by side (the
                      // long "HDA columns inline in BOM" wrapped the group
                      // into a stack); the OptionsField hint carries context.
                      { value: "inline", label: "Inline in BOM" },
                      { value: "separate", label: "Separate HDA file" },
                    ]}
                  />
                </OptionsField>
              </div>

              {isBomOnly ? (
                <div className="setup-block">
                  <OptionsField
                    label="CCA Identifier"
                    hint="Used as the prefix for generated FMEA-IDs — e.g. `PSU` produces `PSU-C200-A`. 1–8 uppercase letters, digits, or hyphens."
                    required
                    htmlFor="fmea-cca-prefix"
                  >
                    <input
                      id="fmea-cca-prefix"
                      type="text"
                      className="fmea-cca-input"
                      value={ccaPrefix}
                      onChange={(event) => handleCcaPrefixChange(event.target.value)}
                      onBlur={() => setCcaPrefixTouched(true)}
                      maxLength={8}
                      placeholder="e.g. PSU"
                      aria-label="CCA identifier"
                      aria-invalid={ccaPrefixError ? true : undefined}
                      aria-describedby={ccaPrefixError ? "fmea-cca-prefix-error" : undefined}
                      autoComplete="off"
                      spellCheck={false}
                    />
                  </OptionsField>
                  {ccaPrefixError ? (
                    <p
                      id="fmea-cca-prefix-error"
                      className="fmea-cca-input__error"
                      role="alert"
                    >
                      {ccaPrefixError}
                    </p>
                  ) : null}
                </div>
              ) : null}

              <div className="setup-block setup-block--full">
                {isPristine ? (
                  <EmptyState
                    icon={TreeStructure}
                    headline="Build or merge an FMEA workbook"
                    body="Browse for your source workbook, or load the example set to explore the workflow first."
                    primaryAction={{
                      label: pristineBrowseLabel,
                      disabled: anyRunIsLive,
                      disabledReason: fileInspectionDisabledReason,
                      onClick: () => {
                        void handleBrowse(pristineBrowseRole);
                      },
                    }}
                    secondaryAction={{
                      label: "Load example",
                      onClick: handleLoadExample,
                    }}
                  />
                ) : (
                  <InputGrid
                    inputs={workflowInputs}
                    onBrowse={handleBrowse}
                    onSheetChange={handleSheetChange}
                    browseDisabledReason={fileInspectionDisabledReason}
                    getDisabledSheetReason={getDisabledSheetReason}
                  />
                )}
              </div>
            </div>
          </SectionCard>

          <SectionCard
            className="section-card--compact"
            step={2}
            title="Outputs"
            eyebrow="Workbook & folder"
            description={
              workflowId === "fill_gaps"
                ? "Choose how the generator writes the finished workbook. Fill-gaps often targets an existing workbook copy, but the output strategy stays explicit here."
                : "Choose how the generator writes the finished workbook, then confirm the destination workbook and output folder."
            }
          >
            <div className="setup-grid">
              <div className="setup-block setup-block--full">
                <OptionsField
                  label="Output Strategy"
                  hint="How the generator writes its results — new workbook, or onto a copy of an existing one."
                >
                  <StrategySelector
                    strategies={outputStrategies}
                    selectedStrategyId={outputStrategyId}
                    onSelect={setOutputStrategyId}
                    disabled={owningRunIsLive}
                  />
                </OptionsField>
              </div>

              {outputInputs.length > 0 ? (
                <div className="setup-block setup-block--full">
                  <InputGrid
                    inputs={outputInputs}
                    onBrowse={handleBrowse}
                    onSheetChange={handleSheetChange}
                    browseDisabledReason={fileInspectionDisabledReason}
                    getDisabledSheetReason={getDisabledSheetReason}
                  />
                </div>
              ) : null}

              <div className="setup-block setup-block--full">
                <OptionsField
                  label="Output Folder"
                  hint="Defaults to the folder of your first loaded input."
                >
                  <div className="fmea-output-folder">
                    <code className="fmea-output-folder__path" title={fmeaOutputDirectory ?? undefined}>
                      {fmeaOutputDirectory ?? "Default: alongside first input"}
                    </code>
                    <div className="fmea-output-folder__actions">
                      <button
                        type="button"
                        className="ghost-button fmea-output-folder__button"
                        onClick={() => {
                          void handleBrowseOutputDirectory();
                        }}
                      >
                        <FolderOpen size={14} weight="regular" aria-hidden="true" />
                        <span>Change…</span>
                      </button>
                      {fmeaOutputDirectory ? (
                        <button
                          type="button"
                          className="ghost-button"
                          onClick={handleClearOutputDirectory}
                        >
                          Reset
                        </button>
                      ) : null}
                    </div>
                  </div>
                </OptionsField>
              </div>
            </div>
          </SectionCard>

          <SectionCard
            className="section-card--compact"
            step={3}
            title="Column Mapping"
            eyebrow="Review"
            description={
              inspectedColumns.length > 0
                ? `Mapping options are currently informed by ${inspectedSourceLabel}.`
                : "Default profile behavior. Select files above to enable column mapping."
            }
          >
            {inspectedColumns.length > 0 ? (
              <div className="analysis-summary">
                <strong>Live workbook columns loaded into mapping review</strong>
                <p>
                  {inspectedColumns.length} column{inspectedColumns.length === 1 ? "" : "s"} available from{" "}
                  {inspectedSourceLabel}.
                </p>
                <div className="analysis-summary__chips">
                  {inspectedColumns.slice(0, 8).map((column) => (
                    <span key={column} className="column-tag">
                      {column}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
            <MappingTable
              rows={effectiveMappings}
              overrides={mappingOverrides}
              onOverride={(canonical, mappedTo) =>
                setMappingOverrides((current) => ({ ...current, [canonical]: mappedTo }))
              }
              onApplyRecommendation={(canonical, suggested) =>
                setMappingOverrides((current) => ({ ...current, [canonical]: suggested }))
              }
              onApplyAllSuggestions={() => {
                setMappingOverrides((current) => {
                  const next = { ...current };
                  for (const row of effectiveMappings) {
                    const mapped = next[row.canonical] ?? row.mappedTo;
                    if (row.recommendation && row.options.includes(row.recommendation) && row.recommendation !== mapped) {
                      next[row.canonical] = row.recommendation;
                    }
                  }
                  return next;
                });
              }}
              onClearAllMappings={() => {
                // "Clear all" is an explicit Do-Not-Map request — we set
                // every row to the DO_NOT_MAP sentinel so the backend sees
                // intentional unmapping rather than a blank mapping that
                // could be silently auto-resolved. Phase 2 infra change.
                setMappingOverrides(() => {
                  const next: Record<string, string> = {};
                  for (const row of effectiveMappings) {
                    next[row.canonical] = DO_NOT_MAP_VALUE;
                  }
                  return next;
                });
              }}
            />
          </SectionCard>
        </div>

        <aside className="workspace-grid__side workspace-grid__side--sticky">
          <SectionCard
            className="section-card--compact"
            variant="divided"
            title="Review Panel"
            eyebrow="Context"
            description={
              contextView === "preview"
                ? "Preview output and validation in one focused panel."
                : "Run feedback stays isolated so it does not compete with setup."
            }
            actions={
              <ContextTabs
                ariaLabel="Context panel"
                tabs={[
                  { id: "preview", label: "Preview" },
                  { id: "run", label: "Run" },
                ]}
                activeId={contextView}
                onChange={setContextView}
              />
            }
          >
            <h3 className="sr-only-focusable" ref={contextHeadingRef} tabIndex={-1}>
              {contextView === "preview" ? "Preview panel" : "Run panel"}
            </h3>
            <ErrorBoundary
              title="Panel failed to render"
              detail="The active FMEA context panel hit an error. Reload this panel without tearing down the shell."
            >
              {contextView === "preview" ? (
                <ValidationPreview
                  validations={previewValidations}
                  previewRows={IS_BROWSER_MOCK ? baseScenario.previewRows : []}
                  analysisCards={analysisCards}
                />
              ) : (
                <RunStatePanel
                  runMode={panelRunMode}
                  progress={panelProgress}
                  timeline={panelTimeline}
                  result={panelRunResult}
                  cancelledNotice={panelCancelledNotice}
                  logLines={panelLogLines}
                  truncatedLogCount={panelTruncatedLogCount}
                  errorCode={panelErrorCode}
                  errorTraceback={panelErrorTraceback}
                  startLabel={backendClient.runtimeMode === "desktop-bridge" ? "Generate FMEA" : "Start demo run"}
                  runId={panelRunId}
                  statusMessage={panelStatusMessage}
                  startDisabled={bomOnlyBlockedReason !== null}
                  startDisabledReason={bomOnlyBlockedReason ?? undefined}
                  onRevealOutput={
                    backendClient.runtimeMode === "desktop-bridge" ? (path) => void handleRevealOutput(path) : undefined
                  }
                  onStart={() => {
                    void handleStartRun();
                  }}
                  onCancel={() => {
                    // Desktop-bridge cancel is owned by the shared controller
                    // (guarded on ``starting``/``running`` to avoid stale-id
                    // and double-click second-cancels reaching the sidecar).
                    if (cancelDesktopRun()) {
                      return;
                    }

                    // Browser-mock: the HoldButton already captured the
                    // press-and-hold confirmation, so cancel immediately.
                    setRunMode("idle");
                    setRunIndex(-1);
                    setRunResult(null);
                    setCancelledNotice("Demo run cancelled. The workspace returned to a safe idle state without losing context.");
                  }}
                />
              )}
            </ErrorBoundary>
          </SectionCard>
        </aside>
      </section>
    </div>
  );
}
