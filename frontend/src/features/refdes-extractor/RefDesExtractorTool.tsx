import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { CustomSelect } from "../../components/CustomSelect";
import {
  FILE_INSPECTION_PAUSED_REASON,
  InputGrid,
} from "../../components/InputGrid";
import { RunStatePanel, runStatusWord, type RunReadinessItem } from "../../components/RunStatePanel";
import { SectionCard } from "../../components/SectionCard";
import { ValidationPreview } from "../../components/ValidationPreview";
import { CheckboxField } from "../../components/primitives/CheckboxField";
import { EmptyState } from "../../components/primitives/EmptyState";
import { NumberField } from "../../components/primitives/NumberField";
import { OptionsField } from "../../components/primitives/OptionsField";
import { OptionsSection } from "../../components/primitives/OptionsSection";
import { OutputFolderPicker } from "../../components/OutputFolderPicker";
import { ToggleChip } from "../../components/primitives/ToggleChip";
import { CaretDown, CaretRight, Info, MagnifyingGlass } from "@phosphor-icons/react";
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
  // Advanced engine-tuning parameters. These mirror the backend
  // ``RefDesConfig`` field names 1:1 (see refdes_extractor/runtime.py), so the
  // whole options object spreads straight into the run payload and the config
  // reads each key by name. Defaults MUST match the backend dataclass defaults.
  geometry_subprocess_enabled: boolean;
  geometry_batch_timeout_seconds: number;
  annotation_page_timeout_seconds: number;
  geometry_batch_checkpoint_enabled: boolean;
  pin_assignment_threshold: number;
  refdes_search_radius: number;
  adaptive_orphan_threshold: number;
  adaptive_orphan_ratio: number;
  adaptive_max_pages: number;
  pinlist_prefers_annotation_mode: boolean;
  [key: string]: unknown;
}

// Hover-tooltip copy for every control. Kept beside the type so the option
// keys and their explanations stay in lockstep.
const OPTION_TOOLTIPS: Record<string, string> = {
  extraction_mode:
    "Functional groups components by schematic annotation boxes; Piece-part additionally qualifies individual pins (uses a pinlist if one is provided).",
  backend_mode:
    "Auto runs the NextGen engine first and falls back to Legacy only on error. Force NextGen or Legacy only for troubleshooting.",
  geometry_analysis_enabled:
    "Use vector geometry (component bodies, pins, wires) to qualify and parent pins. Disable for annotation-text-only extraction.",
  adaptive_geometry_enabled:
    "Only run full geometry on pages that need it (smart gating) instead of every page — faster on large documents.",
  geometry_batch_size: "How many pages to process per geometry batch.",
  max_pin_label_length:
    "Maximum characters for a token to be treated as a pin label (filters out long text).",
  prov_distance:
    "Distance in points used to associate PROV/provenance markers with components.",
  geometry_subprocess_enabled:
    "Run geometry analysis in a separate process for crash isolation (slightly slower). Off by default.",
  geometry_batch_timeout_seconds:
    "Maximum seconds spent on one geometry batch before those pages degrade to annotation-only extraction.",
  annotation_page_timeout_seconds:
    "Pages whose annotation read exceeds this are skipped with a warning. Raise for very dense schematics.",
  geometry_batch_checkpoint_enabled:
    "Write a JSON progress checkpoint into a _refdes_test_checkpoints folder inside the output directory after each geometry batch — useful for triaging long runs. Off by default so runs don't add files next to your report.",
  pin_assignment_threshold:
    "Maximum distance in points for assigning a detected pin to a component body (larger captures more pins but risks wrong parents).",
  refdes_search_radius:
    "Search radius in points for associating a RefDes label with its component body.",
  adaptive_orphan_threshold:
    "Minimum number of unqualified (orphan) pins on a page before adaptive mode runs full geometry on it.",
  adaptive_orphan_ratio:
    "Minimum fraction of pins that are orphans (0-1) before adaptive mode runs full geometry on a page.",
  adaptive_max_pages:
    "In adaptive mode, the maximum number of pages to run full geometry on (highest-need pages first).",
  pinlist_prefers_annotation_mode:
    "When a pinlist is provided, prefer fast annotation-first pin qualification over full geometry.",
};

