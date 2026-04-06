import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemeId = "light_precision" | "dark_precision" | "signal_slate";
export type ThemeMode = "system" | ThemeId;

interface ThemeState {
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      mode: "system",
      setMode: (mode) => set({ mode }),
    }),
    {
      name: "reliability-tools-tauri-theme",
    },
  ),
);
