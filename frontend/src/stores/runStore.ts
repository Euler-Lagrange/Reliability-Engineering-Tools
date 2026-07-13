import { create } from "zustand";
import type { RunEventTemplate, RunMode } from "../app/types";
import {
  INACTIVE_PHASES,
  SETTLED_PHASES,
} from "../shared/backend/runLifecycle";
import type { ToolId } from "./shellStore";

/**
 * Hard cap on the number of streamed run-log lines kept in memory. The full
 * log is always available in `~/.reliability_tools/logs/`. The UI surfaces a
 * truncation indicator when this cap is exceeded so the user knows earlier
 * lines were dropped.
 */
export const MAX_LOG_LINES = 240;

export interface ActiveRunState {
  runId: string;
  toolId: ToolId;
  sessionGeneration: number;
  phase: RunMode;
  progress: number;
  stage: string | null;
  statusMessage: string | null;
  steps: RunEventTemplate[];
  logs: string[];
  truncatedLogCount: number;
  result: unknown;
  errorMessage: string | null;
  errorCode: string | null;
  errorTraceback: string | null;
  startedAt: string;
  finishedAt: string | null;
  isDisconnected: boolean;
}

interface RunStoreState {
  activeRun: ActiveRunState | null;

  /** Replace the active run with a fresh run state. */
  setActiveRun: (run: ActiveRunState) => void;

  /**
   * Patch the existing active run. If there is no active run, this is a no-op
   * — call ``setActiveRun`` first.
   */
  patchActiveRun: (patch: Partial<ActiveRunState>) => void;

  /**
   * Append a single log line to the active run, applying the
   * ``MAX_LOG_LINES`` cap and updating ``truncatedLogCount``.
   */
  appendLog: (line: string) => void;

  /** Clear the active run. */
  clear: () => void;

  /**
   * Mark the active run as disconnected. The phase and statusMessage are
   * updated; logs and result are preserved so the user can still read what
   * happened before the disconnect.
   */
  markDisconnected: (message: string) => void;
}

export const useRunStore = create<RunStoreState>((set) => ({
  activeRun: null,

  setActiveRun: (run) => set({ activeRun: run }),

  patchActiveRun: (patch) =>
    set((state) =>
      state.activeRun ? { activeRun: { ...state.activeRun, ...patch } } : state,
    ),

  appendLog: (line) =>
    set((state) => {
      if (!state.activeRun) {
        return state;
      }
      const nextLogs = [...state.activeRun.logs, line];
      const overflow = Math.max(0, nextLogs.length - MAX_LOG_LINES);
      return {
        activeRun: {
          ...state.activeRun,
          logs: overflow > 0 ? nextLogs.slice(-MAX_LOG_LINES) : nextLogs,
          truncatedLogCount: state.activeRun.truncatedLogCount + overflow,
        },
      };
    }),

  clear: () => set({ activeRun: null }),

  markDisconnected: (message) =>
    set((state) => {
      if (!state.activeRun) {
        return state;
      }
      // Only flip if the run was still alive — settled runs stay settled.
      const currentPhase = state.activeRun.phase;
      const wasSettled = SETTLED_PHASES.some(
        (phase) => phase === currentPhase,
      );
      if (wasSettled) {
        return state;
      }
      return {
        activeRun: {
          ...state.activeRun,
          phase: "disconnected" as RunMode,
          statusMessage: message,
          errorMessage: message,
          isDisconnected: true,
        },
      };
    }),
}));

/**
 * Display labels for the cross-tool run guard's toast. Kept here (not
 * toolRegistry) so the store layer never imports component modules.
 */
export const TOOL_RUN_LABELS: Record<ToolId, string> = {
  dark_star_fmea: "FMEA Generator",
  bom_compare: "BOM Comparison Tool",
  failure_rate: "Failure Rate Integration",
  refdes_extractor: "RefDes Extractor",
  settings: "Settings",
};

/**
 * Return the live run that would conflict with starting a run in
 * ``toolId``, or null when starting is safe. The backend already rejects a
 * second concurrent run; this frontend guard exists so the rejection path
 * can never clobber the OTHER tool's live run UI handle (holistic-review
 * follow-up #1).
 */
export function findLiveRunConflict(toolId: ToolId): ActiveRunState | null {
  const activeRun = useRunStore.getState().activeRun;
  if (!activeRun || activeRun.toolId === toolId) {
    return null;
  }
  return INACTIVE_PHASES.some((phase) => phase === activeRun.phase)
    ? null
    : activeRun;
}

/**
 * Build an ``ActiveRunState`` from a freshly accepted run.
 */
export function buildActiveRunFromAccepted(args: {
  runId: string;
  toolId: ToolId;
  sessionGeneration: number;
}): ActiveRunState {
  return {
    runId: args.runId,
    toolId: args.toolId,
    sessionGeneration: args.sessionGeneration,
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
    truncatedLogCount: 0,
    result: null,
    errorMessage: null,
    errorCode: null,
    errorTraceback: null,
    startedAt: new Date().toISOString(),
    finishedAt: null,
    isDisconnected: false,
  };
}
