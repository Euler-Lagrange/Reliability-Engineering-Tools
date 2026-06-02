import { useEffect, useMemo, useRef } from "react";
import type {
  InputFileState,
  RunEvent,
  RunEventTemplate,
  RunMode,
  RunResult,
} from "../../app/types";
import type { ToolId } from "../../stores/shellStore";
import { useShellStore } from "../../stores/shellStore";
import { useNotificationStore } from "../../stores/notificationStore";
import { backendClient } from "./client";
import { buildCancelNotification } from "./cancelError";
import { buildRunTimeline, useBackendRunLifecycle } from "./runLifecycle";

/**
 * Clone the demo-scenario input states for tool-local `useState` seeding.
 *
 * Extracted verbatim from the four tool components (FailureRate, BOM Compare,
 * RefDes Extractor, FMEA) where the body was byte-identical. The defaults
 * backfill optional fields so a scenario authored before those flags existed
 * still renders without `undefined` leaking into the InputCards.
 */
export function cloneInputs(inputs: InputFileState[]): InputFileState[] {
  return inputs.map((input) => ({
    ...input,
    sheets: input.sheets.map((sheet) => ({ ...sheet })),
    source: input.source ?? "mock",
    isResolvingSheets: input.isResolvingSheets ?? false,
    isAnalyzing: input.isAnalyzing ?? false,
    resolutionError: input.resolutionError ?? null,
  }));
}

/**
 * Browser-mock timeline builder. Maps the scenario run-event templates into
 * `RunEvent`s with a status derived from the simulated `runMode`/`runIndex`.
 *
 * Extracted verbatim from the four tool components where the body was
 * byte-identical. The desktop-bridge timeline uses `buildRunTimeline`
 * (from `runLifecycle`) instead — this helper is only for the demo runtime.
 */
export function buildTimeline(
  runMode: RunMode,
  runIndex: number,
  templates: RunEventTemplate[],
): RunEvent[] {
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

/**
 * Per-tool copy that varies the otherwise-identical desktop run lifecycle.
 *
 * `successMessage` builds the `backendMessage` shown on a successful run —
 * FMEA uses "Generated workbook at …" while the other three use "Report
 * written to …". The three notification titles vary per tool too.
 */
export interface DesktopRunControllerOptions {
  /** Builds the shell `backendMessage` on success (e.g. `Report written to …`). */
  successMessage: (outputFile: string) => string;
  successTitle: string;
  failureTitle: string;
  cancelledTitle: string;
  /**
   * Browser-mock fallbacks. These are only read when the runtime is NOT the
   * desktop bridge, so each tool passes its own demo-runtime state values.
   */
  mockRunMode: RunMode;
  mockTimeline: RunEvent[];
  mockProgress: number;
  mockRunResult: RunResult | null;
  mockLogLines: string[];
  mockCancelledNotice: string | null;
}

/**
 * Owns the desktop-bridge run lifecycle that was duplicated across the four
 * tool components: the `useBackendRunLifecycle` session, the desktop timeline
 * and result projections, every `panel*` runtime-gated value, the terminal
 * `useEffect` that fires shell-state updates + notifications on a run's
 * success/failure/cancellation, and the desktop-bridge cancel request.
 *
 * Behavior is identical to the previous inline copies. Tool-specific bits
 * (the browser-mock run simulation, the run-start request building, and the
 * browser-mock cancel branch) stay in each tool. The hook's `cancel()` only
 * handles the desktop-bridge branch and returns `true` when it did so; tools
 * call it as `if (cancel()) return;` before running their own mock branch.
 */
export function useDesktopRunController(
  toolId: ToolId,
  options: DesktopRunControllerOptions,
) {
  const setBackendState = useShellStore((state) => state.setBackendState);
  const pushNotification = useNotificationStore((state) => state.push);
  const handledDesktopTerminalRef = useRef<string | null>(null);

  const {
    session: desktopRunSession,
    beginAcceptedRun,
    resetSession,
  } = useBackendRunLifecycle(toolId);

  const desktopTimeline = useMemo(
    () => buildRunTimeline(desktopRunSession),
    [desktopRunSession],
  );
  const desktopResult = useMemo<RunResult | null>(
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

  const isDesktop = backendClient.runtimeMode === "desktop-bridge";

  const panelRunMode = isDesktop ? desktopRunSession.phase : options.mockRunMode;
  const panelTimeline = isDesktop ? desktopTimeline : options.mockTimeline;
  const panelProgress = isDesktop ? desktopRunSession.progress : options.mockProgress;
  const panelRunResult = isDesktop ? desktopResult : options.mockRunResult;
  const panelLogLines = isDesktop ? desktopRunSession.logs : options.mockLogLines;
  const panelCancelledNotice = isDesktop
    ? panelRunMode === "cancelled" || panelRunMode === "disconnected"
      ? desktopRunSession.statusMessage
      : null
    : options.mockCancelledNotice;
  const panelRunId = isDesktop ? desktopRunSession.runId : null;
  const panelStatusMessage = isDesktop ? desktopRunSession.statusMessage : null;
  const panelTruncatedLogCount = isDesktop ? desktopRunSession.truncatedLogCount : 0;
  const panelErrorCode = isDesktop ? desktopRunSession.errorCode : null;
  const panelErrorTraceback = isDesktop ? desktopRunSession.errorTraceback : null;

  // Desktop run terminal state handler. Keyed on `${runId}:${phase}` via a
  // ref guard so each terminal transition fires its shell-state update +
  // notification exactly once.
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
        backendMessage: options.successMessage(desktopRunSession.result.output_file),
        lastBackendCheckAt: new Date().toISOString(),
      });
      pushNotification({
        tone: "success",
        title: options.successTitle,
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
        title: options.failureTitle,
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
        title: options.cancelledTitle,
        detail: desktopRunSession.statusMessage ?? "The active backend run was cancelled.",
      });
    }
    // Dependency array preserved from the inline copies: the effect reads
    // `options.*` but those are stable per render and the run session is the
    // real trigger. Keeping the array identical avoids changing fire timing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [desktopRunSession, pushNotification, setBackendState]);

  /**
   * Reset the terminal-handler guard so the next accepted run fires its
   * terminal notification. Tools call this right before `beginAcceptedRun`,
   * matching the previous `handledDesktopTerminalRef.current = null` line.
   */
  function armTerminalHandler() {
    handledDesktopTerminalRef.current = null;
  }

  /**
   * Issue the desktop-bridge cancel for the active run. Returns `true` when
   * the runtime is the desktop bridge (so the caller should stop), `false`
   * when it is the browser mock (so the caller runs its own mock branch).
   *
   * Phase B3 / Fix E3: only fire on `starting`/`running` so stale run IDs and
   * double-click second-cancels never reach the sidecar.
   */
  function cancel(): boolean {
    if (backendClient.runtimeMode !== "desktop-bridge") {
      return false;
    }

    if (
      !desktopRunSession.runId ||
      (desktopRunSession.phase !== "starting" &&
        desktopRunSession.phase !== "running")
    ) {
      return true;
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
        // Phase B3: surface the sidecar's real error message (Tauri rejects
        // with a raw string, not an Error instance).
        pushNotification(buildCancelNotification(error));
      });
    return true;
  }

  return {
    session: desktopRunSession,
    beginAcceptedRun,
    resetSession,
    armTerminalHandler,
    cancel,
    desktopTimeline,
    desktopResult,
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
  };
}
