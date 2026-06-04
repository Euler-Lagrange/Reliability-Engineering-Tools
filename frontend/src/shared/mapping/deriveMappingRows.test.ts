import { describe, expect, test } from "vitest";
import type { ColumnMappingRow, FileRole } from "../../app/types";
import { deriveMappingRows } from "./deriveMappingRows";

const fixture: ColumnMappingRow[] = [
  {
    canonical: "grouping_group_col",
    mappedTo: "Component Group",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Component Group", "Group", "Circuit Block"],
  },
  {
    canonical: "grouping_refdes_col",
    mappedTo: "Reference Designator",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Reference Designator", "RefDes", "Ref Des"],
  },
  {
    canonical: "bom_refdes_col",
    mappedTo: "Reference Designator",
    status: "mapped",
    recommendation: "Exact match",
    options: ["Reference Designator", "RefDes", "Ref Des"],
  },
];

const canonicalToRole: Record<string, FileRole> = {
  grouping_group_col: "grouping",
  grouping_refdes_col: "grouping",
  bom_refdes_col: "bom",
};

describe("deriveMappingRows", () => {
  test("returns the fixture rows unchanged when no role has inspected columns", () => {
    const rows = deriveMappingRows(fixture, canonicalToRole, {});
    // Same shape AND same option/mappedTo values as the fixture — the demo
    // preview must be byte-identical to today.
    expect(rows).toEqual(fixture);
  });

  test("replaces a role's dropdown options with the real inspected headers", () => {
    const rows = deriveMappingRows(fixture, canonicalToRole, {
      grouping: ["Circuit Block", "Ref Des"],
    });

    const groupRow = rows.find((row) => row.canonical === "grouping_group_col")!;
    const refdesRow = rows.find((row) => row.canonical === "grouping_refdes_col")!;

    // The grouping rows now offer the real workbook headers, never the
    // fixture defaults that don't exist in this file.
    expect(groupRow.options).toEqual(["Circuit Block", "Ref Des"]);
    expect(refdesRow.options).toEqual(expect.arrayContaining(["Circuit Block", "Ref Des"]));
    expect(groupRow.options).not.toContain("Component Group");
  });

  test("auto-fills mappedTo by case-insensitive exact match and marks the row mapped", () => {
    const rows = deriveMappingRows(fixture, canonicalToRole, {
      // Differs only in case/spacing from the fixture default
      // "Reference Designator".
      grouping: ["Circuit Block", "reference  designator"],
    });

    const refdesRow = rows.find((row) => row.canonical === "grouping_refdes_col")!;
    // mappedTo takes the real header verbatim, hoisted to the front of options.
    expect(refdesRow.mappedTo).toBe("reference  designator");
    expect(refdesRow.status).toBe("mapped");
    expect(refdesRow.options[0]).toBe("reference  designator");
  });

  test("leaves a row unmapped and flags attention when no inspected header matches", () => {
    const rows = deriveMappingRows(fixture, canonicalToRole, {
      grouping: ["Block Name", "Designator List"],
    });

    const groupRow = rows.find((row) => row.canonical === "grouping_group_col")!;
    expect(groupRow.mappedTo).toBe("");
    expect(groupRow.status).toBe("attention");
    expect(groupRow.options).toEqual(["Block Name", "Designator List"]);
  });

  test("derives each role independently from its own inspected columns", () => {
    const rows = deriveMappingRows(fixture, canonicalToRole, {
      grouping: ["Circuit Block", "Reference Designator"],
      // bom not inspected yet — its row must stay the untouched fixture.
    });

    const groupRow = rows.find((row) => row.canonical === "grouping_group_col")!;
    const bomRow = rows.find((row) => row.canonical === "bom_refdes_col")!;

    expect(groupRow.options).toEqual(["Circuit Block", "Reference Designator"]);
    // bom row is the pristine fixture row.
    expect(bomRow).toBe(fixture[2]);
    expect(bomRow.options).toEqual(["Reference Designator", "RefDes", "Ref Des"]);
  });

  test("preserves every non-derived fixture field on a derived row", () => {
    const helpFixture: ColumnMappingRow[] = [
      {
        canonical: "bom_desc_col",
        mappedTo: "Description",
        status: "mapped",
        recommendation: "Optional",
        options: ["Description", "Part Description"],
        help: "Help text",
        required: false,
      },
    ];
    const rows = deriveMappingRows(
      helpFixture,
      { bom_desc_col: "bom" },
      { bom: ["Description", "Notes"] },
    );

    expect(rows[0].canonical).toBe("bom_desc_col");
    expect(rows[0].recommendation).toBe("Optional");
    expect(rows[0].help).toBe("Help text");
    expect(rows[0].required).toBe(false);
    expect(rows[0].mappedTo).toBe("Description");
    expect(rows[0].status).toBe("mapped");
  });
});
