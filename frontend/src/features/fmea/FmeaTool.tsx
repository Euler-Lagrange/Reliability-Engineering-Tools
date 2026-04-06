import { startTransition, useEffect, useMemo, useRef, useState } from "react";
import { InputGrid } from "../../components/InputGrid";
import { MappingTable } from "../../components/MappingTable";
import { RunStatePanel } from "../../components/RunStatePanel";
import { SectionCard } from "../../components/SectionCard";
import { StrategySelector } from "../../components/StrategySelector";
import { ValidationPreview } from "../../components/ValidationPreview";
import { WorkflowSelector } from "../../components/WorkflowSelector";
import { executeRunResultSchema } from "../../contracts/sidecar";
import { demoScenarios, outputStrategies, workflowOptions } from "../../mocks/scenarios";
import type {
  AnalysisContextCard,
  ColumnMappingRow,
  FileRole,
  InputInspection,
  InputFileState,
  OutputStrategyId,
  RunEvent,
  RunEventTemplate,
  RunMode,
  TemplateAnalysis,
  ValidationMessage,
  WorkflowId,
} from "../../app/types";
import { backendClient, type RunRequestBody } from "../../shared/backend/client";
import { buildRunTimeline, isBusyRunPhase, useBackendRunLifecycle } from "../../shared/backend/runLifecycle";
import { ErrorBoundary } from "../../shared/errors/ErrorBoundary";
import { useNotificationStore } from "../../stores/notificationStore";
import { useShellStore } from "../../stores/shellStore";

const baseScenario = demoScenarios[0];
const phase4RunEvents: RunEventTemplate[] = [
  {
    id: "phase4-1",
    title: "Validate run state",
    detail: "The desktop backend checks required files and confirms the first executable path is supported.",
    progress: 18,
  },
  {
    id: "phase4-2",
    title: "Generate FMEA rows",
    detail: "The copied FMEA processor builds the workbook rows through the migrated backend tree.",
    progress: 64,
  },
  {
    id: "phase4-3",
    title: "Write workbook",
    detail: "The migrated backend writes a new output workbook and returns the artifact path to the shell.",
    progress: 100,
  },
];

const workflowInputRoles: Partial<Record<WorkflowId, FileRole[]>> = {
  piece_part_generate: ["grouping", "bom", "hda", "failureModes"],
  bom_only: ["bom", "hda", "failureModes"],
  fill_gaps: ["existingFmea", "bom", "hda", "grouping", "failureModes"],
};

function buildVisibleInputs(
  inputs: InputFileState[],
  workflowId: WorkflowId,
  outputStrategyId: OutputStrategyId,
  enrichments: { functional: boolean; piecePart: boolean },
) {
  const orderedRoles = [...(workflowInputRoles[workflowId] ?? [])];
  const supportsEnrichment = workflowId !== "fill_gaps";

  if (supportsEnrichment && enrichments.functional) {
    orderedRoles.push("functionalFmea");
  }

  if (supportsEnrichment && enrichments.piecePart) {
    orderedRoles.push("piecePartFmea");
  }

  if (outputStrategyId !== "new_workbook_standard") {
    orderedRoles.push("targetWorkbook");
  }

  return orderedRoles
    .map((role) => inputs.find((input) => input.role === role))
    .filter((input): input is InputFileState => Boolean(input));
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

function buildRunRequest(
  workflowId: WorkflowId,
  outputStrategyId: OutputStrategyId,
  enrichments: { functional: boolean; piecePart: boolean },
  visibleInputs: InputFileState[],
  mappingRows: ColumnMappingRow[],
  mappingOverrides: Record<string, string>,
): RunRequestBody {
  return {
    workflowId,
    outputStrategyId,
    enrichments,
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
  };
}

function toFailureResult(detail: string) {
  return {
    status: "failure" as const,
    title: "Run failed",
    summary: detail,
    outputFile: "",
    primaryMetric: "No workbook written",
    secondaryMetric: "Review backend diagnostics",
    notes: ["This Phase 4 slice returns the backend failure directly instead of attempting recovery."],
  };
}

function parseFmeaRunResult(payload: unknown) {
  return executeRunResultSchema.parse(payload);
}

function normalizeHeader(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, " ");
}

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

