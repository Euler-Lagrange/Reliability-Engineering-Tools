import { describe, expect, test } from "vitest";
import type { InputFileState } from "../../app/types";
import {
  buildAggregatedMappingSource,
  buildWorkbookColumnUnion,
  mergeColumnsByNormalizedName,
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
      optionLabels: {
        "FMEA-ID": "FMEA-ID - Grouping workbook",
        "Failure Mode Causes": "Failure Mode Causes - Grouping workbook",
        "Component Part Description": "Component Part Description - BOM workbook",
        "Part Usage": "Part Usage - BOM workbook",
        "Failure Mode": "Failure Mode - Failure modes workbook",
        "Failure Mode Ratio": "Failure Mode Ratio - Failure modes workbook",
      },
      sourceLabels: ["Grouping workbook", "BOM workbook", "Failure modes workbook"],
      sourceLabelText: "Grouping workbook, BOM workbook, and Failure modes workbook",
    });
  });

  test("merges source provenance when the same header appears in multiple visible roles", () => {
    const inputs = [
      makeInput("bom", "BOM workbook"),
      makeInput("hda", "HDA workbook"),
    ];

    expect(
      buildAggregatedMappingSource(inputs, {
        bom: ["Part Number", "Part Usage"],
        hda: ["Part Number", "Commodity Level 1"],
      }),
    ).toEqual({
      columns: ["Part Number", "Part Usage", "Commodity Level 1"],
      optionLabels: {
        "Part Number": "Part Number - BOM workbook and HDA workbook",
        "Part Usage": "Part Usage - BOM workbook",
        "Commodity Level 1": "Commodity Level 1 - HDA workbook",
      },
      sourceLabels: ["BOM workbook", "HDA workbook"],
      sourceLabelText: "BOM workbook and HDA workbook",
    });
  });

  test("shows target workbook only for preserve-formatting strategy", () => {
    expect(shouldShowTargetWorkbook("new_workbook_standard")).toBe(false);
    expect(shouldShowTargetWorkbook("existing_workbook_preserve_formatting")).toBe(true);
  });

});
