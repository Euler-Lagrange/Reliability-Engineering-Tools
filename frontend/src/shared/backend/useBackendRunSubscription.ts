import { useEffect, useEffectEvent } from "react";
import { executeRunResultSchema, type SidecarRunEvent } from "../../contracts/sidecar";
import { useGlobalLogStore } from "../../stores/globalLogStore";
import { useRunStore, type ActiveRunState } from "../../stores/runStore";
import { backendClient } from "./client";
import { patchFromRunEvent } from "./runLifecycle";

export function useBackendRunSubscription() {
  const appendRunLog = useRunStore((state) => state.appendLog);
  const patchActiveRun = useRunStore((state) => state.patchActiveRun);
  const appendGlobalLog = useGlobalLogStore((state) => state.appendLog);
  const runtimeMode = backendClient.runtimeMode;

  const handleRunEvent = useEffectEvent((event: SidecarRunEvent) => {
    const current = useRunStore.getState().activeRun;
    if (!current || event.run_id !== current.runId) {
      return;
    }

    if (event.kind === "log") {
      appendRunLog(event.payload.line);
      appendGlobalLog({
        toolId: current.toolId,
        runId: current.runId,
        level: event.payload.level,
        line: event.payload.line,
      });
      return;
    }

    let patch: Partial<ActiveRunState> | null;
    try {
      patch = patchFromRunEvent(current, event, (payload) => executeRunResultSchema.parse(payload));
    } catch (error) {
      // A malformed / forward-incompatible result payload would otherwise throw
      // inside this Tauri listen callback and silently strand the run (the
      // preceding success-status event already moved it past "running"). Drive a
      // terminal FAILURE with the validation error surfaced instead of letting
      // the throw escape and drop the result. (Holistic-review finding H-B.)
      const detail = error instanceof Error ? error.message : String(error);
      appendGlobalLog({
        toolId: current.toolId,
        runId: current.runId,
        level: "error",
        line: `Run result failed validation: ${detail}`,
      });
      patch = {
        phase: "failure",
        statusMessage: "Run finished, but its result did not match the expected schema.",
        errorMessage: "Backend returned a result that failed validation.",
        errorCode: "RESULT_SCHEMA_MISMATCH",
        errorTraceback: detail,
        finishedAt: new Date().toISOString(),
      };
    }
    if (patch) {
      patchActiveRun(patch);
    }
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
    // `handleRunEvent` is a `useEffectEvent` return value (stable across
    // renders by design); per React's rules-of-hooks it is intentionally
    // excluded from the dependency array.
  }, [runtimeMode]);
}
