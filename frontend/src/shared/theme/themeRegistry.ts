/**
 * Single source of truth for theme metadata.
 *
 * Before this registry existed, theme metadata was duplicated across four
 * files (the shell rail in App.tsx, the Settings tool, the theme store, and
 * the ThemeController). The lists drifted: the rail only exposed 4 of the
 * 7 themes, the topbar label fell through to "Light Precision" for 5 of
 * them, and the dark-themes list omitted Mission Control so its native
 * controls rendered with the wrong contrast.
 *
 * Every consumer must read from this registry. Do not duplicate the lists.
 */

import {
  Airplane,
  Broadcast,
  CircleHalf,
  Desktop,
  Lightning,
  MoonStars,
  Sparkle,
  Sun,
  type Icon as PhosphorIcon,
} from "@phosphor-icons/react";
import type { ThemeMode } from "../../stores/themeStore";

export interface ThemeRegistryEntry {
  /** Stable theme identifier — also the value of ``data-theme`` on the html root. */
  id: ThemeMode;
  /** Long human-readable label shown in Settings and the topbar chip. */
  label: string;
  /** Compact label used in the shell-rail theme picker. */
  shortLabel: string;
  /** Phosphor icon for the rail and the Settings cards. */
  icon: PhosphorIcon;
  /** One-line description shown in Settings. */
  description: string;
  /**
   * Native colorScheme for HTML form controls. Determines the value
   * applied to ``document.documentElement.style.colorScheme`` so date
   * pickers / scrollbars / autofill chrome render with correct contrast.
   */
  scheme: "light" | "dark";
  /**
   * Whether the theme is exposed in the compact rail picker. The four most
   * common themes appear there; the rest are accessible from the Settings
   * tool only.
   */
  inRail: boolean;
}

export const THEME_REGISTRY: readonly ThemeRegistryEntry[] = [
  {
    id: "system",
    label: "System",
    shortLabel: "Sys",
    icon: Desktop,
    description: "Follow your OS preference.",
    scheme: "light",
    inRail: true,
  },
  {
    id: "light_precision",
    label: "Light Precision",
    shortLabel: "Light",
    icon: Sun,
    description: "Clean light theme for bright environments.",
    scheme: "light",
    inRail: true,
  },
  {
    id: "dark_precision",
    label: "Dark Precision",
    shortLabel: "Dark",
    icon: MoonStars,
    description: "Professional dark theme.",
    scheme: "dark",
    inRail: true,
  },
  {
    id: "signal_slate",
    label: "Signal Slate",
    shortLabel: "Slate",
    icon: Sparkle,
    description: "High-contrast engineering theme.",
    scheme: "light",
    inRail: true,
  },
  {
    id: "midnight_blue",
    label: "Midnight Blue",
    shortLabel: "Navy",
    icon: Airplane,
    description: "Deep navy + ice blue. Aerospace engineering aesthetic.",
    scheme: "dark",
    inRail: false,
  },
  {
    id: "high_contrast",
    label: "High Contrast",
    shortLabel: "WCAG",
    icon: CircleHalf,
    description: "Pure black and white with yellow accents. WCAG AAA.",
    scheme: "dark",
    inRail: false,
  },
  {
    id: "synthwave",
    label: "Synthwave",
    shortLabel: "Wave",
    icon: Lightning,
    description: "Neon pink and purple. Retro-futurist vibes.",
    scheme: "dark",
    inRail: false,
  },
  {
    id: "mission_control",
    label: "Mission Control",
    shortLabel: "MCS",
    icon: Broadcast,
    description: "Monospaced instrument panel. Dimmed readouts, cyan accents.",
    scheme: "dark",
    inRail: false,
  },
];

/** Themes shown in the compact rail picker (the four most common). */
export const RAIL_THEMES: readonly ThemeRegistryEntry[] = THEME_REGISTRY.filter(
  (entry) => entry.inRail,
);

/** Set of theme ids whose native colorScheme is "dark". */
export const DARK_THEME_IDS: ReadonlySet<ThemeMode> = new Set(
  THEME_REGISTRY.filter((entry) => entry.scheme === "dark").map((entry) => entry.id),
);

/** Look up a theme entry by id. Returns undefined for unknown ids. */
export function findTheme(id: ThemeMode | string): ThemeRegistryEntry | undefined {
  return THEME_REGISTRY.find((entry) => entry.id === id);
}

/** Human-readable label for a theme id; falls back to the id itself. */
export function labelForTheme(id: ThemeMode | string): string {
  return findTheme(id)?.label ?? id;
}
