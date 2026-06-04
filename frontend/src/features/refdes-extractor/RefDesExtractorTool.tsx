import { useEffect, useMemo, useRef, useState } from "react";
import { CustomSelect } from "../../components/CustomSelect";
import { InputGrid } from "../../components/InputGrid";
import { RunStatePanel } from "../../components/RunStatePanel";
import { SectionCard } from "../../components/SectionCard";
import { ValidationPreview } from "../../components/ValidationPreview";
import { CheckboxField } from "../../components/primitives/CheckboxField";
import { ContextTabs } from "../../components/primitives/ContextTabs";
import { EmptyState } from "../../components/primitives/EmptyState";
import { OptionsField } from "../../components/primitives/OptionsField";
import { OptionsSection } from "../../components/primitives/OptionsSection";
import { OutputFolderPicker } from "../../components/OutputFolderPicker";
import { ToggleChip } from "../../components/primitives/ToggleChip";
import { MagnifyingGlass } from "@phosphor-icons/react";
import {
  refdesDemoScenarios,
} from "../../mocks/scenarios";
import type {
  FileRole,
  InputFileState,
  RunEventTemplate,
  RunMode,
  ValidationMessage,
} from "../../app/types";
import { backendClient, type RunRequestBody } from "../../shared/backend/client";
import { parentDirectoryForPath } from "../../shared/backend/fileManager";
import {
  buildTimeline,
  cloneInputs,
  useDesktopRunController,
} from "../../shared/backend/useDesktopRunController";
import { ErrorBoundary } from "../../shared/errors/ErrorBoundary";
import { useRoleRequestSequence } from "../../shared/hooks/useRoleRequestSequence";
import { useNotificationStore } from "../../stores/notificationStore";
import { usePreviewStore } from "../../stores/previewStore";
import { useShellStore } from "../../stores/shellStore";

type ExtractionMode = "functional" | "piece_part";
type BackendMode = "auto" | "nextgen" | "legacy";

interface RefDesOptions {
  extraction_mode: ExtractionMode;
  backend_mode: BackendMode;
  geometry_analysis_enabled: boolean;
  adaptive_geometry_enabled: boolean;
  geometry_batch_size: number;
  max_pin_label_length: number;
  prov_distance: number;
  [key: string]: unknown;
}