// Minimal accessible hover-tooltip affordance. No dedicated tooltip primitive
// exists in components/primitives, so this reuses the project's established
// pattern: a Phosphor ``Info`` icon (as in MappingTable) carrying a native
// ``title`` (hover tooltip) plus an ``aria-label`` (screen-reader text). It is
// non-interactive by design — never triggers a native alert/confirm.
function InfoTip({ text }: { text: string }) {
  return (
    <span className="refdes-infotip" role="img" aria-label={text} title={text}>
      <Info size={14} weight="regular" aria-hidden="true" />
    </span>
  );
}

// Lays out a control alongside its InfoTip so every option — existing or
// advanced — gets the same hover-tooltip affordance without modifying the
// shared field primitives. Styled via global classes so theme overrides
// (Mission Control, High Contrast) reach it; the row hugs its content so
// the icon sits next to the control instead of floating at the far edge.
function OptionRow({ info, children }: { info: string; children: ReactNode }) {
  return (
    <div className="option-row">
      <div className="option-row__control">{children}</div>
      <InfoTip text={info} />
    </div>
  );
}

export function RefDesExtractorTool() {
  const baseScenario = refdesDemoScenarios[0];
  // Family 1 fix: browser-mock seeds the demo scenario (populated preview);
  // the real desktop runtime seeds empty slots so no example path leaks into
  // a run — critically, the example PDF would otherwise hard-fail fitz.open
  // and the example BOM would silently degrade extraction. Matches FMEA.
  const [inputStates, setInputStates] = useState<InputFileState[]>(() =>
    backendClient.runtimeMode === "browser-mock"
      ? cloneInputs(baseScenario.inputs)
      : emptyInputsFromScenario(baseScenario.inputs),
  );
  const [options, setOptions] = useState<RefDesOptions>({
    extraction_mode: "functional",
    backend_mode: "auto",
    geometry_analysis_enabled: true,
    adaptive_geometry_enabled: true,
    geometry_batch_size: 10,
    max_pin_label_length: 4,
    prov_distance: 15.0,
    // Advanced engine tuning — defaults mirror the backend RefDesConfig.
    geometry_subprocess_enabled: false,
    geometry_batch_timeout_seconds: 240.0,
    // Wave R: per-page annotation-extraction timeout. Keep in lockstep with
    // the backend RefDesConfig default (refdes_extractor/runtime.py).
    annotation_page_timeout_seconds: 30.0,
    // Opt-in: writes JSON checkpoints into the user's output folder.
    // Keep in lockstep with the backend RefDesConfig default.
    geometry_batch_checkpoint_enabled: false,
    pin_assignment_threshold: 50.0,
    refdes_search_radius: 100.0,
    adaptive_orphan_threshold: 5,
    adaptive_orphan_ratio: 0.3,
    adaptive_max_pages: 10,
    pinlist_prefers_annotation_mode: true,
  });
  // Advanced controls are collapsed by default; their defaults still ship in
  // the payload because ``options`` (spread into the run request) holds them
  // whether or not the disclosure is open.
  const [advancedOpen, setAdvancedOpen] = useState(false);
  // M9: demo validations ("Example data staged") are browser-preview content.
  // Desktop starts empty — rendering them there reads as leftover state
  // from a previous session (Wiring Invariant #3).
  const [validations, setValidations] = useState<ValidationMessage[]>(() =>
    backendClient.runtimeMode === "browser-mock" ? baseScenario.validations : [],
  );
  // v2 N5-clone: the Preview/Run ContextTabs retired — the Run rail and
  // the Validation card are permanently visible siblings.
  const [runMode, setRunMode] = useState<RunMode>("idle");
  const [runIndex, setRunIndex] = useState(-1);
  const [runTemplates, setRunTemplates] = useState<RunEventTemplate[]>(baseScenario.runSequence.events);
  const [runResult, setRunResult] = useState<typeof baseScenario.runSequence.result | null>(null);
  const [runLogLines, setRunLogLines] = useState<string[]>([]);
  const [cancelledNotice, setCancelledNotice] = useState<string | null>(null);
  // Fix 2 (Family 2): re-entrancy guard for the desktop run pipeline. Held
  // for the whole validate→execute window so a double-click on Extract can't
  // launch a second run whose rejection (single-active-run guard) would clear
  // the first, live run's session.
  const isStartingRef = useRef(false);
  const isValidatingRef = useRef(false);
  const runConfigurationEpochRef = useRef(0);
  const setBackendState = useShellStore((state) => state.setBackendState);
  const refdesExtractorOutputDirectory = useShellStore(
    (state) => state.refdesExtractorOutputDirectory,
  );
  const setRefdesExtractorOutputDirectory = useShellStore(
    (state) => state.setRefdesExtractorOutputDirectory,
  );
  const setToolModeLabel = useShellStore((state) => state.setToolModeLabel);
  const pushNotification = useNotificationStore((state) => state.push);
  const setPreview = usePreviewStore((state) => state.setPreview);
  const clearPreview = usePreviewStore((state) => state.clearPreview);

  function invalidateRunConfiguration() {
    runConfigurationEpochRef.current += 1;
    clearPreview("refdes_extractor");
    if (isStartingRef.current && isValidatingRef.current) {
      setBackendState({
        backendStatus: "ready",
        backendMode: backendClient.runtimeMode,
        backendMessage: "Run configuration changed. Review the updated setup and start again.",
        lastBackendCheckAt: new Date().toISOString(),
      });
    }
  }

  // v2 N2: publish the extraction mode to the shell topbar's inline
  // mode indicator (keyed by tool id — keep-alive siblings never clash).
  useEffect(() => {
    setToolModeLabel(
      "refdes_extractor",
      options.extraction_mode === "piece_part" ? "Piece-Part" : "Functional",
    );
  }, [options.extraction_mode, setToolModeLabel]);

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
  const activeRunPhase = useRunStore((state) => state.activeRun?.phase);
  const panelRunIsLive = LIVE_PHASES.some((phase) => phase === panelRunMode);
  const anyRunIsLive =
    panelRunIsLive || LIVE_PHASES.some((phase) => phase === activeRunPhase);
  const fileInspectionDisabledReason = anyRunIsLive
    ? FILE_INSPECTION_PAUSED_REASON
    : undefined;

  async function handleRevealOutput(path: string) {
    try {
      await backendClient.revealInFileManager(parentDirectoryForPath(path));
    } catch (error) {
      const detail = describeBackendError(error, "Failed to open output folder");
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
  // Pristine is mode-independent: toggling Functional/Piece-Part is a light
  // option choice, not engagement, so BOTH modes get the onboarding
  // EmptyState until a real file is browsed. (The pinlist slot appears in
  // the InputGrid as soon as any browse exits pristine.)
  const isPristine =
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
      workflowId: baseScenario.workflowId,
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

    invalidateRunConfiguration();

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
    // Fix #17: clear a lingering terminal run before flipping to busy, else
    // useBackendBusyReset (terminal phase + busy) instantly wipes this
    // "Inspecting..." chip. Guarded so a live sibling run survives.
    resetDesktopRunSessionUnlessLive();
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
                // A successfully-loaded pinlist must graduate from its seeded
                // "optional" status to "ready" so InputGrid renders the ✓
                // loaded chip; an empty workbook needs attention instead.
                status: sheetsResult.sheets.length > 0 ? "ready" : "attention",
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
    invalidateRunConfiguration();
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
      setRunMode("running");
      setRunIndex(0);
      return;
    }

    // Cross-tool guard: another tool's live run must not be clobbered by
    // this start's rejection path — toast and bail before sending anything.
    if (guardCrossToolRun()) {
      return;
    }

    // Fix 2 (Family 2): re-entrancy guard. The Extract button is not disabled
    // during the async validate→execute window, so a fast double-click could
    // fire a second pipeline; the second executeRun is rejected by Python's
    // single-active-run guard and its catch used to wipe the FIRST, live run.
    // Swallow the re-entrant call here.
    if (isStartingRef.current) {
      return;
    }
    isStartingRef.current = true;
    isValidatingRef.current = true;
    const runConfigurationEpoch = runConfigurationEpochRef.current;

    const runRequest = buildRunRequest();

    // Fix R2-C1: clear any stale active run from a previous run BEFORE flipping
    // the busy chip. Otherwise useBackendBusyReset would see (previous run's
    // terminal phase + busy) and instantly clear the "Validating..." message.
    resetDesktopRunSession();
    setRunLogLines([]);
    setRunResult(null);
    setCancelledNotice(null);
    setBackendState({
      backendStatus: "busy",
      backendMessage: "Validating run configuration...",
    });

    try {
      const validation = await backendClient.validateRun(runRequest);
      isValidatingRef.current = false;
      if (runConfigurationEpoch !== runConfigurationEpochRef.current) {
        return;
      }
      setValidations(validation.validations);
      setPreview("refdes_extractor", validation.output_preview ?? null);

      if (!validation.ok) {
        setRunMode("idle");
        setRunIndex(-1);
        setRunTemplates(baseScenario.runSequence.events);
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
      if (
        isValidatingRef.current &&
        runConfigurationEpoch !== runConfigurationEpochRef.current
      ) {
        return;
      }
      isValidatingRef.current = false;
      if (handleExecuteRunDispatchError(error)) {
        return;
      }
      const detail = describeBackendError(error, "Unknown backend execution failure");
      // Fix 2 (Family 2): guarded reset — must not clobber a live sibling run.
      resetDesktopRunSessionUnlessLive();
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
    } finally {
      // Release the re-entrancy guard once the validate→execute window has
      // closed. A run accepted in this window is owned by the run store and
      // survives.
      isValidatingRef.current = false;
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

  // v2 N5-clone: Run-rail readiness + section meta derive from state the
  // tool already tracks. RefDes has no column mapping — readiness is
  // inputs + output folder.
  const requiredVisibleInputs = visibleInputs.filter((input) => input.required);
  const loadedRequiredVisibleInputs = requiredVisibleInputs.filter((input) => !!input.path).length;
  const loadedVisibleInputs = visibleInputs.filter((input) => !!input.path).length;
  const readinessItems: RunReadinessItem[] = [
    {
      label: "Inputs loaded",
      value: `${loadedRequiredVisibleInputs} / ${requiredVisibleInputs.length}`,
      tone:
        requiredVisibleInputs.length === 0 ||
        loadedRequiredVisibleInputs === requiredVisibleInputs.length
          ? "ok"
          : "warn",
    },
    {
      label: "Output folder",
      value: refdesExtractorOutputDirectory ? "Custom" : "Default",
      tone: "ok",
    },
  ];

  return (
    <ErrorBoundary
      title="RefDes Extractor error"
      detail="An error occurred in the RefDes Extractor."
    >
      <div className="tool-workspace">
        <section className="workspace-grid workspace-grid--single">
          <div className="workspace-grid__main">
            {/* v2 N5-clone: numbered bare strips; descriptions retired. */}
            <SectionCard
              variant="bare"
              step={1}
              title="Inputs"
              actions={
                isPristine ? undefined : (
                  <span className="section-card__meta num">
                    {loadedVisibleInputs} of {visibleInputs.length} loaded
                  </span>
                )
              }
            >
              {isPristine ? (
                <EmptyState
                  icon={MagnifyingGlass}
                  headline="Extract reference designators"
                  body="Pick a schematic PDF and BOM to extract reference designators. Piece-part extraction can also use an optional pinlist."
                  primaryAction={{
                    label: "Browse for schematic",
                    disabled: anyRunIsLive,
                    disabledReason: fileInspectionDisabledReason,
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
                  browseDisabledReason={fileInspectionDisabledReason}
                />
              )}
            </SectionCard>

            <OptionsSection variant="bare" step={2} title="Options">
              <OptionRow info={OPTION_TOOLTIPS.extraction_mode}>
                <OptionsField label="Extraction mode">
                  <ToggleChip<ExtractionMode>
                    ariaLabel="Extraction mode"
                    value={options.extraction_mode}
                    onChange={(next) => {
                      const extractionMode = next as ExtractionMode;
                      if (extractionMode !== options.extraction_mode) {
                        invalidateRunConfiguration();
                        setOptions((prev) => ({
                          ...prev,
                          extraction_mode: extractionMode,
                        }));
                      }
                    }}
                    options={[
                      { value: "functional", label: "Functional" },
                      { value: "piece_part", label: "Piece-Part" },
                    ]}
                  />
                </OptionsField>
              </OptionRow>

              <OptionRow info={OPTION_TOOLTIPS.backend_mode}>
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
              </OptionRow>

              <OptionRow info={OPTION_TOOLTIPS.geometry_analysis_enabled}>
                <CheckboxField
                  id="refdes-geometry-analysis"
                  label="Enable geometry analysis"
                  checked={options.geometry_analysis_enabled}
                  onChange={(next) =>
                    setOptions((prev) => ({ ...prev, geometry_analysis_enabled: next }))
                  }
                />
              </OptionRow>

              <OptionRow info={OPTION_TOOLTIPS.adaptive_geometry_enabled}>
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
              </OptionRow>

              <OptionRow info={OPTION_TOOLTIPS.geometry_batch_size}>
                <NumberField
                  id="refdes-geometry-batch-size"
                  label="Geometry batch size"
                  value={options.geometry_batch_size}
                  min={1}
                  step={1}
                  // Consumed only on the geometry path (_run_geometry_in_batches);
                  // the backend never reads it when geometry analysis is off, so
                  // disable (don't mutate) the field to mirror the adaptive
                  // checkbox gate.
                  disabled={!options.geometry_analysis_enabled}
                  hint={
                    options.geometry_analysis_enabled
                      ? "Pages per geometry batch"
                      : "Requires geometry analysis"
                  }
                  onChange={(next) =>
                    setOptions((prev) => ({ ...prev, geometry_batch_size: next }))
                  }
                />
              </OptionRow>

              <OptionRow info={OPTION_TOOLTIPS.max_pin_label_length}>
                <NumberField
                  id="refdes-max-pin-label-length"
                  label="Max pin label length"
                  value={options.max_pin_label_length}
                  min={1}
                  step={1}
                  hint="Longest token treated as a pin label"
                  onChange={(next) =>
                    setOptions((prev) => ({ ...prev, max_pin_label_length: next }))
                  }
                />
              </OptionRow>

              <OptionRow info={OPTION_TOOLTIPS.prov_distance}>
                <NumberField
                  id="refdes-prov-distance"
                  label="Provenance distance"
                  value={options.prov_distance}
                  min={0.5}
                  step={0.5}
                  hint="Max distance for designator-annotation pairing"
                  onChange={(next) =>
                    setOptions((prev) => ({ ...prev, prov_distance: next }))
                  }
                />
              </OptionRow>

              <div className="refdes-advanced">
                <button
                  type="button"
                  className="refdes-advanced__toggle"
                  aria-expanded={advancedOpen}
                  aria-controls="refdes-advanced-panel"
                  onClick={() => setAdvancedOpen((open) => !open)}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "var(--space-2)",
                    appearance: "none",
                    border: "none",
                    background: "transparent",
                    padding: "var(--space-1) 0",
                    color: "var(--text-secondary)",
                    fontFamily: "inherit",
                    fontSize: "var(--text-xs)",
                    fontWeight: "var(--weight-semibold)",
                    letterSpacing: "var(--tracking-uppercase)",
                    textTransform: "uppercase",
                    cursor: "pointer",
                  }}
                >
                  {advancedOpen ? (
                    <CaretDown size={12} weight="bold" />
                  ) : (
                    <CaretRight size={12} weight="bold" />
                  )}
                  Advanced controls
                </button>

                {advancedOpen ? (
                  <div
                    id="refdes-advanced-panel"
                    className="options-section__grid"
                    style={{ marginTop: "var(--space-3)" }}
                  >
                    <OptionRow info={OPTION_TOOLTIPS.geometry_subprocess_enabled}>
                      <CheckboxField
                        id="refdes-geometry-subprocess"
                        label="Geometry subprocess isolation"
                        checked={options.geometry_subprocess_enabled}
                        onChange={(next) =>
                          setOptions((prev) => ({
                            ...prev,
                            geometry_subprocess_enabled: next,
                          }))
                        }
                      />
                    </OptionRow>

                    <OptionRow info={OPTION_TOOLTIPS.annotation_page_timeout_seconds}>
                      <NumberField
                        id="refdes-annotation-page-timeout"
                        label="Annotation page timeout (s)"
                        value={options.annotation_page_timeout_seconds}
                        min={1}
                        step={5}
                        hint="Seconds per page before its annotations are skipped"
                        onChange={(next) =>
                          setOptions((prev) => ({
                            ...prev,
                            annotation_page_timeout_seconds: next,
                          }))
                        }
                      />
                    </OptionRow>

                    <OptionRow info={OPTION_TOOLTIPS.geometry_batch_timeout_seconds}>
                      <NumberField
                        id="refdes-geometry-batch-timeout"
                        label="Geometry batch timeout (s)"
                        value={options.geometry_batch_timeout_seconds}
                        min={1}
                        step={10}
                        hint="Seconds before a batch degrades to annotation-only"
                        onChange={(next) =>
                          setOptions((prev) => ({
                            ...prev,
                            geometry_batch_timeout_seconds: next,
                          }))
                        }
                      />
                    </OptionRow>

                    <OptionRow info={OPTION_TOOLTIPS.geometry_batch_checkpoint_enabled}>
                      <CheckboxField
                        id="refdes-geometry-batch-checkpoint"
                        label="Checkpoint between geometry batches"
                        checked={options.geometry_batch_checkpoint_enabled}
                        onChange={(next) =>
                          setOptions((prev) => ({
                            ...prev,
                            geometry_batch_checkpoint_enabled: next,
                          }))
                        }
                      />
                    </OptionRow>

                    <OptionRow info={OPTION_TOOLTIPS.pin_assignment_threshold}>
                      <NumberField
                        id="refdes-pin-assignment-threshold"
                        label="Pin assignment threshold (pt)"
                        value={options.pin_assignment_threshold}
                        min={1}
                        step={1}
                        hint="Max pin-to-body distance for assignment"
                        onChange={(next) =>
                          setOptions((prev) => ({
                            ...prev,
                            pin_assignment_threshold: next,
                          }))
                        }
                      />
                    </OptionRow>

                    <OptionRow info={OPTION_TOOLTIPS.refdes_search_radius}>
                      <NumberField
                        id="refdes-search-radius"
                        label="RefDes search radius (pt)"
                        value={options.refdes_search_radius}
                        min={1}
                        step={1}
                        hint="Radius for pairing a RefDes label to its body"
                        onChange={(next) =>
                          setOptions((prev) => ({
                            ...prev,
                            refdes_search_radius: next,
                          }))
                        }
                      />
                    </OptionRow>

                    <OptionRow info={OPTION_TOOLTIPS.adaptive_orphan_threshold}>
                      <NumberField
                        id="refdes-adaptive-orphan-threshold"
                        label="Adaptive orphan threshold"
                        value={options.adaptive_orphan_threshold}
                        min={0}
                        step={1}
                        hint="Min orphan pins on a page to trigger full geometry"
                        onChange={(next) =>
                          setOptions((prev) => ({
                            ...prev,
                            adaptive_orphan_threshold: next,
                          }))
                        }
                      />
                    </OptionRow>

                    <OptionRow info={OPTION_TOOLTIPS.adaptive_orphan_ratio}>
                      <NumberField
                        id="refdes-adaptive-orphan-ratio"
                        label="Adaptive orphan ratio"
                        value={options.adaptive_orphan_ratio}
                        min={0}
                        max={1}
                        step={0.05}
                        hint="Min orphan fraction (0-1) to trigger full geometry"
                        onChange={(next) =>
                          setOptions((prev) => ({
                            ...prev,
                            adaptive_orphan_ratio: next,
                          }))
                        }
                      />
                    </OptionRow>

                    <OptionRow info={OPTION_TOOLTIPS.adaptive_max_pages}>
                      <NumberField
                        id="refdes-adaptive-max-pages"
                        label="Adaptive max pages"
                        value={options.adaptive_max_pages}
                        min={1}
                        step={1}
                        hint="Cap on pages that run full geometry in adaptive mode"
                        onChange={(next) =>
                          setOptions((prev) => ({
                            ...prev,
                            adaptive_max_pages: next,
                          }))
                        }
                      />
                    </OptionRow>

                    <OptionRow info={OPTION_TOOLTIPS.pinlist_prefers_annotation_mode}>
                      <CheckboxField
                        id="refdes-pinlist-prefers-annotation"
                        label="Pinlist prefers annotation-first qualification"
                        checked={options.pinlist_prefers_annotation_mode}
                        onChange={(next) =>
                          setOptions((prev) => ({
                            ...prev,
                            pinlist_prefers_annotation_mode: next,
                          }))
                        }
                      />
                    </OptionRow>
                  </div>
                ) : null}
              </div>

              <OutputFolderPicker
                value={refdesExtractorOutputDirectory}
                onChange={setRefdesExtractorOutputDirectory}
              />
            </OptionsSection>
          </div>

          {/* v2 N5-clone: persistent Run rail + Validation sibling card. */}
          <aside className="workspace-grid__side workspace-grid__side--sticky">
            <section className="rail-card" aria-label="Run">
              <header className="rail-card__header">
                <h2>Run</h2>
                <span className="rail-card__status">{runStatusWord(panelRunMode)}</span>
              </header>
              <RunStatePanel
                runMode={panelRunMode}
                progress={panelProgress}
                percent={
                  LIVE_PHASES.some((phase) => phase === panelRunMode)
                    ? panelProgress
                    : undefined
                }
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
                readiness={readinessItems}
                onRevealOutput={
                  backendClient.runtimeMode === "desktop-bridge" ? (path) => void handleRevealOutput(path) : undefined
                }
                startLabel="Extract"
              />
            </section>

            <section className="rail-card" aria-label="Validation and preview">
              <header className="rail-card__header">
                <h2>Validation &amp; preview</h2>
              </header>
              <ValidationPreview validations={validations} previewRows={[]} />
            </section>
          </aside>
        </section>
      </div>
    </ErrorBoundary>
  );
}
