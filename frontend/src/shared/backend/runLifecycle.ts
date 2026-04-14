import { useEffect, useEffectEvent, useMemo } from "react";
import type { RunEvent, RunEventTemplate, RunMode } from "../../app/types";
import type {
  BackendSessionEvent,
  ExecuteRunAcceptedResult,
  SidecarRunEvent,
} from "../../contracts/sidecar";
import {
  type ActiveRunState,
  MAX_LOG_LINES,
  buildActiveRunFromAccepted,
  useRunStore,
} from "../../stores/runStore";
import type { BackendMode, ToolId } from "../../stores/shellStore";
import { backendClient } from "./client";

// Re-export so existing import paths keep working.
export { MAX_LOG_LINES };

export interface ManagedRunSession<ResultT> {
  runId: string | null;
  phase: RunMode;
  progress: number;
  stage: string | null;
  statusMessage: string | null;
  steps: RunEventTemplate[];
  logs: string[];
  truncatedLogCount: number;
  result: ResultT | null;
  errorMessage: string | null;
  errorCode: string | null;
  errorTraceback: string | null;
  isDisconnected: boolean;
}

function stepId(value: string) {
  const normalized = value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return normalized || "run-step";
}

function upsertStep(
  steps: RunEventTemplate[],
  title: string,
  detail: string,
  progress: number,
): RunEventTemplate[] {
  const id = stepId(title);
  const next = { id, title, detail, progress };
  const existingIndex = steps.findIndex((step) => step.id === id);
  if (existingIndex === -1) {
    return [...steps, next];
  }

  return steps.map((step, index) => (index === existingIndex ? next : step));
}

export function createManagedRunSession<ResultT>(): ManagedRunSession<ResultT> {
  return {
    runId: null,
    phase: "idle",
    progress: 0,
    stage: null,
    statusMessage: null,
    steps: [],
    logs: [],
    truncatedLogCount: 0,
    result: null,
    errorMessage: null,
    errorCode: null,
    errorTraceback: null,
    isDisconnected: false,
  };
}

/**
 * Project an ``ActiveRunState`` (the global store shape) into a
 * ``ManagedRunSession<ResultT>`` (the per-tool view shape).
 */
function projectSession<ResultT>(activeRun: ActiveRunState | null): ManagedRunSession<ResultT> {
  if (!activeRun) {
    return createManagedRunSession<ResultT>();
  }
  return {
    runId: activeRun.runId,
    phase: activeRun.phase,
    progress: activeRun.progress,
    stage: activeRun.stage,
    statusMessage: activeRun.statusMessage,
    steps: activeRun.steps,
    logs: activeRun.logs,
    truncatedLogCount: activeRun.truncatedLogCount,
    result: activeRun.result as ResultT | null,
    errorMessage: activeRun.errorMessage,
    errorCode: activeRun.errorCode,
    errorTraceback: activeRun.errorTraceback,
    isDisconnected: activeRun.isDisconnected,
  };
}

/**
 * Apply a streamed sidecar run event to the global active-run state.
 *
 * Mirrors the previous ``applyRunEvent`` but operates on a flat patch
 * computed from the current ``ActiveRunState`` rather than a tool-local
 * ``useState``.
 */
function patchFromRunEvent(
  current: ActiveRunState,
  event: SidecarRunEvent,
  mapResult: (payload: unknown) => unknown,
): Partial<ActiveRunState> | null {
  switch (event.kind) {
    case "ack":
      // Ack arrives via beginAcceptedRun() in normal flow; ignore here so we
      // don't reset state if a duplicate ack comes through.
      return null;
    case "status":
      return {
        runId: event.run_id,
        phase: event.payload.status,
        stage: event.payload.stage,
        statusMessage: event.payload.message,
        errorMessage: event.payload.status === "failure" ? event.payload.message : null,
        steps: upsertStep(current.steps, event.payload.stage, event.payload.message, current.progress),
        finishedAt:
          event.payload.status === "success" ||
          event.payload.status === "failure" ||
          event.payload.status === "cancelled"
            ? new Date().toISOString()
            : current.finishedAt,
      };
    case "progress":
      return {
        runId: event.run_id,
        phase: current.phase === "starting" ? "running" : current.phase,
        progress: event.payload.percent,
        stage: event.payload.stage,
        statusMessage: event.payload.message,
        steps: upsertStep(current.steps, event.payload.stage, event.payload.message, event.payload.percent),
      };
    case "log":
      // Log handled separately via appendLog() in the store so the
      // truncation counter stays accurate.
      return null;
    case "result":
      return {
        runId: event.run_id,
        phase: "success" as RunMode,
        progress: 100,
        stage: "Complete",
        statusMessage: "Run completed successfully.",
        result: mapResult(event.payload),
        errorMessage: null,
        errorCode: null,
        errorTraceback: null,
        steps: upsertStep(current.steps, "Complete", "Run completed successfully.", 100),
        finishedAt: new Date().toISOString(),
      };
    case "backend_error": {
      // Phase 5: optional code/traceback fields. Use record indexing so
      // older backends without the fields still parse cleanly.
      const payload = event.payload as Record<string, unknown>;
      const code = typeof payload["code"] === "string" ? (payload["code"] as string) : null;
      const traceback =
        typeof payload["traceback"] === "string" ? (payload["traceback"] as string) : null;
      return {
        runId: event.run_id,
        phase: "failure" as RunMode,
        statusMessage: event.payload.message,
        errorMessage: event.payload.message,
        errorCode: code,
        errorTraceback: traceback,
        steps: upsertStep(current.steps, "Run failed", event.payload.message, current.progress),
        finishedAt: new Date().toISOString(),
      };
    }
    case "cancelled":
      return {
        runId: event.run_id,
        phase: "cancelled" as RunMode,
        statusMessage: event.payload.message,
        errorMessage: null,
        steps: upsertStep(current.steps, "Cancelled", event.payload.message, current.progress),
        finishedAt: new Date().toISOString(),
      };
  }
}

