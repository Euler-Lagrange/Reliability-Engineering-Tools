import { describe, expect, test } from "vitest";
import {
  FMEA_COLUMN_METADATA,
  migrateFmdOverrides,
  resolveColumnLabel,
  type FmeaColumnMetadata,
} from "./mappingColumns";
import type { WorkflowId } from "../../app/types";

/**
 * Phase 5: metadata tests for the 14 FMEA column rows.
 *
 * These tests fence the canonical list, visibility filters, required
 * flags, and dynamic FMD label swapping. If the metadata changes, update
 * both the spec (plan section A3.4 / A4) and these tests together.
 */

const findByCanonical = (canonical: string): FmeaColumnMetadata => {
  const match = FMEA_COLUMN_METADATA.find((meta) => meta.canonical === canonical);
  if (!match) {
    throw new Error(`No metadata entry for canonical "${canonical}"`);
  }
  return match;
};

describe("FMEA_COLUMN_METADATA — Phase 5 canonical column list", () => {
  test("has exactly 15 entries", () => {
    expect(FMEA_COLUMN_METADATA).toHaveLength(15);
  });

  test("Part Number row is required, mapped-origin, and visible everywhere", () => {
    // 2026-07-20: Part Number is one of only two hard-required BOM columns
    // (it drives the HDA commodity join) but the card never offered it —
    // auto-detect was the only path and a miss failed the run outright.
    const pn = findByCanonical("Part Number");
    expect(pn.required).toBe(true);
    expect(pn.origin).toBe("mapped");
    const modes: WorkflowId[] = [
      "piece_part_generate",
      "bom_only",
      "functional_to_piecepart",
      "fill_gaps",
    ];
    for (const mode of modes) {
      expect(pn.isVisibleInMode(mode)).toBe(true);
    }
  });

  test("every entry has non-empty help text of reasonable length", () => {
    for (const meta of FMEA_COLUMN_METADATA) {
      expect(meta.help.length).toBeGreaterThan(40);
    }
  });

  test("canonical names are unique", () => {
    const names = FMEA_COLUMN_METADATA.map((meta) => meta.canonical);
    expect(new Set(names).size).toBe(names.length);
  });
});

describe("FMEA_COLUMN_METADATA — visibility filters", () => {
  test("FMEA-ID is hidden in bom_only but visible in all other modes", () => {
    const fmeaId = findByCanonical("FMEA-ID");
    expect(fmeaId.isVisibleInMode("bom_only")).toBe(false);
    expect(fmeaId.isVisibleInMode("piece_part_generate")).toBe(true);
    expect(fmeaId.isVisibleInMode("functional_to_piecepart")).toBe(true);
    expect(fmeaId.isVisibleInMode("fill_gaps")).toBe(true);
  });

  test("Local / Next Higher / End Effect rows appear only in merge modes", () => {
    const mergeOnlyCanonicals = ["Local Effect", "Next Higher Effect", "End Effect"];
    const nonMergeModes: WorkflowId[] = ["piece_part_generate", "bom_only"];
    const mergeModes: WorkflowId[] = ["functional_to_piecepart", "fill_gaps"];

    for (const canonical of mergeOnlyCanonicals) {
      const meta = findByCanonical(canonical);
      expect(meta.origin).toBe("merge_only");
      for (const mode of nonMergeModes) {
        expect(meta.isVisibleInMode(mode)).toBe(false);
      }
      for (const mode of mergeModes) {
        expect(meta.isVisibleInMode(mode)).toBe(true);
      }
    }
  });

  test("every other row is visible in every FMEA mode", () => {
    const conditional = new Set([
      "FMEA-ID",
      "Local Effect",
      "Next Higher Effect",
      "End Effect",
    ]);
    const allFmeaModes: WorkflowId[] = [
      "piece_part_generate",
      "bom_only",
      "functional_to_piecepart",
      "fill_gaps",
    ];
    for (const meta of FMEA_COLUMN_METADATA) {
      if (conditional.has(meta.canonical)) {
        continue;
      }
      for (const mode of allFmeaModes) {
        expect(meta.isVisibleInMode(mode)).toBe(true);
      }
    }
  });

  test("bom_only mode exposes 11 rows (15 - FMEA-ID - 3 merge-only)", () => {
    const visible = FMEA_COLUMN_METADATA.filter((meta) =>
      meta.isVisibleInMode("bom_only"),
    );
    expect(visible).toHaveLength(11);
  });

  test("merge modes expose all 15 rows", () => {
    for (const mode of ["functional_to_piecepart", "fill_gaps"] as const) {
      const visible = FMEA_COLUMN_METADATA.filter((meta) =>
        meta.isVisibleInMode(mode),
      );
      expect(visible).toHaveLength(15);
    }
  });

  test("piece_part_generate mode exposes 12 rows", () => {
    const visible = FMEA_COLUMN_METADATA.filter((meta) =>
      meta.isVisibleInMode("piece_part_generate"),
    );
    expect(visible).toHaveLength(12);
  });
});

describe("FMEA_COLUMN_METADATA — required flags", () => {
  test("Failure Mode is required", () => {
    expect(findByCanonical("Failure Mode").required).toBe(true);
  });

  test("Failure Mode Ratio is required", () => {
    expect(findByCanonical("Failure Mode Ratio").required).toBe(true);
  });

  test("FMEA-ID is required", () => {
    expect(findByCanonical("FMEA-ID").required).toBe(true);
  });

  test("other rows default to not required", () => {
    const nonRequired = [
      "Failure Mode Causes",
      "Component Part Description",
      "BAE HDA Commodity Level 1",
      "BAE HDA Commodity Level 2",
      "FMD Commodity Type 1",
      "FMD Commodity Type 2",
      "Part Usage",
      "FMEA Level",
      "Local Effect",
      "Next Higher Effect",
      "End Effect",
    ];
    for (const canonical of nonRequired) {
      expect(findByCanonical(canonical).required).toBe(false);
    }
  });
});

