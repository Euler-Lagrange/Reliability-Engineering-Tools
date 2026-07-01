import { describe, expect, it } from "vitest";

import { migrateShellState } from "./shellStore";
import { migrateThemeState } from "./themeStore";

// Decision E: the persisted stores now carry a version + migration so a stale
// or invalid value (a removed theme id, a wrong-typed output dir) is sanitized
// on rehydrate rather than restored verbatim.
describe("theme store migration", () => {
  it("keeps a valid persisted theme id", () => {
    expect(migrateThemeState({ mode: "synthwave" })).toEqual({ mode: "synthwave" });
  });

  it("keeps the 'system' sentinel", () => {
    expect(migrateThemeState({ mode: "system" })).toEqual({ mode: "system" });
  });

  it("falls back to system for a removed/unknown theme id", () => {
    expect(migrateThemeState({ mode: "retired_theme" })).toEqual({ mode: "system" });
  });

  it("falls back to system for missing or null persisted state", () => {
    expect(migrateThemeState({})).toEqual({ mode: "system" });
    expect(migrateThemeState(null)).toEqual({ mode: "system" });
  });
});

describe("shell store migration", () => {
  it("keeps valid output directories and the contextOpen flag", () => {
    expect(
      migrateShellState({
        fmeaOutputDirectory: "C:\\out",
        bomCompareOutputDirectory: null,
        failureRateOutputDirectory: "D:\\fr",
        refdesExtractorOutputDirectory: null,
        contextOpen: true,
      }),
    ).toEqual({
      fmeaOutputDirectory: "C:\\out",
      bomCompareOutputDirectory: null,
      failureRateOutputDirectory: "D:\\fr",
      refdesExtractorOutputDirectory: null,
      contextOpen: true,
    });
  });

  it("sanitizes wrong-typed values to safe defaults", () => {
    const migrated = migrateShellState({
      fmeaOutputDirectory: 42,
      bomCompareOutputDirectory: "",
      contextOpen: "yes",
    });
    expect(migrated.fmeaOutputDirectory).toBeNull();
    expect(migrated.bomCompareOutputDirectory).toBeNull();
    expect(migrated.failureRateOutputDirectory).toBeNull();
    expect(migrated.contextOpen).toBe(false);
  });

  it("handles null persisted state with full defaults", () => {
    expect(migrateShellState(null)).toEqual({
      fmeaOutputDirectory: null,
      bomCompareOutputDirectory: null,
      failureRateOutputDirectory: null,
      refdesExtractorOutputDirectory: null,
      contextOpen: false,
    });
  });
});
