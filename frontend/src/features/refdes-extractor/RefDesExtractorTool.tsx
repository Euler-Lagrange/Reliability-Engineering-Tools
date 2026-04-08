import { useEffect, useMemo, useRef, useState } from "react";
import { CustomSelect } from "../../components/CustomSelect";
import { InputGrid } from "../../components/InputGrid";
import { RunStatePanel } from "../../components/RunStatePanel";
import { SectionCard } from "../../components/SectionCard";
import { ValidationPreview } from "../../components/ValidationPreview";
import { executeRunResultSchema } from "../../contracts/sidecar";
import {
  refdesDemoScenarios,
} from "../../mocks/scenarios";
import type {
  FileRole,
  InputFileState,
  RunEvent,
  RunEventTemplate,
  RunMode,
  ValidationMessage,
} from "../../app/types";
import { backendClient, type RunRequestBody } from "../../shared/backend/client";
import { buildRunTimeline, isBusyRunPhase, useBackendRunLifecycle } from "../../shared/backend/runLifecycle";
import { ErrorBoundary } from "../../shared/errors/ErrorBoundary";
import { useRoleRequestSequence } from "../../shared/hooks/useRoleRequestSequence";
import { useNotificationStore } from "../../stores/notificationStore";
import { useShellStore } from "../../stores/shellStore";

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

function parseRefDesRunResult(payload: unknown) {
  return executeRunResultSchema.parse(payload);
}

