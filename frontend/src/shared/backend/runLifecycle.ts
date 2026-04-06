import { useEffect, useEffectEvent, useState } from "react";
import type { RunEvent, RunEventTemplate, RunMode } from "../../app/types";
import type {
  BackendSessionEvent,
  ExecuteRunAcceptedResult,
  SidecarRunEvent,
} from "../../contracts/sidecar";
import type { BackendMode } from "../../stores/shellStore";
import { backendClient } from "./client";

const MAX_LOG_LINES = 240;

export interface ManagedRunSession<ResultT> {
  runId: string | null;
  phase: RunMode;
  progress: number;
  stage: string | null;
  statusMessage: string | null;
  steps: RunEventTemplate[];
  logs: string[];
  result: ResultT | null;
  errorMessage: string | null;
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
    result: null,
    errorMessage: null,
  };
}

export function acceptRun<ResultT>(accepted: ExecuteRunAcceptedResult): ManagedRunSession<ResultT> {
  return {
    runId: accepted.run_id,
    phase: "starting",
    progress: 1,
    stage: "Run accepted",
    statusMessage: "Run accepted by the desktop backend.",
    steps: [
      {
        id: "run-accepted",
        title: "Run accepted",
        detail: "Run accepted by the desktop backend.",
        progress: 1,
      },
    ],
    logs: [],
    result: null,
    errorMessage: null,
  };
}

export function applyRunEvent<ResultT>(
  session: ManagedRunSession<ResultT>,
  event: SidecarRunEvent,
  mapResult: (payload: unknown) => ResultT,
): ManagedRunSession<ResultT> {
  switch (event.kind) {
    case "ack":
      return acceptRun<ResultT>(event.payload);
    case "status":
      return {
        ...session,
        runId: event.run_id,
        phase: event.payload.status,
        stage: event.payload.stage,
        statusMessage: event.payload.message,
        errorMessage: event.payload.status === "failure" ? event.payload.message : null,
        steps: upsertStep(session.steps, event.payload.stage, event.payload.message, session.progress),
      };
    case "progress":
      return {
        ...session,
        runId: event.run_id,
        phase: session.phase === "starting" ? "running" : session.phase,
        progress: event.payload.percent,
        stage: event.payload.stage,
        statusMessage: event.payload.message,
        steps: upsertStep(session.steps, event.payload.stage, event.payload.message, event.payload.percent),
      };
    case "log":
      return {
        ...session,
        runId: event.run_id,
        logs: [...session.logs, event.payload.line].slice(-MAX_LOG_LINES),
      };
    case "result":
      return {
        ...session,
        runId: event.run_id,
        phase: "success",
        progress: 100,
        stage: "Complete",
        statusMessage: "Run completed successfully.",
        result: mapResult(event.payload),
        errorMessage: null,
        steps: upsertStep(session.steps, "Complete", "Run completed successfully.", 100),
      };
    case "backend_error":
      return {
        ...session,
        runId: event.run_id,
        phase: "failure",
        statusMessage: event.payload.message,
        errorMessage: event.payload.message,
        steps: upsertStep(session.steps, "Run failed", event.payload.message, session.progress),
      };
    case "cancelled":
      return {
        ...session,
        runId: event.run_id,
        phase: "cancelled",
        statusMessage: event.payload.message,
        errorMessage: null,
        steps: upsertStep(session.steps, "Cancelled", event.payload.message, session.progress),
      };
  }
}

export function markRunDisconnected<ResultT>(
  session: ManagedRunSession<ResultT>,
  message: string,
): ManagedRunSession<ResultT> {
  if (!session.runId && session.phase === "idle") {
    return session;
  }

  return {
    ...session,
    phase: "disconnected",
    statusMessage: message,
    errorMessage: message,
    steps: upsertStep(session.steps, "Backend disconnected", message, session.progress),
  };
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

export function isBusyRunPhase(phase: RunMode) {
  return phase === "starting" || phase === "running" || phase === "cancelling";
}

export function useBackendRunLifecycle<ResultT>(
  runtimeMode: BackendMode,
  mapResult: (payload: unknown) => ResultT,
) {
  const [session, setSession] = useState<ManagedRunSession<ResultT>>(() => createManagedRunSession());

  const handleRunEvent = useEffectEvent((event: SidecarRunEvent) => {
    setSession((current) => applyRunEvent(current, event, mapResult));
  });

  const handleSessionEvent = useEffectEvent((event: BackendSessionEvent) => {
    if (event.kind === "disconnected") {
      setSession((current) => markRunDisconnected(current, event.message));
    }
  });

  useEffect(() => {
    setSession(createManagedRunSession());
  }, [runtimeMode]);

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
      setSession(acceptRun<ResultT>(accepted));
    },
    resetSession() {
      setSession(createManagedRunSession());
    },
  };
}
