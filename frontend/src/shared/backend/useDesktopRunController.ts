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
import {
  TOOL_RUN_LABELS,
  findLiveRunConflict,
  useRunStore,
} from "../../stores/runStore";
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
 * Desktop-runtime seed: an empty `InputFileState[]` that preserves only the
 * scenario scaffolding (role/label/helper) so the InputCards render with the
 * right structure, but carries NO file paths, sheets, or loaded flags.
 *
 * Family 1 fix: the three non-FMEA tools used to seed desktop `useState` with
 * `cloneInputs(scenario.inputs)`, leaking the demo example paths
 * (`DRIVE\inputs\…`) into REAL runs. Those un-browsed slots had a non-empty
 * path + a sheet, so they passed backend validation and then crashed mid-run
 * with a FileNotFoundError naming a path the user never typed (and the RefDes
 * example PDF hard-failed on `fitz.open`). FMEA already seeded empty via a
 * local copy of this helper; this is the unified shared version.
 *
 * `status`/`tag` use the codebase's neutral empty-slot vocabulary (matching
 * the pinlist seed: `optional` chip + "Not loaded"), NOT the green
 * `ready`/"Loaded" chip — an un-browsed desktop card must not look loaded.
 *
 * `isExample` stays `true` so every tool's `isPristine` check (which requires
 * `every(isExample === true)`) keeps the first-contact EmptyState visible.
 * Browsing a real file flips `isExample` to `false`, exiting pristine. The
 * `isExample` flag is inert in InputGrid for empty paths (its example styling
 * additionally requires a non-empty path), so this is purely the pristine
 * gate.
 */
export function emptyInputsFromScenario(inputs: InputFileState[]): InputFileState[] {
  return inputs.map((input) => ({
    ...input,
    path: "",
    sheets: [],
    selectedSheet: "",
    status: "optional",
    tag: "Not loaded",
    isExample: true,
    source: "desktop-bridge",
    isResolvingSheets: false,
    isAnalyzing: false,
    resolutionError: null,
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
            warningCount: desktopRunSession.result.warning_count,
            noMatchCount: desktopRunSession.result.no_match_count,
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
    // #10: the backend emits status:success (result still null) BEFORE the
    // result event. Wait for the result rather than marking the terminal handled
    // now — otherwise this fires with result===null, skips the success branch
    // below, and the later result event short-circuits on the handled key, so
    // the success toast + shell message are lost on every successful run.
    if (phase === "success" && !desktopRunSession.result) {
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
      // A run that "succeeded" with warnings must not toast as an
      // unqualified success — the count would otherwise live only in the
      // run panel's secondary metric.
      const warningCount = desktopRunSession.result.warning_count ?? 0;
      pushNotification({
        tone: "success",
        title: options.successTitle,
        detail:
          warningCount > 0
            ? `${desktopRunSession.result.output_file} — ${warningCount} warning(s) captured in the output workbook`
            : desktopRunSession.result.output_file,
      });
      return;
    }

    if (phase === "failure") {
      // Intentionally do NOT set backendStatus here: useBackendBusyReset owns
      // the shell chip and returns it to "ready" on every terminal phase, so a
      // "error" write here is immediately overridden (a dead write). The
      // failure still surfaces via the error toast below and the run panel.
      setBackendState({
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

  /**
   * Fix 2 (Family 2) defense-in-depth: a catch-path reset that REFUSES to
   * clear a live (``starting``/``running``) run belonging to this tool.
   *
   * The double-click bug let a second `handleStartRun` reach its catch (its
   * `executeRun` rejected by Python's single-active-run guard) and call the
   * plain `resetSession`, which wiped the FIRST, live run's session — dropping
   * its streamed events and its terminal result/toast. The re-entrancy ref in
   * each tool is the primary guard; this is the belt-and-suspenders layer so
   * an error path can never destroy a live sibling run it did not create.
   *
   * Legitimate resets (workflow-change effects, the pre-validate stale-session
   * clear at the TOP of `handleStartRun`, which runs before any live run
   * exists for this flow) keep calling the plain `resetSession` and are
   * unaffected — only the error catch should consult this guarded variant.
   */
  function resetSessionUnlessLive() {
    const current = useRunStore.getState().activeRun;
    if (
      current &&
      current.toolId === toolId &&
      (current.phase === "starting" || current.phase === "running")
    ) {
      // A live run for this tool is in flight — leave it alone.
      return;
    }
    resetSession();
  }

  /**
   * Cross-tool run guard (holistic-review follow-up #1). Returns true —
   * after toasting which tool owns the live run — when ANOTHER tool's run
   * is still in flight, so `handleStartRun` can bail before sending
   * anything. The backend's single-active-run guard would reject the
   * request anyway, but the rejection used to land in this tool's catch
   * path and clobber the other tool's live run UI handle.
   */
  function guardCrossToolRun(): boolean {
    const conflict = findLiveRunConflict(toolId);
    if (!conflict) {
      return false;
    }
    pushNotification({
      tone: "warning",
      title: "Another run is active",
      detail:
        `${TOOL_RUN_LABELS[conflict.toolId]} is still running. ` +
        `Wait for it to finish or cancel it from that tool before starting a new run.`,
    });
    return true;
  }

  return {
    session: desktopRunSession,
    beginAcceptedRun,
    resetSession,
    resetSessionUnlessLive,
    guardCrossToolRun,
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
