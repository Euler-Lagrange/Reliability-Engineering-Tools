import { create } from "zustand";
import type { ToolId } from "./shellStore";

/**
 * Hard cap on the number of log entries kept in memory across all tools and
 * runs. The full log is always written to disk by the Python sidecar at
 * `~/.reliability_tools/logs/`. This in-memory ring buffer powers the
 * cross-tool Run Log panel.
 */
export const MAX_GLOBAL_LOG_ENTRIES = 5000;

export type GlobalLogLevel = "debug" | "info" | "warning" | "error";

export interface GlobalLogEntry {
  /** Monotonic id used as a stable React key. */
  id: number;
  toolId: ToolId;
  runId: string | null;
  level: GlobalLogLevel;
  line: string;
  /** ISO timestamp captured when the entry was appended. */
  timestamp: string;
}

export type GlobalLogFilterMode = "all" | "active";

interface GlobalLogStoreState {
  entries: GlobalLogEntry[];
  /** Total number of entries appended since the last clear, including dropped ring-buffer overflow. */
  totalAppended: number;
  /** Number of entries that were dropped from the head of the ring buffer. */
  truncatedCount: number;
  /** Whether the log panel body is expanded or collapsed to just its header. */
  isVisible: boolean;
  /** "all" shows entries from every tool; "active" filters to the currently selected tool. */
  filterMode: GlobalLogFilterMode;

  appendLog: (entry: Omit<GlobalLogEntry, "id" | "timestamp">) => void;
  clear: () => void;
  toggleVisible: () => void;
  setVisible: (visible: boolean) => void;
  setFilterMode: (mode: GlobalLogFilterMode) => void;
}

let nextId = 1;

export const useGlobalLogStore = create<GlobalLogStoreState>((set) => ({
  entries: [],
  totalAppended: 0,
  truncatedCount: 0,
  isVisible: false,
  filterMode: "all",

  appendLog: (entry) =>
    set((state) => {
      const next: GlobalLogEntry = {
        ...entry,
        id: nextId++,
        timestamp: new Date().toISOString(),
      };
      const combined = [...state.entries, next];
      const overflow = Math.max(0, combined.length - MAX_GLOBAL_LOG_ENTRIES);
      return {
        entries: overflow > 0 ? combined.slice(overflow) : combined,
        totalAppended: state.totalAppended + 1,
        truncatedCount: state.truncatedCount + overflow,
      };
    }),

  clear: () =>
    set({
      entries: [],
      totalAppended: 0,
      truncatedCount: 0,
    }),

  toggleVisible: () => set((state) => ({ isVisible: !state.isVisible })),

  setVisible: (visible) => set({ isVisible: visible }),

  setFilterMode: (mode) => set({ filterMode: mode }),
}));

/**
 * Format a log entry into a single human-readable line. Used for the
 * UI rendering and for the export-to-file path so the on-disk artifact
 * matches what the user sees.
 */
export function formatGlobalLogEntry(entry: GlobalLogEntry): string {
  const time = entry.timestamp.slice(11, 19); // HH:MM:SS from ISO
  const level = entry.level.toUpperCase().padEnd(7);
  const tool = `[${entry.toolId}]`.padEnd(20);
  const runTag = entry.runId ? ` (${entry.runId.slice(0, 8)})` : "";
  return `${time} ${level} ${tool}${runTag} ${entry.line}`;
}
