import { startTransition, useEffect, useMemo, useRef, useState } from "react";
import { InputGrid } from "../../components/InputGrid";
import { MappingTable } from "../../components/MappingTable";
import { RunStatePanel } from "../../components/RunStatePanel";
import { SectionCard } from "../../components/SectionCard";
import { ValidationPreview } from "../../components/ValidationPreview";
import { WorkflowSelector } from "../../components/WorkflowSelector";
import { executeRunResultSchema } from "../../contracts/sidecar";
import {
  bomCompareWorkflowOptions,
  bomCompareDemoScenarios,
  bomCompareGroupMappings,
  bomCompareCustomMappings,
} from "../../mocks/scenarios";
import type {
  ColumnMappingRow,
  FileRole,
  InputFileState,
  RunEvent,
  RunEventTemplate,
  RunMode,
  ValidationMessage,
  WorkflowId,
} from "../../app/types";
import { backendClient, type RunRequestBody } from "../../shared/backend/client";
import { buildRunTimeline, isBusyRunPhase, useBackendRunLifecycle } from "../../shared/backend/runLifecycle";
import { ErrorBoundary } from "../../shared/errors/ErrorBoundary";
import { useRoleRequestSequence } from "../../shared/hooks/useRoleRequestSequence";
import { useNotificationStore } from "../../stores/notificationStore";
import { useShellStore } from "../../stores/shellStore";

const workflowInputRoles: Partial<Record<WorkflowId, FileRole[]>> = {
  bom_compare_group: ["grouping", "bom"],
  bom_compare_custom: ["bomA", "bomB"],
};

function cloneInputs(inputs: InputFileState[]) {
  return inputs.map((input) => ({
    ...input,
    sheets: input.sheets.map((sheet) => ({ ...sheet })),
    source: input.source ?? "mock",
    isResolvingSheets: input.isResolvingSheets ?? false,
    isAnalyzing: input.isAnalyzing ?? false,
    resolutionError: input.resolutionError ?? null,
  }));
}

function toFailureResult(detail: string) {
  return {
    status: "failure" as const,
    title: "Run failed",
    summary: detail,
    outputFile: "",
    primaryMetric: "No report written",
    secondaryMetric: "Review backend diagnostics",
    notes: ["The backend returned a failure before comparison could complete."],
  };
}

function normalizeHeader(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, " ");
}

function buildTimeline(runMode: RunMode, runIndex: number, templates: RunEventTemplate[]): RunEvent[] {
  return templates.map((event, index) => {
    let status: RunEvent["status"] = "pending";

    if (runMode === "running") {
      if (index < runIndex) status = "completed";
      if (index === runIndex) status = "active";
    }

    if (runMode === "success" || runMode === "failure") {
      status = "completed";
    }

    return { ...event, status };
  });
}

function parseBomCompareRunResult(payload: unknown) {
  return executeRunResultSchema.parse(payload);
}

