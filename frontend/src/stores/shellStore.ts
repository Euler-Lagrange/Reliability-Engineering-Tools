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
   */
  fmeaOutputDirectory: string | null;
  bomCompareOutputDirectory: string | null;
  failureRateOutputDirectory: string | null;
  refdesExtractorOutputDirectory: string | null;
  /**
   * Review drawer visibility — design handoff principle D. The drawer
   * slides in from the right and displays the active tool's run summary
   * and `output_preview` from the last validate_run. Persisted so the
   * drawer state survives navigation but defaults closed on first load.
   */
  contextOpen: boolean;
  setActiveToolId: (toolId: ToolId) => void;
  setBackendState: (state: Partial<Pick<ShellState, "backendStatus" | "backendMode" | "backendMessage" | "lastBackendCheckAt">>) => void;
  setFmeaOutputDirectory: (path: string | null) => void;
  setBomCompareOutputDirectory: (path: string | null) => void;
  setFailureRateOutputDirectory: (path: string | null) => void;
  setRefdesExtractorOutputDirectory: (path: string | null) => void;
  setContextOpen: (open: boolean) => void;
  toggleContext: () => void;
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
      bomCompareOutputDirectory: null,
      failureRateOutputDirectory: null,
      refdesExtractorOutputDirectory: null,
      contextOpen: false,
      setActiveToolId: (activeToolId) => set({ activeToolId }),
      setBackendState: (state) => set((current) => ({ ...current, ...state })),
      setFmeaOutputDirectory: (path) => set({ fmeaOutputDirectory: path }),
      setBomCompareOutputDirectory: (path) => set({ bomCompareOutputDirectory: path }),
      setFailureRateOutputDirectory: (path) => set({ failureRateOutputDirectory: path }),
      setRefdesExtractorOutputDirectory: (path) => set({ refdesExtractorOutputDirectory: path }),
      setContextOpen: (contextOpen) => set({ contextOpen }),
      toggleContext: () => set((state) => ({ contextOpen: !state.contextOpen })),
    }),
    {
      // Only the small subset of ShellState that should survive a reload is
      // persisted. Transient backend status/message must NOT be persisted —
      // they would stick as "connecting" or stale messages on the next boot.
      name: "reliability-tools-tauri-shell",
      partialize: (state) => ({
        fmeaOutputDirectory: state.fmeaOutputDirectory,
        bomCompareOutputDirectory: state.bomCompareOutputDirectory,
        failureRateOutputDirectory: state.failureRateOutputDirectory,
        refdesExtractorOutputDirectory: state.refdesExtractorOutputDirectory,
        contextOpen: state.contextOpen,
      }),
    },
  ),
);
