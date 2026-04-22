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
import { GitDiff } from "@phosphor-icons/react";
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
import { DO_NOT_MAP_VALUE } from "../../app/types";
import { backendClient, type RunRequestBody } from "../../shared/backend/client";
import { buildCancelNotification } from "../../shared/backend/cancelError";
import { parentDirectoryForPath } from "../../shared/backend/fileManager";
import { buildRunTimeline, useBackendRunLifecycle } from "../../shared/backend/runLifecycle";
import { ErrorBoundary } from "../../shared/errors/ErrorBoundary";
import { useRoleRequestSequence } from "../../shared/hooks/useRoleRequestSequence";
import { useNotificationStore } from "../../stores/notificationStore";
import { usePreviewStore } from "../../stores/previewStore";
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
  const contextHeadingRef = useRef<HTMLHeadingElement | null>(null);
  const handledDesktopTerminalRef = useRef<string | null>(null);
  const backendMode = useShellStore((state) => state.backendMode);
  const setBackendState = useShellStore((state) => state.setBackendState);
  const bomCompareOutputDirectory = useShellStore(
    (state) => state.bomCompareOutputDirectory,
  );
  const setBomCompareOutputDirectory = useShellStore(
    (state) => state.setBomCompareOutputDirectory,
  );
  const pushNotification = useNotificationStore((state) => state.push);
  const setPreview = usePreviewStore((state) => state.setPreview);

  const {
    session: desktopRunSession,
    beginAcceptedRun,
    resetSession: resetDesktopRunSession,
  } = useBackendRunLifecycle("bom_compare");
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
  const panelTruncatedLogCount =
    backendClient.runtimeMode === "desktop-bridge" ? desktopRunSession.truncatedLogCount : 0;
  const panelErrorCode =
    backendClient.runtimeMode === "desktop-bridge" ? desktopRunSession.errorCode : null;
  const panelErrorTraceback =
    backendClient.runtimeMode === "desktop-bridge" ? desktopRunSession.errorTraceback : null;

  async function handleRevealOutput(path: string) {
    try {
      await backendClient.revealInFileManager(parentDirectoryForPath(path));
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Failed to open output folder";
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
    // TODO (Phase 4 Task 6): promote the FMEA OutputStrategySelector to
    // shared and wire it here. Deferred: `backend/python/bom_compare/runtime.py`
    // currently only accepts `new_workbook_standard` (no `output_strategy`
    // handling), so adding a selector would be user-visible but would
    // silently no-op until backend support lands. Re-evaluate when the
    // backend runtime surfaces a `preserve_formatting` code path.
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
      setContextView("run");
      setRunMode("running");
      setRunIndex(0);
      return;
    }

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
      // Phase B3: reject cancels issued while the session is still idle
      // so stale run IDs never reach the sidecar.
      //
      // Fix E3: only fire the cancel on ``starting`` / ``running``
      // phases. A previous helper also matched ``cancelling`` which
      // let a double-click trigger a second cancel_run request — the
      // sidecar would reject the second one with "No active run
      // matches" and the user saw a confusing notification after
      // they already cancelled.
      if (
        !desktopRunSession.runId ||
        (desktopRunSession.phase !== "starting" &&
          desktopRunSession.phase !== "running")
      ) {
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
          // Phase B3: surface the sidecar's real error message (Tauri
          // rejects with a raw string, not an Error instance).
          pushNotification(buildCancelNotification(error));
        });
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
            <SectionCard
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
              title="Input Files"
              eyebrow="Data Sources"
              description="Load the workbooks you want to compare."
            >
              {isPristine ? (
                <EmptyState
                  icon={GitDiff}
                  headline="Compare two BOMs"
                  body="Load the workbooks you want to compare. Group mode aligns a grouping sheet to a BOM; custom mode compares two BOMs directly."
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
              {Object.entries(options).map(([key, value]) => (
                <CheckboxField
                  key={key}
                  id={`bom-compare-option-${key}`}
                  label={key.replace(/_/g, " ")}
                  checked={value}
                  onChange={(next) =>
                    setOptions((prev) => ({ ...prev, [key]: next } as typeof prev))
                  }
                />
              ))}
              <OutputFolderPicker
                value={bomCompareOutputDirectory}
                onChange={setBomCompareOutputDirectory}
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
