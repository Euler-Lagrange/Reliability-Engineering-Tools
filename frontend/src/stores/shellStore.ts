import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ToolId =
  | "dark_star_fmea"
  | "bom_compare"
  | "failure_rate"
  | "refdes_extractor"
  | "settings";

export type BackendStatus = "connecting" | "ready" | "busy" | "disconnected" | "error";
export type BackendMode = "unknown" | "browser-mock" | "desktop-bridge";

interface ShellState {
  activeToolId: ToolId;
  backendStatus: BackendStatus;
  backendMode: BackendMode;
  backendMessage: string | null;
  lastBackendCheckAt: string | null;
  /**
   * Per-tool output folder overrides. When a tool records an explicit output
   * directory (via its folder picker), the path lives here so it survives
   * tab switches and app reloads. Empty/null = fall back to the backend's
   * "first input file parent" heuristic.
   *
   * Phase 3 wires the FMEA tool first. Other tools (BOM Compare, Failure
   * Rate, RefDes) can adopt this field later by adding their own key.
   */
  fmeaOutputDirectory: string | null;
  setActiveToolId: (toolId: ToolId) => void;
  setBackendState: (state: Partial<Pick<ShellState, "backendStatus" | "backendMode" | "backendMessage" | "lastBackendCheckAt">>) => void;
  setFmeaOutputDirectory: (path: string | null) => void;
}

export const useShellStore = create<ShellState>()(
  persist(
    (set) => ({
      activeToolId: "dark_star_fmea",
      backendStatus: "connecting",
      backendMode: "unknown",
      backendMessage: "Initializing backend bridge...",
      lastBackendCheckAt: null,
      fmeaOutputDirectory: null,
      setActiveToolId: (activeToolId) => set({ activeToolId }),
      setBackendState: (state) => set((current) => ({ ...current, ...state })),
      setFmeaOutputDirectory: (path) => set({ fmeaOutputDirectory: path }),
    }),
    {
      // Only the small subset of ShellState that should survive a reload is
      // persisted. Transient backend status/message must NOT be persisted —
      // they would stick as "connecting" or stale messages on the next boot.
      name: "reliability-tools-tauri-shell",
      partialize: (state) => ({
        fmeaOutputDirectory: state.fmeaOutputDirectory,
      }),
    },
  ),
);