export function RefDesExtractorTool() {
  const baseScenario = refdesDemoScenarios[0];
  const [inputStates, setInputStates] = useState<InputFileState[]>(() => cloneInputs(baseScenario.inputs));
  const [options, setOptions] = useState({
    extraction_mode: "functional",
    backend_mode: "auto",
    geometry_analysis_enabled: true,
    adaptive_geometry_enabled: true,
    geometry_batch_size: 10,
    max_pin_label_length: 4,
    prov_distance: 15.0,
  });
  const [validations, setValidations] = useState<ValidationMessage[]>(baseScenario.validations);
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
  } = useBackendRunLifecycle("refdes_extractor", backendClient.runtimeMode, parseRefDesRunResult);
  // Per-role token used to discard stale async listSheets results.
  const fileRequestSeq = useRoleRequestSequence<FileRole>();

  const inputRoles = useMemo(() => {
    const roles: FileRole[] = ["pdf", "bom"];
    if (options.extraction_mode === "piece_part") {
      roles.push("pinlist");
    }
    return roles;
  }, [options.extraction_mode]);

  const visibleInputs = useMemo(
    () => inputStates.filter((i) => inputRoles.includes(i.role as FileRole)),
    [inputStates, inputRoles],
  );

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
        title: "RefDes extraction complete",
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
        title: "RefDes extraction failed",
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
        title: "RefDes extraction cancelled",
        detail: desktopRunSession.statusMessage ?? "The active backend run was cancelled.",
      });
    }
  }, [desktopRunSession, pushNotification, setBackendState]);

  function buildRunRequest(): RunRequestBody {
    return {
      workflowId: "refdes_extract",
      outputStrategyId: "new_workbook_standard",
      inputs: visibleInputs
        .filter((i) => Boolean(i.path))
        .map((input) => ({
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
      mappings: [],
      options,
    };
  }

  async function handleBrowse(role: FileRole) {
    const pickedPath =
      role === "pdf"
        ? await backendClient.openPdfFile()
        : await backendClient.openExcelFile();

    if (!pickedPath) {
      if (backendClient.runtimeMode !== "desktop-bridge") {
        pushNotification({
          tone: "info",
          title: "Browser preview active",
          detail: "Run the Tauri desktop shell to browse a real file and load it from Python.",
        });
      }
      return;
    }

    if (role === "pdf") {
      setInputStates((current) =>
        current.map((input) =>
          input.role === role
            ? {
                ...input,
                path: pickedPath,
                source: "desktop-bridge" as const,
                tag: "Ready",
                status: "ready" as const,
              }
            : input,
        ),
      );
      return;
    }

    // Excel: standard sheet resolution flow
    // Stale-safe: bump the per-role token so any older listSheets in flight
    // for this role is ignored when it eventually resolves.
    const token = fileRequestSeq.begin(role);

    setInputStates((current) =>
      current.map((input) =>
        input.role === role
          ? {
              ...input,
              path: pickedPath,
              source: "desktop-bridge" as const,
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
      const sheetsResult = await backendClient.listSheets(pickedPath);
      if (!fileRequestSeq.isCurrent(role, token)) return;
      setInputStates((current) =>
        current.map((input) =>
          input.role === role
            ? {
                ...input,
                path: sheetsResult.path,
                source: "desktop-bridge" as const,
                sheets: sheetsResult.sheets.map((s) => ({
                  id: s.toLowerCase().replace(/\s+/g, "_"),
                  label: s,
                })),
                selectedSheet: sheetsResult.sheets[0] ?? "",
                isResolvingSheets: false,
                isAnalyzing: false,
                resolutionError:
                  sheetsResult.sheets.length > 0
                    ? null
                    : "No sheets were found in the selected workbook.",
                tag: sheetsResult.sheets.length > 0 ? "Loaded" : "Empty workbook",
              }
            : input,
        ),
      );
      setBackendState({
        backendStatus: "ready",
        backendMode: sheetsResult.mode,
        backendMessage: `Loaded ${sheetsResult.sheets.length} sheet${sheetsResult.sheets.length === 1 ? "" : "s"} from ${role}.`,
        lastBackendCheckAt: new Date().toISOString(),
      });
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

  function handleSheetChange(role: FileRole, selectedSheet: string) {
    setInputStates((current) =>
      current.map((input) => {
        if (input.role !== role) {
          return input;
        }
        return {
          ...input,
          selectedSheet,
        };
      }),
    );
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
        backendMessage: "Running RefDes extraction through the desktop backend...",
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
        title: "RefDes extraction failed",
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
      title="RefDes Extractor error"
      detail="An error occurred in the RefDes Extractor."
    >
      <div className="tool-workspace">
        <section className="tool-banner">
          <div>
            <p className="eyebrow">RefDes Extractor</p>
            <h2 className="tool-banner__title">RefDes Extractor</h2>
          </div>
          <div className="tool-banner__chips">
            <span className={`status-chip status-chip--${backendMode === "desktop-bridge" ? "success" : "pending"}`}>
              {backendMode === "desktop-bridge" ? "Desktop bridge" : "Browser preview"}
            </span>
          </div>
        </section>

        <section className="workspace-grid workspace-grid--single">
          <div className="workspace-grid__main">
            <SectionCard title="Input Files" eyebrow="Data Sources">
              <InputGrid inputs={visibleInputs} onBrowse={handleBrowse} onSheetChange={handleSheetChange} />
            </SectionCard>

            <SectionCard title="Options" eyebrow="Extraction Settings">
              <div className="setup-grid">
                <div className="setup-block">
                  <p className="setup-block__label">Extraction mode</p>
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    {(["functional", "piece_part"] as const).map((mode) => (
                      <button
                        key={mode}
                        type="button"
                        className={`toggle-chip ${options.extraction_mode === mode ? "toggle-chip--active" : ""}`}
                        data-active={options.extraction_mode === mode}
                        onClick={() => setOptions((prev) => ({ ...prev, extraction_mode: mode }))}
                        style={{
                          padding: "4px 12px",
                          borderRadius: "999px",
                          border: options.extraction_mode === mode ? "1px solid var(--accent)" : "1px solid var(--line)",
                          background: options.extraction_mode === mode ? "var(--accent)" : "transparent",
                          color: options.extraction_mode === mode ? "#ffffff" : "var(--text)",
                          cursor: "pointer",
                          fontSize: "var(--text-base)",
                          fontWeight: "var(--weight-medium)",
                          fontFamily: "inherit",
                        }}
                      >
                        {mode === "functional" ? "Functional" : "Piece-Part"}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="setup-block">
                  <p className="setup-block__label">Backend</p>
                  <CustomSelect
                    label="Backend mode"
                    value={options.backend_mode}
                    options={[
                      { value: "auto", label: "Auto (recommended)" },
                      { value: "nextgen", label: "NextGen only" },
                      { value: "legacy", label: "Legacy only" },
                    ]}
                    onChange={(v) => setOptions((prev) => ({ ...prev, backend_mode: v }))}
                  />
                </div>

                <div className="setup-block">
                  <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={options.geometry_analysis_enabled}
                      onChange={() =>
                        setOptions((prev) => ({
                          ...prev,
                          geometry_analysis_enabled: !prev.geometry_analysis_enabled,
                        }))
                      }
                    />
                    <span>Enable geometry analysis</span>
                  </label>
                </div>

                <div className="setup-block">
                  <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={options.adaptive_geometry_enabled}
                      onChange={() =>
                        setOptions((prev) => ({
                          ...prev,
                          adaptive_geometry_enabled: !prev.adaptive_geometry_enabled,
                        }))
                      }
                    />
                    <span>Adaptive geometry (smart page gating)</span>
                  </label>
                </div>
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
                  startLabel="Extract"
                />
              )}
            </SectionCard>
          </aside>
        </section>
      </div>
    </ErrorBoundary>
  );
}