function buildMappingRows(
  rows: ColumnMappingRow[],
  inspectedColumns: string[],
  sourceLabel: string | null,
): ColumnMappingRow[] {
  if (inspectedColumns.length === 0) {
    return rows;
  }

  const exactMap = new Map(inspectedColumns.map((column) => [normalizeHeader(column), column]));

  return rows.map((row) => {
    const exactMatch = exactMap.get(normalizeHeader(row.canonical));
    const mergedOptions = Array.from(new Set([...(exactMatch ? [exactMatch] : []), ...inspectedColumns, ...row.options]));

    if (!exactMatch) {
      return {
        ...row,
        options: mergedOptions,
      };
    }

    return {
      ...row,
      mappedTo: exactMatch,
      status: "mapped",
      recommendation: sourceLabel
        ? `Exact header found in ${sourceLabel}.`
        : "Exact header found in inspected workbook.",
      options: mergedOptions,
    };
  });
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
      detail: `${inspection.columns.length} headers were found in the selected input workbook.`,
      metrics: [`Header row ${inspection.headerRow}`, `${inspection.rowCount} data rows`],
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
      ],
    });
  }

  return cards;
}

export function FmeaTool() {
  const [workflowId, setWorkflowId] = useState<WorkflowId>(baseScenario.workflowId);
  const [outputStrategyId, setOutputStrategyId] = useState<OutputStrategyId>(baseScenario.outputStrategyId);
  const [enrichments, setEnrichments] = useState(baseScenario.enrichments);
  const [inputStates, setInputStates] = useState<InputFileState[]>(() => cloneInputs(baseScenario.inputs));
  const [validations, setValidations] = useState<ValidationMessage[]>(baseScenario.validations);
  const [inputInspections, setInputInspections] = useState<Partial<Record<FileRole, InputInspection>>>({});
  const [templateAnalyses, setTemplateAnalyses] = useState<Partial<Record<FileRole, TemplateAnalysis>>>({});
  const [mappingOverrides, setMappingOverrides] = useState<Record<string, string>>({});
  const [runMode, setRunMode] = useState<RunMode>("idle");
  const [runIndex, setRunIndex] = useState(-1);
  const [runTemplates, setRunTemplates] = useState<RunEventTemplate[]>(baseScenario.runSequence.events);
  const [runResult, setRunResult] = useState<typeof baseScenario.runSequence.result | null>(null);
  const [runLogLines, setRunLogLines] = useState<string[]>([]);
  const [cancelledNotice, setCancelledNotice] = useState<string | null>(null);
  const [contextView, setContextView] = useState<"preview" | "run">("preview");
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
  } = useBackendRunLifecycle(backendClient.runtimeMode, parseFmeaRunResult);

  useEffect(() => {
    startTransition(() => {
      setValidations(baseScenario.validations);
      setMappingOverrides({});
      setInputInspections({});
      setTemplateAnalyses({});
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
  }, [workflowId, outputStrategyId]);

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

  const visibleInputs = useMemo(
    () => buildVisibleInputs(inputStates, workflowId, outputStrategyId, enrichments),
    [enrichments, inputStates, outputStrategyId, workflowId],
  );
  const preferredAnalysisRole = visibleInputs.find((input) => input.source === "desktop-bridge")?.role ?? null;
  const activeInspection = preferredAnalysisRole ? inputInspections[preferredAnalysisRole] ?? null : null;
  const activeTemplateAnalysis = templateAnalyses.targetWorkbook ?? null;
  const inspectedColumns =
    activeTemplateAnalysis?.columns ??
    activeInspection?.columns ??
    [];
  const inspectedSourceLabel = activeTemplateAnalysis
    ? `${activeTemplateAnalysis.sheet} template`
    : activeInspection
      ? `${activeInspection.sheet} input`
      : null;
  const effectiveMappings = useMemo(
    () => buildMappingRows(baseScenario.mappings, inspectedColumns, inspectedSourceLabel),
    [inspectedColumns, inspectedSourceLabel],
  );
  const analysisCards = useMemo(
    () => buildAnalysisCards(activeInspection, activeTemplateAnalysis),
    [activeInspection, activeTemplateAnalysis],
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
  const panelRunId = backendClient.runtimeMode === "desktop-bridge" ? desktopRunSession.runId : null;
  const panelStatusMessage =
    backendClient.runtimeMode === "desktop-bridge" ? desktopRunSession.statusMessage : null;

  const mappingCoverage = Math.round(
    (effectiveMappings.filter((row) => row.status === "mapped").length / effectiveMappings.length) * 100,
  );

  const activeWorkflow = workflowOptions.find((workflow) => workflow.id === workflowId) ?? workflowOptions[0];

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
        backendMessage: `Generated workbook at ${desktopRunSession.result.output_file}.`,
        lastBackendCheckAt: new Date().toISOString(),
      });
      pushNotification({
        tone: "success",
        title: "FMEA generated",
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
        title: "FMEA run failed",
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
        title: "FMEA run cancelled",
        detail: desktopRunSession.statusMessage ?? "The active backend run was cancelled.",
      });
    }
  }, [desktopRunSession, pushNotification, setBackendState]);

  async function inspectRole(role: FileRole, path: string, sheet: string) {
    if (!sheet) {
      return;
    }

    const requestedPath = path;
    const requestedSheet = sheet;

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
      if (role === "targetWorkbook" && outputStrategyId !== "new_workbook_standard") {
        const template = await backendClient.analyzeTemplate(path, sheet, role);
        setInputStates((current) => {
          const cur = current.find((i) => i.role === role);
          if (cur?.path !== requestedPath || cur?.selectedSheet !== requestedSheet) return current;
          return current.map((input) =>
            input.role === role ? { ...input, isAnalyzing: false, tag: "Analyzed" } : input,
          );
        });
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
        const inspection = await backendClient.inspectInput(path, sheet, role);
        setInputStates((current) => {
          const cur = current.find((i) => i.role === role);
          if (cur?.path !== requestedPath || cur?.selectedSheet !== requestedSheet) return current;
          return current.map((input) =>
            input.role === role ? { ...input, isAnalyzing: false, tag: "Analyzed" } : input,
          );
        });
        setInputInspections((current) => ({
          ...current,
          [role]: {
            role,
            path: inspection.path,
            sheet: inspection.sheet,
            headerRow: inspection.header_row,
            rowCount: inspection.row_count,
            columns: inspection.columns,
            previewRows: inspection.preview_rows,
            mode: inspection.mode,
          },
        }));
        setBackendState({
          backendStatus: "ready",
          backendMode: inspection.mode,
          backendMessage: `Inspected ${inspection.sheet} with ${inspection.columns.length} headers.`,
          lastBackendCheckAt: new Date().toISOString(),
        });
      }
    } catch (error) {
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

    const runRequest = buildRunRequest(
      workflowId,
      outputStrategyId,
      enrichments,
      visibleInputs,
      effectiveMappings,
      mappingOverrides,
    );

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
        setRunTemplates(phase4RunEvents);
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

      setRunTemplates(phase4RunEvents);
      setBackendState({
        backendStatus: "busy",
        backendMode: validation.mode,
        backendMessage: "Generating workbook through the migrated backend...",
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
        title: "FMEA run failed",
        detail,
      });
    }
  }

  return (
    <div className="tool-workspace">
      <section className="tool-banner">
        <div>
          <p className="eyebrow">Dark Star FMEA</p>
          <h2 className="tool-banner__title">Suite shell wired to the migrated FMEA workspace</h2>
          <p className="section-card__description">
            The old scenario rail is removed from the shell path. This screen now behaves like a real tool tab that is ready
            for sidecar wiring.
          </p>
        </div>
        <div className="tool-banner__chips">
          <span className={`status-chip status-chip--${backendMode === "desktop-bridge" ? "success" : "pending"}`}>
            {backendMode === "desktop-bridge" ? "Desktop bridge" : "Browser preview"}
          </span>
          <span className="status-chip status-chip--info">Phase 4 run slice</span>
        </div>
      </section>

      <section className="workspace-grid workspace-grid--single">
        <div className="workspace-grid__main">
          <SectionCard
            className="section-card--compact"
            title="Run Setup"
            eyebrow="Configuration"
            description="Choose the workflow, output path, and optional enrichments before reviewing inputs and mappings."
            actions={
              <div className="header-metrics">
                <span className="header-metric">
                  <span>Workflow</span>
                  <strong>{activeWorkflow.title}</strong>
                </span>
                <span className="header-metric">
                  <span>Auto-mapped</span>
                  <strong>{mappingCoverage}%</strong>
                </span>
              </div>
            }
          >
            <div className="setup-grid">
              <div className="setup-block">
                <p className="setup-block__label">Workflow</p>
                <WorkflowSelector workflows={workflowOptions} selectedWorkflowId={workflowId} onSelect={setWorkflowId} />
              </div>

              <div className="setup-block">
                <p className="setup-block__label">Output</p>
                <StrategySelector
                  strategies={outputStrategies}
                  selectedStrategyId={outputStrategyId}
                  onSelect={setOutputStrategyId}
                />
              </div>

              <div className="setup-block setup-block--full">
                <p className="setup-block__label">Enrichments</p>
                {activeWorkflow.supportsEnrichment ? (
                  <div className="toggle-row">
                    <button
                      type="button"
                      className="toggle-chip"
                      data-active={enrichments.functional}
                      onClick={() =>
                        setEnrichments((current) => ({ ...current, functional: !current.functional }))
                      }
                    >
                      Functional FMEA
                    </button>
                    <button
                      type="button"
                      className="toggle-chip"
                      data-active={enrichments.piecePart}
                      onClick={() =>
                        setEnrichments((current) => ({ ...current, piecePart: !current.piecePart }))
                      }
                    >
                      Piece-Part FMEA
                    </button>
                  </div>
                ) : (
                  <p className="section-card__microcopy">
                    Fill-gaps keeps enrichment disabled so the UI stays focused on delta review.
                  </p>
                )}
              </div>
            </div>
          </SectionCard>

          <SectionCard
            className="section-card--compact"
            title="Input Files"
            eyebrow="Inputs"
            description="Only the files needed for the active run are shown. Browse a real workbook to load sheets through the desktop backend bridge."
          >
            <InputGrid inputs={visibleInputs} onBrowse={handleBrowse} onSheetChange={handleSheetChange} />
          </SectionCard>

          <SectionCard
            className="section-card--compact"
            title="Column Mapping"
            eyebrow="Review"
            description={
              inspectedColumns.length > 0
                ? `Mapping options are currently informed by ${inspectedSourceLabel}.`
                : "Legacy-parity/default profile behavior only in the first Tauri FMEA slice."
            }
            actions={
              <button className="ghost-button" type="button" disabled>
                Profile editor later
              </button>
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
                    <span key={column} className="status-chip status-chip--info">
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
            />
          </SectionCard>
        </div>

        <aside className="workspace-grid__side workspace-grid__side--sticky">
          <SectionCard
            className="section-card--compact"
            title="Review Panel"
            eyebrow="Context"
            description={
              contextView === "preview"
                ? "Preview output and validation in one focused panel."
                : "Run feedback stays isolated so it does not compete with setup."
            }
            actions={
              <div className="panel-toggle" role="tablist" aria-label="Context panel">
                <button
                  type="button"
                  className="panel-toggle__button"
                  data-active={contextView === "preview"}
                  role="tab"
                  aria-selected={contextView === "preview"}
                  onClick={() => setContextView("preview")}
                >
                  Preview
                </button>
                <button
                  type="button"
                  className="panel-toggle__button"
                  data-active={contextView === "run"}
                  role="tab"
                  aria-selected={contextView === "run"}
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
            <ErrorBoundary
              title="Panel failed to render"
              detail="The active FMEA context panel hit an error. Reload this panel without tearing down the shell."
            >
              {contextView === "preview" ? (
                <ValidationPreview
                  validations={validations}
                  previewRows={baseScenario.previewRows}
                  analysisCards={analysisCards}
                />
              ) : (
                <RunStatePanel
                  runMode={panelRunMode}
                  progress={panelProgress}
                  timeline={panelTimeline}
                  result={panelRunResult}
                  cancelledNotice={panelCancelledNotice}
                  cancelPending={panelCancelPending}
                  logLines={panelLogLines}
                  startLabel={backendClient.runtimeMode === "desktop-bridge" ? "Start real run" : "Start demo run"}
                  runId={panelRunId}
                  statusMessage={panelStatusMessage}
                  onStart={() => {
                    void handleStartRun();
                  }}
                  onCancel={() => {
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
                      setCancelledNotice("Press cancel again to confirm. This matches the future sidecar cancellation flow.");
                      return;
                    }

                    setRunMode("idle");
                    setRunIndex(-1);
                    setRunResult(null);
                    setCancelPending(false);
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
