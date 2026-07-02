import { startTransition, useEffect, useMemo, useRef, useState } from "react";
import { InputGrid } from "../../components/InputGrid";
import { MappingTable } from "../../components/MappingTable";
import { RunStatePanel } from "../../components/RunStatePanel";
import { SectionCard } from "../../components/SectionCard";
import { ValidationPreview } from "../../components/ValidationPreview";
import { WorkflowSelector } from "../../components/WorkflowSelector";
import { CheckboxField } from "../../components/primitives/CheckboxField";
import { ContextTabs } from "../../components/primitives/ContextTabs";
import { EmptyState } from "../../components/primitives/EmptyState";
import { OptionsSection } from "../../components/primitives/OptionsSection";
import { OutputFolderPicker } from "../../components/OutputFolderPicker";
import { ColumnPairPicker } from "./ColumnPairPicker";
import { GitDiff } from "@phosphor-icons/react";
import {
  bomCompareWorkflowOptions,
  bomCompareDemoScenarios,
  bomCompareGroupMappings,
  bomCompareCustomMappings,
  bomCompareCustomColumns,
} from "../../mocks/scenarios";
import type {
  ColumnMappingRow,
  ComparePair,
  FileRole,
  InputFileState,
  RunEventTemplate,
  RunMode,
  ValidationMessage,
  WorkflowId,
} from "../../app/types";
import { DO_NOT_MAP_VALUE } from "../../app/types";
import { backendClient, type RunRequestBody } from "../../shared/backend/client";
import { deriveMappingRows } from "../../shared/mapping/deriveMappingRows";
import { buildWorkbookColumnUnion } from "../fmea/mappingAnalysis";
import { describeBackendError } from "../../shared/backend/cancelError";
import { parentDirectoryForPath } from "../../shared/backend/fileManager";
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
import { useShellStore } from "../../stores/shellStore";

const workflowInputRoles: Partial<Record<WorkflowId, FileRole[]>> = {
  bom_compare_group: ["grouping", "bom"],
  bom_compare_custom: ["bomA", "bomB"],
};

/**
 * Bug fix: which file role each canonical mapping addresses, so the Column
 * Mapping dropdowns can be rebuilt from THAT role's inspected workbook
 * headers instead of the static fixture options. Verified against
 * `backend/python/bom_compare/runtime.py`:
 *   - group:  grouping_group_col / grouping_refdes_col read the grouping file;
 *             bom_refdes_col / bom_desc_col read the BOM file.
 *   - custom: refdes_col_a is File 1 (bomA); refdes_col_b is File 2 (bomB).
 */
const canonicalRolesByWorkflow: Partial<Record<WorkflowId, Record<string, FileRole>>> = {
  bom_compare_group: {
    grouping_group_col: "grouping",
    grouping_refdes_col: "grouping",
    bom_refdes_col: "bom",
    bom_desc_col: "bom",
  },
  bom_compare_custom: {
    refdes_col_a: "bomA",
    refdes_col_b: "bomB",
  },
};

/**
 * Family 1 fix: seed inputs from the demo scenario in browser-mock mode (so
 * the preview is populated) but from empty desktop slots in the real desktop
 * runtime (so no fake example path leaks into a run). Used for both the
 * initial `useState` seed and the workflow-change scenario-seed fallback —
 * without it, switching to a never-visited workflow re-introduced the example
 * paths in desktop mode.
 */
function seedInputsForRuntime(inputs: InputFileState[]): InputFileState[] {
  return backendClient.runtimeMode === "browser-mock"
    ? cloneInputs(inputs)
    : emptyInputsFromScenario(inputs);
}

/**
 * Tier-1 #5: browser-mock seed for the ColumnPairPicker. The picker derives its
 * column choices from inspected workbook headers (`workbookColumnsByRole`),
 * which only populate in the desktop runtime. In browser-mock there is no
 * inspect round-trip, so we seed the custom workflow's two roles from the demo
 * scenario's example headers (Wiring Invariant #4/#7) — without this the
 * browser preview's picker would always show its empty state. Returns an empty
 * record for the group workflow (no picker there) and in the desktop runtime
 * (real inspection populates it).
 */
