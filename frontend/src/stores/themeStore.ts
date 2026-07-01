import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemeId =
  | "light_precision"
  | "dark_precision"
  | "signal_slate"
  | "midnight_blue"
  | "high_contrast"
  | "synthwave"
  | "mission_control"
  | "kraft_paper"
  | "forest_depth"
  | "graphite_dawn";
export type ThemeMode = "system" | ThemeId;

interface ThemeState {
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
}

// Keep in sync with the ThemeMode union above. Used by the persist migration
// to reject a stored theme id that no longer exists.
export const VALID_THEME_MODES: ReadonlySet<ThemeMode> = new Set<ThemeMode>([
  "system",
  "light_precision",
  "dark_precision",
  "signal_slate",
  "midnight_blue",
  "high_contrast",
  "synthwave",
  "mission_control",
  "kraft_paper",
  "forest_depth",
  "graphite_dawn",
]);

export const THEME_PERSIST_VERSION = 1;

/**
 * Decision E: a persisted theme id that no longer exists (a renamed or removed
 * theme) must not rehydrate verbatim — fall back to "system".
 */
export function migrateThemeState(persisted: unknown): { mode: ThemeMode } {
  const mode = (persisted as { mode?: unknown } | null)?.mode as ThemeMode | undefined;
  return { mode: mode && VALID_THEME_MODES.has(mode) ? mode : "system" };
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      mode: "system",
      setMode: (mode) => set({ mode }),
    }),
    {
      name: "reliability-tools-tauri-theme",
      version: THEME_PERSIST_VERSION,
      migrate: (persisted) => migrateThemeState(persisted) as unknown as ThemeState,
    },
  ),
);
