import { describe, expect, test } from "vitest";

import { findSynonymMatch } from "./columnSynonyms";
import { buildFmeaMappingRows } from "./FmeaTool";
import { normalizeHeader } from "../../shared/mapping/normalizeHeader";

/**
 * 2026-07-20: the mapping card used to automap ONLY on an exact match of
 * the canonical display label, while the backend's rich synonym list ran
 * at execute time — so headers like "BAE PN" or "FMD-2016 Commodity Type I"
 * (all registered backend synonyms) rendered as "Select column" even though
 * the run would resolve them. These pin the card-side synonym automap.
 */

const exactMapOf = (columns: string[]) =>
  new Map(columns.map((column) => [normalizeHeader(column), column] as const));

describe("findSynonymMatch — mirrored backend synonyms", () => {
  test("BAE PN resolves for the Part Number row", () => {
    expect(findSynonymMatch("Part Number", exactMapOf(["RefDes", "BAE PN"]))).toBe(
      "BAE PN",
    );
  });

  test("Roman-numeral FMD headers resolve to their rows", () => {
    expect(
      findSynonymMatch(
        "FMD-2016 Commodity Type 1",
        exactMapOf(["FMD-2016 Commodity Type I"]),
      ),
    ).toBe("FMD-2016 Commodity Type I");
    expect(
      findSynonymMatch(
        "FMD-2016 Commodity Type 2",
        exactMapOf(["FMD-2016 Commodity Type II"]),
      ),
    ).toBe("FMD-2016 Commodity Type II");
  });

  test("HDA Commodity Level I resolves for BAE HDA Commodity Level 1", () => {
    expect(
      findSynonymMatch("BAE HDA Commodity Level 1", exactMapOf(["HDA Commodity Level I"])),
    ).toBe("HDA Commodity Level I");
  });

  test("unknown canonical or no matching header returns undefined", () => {
    expect(findSynonymMatch("FMEA Level", exactMapOf(["Whatever"]))).toBeUndefined();
    expect(
      findSynonymMatch("Part Number", exactMapOf(["Totally Unrelated"])),
    ).toBeUndefined();
  });

  test("Failure Mode Ratio automaps via the strict FMR list only", () => {
    // The dropdown draws from the union of every loaded file's headers, so
    // a generic BOM "Percentage" column must never grab the ratio row.
    expect(
      findSynonymMatch("Failure Mode Ratio", exactMapOf(["Percentage"])),
    ).toBeUndefined();
    expect(findSynonymMatch("Failure Mode Ratio", exactMapOf(["FMR"]))).toBe("FMR");
  });
});

describe("buildFmeaMappingRows — synonym automap", () => {
  const rowsFor = (columns: string[]) =>
    buildFmeaMappingRows("piece_part_generate", "FMD-2016", columns, "BOM.xlsx", {});

  test("BAE PN automaps the Part Number row", () => {
    const row = rowsFor(["Reference Designator", "BAE PN"]).find(
      (candidate) => candidate.canonical === "Part Number",
    );
    expect(row?.mappedTo).toBe("BAE PN");
    expect(row?.status).toBe("mapped");
  });

  test("an exact canonical header still wins over synonyms", () => {
    const row = rowsFor(["Part Number", "BAE PN"]).find(
      (candidate) => candidate.canonical === "Part Number",
    );
    expect(row?.mappedTo).toBe("Part Number");
  });

  test("Roman-numeral headers automap their FMD/HDA rows", () => {
    const built = rowsFor([
      "FMD-2016 Commodity Type I",
      "FMD-2016 Commodity Type II",
      "HDA Commodity Level I",
    ]);
    expect(
      built.find((row) => row.canonical === "FMD-2016 Commodity Type 1")?.mappedTo,
    ).toBe("FMD-2016 Commodity Type I");
    expect(
      built.find((row) => row.canonical === "FMD-2016 Commodity Type 2")?.mappedTo,
    ).toBe("FMD-2016 Commodity Type II");
    expect(
      built.find((row) => row.canonical === "BAE HDA Commodity Level 1")?.mappedTo,
    ).toBe("HDA Commodity Level I");
  });

  test("derived rows never automap", () => {
    const row = rowsFor(["FMEA Level"]).find(
      (candidate) => candidate.canonical === "FMEA Level",
    );
    expect(row?.status).toBe("derived");
    expect(row?.mappedTo).toBe("");
  });
});
