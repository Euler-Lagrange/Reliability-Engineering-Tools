import type { RunEventTemplate, RunResult } from "../../app/types";
import { useGlobalLogStore } from "../../stores/globalLogStore";
import { useNotificationStore } from "../../stores/notificationStore";
import type { ToolId } from "../../stores/shellStore";
import { buildActiveRunFromAccepted, useRunStore } from "../../stores/runStore";

/**
 * Browser-mock runs used to live only in tool-local React state, so the
 * Review drawer (which reads the shared `runStore`) said "No run has
 * started for this tool yet" while the Run rail showed a completed
 * result, and the Global Log strip stayed at "0 entries" forever.
 *
 * These helpers mirror the demo-run lifecycle into the same stores the
 * desktop bridge writes, so every shared surface (Review drawer,
 * GlobalLogPanel, cross-tool "another run is active" affordances,
 * completion toasts) behaves identically in browser preview.
 *
 * Desktop-bridge behavior is untouched: every call site is inside a
 * `runtimeMode === "browser-mock"` branch.
 */

let mockRunCounter = 0;

/** Start mirroring a demo run. Returns the synthetic run id. */
export function mirrorMockRunStart(toolId: ToolId): string {
  mockRunCounter += 1;
  const runId = `mock_${toolId}_${mockRunCounter}`;
  useRunStore.getState().setActiveRun({
    ...buildActiveRunFromAccepted({ runId, toolId, sessionGeneration: 0 }),
    phase: "running",
    progress: 0,
    stage: null,
    statusMessage: "Demo run in progress (browser preview).",
    steps: [],
  });
  return runId;
}

/** Mirror a replayed event: progress + stage + its log lines. */
export function mirrorMockRunEvent(
  toolId: ToolId,
  runId: string | null,
  template: RunEventTemplate,
): void {
  const { activeRun, patchActiveRun } = useRunStore.getState();
  if (!runId || activeRun?.runId !== runId) {
    return;
  }
  patchActiveRun({
    progress: template.progress,
    stage: template.title,
    statusMessage: template.detail,
  });
  appendMockRunLogs(toolId, runId, template.logs ?? []);
}

/** Mirror the terminal result, append a closing log line, and toast —
 * matching the desktop controller's success/failure semantics
 * (warnings qualify the success detail, never the tone). */
export function mirrorMockRunTerminal(
  toolId: ToolId,
  runId: string | null,
  result: RunResult,
): void {
  const { activeRun, patchActiveRun } = useRunStore.getState();
  if (runId && activeRun?.runId === runId) {
    patchActiveRun({
      phase: result.status,
      progress: result.status === "success" ? 100 : activeRun.progress,
      statusMessage: result.title,
      finishedAt: new Date().toISOString(),
    });
  }
  const warningCount = result.warningCount ?? 0;
  appendMockRunLogs(
    toolId,
    runId,
    [
      result.status === "success"
        ? `Run complete — ${result.outputFile}`
        : `Run stopped — ${result.summary}`,
    ],
    result.status === "success" ? (warningCount > 0 ? "warning" : "info") : "error",
  );
  useNotificationStore.getState().push(
    result.status === "success"
      ? {
          tone: "success",
          title: result.title,
          detail:
            warningCount > 0
              ? `${result.outputFile} — ${warningCount} warning(s) captured in the output workbook`
              : result.outputFile,
        }
      : {
          tone: "error",
          title: result.title,
          detail: result.summary,
        },
  );
}

/** Mirror a demo-run cancellation. */
export function mirrorMockRunCancelled(toolId: ToolId, runId: string | null): void {
  if (!runId) {
    return;
  }
  const { activeRun, patchActiveRun } = useRunStore.getState();
  if (activeRun?.runId !== runId) {
    return;
  }
  patchActiveRun({
    phase: "cancelled",
    statusMessage: "Demo run cancelled.",
    finishedAt: new Date().toISOString(),
  });
  appendMockRunLogs(toolId, runId, ["Run cancelled by the operator."], "warning");
}

/** Append demo log lines to the shared Global Log strip. */
export function appendMockRunLogs(
  toolId: ToolId,
  runId: string | null,
  lines: string[],
  level: "debug" | "info" | "warning" | "error" = "info",
): void {
  const append = useGlobalLogStore.getState().appendLog;
  for (const line of lines) {
    append({ toolId, runId, level, line });
  }
}