describe("FMEA_COLUMN_METADATA — FMD standard label swapping", () => {
  test("row 6 label tracks the FMD-91 standard", () => {
    const row = findByCanonical("FMD Commodity Type 1");
    const label = resolveColumnLabel(row, "FMD-91");
    expect(label).toContain("FMD-91");
    expect(label).toContain("Commodity Type 1");
  });

  test("row 6 label tracks the FMD-2016 standard", () => {
    const row = findByCanonical("FMD Commodity Type 1");
    const label = resolveColumnLabel(row, "FMD-2016");
    expect(label).toContain("FMD-2016");
    expect(label).toContain("Commodity Type 1");
  });

  test("row 7 label tracks the FMD-91 standard", () => {
    const row = findByCanonical("FMD Commodity Type 2");
    const label = resolveColumnLabel(row, "FMD-91");
    expect(label).toContain("FMD-91");
    expect(label).toContain("Commodity Type 2");
  });

  test("row 7 label tracks the FMD-2016 standard", () => {
    const row = findByCanonical("FMD Commodity Type 2");
    const label = resolveColumnLabel(row, "FMD-2016");
    expect(label).toContain("FMD-2016");
    expect(label).toContain("Commodity Type 2");
  });

  test("non-FMD rows use their static canonical name regardless of standard", () => {
    const row = findByCanonical("Failure Mode");
    expect(resolveColumnLabel(row, "FMD-91")).toBe("Failure Mode");
    expect(resolveColumnLabel(row, "FMD-2016")).toBe("Failure Mode");
  });
});

describe("migrateFmdOverrides — Fix B-FMD: dynamic override key migration", () => {
  // Fix B-FMD: mappingOverrides is keyed by the resolved (dynamic) label,
  // so toggling the FMD standard would otherwise orphan overrides stored
  // under the FMD Commodity Type rows. migrateFmdOverrides remaps those
  // dynamic keys to the new standard's labels so the user's mapping work
  // survives the toggle.

  test("migrates an FMD-2016 Commodity Type 1 override to the FMD-91 key", () => {
    const overrides = { "FMD-2016 Commodity Type 1": "HDA Col A" };
    const next = migrateFmdOverrides(overrides, "FMD-2016", "FMD-91");

    expect(next["FMD-91 Commodity Type 1"]).toBe("HDA Col A");
    expect(next).not.toHaveProperty("FMD-2016 Commodity Type 1");
  });

  test("migrates the reverse direction (FMD-91 -> FMD-2016)", () => {
    const overrides = { "FMD-91 Commodity Type 2": "HDA Col B" };
    const next = migrateFmdOverrides(overrides, "FMD-91", "FMD-2016");

    expect(next["FMD-2016 Commodity Type 2"]).toBe("HDA Col B");
    expect(next).not.toHaveProperty("FMD-91 Commodity Type 2");
  });

  test("migrates every dynamic FMD Commodity Type row at once", () => {
    const overrides = {
      "FMD-2016 Commodity Type 1": "Col One",
      "FMD-2016 Commodity Type 2": "Col Two",
    };
    const next = migrateFmdOverrides(overrides, "FMD-2016", "FMD-91");

    expect(next).toEqual({
      "FMD-91 Commodity Type 1": "Col One",
      "FMD-91 Commodity Type 2": "Col Two",
    });
  });

  test("leaves non-dynamic override keys untouched", () => {
    const overrides = {
      "Failure Mode": "Mode Col",
      "FMD-2016 Commodity Type 1": "HDA Col A",
    };
    const next = migrateFmdOverrides(overrides, "FMD-2016", "FMD-91");

    expect(next["Failure Mode"]).toBe("Mode Col");
    expect(next["FMD-91 Commodity Type 1"]).toBe("HDA Col A");
    expect(next).not.toHaveProperty("FMD-2016 Commodity Type 1");
  });

  test("is a no-op when the standard does not change", () => {
    const overrides = { "FMD-2016 Commodity Type 1": "HDA Col A" };
    const next = migrateFmdOverrides(overrides, "FMD-2016", "FMD-2016");

    expect(next).toEqual(overrides);
  });

  test("does not mutate the input overrides object", () => {
    const overrides = { "FMD-2016 Commodity Type 1": "HDA Col A" };
    const snapshot = { ...overrides };
    migrateFmdOverrides(overrides, "FMD-2016", "FMD-91");

    expect(overrides).toEqual(snapshot);
  });
});

describe("FMEA_COLUMN_METADATA — origin flags", () => {
  test("FMEA Level is marked as derived", () => {
    expect(findByCanonical("FMEA Level").origin).toBe("derived");
  });

  test("merge-only rows carry the merge_only origin", () => {
    for (const canonical of ["Local Effect", "Next Higher Effect", "End Effect"]) {
      expect(findByCanonical(canonical).origin).toBe("merge_only");
    }
  });

  test("most rows carry the mapped origin", () => {
    const mapped = FMEA_COLUMN_METADATA.filter((meta) => meta.origin === "mapped");
    // 15 total - 1 derived - 3 merge_only = 11 mapped
    expect(mapped).toHaveLength(11);
  });
});
