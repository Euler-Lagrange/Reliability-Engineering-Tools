import { normalizeHeader } from "../../shared/mapping/normalizeHeader";

/**
 * Mirrored subset of `backend/python/common/column_synonyms.py`
 * (`COLUMN_SYNONYMS`) powering the mapping card's synonym automap.
 *
 * TWO-DEFINITION LOCKSTEP — same pattern as `DO_NOT_MAP_VALUE`: the backend
 * test `backend/tests/test_fmea_column_resolution.py`
 * (`test_frontend_synonym_mirror_matches_backend_lists`) parses this file
 * and fails the moment any list here drifts from the Python source of
 * truth. Edit both files together, keeping order and spelling identical.
 *
 * Why a mirror instead of one source: the card previously automapped ONLY
 * on an exact match of the canonical display label, while the backend's
 * synonym heuristics ran at execute time — so registered headers like
 * "BAE PN" or "FMD-2016 Commodity Type I" rendered as "Select column"
 * even though the run would resolve them (2026-07-20 field report).
 *
 * Note: `Failure Mode Ratio` deliberately mirrors `fmr_strict` (not the
 * broad `ratio` list) — the dropdown draws from the union of every loaded
 * file's headers, and a generic BOM "Percentage" column must never grab
 * the ratio row.
 */
export const FMEA_HEADER_SYNONYMS: Record<string, readonly string[]> = {
  component_group: [
    "Component Group", "Component Grouping", "Group", "Function Block",
    "Circuit Block", "Partition", "Block", "Area", "Function Group",
    "Group ID", "Function_Group",
  ],
  ref_des: [
    "RefDes", "Reference Designator", "Reference Designators",
    "ReferenceDesignator", "ReferenceDesignators",
    "Part Reference Designator", "Ref Des", "Ref_Des", "Designator",
    "Refs", "Components", "Parts", "RefDes List", "Ref",
    "Failure Mode Causes",
    "Failure Mode Cause",
    "FMCs",
  ],
  part_number: [
    "Part Number", "PartNumber", "P/N", "Part_Number", "PN",
    "BAE Part Number", "BAE PN",
  ],
  description: [
    "Name", "Part Description", "Primary Part Description",
    "Description", "Part_Description", "Item Description",
    "Desc", "PartDesc", "Part Name", "Component Name",
  ],
  commodity_level1: [
    "Commodity Level 1", "Commodity Level I",
    "HDA Commodity Level 1", "HDA Commodity Level I",
    "BAE HDA Commodity I",
    "BAE HDA Commodity Level", "BAE HDA Commodity Level I", "BAE HDA Commodity Level 1",
    "HDA Commodity", "HDA Commodity I", "Commodity", "Commodity I",
  ],
  commodity_level2: [
    "Commodity Level 2", "Commodity Level II",
    "HDA Commodity Level 2", "HDA Commodity Level II",
    "BAE HDA Commodity II",
    "BAE HDA Commodity Level II", "BAE HDA Commodity Level 2",
    "HDA Commodity II", "Commodity II",
  ],
  fmd_type1: [
    "FMD-91 Component Type 1", "FMD-2016 Component Type 1",
    "FMD Component Type 1", "FMD Type 1",
    "Component Type 1", "Type 1", "FMD-2016 Commodity Type 1",
    "FMD-2016 Commodity I", "FMD-91 Commodity I",
    "FMD-2016 I", "FMD-91 I",
    "FMD-2016 Commodity Level I", "FMD-91 Commodity Level I",
    "FMD Commodity Level I", "FMD Commodity Level 1",
    "FMD-2016 Commodity Type I", "FMD-91 Commodity Type I",
    "FMD Commodity Type I", "Component Type I", "Type I",
  ],
  fmd_type2: [
    "FMD-91 Component Type 2", "FMD-2016 Component Type 2",
    "FMD Component Type 2", "FMD Type 2",
    "Component Type 2", "Type 2", "FMD-2016 Commodity Type 2",
    "FMD-2016 Commodity II", "FMD-91 Commodity II",
    "FMD-2016 II", "FMD-91 II",
    "FMD-2016 Commodity Level II", "FMD-91 Commodity Level II",
    "FMD Commodity Level II", "FMD Commodity Level 2",
    "FMD-2016 Commodity Type II", "FMD-91 Commodity Type II",
    "FMD Commodity Type II", "Component Type II", "Type II",
  ],
  failure_mode: [
    "Failure Mode", "Failure Modes", "Main Failure Modes", "Mode",
    "FM", "Main Failure Mode", "Functional Failure Mode",
  ],
  fmr_strict: [
    "FMR", "Failure Mode Ratio", "FM Ratio", "Ratio",
  ],
  part_usage: [
    "Part Usage", "Usage", "Quantity", "Qty",
  ],
  local_effect: [
    "Local Effect", "Local Effects", "Local",
    "Local Effect (Board)", "Board Effect", "Board",
  ],
  next_higher_effect: [
    "Next Higher Effect", "Next-Higher Effect", "Next Effect",
    "Channel Effect", "Channel", "Next Higher Effect (Channel)",
  ],
  end_effect: [
    "End Effect", "FADEC Effect", "System Effect",
    "Top Effect", "FADEC", "End Effect (FADEC)",
  ],
};

/**
 * Resolved canonical row label → synonym-list key. Mirrors the file/key
 * targets in `fmea/runtime.py FRONTEND_TO_BACKEND_MAPPING` (e.g. FMEA-ID
 * maps the grouping file's component-group column, so it automaps on
 * component-group synonyms).
 */
const CANONICAL_TO_SYNONYM_KEY: Record<string, string> = {
  "FMEA-ID": "component_group",
  "Failure Mode Causes": "ref_des",
  "Part Number": "part_number",
  "Component Part Description": "description",
  "BAE HDA Commodity Level 1": "commodity_level1",
  "BAE HDA Commodity Level 2": "commodity_level2",
  "FMD-91 Commodity Type 1": "fmd_type1",
  "FMD-2016 Commodity Type 1": "fmd_type1",
  "FMD-91 Commodity Type 2": "fmd_type2",
  "FMD-2016 Commodity Type 2": "fmd_type2",
  "Failure Mode": "failure_mode",
  "Failure Mode Ratio": "fmr_strict",
  "Part Usage": "part_usage",
  "Local Effect": "local_effect",
  "Next Higher Effect": "next_higher_effect",
  "End Effect": "end_effect",
};

/**
 * Find the first inspected header that matches one of the canonical row's
 * registered synonyms (normalized exact comparison — no substring
 * guessing in the card; the backend's fuzzier heuristics still run at
 * execute time for rows left unmapped).
 *
 * `exactMap` is the caller's normalized-header → verbatim-header map, the
 * same one used for the exact canonical match.
 */
export function findSynonymMatch(
  canonical: string,
  exactMap: ReadonlyMap<string, string>,
): string | undefined {
  const key = CANONICAL_TO_SYNONYM_KEY[canonical];
  if (!key) {
    return undefined;
  }
  for (const synonym of FMEA_HEADER_SYNONYMS[key]) {
    const match = exactMap.get(normalizeHeader(synonym));
    if (match) {
      return match;
    }
  }
  return undefined;
}