export function buildRunTimeline<ResultT>(session: ManagedRunSession<ResultT>): RunEvent[] {
  return session.steps.map((step, index) => {
    const isLast = index === session.steps.length - 1;
    const status: RunEvent["status"] =
      isLast && (session.phase === "starting" || session.phase === "running" || session.phase === "cancelling")
        ? "active"
        : "completed";

    return {
      ...step,
      status,
    };
  });
}

/**
 * Hook that exposes the active run for a specific tool, persisted in the
 * global ``runStore`` so it survives tool unmount/remount.
 *
 * The hook subscribes to backend run events while the tool component is
 * mounted, but the underlying state lives in the store and is keyed by the
 * tool that started the run. If the user switches tools and returns, the
 * hook re-attaches to the existing active run as long as the run's
 * ``toolId`` matches.
 *
 * On a backend disconnect, the run is marked disconnected (state preserved
 * so the user can still see what happened). On reconnect, the hook calls
 * ``backendClient.sessionStatus()`` to reconcile: if the sidecar reports a
 * new session generation, the local active run is cleared because the old
 * run belonged to a different bridge-managed sidecar process.
 */
export function useBackendRunLifecycle<ResultT>(
  toolId: ToolId,
  runtimeMode: BackendMode,
  mapResult: (payload: unknown) => ResultT,
) {
  const activeRun = useRunStore((state) => state.activeRun);
  const setActiveRun = useRunStore((state) => state.setActiveRun);
  const patchActiveRun = useRunStore((state) => state.patchActiveRun);
  const appendLog = useRunStore((state) => state.appendLog);
  const markDisconnected = useRunStore((state) => state.markDisconnected);
  const markReconnected = useRunStore((state) => state.markReconnected);
  const clearActiveRun = useRunStore((state) => state.clear);

  // Only project the active run if it belongs to this tool. Other tools'
  // runs are not visible from here, but they ARE preserved in the store.
  const session = useMemo<ManagedRunSession<ResultT>>(
    () => projectSession<ResultT>(activeRun && activeRun.toolId === toolId ? activeRun : null),
    [activeRun, toolId],
  );

  const handleRunEvent = useEffectEvent((event: SidecarRunEvent) => {
    // Only react to events that belong to MY tool's active run.
    const current = useRunStore.getState().activeRun;
    if (!current || current.toolId !== toolId) {
      return;
    }
    if (event.run_id !== current.runId) {
      return;
    }
    if (event.kind === "log") {
      appendLog(event.payload.line);
      return;
    }
    const patch = patchFromRunEvent(current, event, mapResult);
    if (patch) {
      patchActiveRun(patch);
    }
  });

  const handleSessionEvent = useEffectEvent((event: BackendSessionEvent) => {
    if (event.kind === "disconnected") {
      markDisconnected(event.message);
      return;
    }
    if (event.kind === "connected") {
      // Reconcile against the sidecar's actual session generation. A
      // restart spawns a brand-new sidecar, so the previous run handle
      // is stale even though the bridge may already be "connected" again.
      void backendClient
        .sessionStatus()
        .then((status) => {
          const current = useRunStore.getState().activeRun;
          if (!current || current.toolId !== toolId) {
            return;
          }
          if (
            !status.connected ||
            current.sessionGeneration !== status.session_generation
          ) {
            // Sidecar reports a different managed session — drop the local
            // active run so the tool can offer a fresh start.
            clearActiveRun();
            return;
          }
          markReconnected();
        })
        .catch(() => {
          // Reconciliation is best-effort; surface failures via the next
          // backend event rather than throwing here.
        });
    }
  });

  useEffect(() => {
    if (runtimeMode !== "desktop-bridge") {
      return;
    }

    let disposed = false;
    let unlistenRun: (() => void) | undefined;
    let unlistenSession: (() => void) | undefined;

    void Promise.all([
      backendClient.subscribeToRunEvents(handleRunEvent),
      backendClient.subscribeToSessionEvents(handleSessionEvent),
    ]).then(([runUnlisten, sessionUnlisten]) => {
      if (disposed) {
        runUnlisten();
        sessionUnlisten();
        return;
      }

      unlistenRun = runUnlisten;
      unlistenSession = sessionUnlisten;
    });

    return () => {
      disposed = true;
      unlistenRun?.();
      unlistenSession?.();
    };
  }, [handleRunEvent, handleSessionEvent, runtimeMode]);

  return {
    session,
    beginAcceptedRun(accepted: ExecuteRunAcceptedResult) {
      setActiveRun(
        buildActiveRunFromAccepted({
          runId: accepted.run_id,
          toolId,
          sessionGeneration: accepted.session_generation,
        }),
      );
    },
    resetSession() {
      // Only clear the global state if the active run belongs to this tool.
      // Otherwise leave it alone so the other tool can keep observing it.
      const current = useRunStore.getState().activeRun;
      if (current && current.toolId === toolId) {
        clearActiveRun();
      }
    },
  };
}
