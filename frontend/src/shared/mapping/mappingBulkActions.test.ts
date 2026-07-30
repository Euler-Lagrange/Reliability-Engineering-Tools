import { describe, expect, test } from "vitest";
import { DO_NOT_MAP_VALUE, type ColumnMappingRow } from "../../app/types";
import {
  applyAllSuggestions,
  clearAllMappings,
  hasRestorableOverride,
} from "./mappingBulkActions";

function makeRow(overridesFields: Partial<ColumnMappingRow>): ColumnMappingRow {
  return {
    canonical: "Field",
    mappedTo: "",
    status: "not_mapped",
    recommendation: "No column mapped yet.",
    options: ["Column A", "Column B"],
    ...overridesFields,
  } as ColumnMappingRow;
}

const autoMapped = makeRow({
  canonical: "FMEA-ID",
  mappedTo: "Column A",
  status: "mapped",
  recommendation: "Exact header found in BOM workbook.",
});
const unmatched = makeRow({
  canonical: "Part Number",
  mappedTo: "",
  status: "attention",
  recommendation: "No column mapped yet.",
});
const derived = makeRow({
  canonical: "FMEA Level",
  mappedTo: "",
  status: "derived",
  origin: "derived",
  recommendation: "Generated automatically from BOM and grouping data.",
});

describe("clearAllMappings", () => {
  test("writes the Do-Not-Map sentinel for every row", () => {
    const cleared = clearAllMappings([autoMapped, unmatched, derived]);
    expect(cleared).toEqual({
      "FMEA-ID": DO_NOT_MAP_VALUE,
      "Part Number": DO_NOT_MAP_VALUE,
      "FMEA Level": DO_NOT_MAP_VALUE,
    });
  });
});

describe("applyAllSuggestions", () => {
  test("clear-all then apply-all round-trips back to the suggested state", () => {
    const cleared = clearAllMappings([autoMapped, unmatched, derived]);
    const restored = applyAllSuggestions(cleared, [autoMapped, unmatched, derived]);
    // Every Do-Not-Map override is dropped — auto rows return to their
    // auto-match, derived rows to Derived, unmatched rows to Not mapped.
    expect(restored).toEqual({});
  });

  test("replaces a manual pick with the suggestion when one exists", () => {
    const restored = applyAllSuggestions({ "FMEA-ID": "Column B" }, [autoMapped]);
    expect(restored).toEqual({});
  });

  test("keeps a manual pick on a row that has no suggestion", () => {
    const restored = applyAllSuggestions({ "Part Number": "Column B" }, [unmatched]);
    expect(restored).toEqual({ "Part Number": "Column B" });
  });

  test("does not invent overrides for untouched rows", () => {
    const restored = applyAllSuggestions({}, [autoMapped, unmatched]);
    expect(restored).toEqual({});
  });
});

describe("hasRestorableOverride", () => {
  test("false with no overrides", () => {
    expect(hasRestorableOverride({}, [autoMapped, unmatched])).toBe(false);
  });

  test("true after clear-all so the bulk button stays enabled", () => {
    const cleared = clearAllMappings([autoMapped, unmatched]);
    expect(hasRestorableOverride(cleared, [autoMapped, unmatched])).toBe(true);
  });

  test("true for a manual pick on an auto-matched row", () => {
    expect(hasRestorableOverride({ "FMEA-ID": "Column B" }, [autoMapped])).toBe(true);
  });

  test("false for a manual pick on a row with no suggestion", () => {
    expect(hasRestorableOverride({ "Part Number": "Column B" }, [unmatched])).toBe(false);
  });
});
