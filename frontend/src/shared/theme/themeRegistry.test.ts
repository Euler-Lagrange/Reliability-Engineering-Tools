import { describe, expect, it } from "vitest";
import {
  DARK_THEME_IDS,
  RAIL_THEMES,
  THEME_REGISTRY,
  findTheme,
  labelForTheme,
} from "./themeRegistry";

describe("THEME_REGISTRY", () => {
  it("contains every theme exposed by the store", () => {
    // Mirror the ThemeMode type union here so that adding/removing a theme in
    // the store will fail this test until the registry is updated to match.
    const expected = new Set([
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
    const actual = new Set(THEME_REGISTRY.map((entry) => entry.id));
    expect(actual).toEqual(expected);
  });

  it("has unique theme ids", () => {
    const ids = THEME_REGISTRY.map((entry) => entry.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("has non-empty label, shortLabel, and description for every theme", () => {
    for (const entry of THEME_REGISTRY) {
      expect(entry.label.length).toBeGreaterThan(0);
      expect(entry.shortLabel.length).toBeGreaterThan(0);
      expect(entry.description.length).toBeGreaterThan(0);
    }
  });

  it("classifies mission_control as a dark theme", () => {
    // Regression: mission_control was missing from the dark list, which made
    // its native form controls render with light contrast against a near-black
    // background. The single source of truth must report it as dark.
    const entry = findTheme("mission_control");
    expect(entry).toBeDefined();
    expect(entry?.scheme).toBe("dark");
    expect(DARK_THEME_IDS.has("mission_control")).toBe(true);
  });

  it("includes every dark theme in DARK_THEME_IDS", () => {
    const darkFromRegistry = THEME_REGISTRY.filter((entry) => entry.scheme === "dark").map(
      (entry) => entry.id,
    );
    for (const id of darkFromRegistry) {
      expect(DARK_THEME_IDS.has(id)).toBe(true);
    }
    expect(DARK_THEME_IDS.size).toBe(darkFromRegistry.length);
  });

  it("RAIL_THEMES contains exactly the entries flagged inRail", () => {
    const inRail = THEME_REGISTRY.filter((entry) => entry.inRail);
    expect(RAIL_THEMES.length).toBe(inRail.length);
    for (const entry of inRail) {
      expect(RAIL_THEMES.find((rail) => rail.id === entry.id)).toBeDefined();
    }
  });

  it("RAIL_THEMES exposes at least the four common themes", () => {
    const expected = ["system", "light_precision", "dark_precision", "signal_slate"];
    for (const id of expected) {
      expect(RAIL_THEMES.find((entry) => entry.id === id)).toBeDefined();
    }
  });
});

describe("labelForTheme", () => {
  it("returns the registry label for known ids", () => {
    expect(labelForTheme("dark_precision")).toBe("Dark Precision");
    expect(labelForTheme("mission_control")).toBe("Mission Control");
    expect(labelForTheme("signal_slate")).toBe("Signal Slate");
  });

  it("returns the input itself for unknown ids", () => {
    expect(labelForTheme("not_a_real_theme")).toBe("not_a_real_theme");
  });

  it("does NOT fall through to 'Light Precision' for non-light themes", () => {
    // Regression: the previous shell-rail label only checked dark_precision
    // and signal_slate, falling through to 'Light Precision' for everything
    // else, which silently mislabeled four other themes.
    expect(labelForTheme("midnight_blue")).not.toBe("Light Precision");
    expect(labelForTheme("high_contrast")).not.toBe("Light Precision");
    expect(labelForTheme("synthwave")).not.toBe("Light Precision");
    expect(labelForTheme("mission_control")).not.toBe("Light Precision");
  });
});
