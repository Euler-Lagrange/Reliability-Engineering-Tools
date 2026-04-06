import { create } from "zustand";

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
  setActiveToolId: (toolId: ToolId) => void;
  setBackendState: (state: Partial<Pick<ShellState, "backendStatus" | "backendMode" | "backendMessage" | "lastBackendCheckAt">>) => void;
}

export const useShellStore = create<ShellState>((set) => ({
  activeToolId: "dark_star_fmea",
  backendStatus: "connecting",
  backendMode: "unknown",
  backendMessage: "Initializing backend bridge...",
  lastBackendCheckAt: null,
  setActiveToolId: (activeToolId) => set({ activeToolId }),
  setBackendState: (state) => set((current) => ({ ...current, ...state })),
}));
