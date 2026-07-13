import { useEffect, useMemo, useRef, useState } from "react";
import { CustomSelect } from "../../components/CustomSelect";
import { InputGrid } from "../../components/InputGrid";
import { MappingTable } from "../../components/MappingTable";
import { RunStatePanel } from "../../components/RunStatePanel";
import { SectionCard } from "../../components/SectionCard";
import { ValidationPreview } from "../../components/ValidationPreview";
import { CheckboxField } from "../../components/primitives/CheckboxField";
import { ContextTabs } from "../../components/primitives/ContextTabs";
import { EmptyState } from "../../components/primitives/EmptyState";
import { OptionsField } from "../../components/primitives/OptionsField";
import { OptionsSection } from "../../components/primitives/OptionsSection";
import { OutputFolderPicker } from "../../components/OutputFolderPicker";
import { ChartLine } from "@phosphor-icons/react";
import {
  failureRateDemoScenarios,
  failureRateMappings,
} from "../../mocks/scenarios";
import type {
  ColumnMappingRow,
  FileRole,
  InputFileState,
  RunEventTemplate,
  RunMode,
  ValidationMessage,
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

/**
 * Bug fix: which file role each canonical mapping addresses, so the Column
 * Mapping dropdowns can be rebuilt from THAT role's inspected workbook headers
 * instead of the static fixture options. Verified against
 * `backend/python/failure_rate/runtime.py`: pred_ref / pred_fr read the
 * prediction workbook; fmea_cause / fmea_ratio / fmea_usage / fmea_func read
 * the FMEA workbook.
 */
const FAILURE_RATE_CANONICAL_ROLES: Record<string, FileRole> = {
  pred_ref: "prediction",
  pred_fr: "prediction",
  fmea_cause: "fmea",
  fmea_ratio: "fmea",
  fmea_usage: "fmea",
  fmea_func: "fmea",
};

export function FailureRateTool() {
  const baseScenario = failureRateDemoScenarios[0];
  // Family 1 fix: browser-mock seeds the demo scenario (populated preview);
  // the real desktop runtime seeds empty slots so no example path leaks into
  // a run. Matches FMEA's gated seeding.
  const [inputStates, setInputStates] = useState<InputFileState[]>(() =>
    backendClient.runtimeMode === "browser-mock"
      ? cloneInputs(baseScenario.inputs)
      : emptyInputsFromScenario(baseScenario.inputs),
  );
  const [mappingOverrides, setMappingOverrides] = useState<Record<string, string>>({});
  // Bug fix: per-role inspected workbook headers, populated from
  // inspection.columns in inspectRole's success path and cleared for a role on
  // re-browse. Keyed by FileRole (prediction / fmea); the mapping rows are
  // derived from this below.
  const [workbookColumnsByRole, setWorkbookColumnsByRole] = useState<
    Partial<Record<FileRole, string[]>>
  >({});
  const [options, setOptions] = useState({ unitMode: "per_hour", validateFmr: false });
  // M9: demo validations ("Example data staged") are browser-preview content.
  // Desktop starts empty (Wiring Invariant #3).
  const [validations, setValidations] = useState<ValidationMessage[]>(() =>
    backendClient.runtimeMode === "browser-mock" ? baseScenario.validations : [],
  );
  const [contextView, setContextView] = useState<"preview" | "run">("preview");
  const [runMode, setRunMode] = useState<RunMode>("idle");
  const [runIndex, setRunIndex] = useState(-1);
  const [runTemplates, setRunTemplates] = useState<RunEventTemplate[]>(baseScenario.runSequence.events);
  const [runResult, setRunResult] = useState<typeof baseScenario.runSequence.result | null>(null);
  const [runLogLines, setRunLogLines] = useState<string[]>([]);
  const [cancelledNotice, setCancelledNotice] = useState<string | null>(null);
  const contextHeadingRef = useRef<HTMLHeadingElement | null>(null);
  // Fix 2 (Family 2): re-entrancy guard for the desktop run pipeline. Held
  // for the whole validate→execute window so a double-click on Link Rates
  // can't launch a second run whose rejection (single-active-run guard) would
  // clear the first, live run's session.
  const isStartingRef = useRef(false);
  const setBackendState = useShellStore((state) => state.setBackendState);
  const failureRateOutputDirectory = useShellStore(
    (state) => state.failureRateOutputDirectory,
  );
  const setFailureRateOutputDirectory = useShellStore(
    (state) => state.setFailureRateOutputDirectory,
  );
  const pushNotification = useNotificationStore((state) => state.push);
  const setPreview = usePreviewStore((state) => state.setPreview);

  // Per-role token used to discard stale async listSheets/inspect results.
  const fileRequestSeq = useRoleRequestSequence<FileRole>();

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
    panelTruncatedLogCount,
    panelErrorCode,
    panelErrorTraceback,
  } = useDesktopRunController("failure_rate", {
    successMessage: (outputFile) => `Report written to ${outputFile}.`,
    successTitle: "Failure rate linking complete",
    failureTitle: "Failure rate linking failed",
    cancelledTitle: "Failure rate linking cancelled",
    mockRunMode: runMode,
    mockTimeline: timeline,
    mockProgress: progress,
    mockRunResult: runResult,
    mockLogLines: runLogLines,
    mockCancelledNotice: cancelledNotice,
  });

  async function handleRevealOutput(path: string) {
    try {
      await backendClient.revealInFileManager(parentDirectoryForPath(path));
    } catch (error) {
      const detail = describeBackendError(error, "Failed to open output folder");
      pushNotification({ tone: "error", title: "Open output folder failed", detail });
    }
  }

  // Pristine = no real input loaded yet AND no run has been started.
  const isPristine =
    inputStates.every((input) => input.isExample === true) &&
    panelRunMode === "idle";

  const handleLoadExample = () => {
    pushNotification({
      tone: "info",
      title: "Example files coming soon",
      detail: "Bundled example parts lists aren't shipping yet. For now, browse to a real workbook.",
    });
  };

  const firstInputRole = inputStates[0]?.role ?? null;

  // Bug fix: derive the Column Mapping rows from the static fixture AND the
  // inspected workbook headers for each row's file role. A role with no
  // inspected columns yet (nothing browsed — including all of browser-mock
  // preview) keeps its fixture row verbatim, so the demo preview and existing
  // tests are unchanged.
  const mappingRows = useMemo<ColumnMappingRow[]>(
    () =>
      deriveMappingRows(failureRateMappings, FAILURE_RATE_CANONICAL_ROLES, workbookColumnsByRole),
    [workbookColumnsByRole],
  );

  function buildRunRequest(): RunRequestBody {
    return {
      workflowId: baseScenario.workflowId,
      outputStrategyId: "new_workbook_standard",
      inputs: inputStates.map((input) => ({
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
      options: { unit_mode: options.unitMode, validate_fmr: options.validateFmr },
      outputDirectory: failureRateOutputDirectory,
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

    // Stale-safe: bump the per-role token before any async work begins.
    const browseToken = fileRequestSeq.begin(role);

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
      if (!fileRequestSeq.isCurrent(role, browseToken)) return;
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
      if (!fileRequestSeq.isCurrent(role, browseToken)) return;
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

    // Stale-safe: bump per-role token. Bumping is also done by handleBrowse
    // before it calls here; bumping again is safe and covers direct calls
    // from handleSheetChange.
    const inspectToken = fileRequestSeq.begin(role);

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
      if (!fileRequestSeq.isCurrent(role, inspectToken)) return;
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
      if (!fileRequestSeq.isCurrent(role, inspectToken)) return;
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

    // Cross-tool guard: another tool's live run must not be clobbered by
    // this start's rejection path — toast and bail before sending anything.
    if (guardCrossToolRun()) {
      return;
    }

    // Fix 2 (Family 2): re-entrancy guard. The Link Rates button is not
    // disabled during the async validate→execute window, so a fast
    // double-click could fire a second pipeline; the second executeRun is
    // rejected by Python's single-active-run guard and its catch used to wipe
    // the FIRST, live run. Swallow the re-entrant call here.
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
      setPreview("failure_rate", validation.output_preview ?? null);

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
        backendMessage: "Running failure rate linking through the desktop backend...",
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
        title: "Failure rate linking failed",
        detail,
      });
    } finally {
      // Release the re-entrancy guard once the validate→execute window has
      // closed. A run accepted in this window is owned by the run store and
      // survives.
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
      title="Failure Rate panel failed to render"
      detail="The Failure Rate tool hit an error. Reload the panel without tearing down the shell."
    >
      <div className="tool-workspace">
        <section className="workspace-grid workspace-grid--single">
          <div className="workspace-grid__main">
            <SectionCard
              step={1}
              title="Input Files"
              eyebrow="Data Sources"
              description="Load the parts list to enrich with failure rates."
            >
              {isPristine ? (
                <EmptyState
                  icon={ChartLine}
                  headline="Link failure rates"
                  body="Select a parts list to enrich with failure rate data. Outputs are written alongside the original workbook."
                  primaryAction={{
                    label: "Browse for parts list",
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
                  inputs={inputStates}
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
                      return "Select a parts list first";
                    }
                    return undefined;
                  }}
                />
              )}
            </SectionCard>

            <SectionCard
              step={2}
              title="Column Mapping"
              eyebrow="Field Assignment"
              description="Map the part identifier columns."
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
              eyebrow="Configuration"
              description="Choose units and validation behavior."
            >
              <OptionsField label="Failure rate unit">
                <CustomSelect
                  label="Unit mode"
                  value={options.unitMode}
                  options={[
                    { value: "per_hour", label: "Per hour" },
                    { value: "per_million_hours", label: "Per million hours" },
                    { value: "per_billion_hours", label: "Per billion hours" },
                  ]}
                  onChange={(value) => setOptions((prev) => ({ ...prev, unitMode: value }))}
                />
              </OptionsField>
              <CheckboxField
                id="failure-rate-validate-fmr"
                label="Validate FMR sums (sum to 1.0)"
                checked={options.validateFmr}
                onChange={(next) => setOptions((prev) => ({ ...prev, validateFmr: next }))}
              />
              <OutputFolderPicker
                value={failureRateOutputDirectory}
                onChange={setFailureRateOutputDirectory}
              />
            </OptionsSection>
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
                  startLabel="Link Rates"
                />
              )}
            </SectionCard>
          </aside>
        </section>
      </div>
    </ErrorBoundary>
  );
}