export function RefDesExtractorTool() {
  const baseScenario = refdesDemoScenarios[0];
  const [inputStates, setInputStates] = useState<InputFileState[]>(() => cloneInputs(baseScenario.inputs));
  const [options, setOptions] = useState<RefDesOptions>({
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
  const contextHeadingRef = useRef<HTMLHeadingElement | null>(null);
  const backendMode = useShellStore((state) => state.backendMode);
  const setBackendState = useShellStore((state) => state.setBackendState);
  const refdesExtractorOutputDirectory = useShellStore(
    (state) => state.refdesExtractorOutputDirectory,
  );
  const setRefdesExtractorOutputDirectory = useShellStore(
    (state) => state.setRefdesExtractorOutputDirectory,
  );
  const pushNotification = useNotificationStore((state) => state.push);
  const setPreview = usePreviewStore((state) => state.setPreview);

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
  const {
    beginAcceptedRun,
    resetSession: resetDesktopRunSession,
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
  } = useDesktopRunController("refdes_extractor", {
    successMessage: (outputFile) => `Report written to ${outputFile}.`,
    successTitle: "RefDes extraction complete",
    failureTitle: "RefDes extraction failed",
    cancelledTitle: "RefDes extraction cancelled",
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
      const detail = error instanceof Error ? error.message : "Failed to open output folder";
      pushNotification({ tone: "error", title: "Open output folder failed", detail });
    }
  }

  // Pristine = no real input loaded yet AND no run has been started.
  // Switching to piece-part extraction is a sign of engagement (and
  // reveals the pinlist slot), so we exit pristine then — mirroring the
  // BOM Compare workflow-switch escape.
  //
  // We evaluate the example check against ALL inputStates, not just
  // visibleInputs: in Functional mode the pinlist is filtered out of
  // visibleInputs (inputRoles), so a pinlist that was loaded in Piece-Part
  // mode and survives in state still counts as engagement. Scoping to
  // visibleInputs would lose that engagement on toggle-back and wrongly
  // revert the InputGrid to the pristine EmptyState.
  const isPristine =
    options.extraction_mode === "functional" &&
    inputStates.every((input) => input.isExample === true) &&
    panelRunMode === "idle";

  const handleLoadExample = () => {
    pushNotification({
      tone: "info",
      title: "Example files coming soon",
      detail: "Bundled example schematics aren't shipping yet. For now, browse to a real PDF.",
    });
  };

  const firstInputRole = visibleInputs[0]?.role ?? null;

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
      outputDirectory: refdesExtractorOutputDirectory,
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
                // A real file replaces the example mock — clears the
                // pristine EmptyState so the full input grid renders.
                isExample: false,
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
      setPreview("refdes_extractor", validation.output_preview ?? null);

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

      armTerminalHandler();
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
            <SectionCard
              title="Input Files"
              eyebrow="Data Sources"
              description="Load the schematic PDF and the BOM. The pinlist is required for piece-part extraction."
            >
              {isPristine ? (
                <EmptyState
                  icon={MagnifyingGlass}
                  headline="Extract reference designators"
                  body="Pick a schematic PDF and BOM to extract reference designators. Piece-part extraction also requires a pinlist."
                  primaryAction={{
                    label: "Browse for schematic",
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
                <InputGrid inputs={visibleInputs} onBrowse={handleBrowse} onSheetChange={handleSheetChange} />
              )}
            </SectionCard>

            <OptionsSection
              title="Options"
              eyebrow="Extraction Settings"
              description="Pick the extraction strategy and backend."
            >
              <OptionsField label="Extraction mode">
                <ToggleChip<ExtractionMode>
                  ariaLabel="Extraction mode"
                  mode="radio"
                  value={options.extraction_mode}
                  onChange={(next) =>
                    setOptions((prev) => ({ ...prev, extraction_mode: next as ExtractionMode }))
                  }
                  options={[
                    { value: "functional", label: "Functional" },
                    { value: "piece_part", label: "Piece-Part" },
                  ]}
                />
              </OptionsField>

              <OptionsField label="Backend">
                <CustomSelect
                  label="Backend mode"
                  value={options.backend_mode}
                  options={[
                    { value: "auto", label: "Auto (recommended)" },
                    { value: "nextgen", label: "NextGen only" },
                    { value: "legacy", label: "Legacy only" },
                  ]}
                  onChange={(v) =>
                    setOptions((prev) => ({ ...prev, backend_mode: v as BackendMode }))
                  }
                />
              </OptionsField>

              <CheckboxField
                id="refdes-geometry-analysis"
                label="Enable geometry analysis"
                checked={options.geometry_analysis_enabled}
                onChange={(next) =>
                  setOptions((prev) => ({ ...prev, geometry_analysis_enabled: next }))
                }
              />

              <CheckboxField
                id="refdes-adaptive-geometry"
                label="Adaptive geometry (smart page gating)"
                checked={options.adaptive_geometry_enabled}
                // Presentation-only gate: the backend returns from the
                // annotation-only branch before reading adaptive_geometry_enabled
                // when geometry analysis is off, so the option is silently inert.
                // Disable (don't mutate) the value to reflect that.
                disabled={!options.geometry_analysis_enabled}
                hint={
                  !options.geometry_analysis_enabled
                    ? "Requires geometry analysis"
                    : undefined
                }
                onChange={(next) =>
                  setOptions((prev) => ({ ...prev, adaptive_geometry_enabled: next }))
                }
              />

              <OutputFolderPicker
                value={refdesExtractorOutputDirectory}
                onChange={setRefdesExtractorOutputDirectory}
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
