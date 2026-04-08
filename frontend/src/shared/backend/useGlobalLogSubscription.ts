import { useEffect, useEffectEvent } from "react";
import type { SidecarRunEvent } from "../../contracts/sidecar";
import { useGlobalLogStore } from "../../stores/globalLogStore";
import { useRunStore } from "../../stores/runStore";
import { backendClient } from "./client";

/**
 * Global, app-shell-level subscription to backend run events that funnels every
 * log line into the {@link useGlobalLogStore}. Unlike the per-tool
 * {@link useBackendRunLifecycle} hook, this subscription does NOT filter by
 * which tool is currently mounted — it captures logs from any tool's run so
 * the cross-tool Run Log panel stays populated even when the user has switched
 * away from the originating tool.
 *
 * The toolId for each log line is read from `useRunStore.activeRun.toolId`
 * (the active run's owner). This works because the sidecar enforces a single
 * active run at a time.
 *
 * Only effective in `desktop-bridge` runtime mode. In browser-mock mode the
 * subscription is a no-op and the panel stays empty until tools push their
 * own demo log lines via {@link useGlobalLogStore.appendLog} directly.
 */
export function useGlobalLogSubscription() {
  const appendLog = useGlobalLogStore((state) => state.appendLog);
  const runtimeMode = backendClient.runtimeMode;

  const handleRunEvent = useEffectEvent((event: SidecarRunEvent) => {
    if (event.kind !== "log") {
      return;
    }
    const current = useRunStore.getState().activeRun;
    if (!current || event.run_id !== current.runId) {
      return;
    }
    appendLog({
      toolId: current.toolId,
      runId: current.runId,
      level: event.payload.level,
      line: event.payload.line,
    });
  });

  useEffect(() => {
    if (runtimeMode !== "desktop-bridge") {
      return;
    }

    let disposed = false;
    let unlisten: (() => void) | undefined;

    void backendClient.subscribeToRunEvents(handleRunEvent).then((unsubscribe) => {
      if (disposed) {
        unsubscribe();
        return;
      }
      unlisten = unsubscribe;
    });

    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [handleRunEvent, runtimeMode]);
}
