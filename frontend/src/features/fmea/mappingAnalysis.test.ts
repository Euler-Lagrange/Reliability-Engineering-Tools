import { describe, expect, test } from "vitest";
import type { InputFileState } from "../../app/types";
import {
  buildAggregatedMappingSource,
  buildWorkbookColumnUnion,
  mergeColumnsByNormalizedName,
  resolveSheetInspections,
  shouldShowTargetWorkbook,
} from "./mappingAnalysis";

function makeInput(role: InputFileState["role"], label: string): InputFileState {
  return {
    role,
    label,
    path: "",
    helper: "",
    status: "ready",
    sheets: [],
    selectedSheet: "",
    tag: "Ready",
  };
}

describe("mappingAnalysis", () => {
  test("merges duplicate headers by normalized name", () => {
    expect(
      mergeColumnsByNormalizedName([
        "Reference Designator",
        "reference-designator",
        "Reference   Designator",
        "Part Usage",
      ]),
    ).toEqual(["Reference Designator", "Part Usage"]);
  });

  test("unions workbook columns across multiple sheets", () => {
    expect(
      buildWorkbookColumnUnion([
        ["Reference Designator", "Part Usage"],
        ["Failure Mode", "Reference-Designator"],
      ]),
    ).toEqual(["Reference Designator", "Part Usage", "Failure Mode"]);
  });

  test("aggregates mapping columns across multiple visible roles", () => {
    const inputs = [
      makeInput("grouping", "Grouping workbook"),
      makeInput("bom", "BOM workbook"),
      makeInput("failureModes", "Failure modes workbook"),
    ];

    expect(
      buildAggregatedMappingSource(inputs, {
        grouping: ["FMEA-ID", "Failure Mode Causes"],
        bom: ["Component Part Description", "Part Usage"],
        failureModes: ["Failure Mode", "Failure Mode Ratio"],
      }),
    ).toEqual({
      columns: [
        "FMEA-ID",
        "Failure Mode Causes",
        "Component Part Description",
        "Part Usage",
        "Failure Mode",
        "Failure Mode Ratio",
      ],
      sourceLabels: ["Grouping workbook", "BOM workbook", "Failure modes workbook"],
      sourceLabelText: "Grouping workbook, BOM workbook, and Failure modes workbook",
    });
  });

  test("shows target workbook only for preserve-formatting strategy", () => {
    expect(shouldShowTargetWorkbook("new_workbook_standard")).toBe(false);
    expect(shouldShowTargetWorkbook("existing_workbook_best_effort")).toBe(false);
    expect(shouldShowTargetWorkbook("existing_workbook_preserve_formatting")).toBe(true);
  });

  test("keeps successful sheet inspections when unrelated workbook sheets fail", () => {
    expect(
      resolveSheetInspections("BOM", [
        {
          sheetName: "BOM",
          result: {
            status: "fulfilled",
            value: { sheet: "BOM", columns: ["Part Usage"] },
          },
        },
        {
          sheetName: "Notes",
          result: {
            status: "rejected",
            reason: new Error("Could not locate a non-empty header row in the selected worksheet."),
          },
        },
      ]),
    ).toEqual({
      selectedInspection: { sheet: "BOM", columns: ["Part Usage"] },
      successfulInspections: [{ sheet: "BOM", columns: ["Part Usage"] }],
      skippedSheets: ["Notes"],
    });
  });

  test("fails when the selected sheet inspection fails", () => {
    expect(() =>
      resolveSheetInspections("BOM", [
        {
          sheetName: "BOM",
          result: {
            status: "rejected",
            reason: new Error("Could not locate a non-empty header row in the selected worksheet."),
          },
        },
      ]),
    ).toThrow("Could not locate a non-empty header row");
  });
});