export function BomCompareTool() {
  const baseScenario = bomCompareDemoScenarios[0];
  const [workflowId, setWorkflowId] = useState<WorkflowId>(baseScenario.workflowId);
  const [inputStates, setInputStates] = useState<InputFileState[]>(() => cloneInputs(baseScenario.inputs));
  const [mappingRows, setMappingRows] = useState<ColumnMappingRow[]>(bomCompareGroupMappings);
  const [mappingOverrides, setMappingOverrides] = useState<Record<string, string>>({});
  const [validations, setValidations] = useState<ValidationMessage[]>(baseScenario.validations);
  const [options, setOptions] = useState({
    base_match: true,
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
  const [cancelPending, setCancelPending] = useState(false);
  const contextHeadingRef = useRef<HTMLHeadingElement | null>(null);
  const handledDesktopTerminalRef = useRef<string | null>(null);
  const backendMode = useShellStore((state) => state.backendMode);
  const setBackendState = useShellStore((state) => state.setBackendState);
  const pushNotification = useNotificationStore((state) => state.push);

  const {
    session: desktopRunSession,
    beginAcceptedRun,
    resetSession: resetDesktopRunSession,
  } = useBackendRunLifecycle("bom_compare", backendClient.runtimeMode, parseBomCompareRunResult);
  // Per-role token used to discard stale async listSheets/inspect results.
  const fileRequestSeq = useRoleRequestSequence<FileRole>();

  // Reset state when workflow changes
  useEffect(() => {
    startTransition(() => {
      const newMappings = workflowId === "bom_compare_custom" ? bomCompareCustomMappings : bomCompareGroupMappings;
      setMappingRows([...newMappings]);
      setMappingOverrides({});
      const scenario = bomCompareDemoScenarios.find((s) => s.workflowId === workflowId) ?? baseScenario;
      setInputStates(cloneInputs(scenario.inputs));
      setValidations(scenario.validations);
      setRunMode("idle");
      setRunIndex(-1);
      setRunTemplates(baseScenario.runSequence.events);
      setRunResult(null);
      setRunLogLines([]);
      setCancelledNotice(null);
      setCancelPending(false);
      setContextView("preview");
      handledDesktopTerminalRef.current = null;
      resetDesktopRunSession();
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

  const timeline = useMemo(() => buildTimeline(runMode, runIndex, runTemplates), [runIndex, runMode, runTemplates]);
  const progress =
    runMode === "running" && runIndex >= 0
      ? runTemplates[runIndex]?.progress ?? 0
      : runResult
        ? 100
        : 0;
  const desktopTimeline = useMemo(() => buildRunTimeline(desktopRunSession), [desktopRunSession]);
  const desktopRunResult = useMemo(
    () =>
      desktopRunSession.result
        ? {
            status: desktopRunSession.result.status,
            title: desktopRunSession.result.title,
            summary: desktopRunSession.result.summary,
            outputFile: desktopRunSession.result.output_file,
            primaryMetric: desktopRunSession.result.primary_metric,
            secondaryMetric: desktopRunSession.result.secondary_metric,
            notes: desktopRunSession.result.notes,
          }
        : null,
    [desktopRunSession.result],
  );
  const panelRunMode = backendClient.runtimeMode === "desktop-bridge" ? desktopRunSession.phase : runMode;
  const panelTimeline = backendClient.runtimeMode === "desktop-bridge" ? desktopTimeline : timeline;
  const panelProgress = backendClient.runtimeMode === "desktop-bridge" ? desktopRunSession.progress : progress;
  const panelRunResult = backendClient.runtimeMode === "desktop-bridge" ? desktopRunResult : runResult;
  const panelLogLines = backendClient.runtimeMode === "desktop-bridge" ? desktopRunSession.logs : runLogLines;
  const panelCancelledNotice =
    backendClient.runtimeMode === "desktop-bridge"
      ? panelRunMode === "cancelled" || panelRunMode === "disconnected"
        ? desktopRunSession.statusMessage
        : null
      : cancelledNotice;
  const panelCancelPending =
    backendClient.runtimeMode === "desktop-bridge" ? panelRunMode === "cancelling" : cancelPending;
  const panelTruncatedLogCount =
    backendClient.runtimeMode === "desktop-bridge" ? desktopRunSession.truncatedLogCount : 0;
  const panelErrorCode =
    backendClient.runtimeMode === "desktop-bridge" ? desktopRunSession.errorCode : null;
  const panelErrorTraceback =
    backendClient.runtimeMode === "desktop-bridge" ? desktopRunSession.errorTraceback : null;

  // Desktop run terminal state handler
  useEffect(() => {
    if (backendClient.runtimeMode !== "desktop-bridge" || !desktopRunSession.runId) {
      return;
    }

    const phase = desktopRunSession.phase;
    if (!["success", "failure", "cancelled", "disconnected"].includes(phase)) {
      return;
    }

    const terminalKey = `${desktopRunSession.runId}:${phase}`;
    if (handledDesktopTerminalRef.current === terminalKey) {
      return;
    }
    handledDesktopTerminalRef.current = terminalKey;

    if (phase === "success" && desktopRunSession.result) {
      setBackendState({
        backendStatus: "ready",
        backendMode: desktopRunSession.result.mode,
        backendMessage: `Report written to ${desktopRunSession.result.output_file}.`,
        lastBackendCheckAt: new Date().toISOString(),
      });
      pushNotification({
        tone: "success",
        title: "BOM comparison complete",
        detail: desktopRunSession.result.output_file,
      });
      return;
    }

    if (phase === "failure") {
      setBackendState({
        backendStatus: "error",
        backendMode: "desktop-bridge",
        backendMessage: desktopRunSession.statusMessage,
        lastBackendCheckAt: new Date().toISOString(),
      });
      pushNotification({
        tone: "error",
        title: "BOM comparison failed",
        detail: desktopRunSession.statusMessage ?? "Unknown backend execution failure",
      });
      return;
    }

    if (phase === "cancelled") {
      setBackendState({
        backendStatus: "ready",
        backendMode: "desktop-bridge",
        backendMessage: desktopRunSession.statusMessage,
        lastBackendCheckAt: new Date().toISOString(),
      });
      pushNotification({
        tone: "warning",
        title: "BOM comparison cancelled",
        detail: desktopRunSession.statusMessage ?? "The active backend run was cancelled.",
      });
    }
  }, [desktopRunSession, pushNotification, setBackendState]);

  function buildRunRequest(): RunRequestBody {
    const currentRoles = workflowInputRoles[workflowId] ?? [];
    const currentVisibleInputs = inputStates.filter((i) => currentRoles.includes(i.role));
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
      options,
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
              isResolvingSheets: true,
              resolutionError: null,
              tag: "Inspecting",
            }
          : input,
      ),
    );
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
      const detail = error instanceof Error ? error.message : "Unknown sheet inspection failure";
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
      const detail = error instanceof Error ? error.message : "Unknown workbook analysis failure";
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
      setCancelPending(false);
      setContextView("run");
      setRunMode("running");
      setRunIndex(0);
      return;
    }

    const runRequest = buildRunRequest();

    setContextView("run");
    setRunLogLines([]);
    setRunResult(null);
    setCancelledNotice(null);
    setCancelPending(false);
    setBackendState({
      backendStatus: "busy",
      backendMessage: "Validating run configuration...",
    });

    try {
      const validation = await backendClient.validateRun(runRequest);
      setValidations(validation.validations);

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

      handledDesktopTerminalRef.current = null;
      beginAcceptedRun(await backendClient.executeRun(runRequest));
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Unknown backend execution failure";
      resetDesktopRunSession();
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
    }
  }

  function handleCancel() {
    if (backendClient.runtimeMode === "desktop-bridge") {
      if (!desktopRunSession.runId || !isBusyRunPhase(desktopRunSession.phase)) {
        return;
      }

      void backendClient
        .cancelRun(desktopRunSession.runId)
        .then((result) => {
          setBackendState({
            backendStatus: "busy",
            backendMode: result.mode,
            backendMessage: "Cancelling active backend run...",
            lastBackendCheckAt: new Date().toISOString(),
          });
        })
        .catch((error: unknown) => {
          const detail = error instanceof Error ? error.message : "Unknown cancel failure";
          pushNotification({
            tone: "error",
            title: "Cancel failed",
            detail,
          });
        });
      return;
    }

    if (!cancelPending) {
      setCancelPending(true);
      setCancelledNotice("Press cancel again to confirm.");
      return;
    }

    setRunMode("idle");
    setRunIndex(-1);
    setRunResult(null);
    setCancelPending(false);
    setCancelledNotice("Demo run cancelled. The workspace returned to a safe idle state.");
  }

  return (
    <ErrorBoundary
      title="BOM Compare panel failed to render"
      detail="The BOM Compare tool hit an error. Reload the panel without tearing down the shell."
    >
      <div className="tool-workspace">
        <section className="tool-banner">
          <div>
            <p className="eyebrow">BOM Compare</p>
            <h2 className="tool-banner__title">BOM Comparison Tool</h2>
          </div>
          <div className="tool-banner__chips">
            <span className={`status-chip status-chip--${backendMode === "desktop-bridge" ? "success" : "pending"}`}>
              {backendMode === "desktop-bridge" ? "Desktop bridge" : "Browser preview"}
            </span>
          </div>
        </section>

        <section className="workspace-grid workspace-grid--single">
          <div className="workspace-grid__main">
            <SectionCard title="Run Setup" eyebrow="Workflow">
              <WorkflowSelector
                workflows={bomCompareWorkflowOptions}
                selectedWorkflowId={workflowId}
                onSelect={setWorkflowId}
              />
            </SectionCard>

            <SectionCard title="Input Files" eyebrow="Data Sources">
              <InputGrid inputs={visibleInputs} onBrowse={handleBrowse} onSheetChange={handleSheetChange} />
            </SectionCard>

            <SectionCard title="Column Mapping" eyebrow="Field Assignment">
              <MappingTable
                rows={mappingRows}
                overrides={mappingOverrides}
                onOverride={(canonical, mappedTo) =>
                  setMappingOverrides((current) => ({ ...current, [canonical]: mappedTo }))
                }
              />
            </SectionCard>

            <SectionCard title="Options" eyebrow="Comparison Settings">
              <div className="setup-grid">
                {Object.entries(options).map(([key, value]) => (
                  <label
                    key={key}
                    className="setup-block"
                    style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}
                  >
                    <input
                      type="checkbox"
                      checked={value}
                      onChange={() => setOptions((prev) => ({ ...prev, [key]: !prev[key as keyof typeof prev] }))}
                    />
                    <span className="setup-block__label">{key.replace(/_/g, " ")}</span>
                  </label>
                ))}
              </div>
            </SectionCard>
          </div>

          <aside className="workspace-grid__side workspace-grid__side--sticky">
            <SectionCard
              title={contextView === "preview" ? "Review" : "Execution"}
              eyebrow="Context Panel"
              actions={
                <div style={{ display: "flex", gap: "0.25rem" }}>
                  <button
                    type="button"
                    className={`context-tab ${contextView === "preview" ? "context-tab--active" : ""}`}
                    onClick={() => setContextView("preview")}
                  >
                    Preview
                  </button>
                  <button
                    type="button"
                    className={`context-tab ${contextView === "run" ? "context-tab--active" : ""}`}
                    onClick={() => setContextView("run")}
                  >
                    Run
                  </button>
                </div>
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
                  cancelPending={panelCancelPending}
                  logLines={panelLogLines}
                  truncatedLogCount={panelTruncatedLogCount}
                  errorCode={panelErrorCode}
                  errorTraceback={panelErrorTraceback}
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