function seedColumnsForWorkflow(
  workflowId: WorkflowId,
): Partial<Record<FileRole, string[]>> {
  if (
    backendClient.runtimeMode === "browser-mock" &&
    workflowId === "bom_compare_custom"
  ) {
    return { bomA: bomCompareCustomColumns, bomB: bomCompareCustomColumns };
  }
  return {};
}

/**
 * A slot whose async inspection was interrupted by a workflow switch must
 * not be cached with its busy flags set — restoring `isResolvingSheets` /
 * `isAnalyzing` verbatim would leave Browse and the sheet picker disabled
 * forever (the orphaned continuation can never clear them because it maps
 * over the OTHER workflow's roles). Convert the slot to a recoverable
 * "Review needed" state instead.
 */
function sanitizeInterruptedInput(input: InputFileState): InputFileState {
  if (!input.isResolvingSheets && !input.isAnalyzing) {
    return input;
  }
  return {
    ...input,
    isResolvingSheets: false,
    isAnalyzing: false,
    tag: "Review needed",
    resolutionError: "Inspection was interrupted by the workflow switch. Browse the file again.",
  };
}

export function BomCompareTool() {
  const baseScenario = bomCompareDemoScenarios[0];
  const [workflowId, setWorkflowId] = useState<WorkflowId>(baseScenario.workflowId);
  const [inputStates, setInputStates] = useState<InputFileState[]>(() =>
    seedInputsForRuntime(baseScenario.inputs),
  );
  const [mappingOverrides, setMappingOverrides] = useState<Record<string, string>>({});
  // Bug fix: per-role inspected workbook headers, populated from
  // inspection.columns in inspectRole's success path and cleared for a role
  // on re-browse. A SINGLE record keyed by FileRole survives workflow switches
  // naturally: the two BOM-compare workflows use disjoint roles (group:
  // grouping/bom, custom: bomA/bomB), so nothing leaks across a switch and we
  // don't need to stash it in workflowStateCache.
  const [workbookColumnsByRole, setWorkbookColumnsByRole] = useState<
    Partial<Record<FileRole, string[]>>
  >(() => seedColumnsForWorkflow(baseScenario.workflowId));
  // Tier-1 #5: per-column VALUE diff pairs for Custom Compare. Sent as
  // `options.compare_columns` for the custom workflow only. Auto-populated from
  // headers that match (case-insensitively) in BOTH files once they're both
  // inspected; the user can add/remove/edit pairs afterward. Stashed per
  // workflow (Wiring Invariant #9) so it survives a Group<->Custom round-trip.
  const [comparePairs, setComparePairs] = useState<ComparePair[]>([]);
  const [validations, setValidations] = useState<ValidationMessage[]>(baseScenario.validations);
  const [options, setOptions] = useState({
    // "base match" maps to the backend's loose/prefix base-matching mode
    // (AnalyzeOptions.loose_base_match). It defaults to FALSE so a default run
    // produces byte-identical output to the pre-wiring behavior (the backend
    // base-matching default has always been loose=off). Checking it opts into
    // fuzzy-prefix base coverage on BOTH the group and custom workflows.
    base_match: false,
    exact_match: false,
    ignore_dnp: true,
    check_part_usage: true,
    check_fmr: false,
    treat_prov_as_covered: true,
  });
  const [contextView, setContextView] = useState<"preview" | "run">("preview");
  const [runMode, setRunMode] = useState<RunMode>("idle");
  const [runIndex, setRunIndex] = useState(-1);
  const [runTemplates, setRunTemplates] = useState<RunEventTemplate[]>(baseScenario.runSequence.events);
  const [runResult, setRunResult] = useState<typeof baseScenario.runSequence.result | null>(null);
  const [runLogLines, setRunLogLines] = useState<string[]>([]);
  const [cancelledNotice, setCancelledNotice] = useState<string | null>(null);
  const contextHeadingRef = useRef<HTMLHeadingElement | null>(null);
  // Fix 2 (Family 2): re-entrancy guard for the desktop run pipeline. Held
  // for the whole validate→execute window so a double-click on Compare can't
  // launch a second run whose rejection (single-active-run guard) would clear
  // the first, live run's session.
  const isStartingRef = useRef(false);
  const setBackendState = useShellStore((state) => state.setBackendState);
  const bomCompareOutputDirectory = useShellStore(
    (state) => state.bomCompareOutputDirectory,
  );
  const setBomCompareOutputDirectory = useShellStore(
    (state) => state.setBomCompareOutputDirectory,
  );
  const pushNotification = useNotificationStore((state) => state.push);
  const setPreview = usePreviewStore((state) => state.setPreview);

  // Per-role token used to discard stale async listSheets/inspect results.
  const fileRequestSeq = useRoleRequestSequence<FileRole>();

  // Per-workflow state cache (Fix 1). The two BOM-compare workflows use
  // disjoint roles (group: grouping/bom, custom: bomA/bomB), so a fresh
  // scenario seed on FIRST visit is correct. But re-seeding on EVERY switch
  // discarded files loaded under one workflow when the user round-tripped
  // through the other. We stash the outgoing workflow's input/mapping/
  // validation slices here and restore them when the user returns, falling
  // back to the scenario seed only for a workflow never visited this mount.
  const workflowStateCache = useRef<
    Partial<
      Record<
        WorkflowId,
        {
          inputStates: InputFileState[];
          mappingOverrides: Record<string, string>;
          validations: ValidationMessage[];
          comparePairs: ComparePair[];
        }
      >
    >
  >({});
  // Tracks the workflow whose slices are currently live so the change effect
  // knows which cache key to stash under before switching.
  const previousWorkflowId = useRef<WorkflowId>(workflowId);
  // Latest-value mirrors of the cached slices. The workflow-change effect only
  // runs on `workflowId`, so it must read the OUTGOING slices from refs rather
  // than the stale closure to stash exactly what the user last saw.
  const latestInputStates = useRef(inputStates);
  const latestMappingOverrides = useRef(mappingOverrides);
  const latestValidations = useRef(validations);
  const latestComparePairs = useRef(comparePairs);
  latestInputStates.current = inputStates;
  latestMappingOverrides.current = mappingOverrides;
  latestValidations.current = validations;
  latestComparePairs.current = comparePairs;

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
    armTerminalHandler,
    cancel: cancelDesktopRun,
    panelRunMode,
    panelTimeline,
    panelProgress,
    panelRunResult,
    panelLogLines,
    panelCancelledNotice,
    panelTruncatedLogCount,
    panelErrorCode,
    panelErrorTraceback,
  } = useDesktopRunController("bom_compare", {
    successMessage: (outputFile) => `Report written to ${outputFile}.`,
    successTitle: "BOM comparison complete",
    failureTitle: "BOM comparison failed",
    cancelledTitle: "BOM comparison cancelled",
    mockRunMode: runMode,
    mockTimeline: timeline,
    mockProgress: progress,
    mockRunResult: runResult,
    mockLogLines: runLogLines,
    mockCancelledNotice: cancelledNotice,
  });

  // Reset state when workflow changes
  useEffect(() => {
    startTransition(() => {
      // Fix 1: stash the OUTGOING workflow's input/mapping/validation slices
      // under its id before switching, so a later round-trip restores them.
      const outgoing = previousWorkflowId.current;
      if (outgoing !== workflowId) {
        // Invalidate in-flight listSheets/inspect continuations for the
        // outgoing roles. Without this, a late resolution fires against the
        // incoming workflow's role set (a silent no-op) or surfaces stale
        // backend status/toasts for a workflow the user has left. Bump
        // (never reset) so old tokens can't collide with reissued ones.
        for (const role of workflowInputRoles[outgoing] ?? []) {
          fileRequestSeq.begin(role);
        }
        workflowStateCache.current[outgoing] = {
          inputStates: latestInputStates.current.map(sanitizeInterruptedInput),
          mappingOverrides: latestMappingOverrides.current,
          validations: latestValidations.current,
          comparePairs: latestComparePairs.current,
        };
      }
      previousWorkflowId.current = workflowId;

      // Bug fix: mappingRows are now DERIVED (useMemo) from workflowId +
      // workbookColumnsByRole, so there is no setMappingRows here. The fixture
      // selection (group vs custom) and the inspected-header derivation both
      // happen in that memo; this effect only resets the override/cache slices.

      // Fix 1: restore the incoming workflow's cached slices if we have visited
      // it this mount; otherwise seed from the scenario exactly as before.
      const cached = workflowStateCache.current[workflowId];
      if (cached) {
        setInputStates(cached.inputStates);
        setMappingOverrides(cached.mappingOverrides);
        setValidations(cached.validations);
        // Tier-1 #5: restore the cached compare pairs. For a workflow visited
        // before, this preserves the user's edits (and is [] for group, since
        // the picker never renders there). On a switch INTO custom for the
        // first time the else-branch clears it so the auto-pair effect can seed.
        setComparePairs(cached.comparePairs);
      } else {
        setMappingOverrides({});
        const scenario = bomCompareDemoScenarios.find((s) => s.workflowId === workflowId) ?? baseScenario;
        // Family 1 fix: desktop-aware seed for a never-visited workflow.
        // Using cloneInputs here re-introduced the example paths in desktop
        // mode when switching Group <-> Custom for the first time.
        setInputStates(seedInputsForRuntime(scenario.inputs));
        setValidations(scenario.validations);
        // Tier-1 #5: clear compare pairs for a never-visited workflow. Group
        // mode keeps it empty (no picker); custom mode lets the auto-pair
        // effect populate it once both files are inspected.
        setComparePairs([]);
      }
      // Tier-1 #5: in browser-mock there's no inspect round-trip, so seed the
      // incoming custom workflow's example columns for the picker. Merge so a
      // role already populated by a real (desktop) inspection is never clobbered.
      const seededColumns = seedColumnsForWorkflow(workflowId);
      if (Object.keys(seededColumns).length > 0) {
        setWorkbookColumnsByRole((current) => ({ ...seededColumns, ...current }));
      }
      setRunMode("idle");
      setRunIndex(-1);
      setRunTemplates(baseScenario.runSequence.events);
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

  // Focus context heading when view switches
  useEffect(() => {
    contextHeadingRef.current?.focus();
  }, [contextView]);

  // Browser-mock run simulation
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
  }, [runIndex, runMode, runTemplates, baseScenario.runSequence.result]);

  // Compute visible inputs from current workflow
  const roles = workflowInputRoles[workflowId] ?? [];
  const visibleInputs = useMemo(
    () =>
      roles
        .map((role) => inputStates.find((input) => input.role === role))
        .filter((input): input is InputFileState => Boolean(input)),
    [inputStates, roles],
  );

  // Bug fix: derive the Column Mapping rows from the active workflow's fixture
  // AND the inspected workbook headers for each row's file role. When a role
  // has no inspected columns yet (nothing browsed — including all of
  // browser-mock preview) its fixture row is kept verbatim, so the demo
  // preview and existing tests are unchanged. Derived from state (not stored
  // in setState) so it can never drift from workbookColumnsByRole.
  const mappingRows = useMemo<ColumnMappingRow[]>(() => {
    const fixtureRows =
      workflowId === "bom_compare_custom" ? bomCompareCustomMappings : bomCompareGroupMappings;
    const canonicalToRole = canonicalRolesByWorkflow[workflowId] ?? {};
    return deriveMappingRows(fixtureRows, canonicalToRole, workbookColumnsByRole);
  }, [workflowId, workbookColumnsByRole]);

  // Tier-1 #5: the effective RefDes key columns for each custom file (mapping
  // override wins over the derived fixture default). These are EXCLUDED from
  // auto-pairing — the key column is the join, not a value to diff.
  const mappedColumnFor = (canonical: string): string => {
    const override = mappingOverrides[canonical];
    if (override !== undefined) {
      return override;
    }
    return mappingRows.find((row) => row.canonical === canonical)?.mappedTo ?? "";
  };
  const refdesColA = mappedColumnFor("refdes_col_a");
  const refdesColB = mappedColumnFor("refdes_col_b");

  const customColumnsA = workbookColumnsByRole.bomA ?? [];
  const customColumnsB = workbookColumnsByRole.bomB ?? [];

  // Tier-1 #5: signature of the inspected column set we last auto-paired for.
  // The one-shot seed keys off this (NOT comparePairs.length): deleting the last
  // pair or round-tripping Group<->Custom keeps the same signature, so it does
  // not re-seed — only a genuinely new inspection (different columns) re-pairs.
  const autoPairedSignatureRef = useRef<string | null>(null);

  // Tier-1 #5 auto-pair: when both custom files are inspected, seed compare
  // pairs ONCE per inspected column set from headers that match (normalized) in
  // both files, excluding the mapped RefDes key columns. comparePairs is read
  // via ref so it is not an effect dep (a dep would re-fire the seed every time
  // the array returns to empty — re-adding rows the user just deleted, and
  // clobbering a restored cache mid-round-trip).
  useEffect(() => {
    if (workflowId !== "bom_compare_custom") {
      return;
    }
    if (customColumnsA.length === 0 || customColumnsB.length === 0) {
      return;
    }
    const signature = JSON.stringify([
      customColumnsA,
      customColumnsB,
      refdesColA,
      refdesColB,
    ]);
    if (autoPairedSignatureRef.current === signature) {
      return;
    }
    autoPairedSignatureRef.current = signature;
    if (latestComparePairs.current.length > 0) {
      // A restored cache or the user's existing edits — never clobber.
      return;
    }
    const normalize = (value: string) => value.trim().toLowerCase();
    const excluded = new Set(
      [refdesColA, refdesColB].filter(Boolean).map(normalize),
    );
    const bByNormalized = new Map<string, string>();
    for (const column of customColumnsB) {
      const key = normalize(column);
      if (!bByNormalized.has(key)) {
        bByNormalized.set(key, column);
      }
    }
    const seenA = new Set<string>();
    const autoPairs: ComparePair[] = [];
    for (const column of customColumnsA) {
      const key = normalize(column);
      if (!key || excluded.has(key) || seenA.has(key)) {
        continue;
      }
      seenA.add(key);
      const matchB = bByNormalized.get(key);
      if (matchB) {
        autoPairs.push({ col_a: column, col_b: matchB, rule: "Text (ignore case)" });
      }
    }
    if (autoPairs.length > 0) {
      setComparePairs(autoPairs);
    }
  }, [workflowId, customColumnsA, customColumnsB, refdesColA, refdesColB]);

  async function handleRevealOutput(path: string) {
    try {
      await backendClient.revealInFileManager(parentDirectoryForPath(path));
    } catch (error) {
      const detail = describeBackendError(error, "Failed to open output folder");
      pushNotification({ tone: "error", title: "Open output folder failed", detail });
    }
  }

  // Pristine = first contact with the tool: still on the default workflow,
  // all visible inputs are example mocks, no run has started. Switching
  // workflow is a sign of engagement, so we exit pristine then.
  const isPristine =
    workflowId === baseScenario.workflowId &&
    visibleInputs.every((input) => input.isExample === true) &&
    panelRunMode === "idle";

  const handleLoadExample = () => {
    pushNotification({
      tone: "info",
      title: "Example files coming soon",
      detail: "Bundled example BOMs aren't shipping yet. For now, browse to a real workbook.",
    });
  };

  const firstInputRole = visibleInputs[0]?.role ?? null;

  function buildRunRequest(): RunRequestBody {
    const currentRoles = workflowInputRoles[workflowId] ?? [];
    const currentVisibleInputs = inputStates.filter((i) => currentRoles.includes(i.role));
    // TODO (Phase 4 Task 6): promote the FMEA OutputStrategySelector to
    // shared and wire it here. Deferred: `backend/python/bom_compare/runtime.py`
    // currently only accepts `new_workbook_standard` (no `output_strategy`
    // handling), so adding a selector would be user-visible but would
    // silently no-op until backend support lands. Re-evaluate when the
    // backend runtime surfaces a `preserve_formatting` code path.
    // Tier-1 #5: the custom path's per-column value diffs ride along in
    // options.compare_columns (array of {col_a, col_b, rule}). Group mode has
    // no second BOM to pair against, so the key is omitted there. Pairs with an
    // empty File-1 or File-2 column are dropped — the backend reader
    // (_run_custom_compare) also guards this, but pruning here keeps the
    // payload clean.
    const runOptions =
      workflowId === "bom_compare_custom"
        ? {
            ...options,
            compare_columns: comparePairs.filter((pair) => pair.col_a && pair.col_b),
          }
        : options;

    return {
      workflowId,
      outputStrategyId: "new_workbook_standard",
      inputs: currentVisibleInputs.map((input) => ({
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
      options: runOptions,
      outputDirectory: bomCompareOutputDirectory,
    };
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

    // Stale-safe: bump the per-role token before kicking off async work.
    const token = fileRequestSeq.begin(role);

    setInputStates((current) =>
      current.map((input) =>
        input.role === role
          ? {
              ...input,
              path: pickedPath,
              source: "desktop-bridge",
              // A real file replaces the example mock — clears the
              // pristine EmptyState so the full input grid renders.
              isExample: false,
              isResolvingSheets: true,
              resolutionError: null,
              tag: "Inspecting",
            }
          : input,
      ),
    );
    // Fix 2: a new file invalidates the previous validate_run result — clear
    // the stale validation cards so the Preview tab shows its neutral empty
    // state instead of warnings that describe the OLD file/sheet.
    setValidations([]);
    // Bug fix: a new file replaces this role's inspected headers — drop the
    // previous set so the mapping rows fall back to the fixture until the
    // fresh inspection lands (and never offer the OLD workbook's headers).
    setWorkbookColumnsByRole((current) => {
      const next = { ...current };
      delete next[role];
      return next;
    });
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
        await inspectRole(role, result.path, result.sheets[0]);
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

  async function inspectRole(role: FileRole, path: string, sheet: string) {
    if (!sheet) {
      return;
    }

    // Stale-safe: bump the per-role token. Note that handleBrowse already
    // bumps before calling here, but bumping again is safe and covers the
    // case where inspectRole is called directly from handleSheetChange.
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
      const inspection = await backendClient.inspectInput(path, sheet, role);
      if (!fileRequestSeq.isCurrent(role, token)) return;
      // Bug fix: record the inspected headers for this role so the Column
      // Mapping dropdowns are rebuilt from real workbook columns. inspectRole
      // used to read only `.length` here and discard `.columns`.
      const workbookColumns = buildWorkbookColumnUnion([inspection.columns]);
      setWorkbookColumnsByRole((current) => ({
        ...current,
        [role]: workbookColumns,
      }));
      setBackendState({
        backendStatus: "ready",
        backendMode: inspection.mode,
        backendMessage: `Inspected ${inspection.sheet} with ${inspection.columns.length} headers.`,
        lastBackendCheckAt: new Date().toISOString(),
      });

      setInputStates((current) =>
        current.map((input) =>
          input.role === role
            ? {
                ...input,
                isAnalyzing: false,
                tag: "Analyzed",
              }
            : input,
        ),
      );
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
        title: "Workbook inspection failed",
        detail,
      });
    }
  }

  function handleSheetChange(role: FileRole, selectedSheet: string) {
    let nextPath = "";
    setInputStates((current) =>
      current.map((input) => {
        if (input.role !== role) {
          return input;
        }

        nextPath = input.path;
        return {
          ...input,
          selectedSheet,
        };
      }),
    );

    // Fix 2: a sheet change re-points the input at different data, so the
    // previous validate_run result is now stale — clear it so Preview shows
    // its neutral empty state rather than cards describing the OLD sheet.
    setValidations([]);

    if (backendClient.runtimeMode === "desktop-bridge" && nextPath) {
      void inspectRole(role, nextPath, selectedSheet);
    }
  }

  async function handleStartRun() {
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

    // Fix 2 (Family 2): re-entrancy guard. The Compare button is not disabled
    // during the async validate→execute window, so a fast double-click could
    // fire a second pipeline; the second executeRun is rejected by Python's
    // single-active-run guard and its catch used to wipe the FIRST, live run.
    // Swallow the re-entrant call here.
    if (isStartingRef.current) {
      return;
    }
    isStartingRef.current = true;

    const runRequest = buildRunRequest();

    // Fix R2-C1: clear any stale active run from a previous run BEFORE flipping
    // the busy chip. Otherwise useBackendBusyReset would see (previous run's
    // terminal phase + busy) and instantly clear the "Validating..." message.
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
      setPreview("bom_compare", validation.output_preview ?? null);

      if (!validation.ok) {
        setRunMode("idle");
        setRunIndex(-1);
        setRunTemplates(baseScenario.runSequence.events);
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

      setRunTemplates(baseScenario.runSequence.events);
      setBackendState({
        backendStatus: "busy",
        backendMode: validation.mode,
        backendMessage: "Running BOM comparison through the desktop backend...",
      });

      armTerminalHandler();
      beginAcceptedRun(await backendClient.executeRun(runRequest));
    } catch (error) {
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
        title: "BOM comparison failed",
        detail,
      });
    } finally {
      // Release the re-entrancy guard once the validate→execute window has
      // closed (success, validation block, or error). The live run, if one
      // was accepted, is now owned by the run store and survives.
      isStartingRef.current = false;
    }
  }

  function handleCancel() {
    // Desktop-bridge cancel is owned by the shared controller (guarded on
    // ``starting``/``running`` to avoid stale-id and double-click cancels).
    if (cancelDesktopRun()) {
      return;
    }

    // Browser-mock: HoldButton already captured the press-and-hold
    // confirmation, so cancel immediately.
    setRunMode("idle");
    setRunIndex(-1);
    setRunResult(null);
    setCancelledNotice("Demo run cancelled. The workspace returned to a safe idle state.");
  }

  return (
    <ErrorBoundary
      title="BOM Compare panel failed to render"
      detail="The BOM Compare tool hit an error. Reload the panel without tearing down the shell."
    >
      <div className="tool-workspace">
        <section className="workspace-grid workspace-grid--single">
          <div className="workspace-grid__main">
            <SectionCard
              step={1}
              title="Run Setup"
              eyebrow="Workflow"
              description="Pick the BOM comparison style. Group mode compares a grouping sheet to a BOM; custom mode compares two BOMs directly."
            >
              <WorkflowSelector
                workflows={bomCompareWorkflowOptions}
                selectedWorkflowId={workflowId}
                onSelect={setWorkflowId}
              />
            </SectionCard>

            <SectionCard
              step={2}
              title="Input Files"
              eyebrow="Data Sources"
              description="Load the workbooks you want to compare."
            >
              {isPristine ? (
                <EmptyState
                  icon={GitDiff}
                  headline="Compare two BOMs"
                  body="Browse for your files, or load the example pair to explore the workflow first."
                  primaryAction={{
                    label: "Browse for first BOM",
                    onClick: () => {
                      if (firstInputRole) {
                        void handleBrowse(firstInputRole);
                      }
                    },
                  }}
                  secondaryAction={{
                    label: "Load example",
                    onClick: handleLoadExample,
                  }}
                />
              ) : (
                <InputGrid
                  inputs={visibleInputs}
                  onBrowse={handleBrowse}
                  onSheetChange={handleSheetChange}
                  getDisabledSheetReason={(input) => {
                    // Sheet picker disabledReason — surfaced as a muted
                    // caption below the disabled CustomSelect via
                    // aria-describedby.
                    if (input.isResolvingSheets) {
                      return "Loading sheets from the desktop bridge…";
                    }
                    if (input.sheets.length === 0) {
                      return "Load a BOM first";
                    }
                    return undefined;
                  }}
                />
              )}
            </SectionCard>

            <SectionCard
              step={3}
              title="Column Mapping"
              eyebrow="Field Assignment"
              description="Map columns between the two BOMs to align rows."
            >
              <MappingTable
                rows={mappingRows}
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
                    for (const row of mappingRows) {
                      const mapped = next[row.canonical] ?? row.mappedTo;
                      if (
                        row.recommendation &&
                        row.options.includes(row.recommendation) &&
                        row.recommendation !== mapped
                      ) {
                        next[row.canonical] = row.recommendation;
                      }
                    }
                    return next;
                  });
                }}
                onClearAllMappings={() => {
                  // "Clear all" is an explicit Do-Not-Map request; see
                  // MappingTable Phase 2 comment. Sets every row to the
                  // sentinel so the backend can distinguish intentional
                  // unmapping from missing defaults.
                  setMappingOverrides(() => {
                    const next: Record<string, string> = {};
                    for (const row of mappingRows) {
                      next[row.canonical] = DO_NOT_MAP_VALUE;
                    }
                    return next;
                  });
                }}
              />
            </SectionCard>

            <OptionsSection
              title="Options"
              eyebrow="Comparison Settings"
              description="Tune the comparison output."
            >
              {Object.entries(options).map(([key, value]) => {
                // treat_prov_as_covered keys off the grouping file's
                // group-name column ("PROV" groups), which a two-BOM custom
                // compare does not have — the backend provably never reads
                // it on the custom path, so disable it there with a hint
                // (mirrors the RefDes adaptive-geometry pattern).
                const groupOnly =
                  key === "treat_prov_as_covered" && workflowId === "bom_compare_custom";
                return (
                  <CheckboxField
                    key={key}
                    id={`bom-compare-option-${key}`}
                    label={key.replace(/_/g, " ")}
                    checked={value}
                    disabled={groupOnly}
                    hint={groupOnly ? "Group vs BOM mode only" : undefined}
                    onChange={(next) =>
                      setOptions((prev) => ({ ...prev, [key]: next } as typeof prev))
                    }
                  />
                );
              })}
              <OutputFolderPicker
                value={bomCompareOutputDirectory}
                onChange={setBomCompareOutputDirectory}
              />
            </OptionsSection>

            {/* Tier-1 #5: column-value diff pairs. Rendered ONLY in Custom
                Compare — Group mode has no second BOM to pair against, so the
                control is inert there and is hidden entirely (mirrors the
                treat_prov_as_covered hide/disable pattern). */}
            {workflowId === "bom_compare_custom" ? (
              <SectionCard
                title="Column Value Comparison"
                eyebrow="Custom Compare"
                description="Diff specific column values for RefDes present in both files. Matching headers are paired automatically once both files are inspected."
              >
                <ColumnPairPicker
                  pairs={comparePairs}
                  columnsA={customColumnsA}
                  columnsB={customColumnsB}
                  onChange={setComparePairs}
                />
              </SectionCard>
            ) : null}
          </div>

          <aside className="workspace-grid__side workspace-grid__side--sticky">
            <SectionCard
              variant="divided"
              title={contextView === "preview" ? "Review" : "Execution"}
              eyebrow="Context Panel"
              actions={
                <ContextTabs<"preview" | "run">
                  ariaLabel="Context panel"
                  activeId={contextView}
                  onChange={(id) => setContextView(id)}
                  tabs={[
                    { id: "preview", label: "Preview" },
                    { id: "run", label: "Run" },
                  ]}
                />
              }
            >
              <h3 className="sr-only-focusable" ref={contextHeadingRef} tabIndex={-1}>
                {contextView === "preview" ? "Preview panel" : "Run panel"}
              </h3>
              {contextView === "preview" ? (
                <ValidationPreview validations={validations} previewRows={[]} />
              ) : (
                <RunStatePanel
                  runMode={panelRunMode}
                  progress={panelProgress}
                  timeline={panelTimeline}
                  result={panelRunResult}
                  onStart={() => {
                    void handleStartRun();
                  }}
                  onCancel={handleCancel}
                  cancelledNotice={panelCancelledNotice}
                  logLines={panelLogLines}
                  truncatedLogCount={panelTruncatedLogCount}
                  errorCode={panelErrorCode}
                  errorTraceback={panelErrorTraceback}
                  onRevealOutput={
                    backendClient.runtimeMode === "desktop-bridge" ? (path) => void handleRevealOutput(path) : undefined
                  }
                  startLabel="Compare"
                />
              )}
            </SectionCard>
          </aside>
        </section>
      </div>
    </ErrorBoundary>
  );
}
