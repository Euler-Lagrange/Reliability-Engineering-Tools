import type { ColumnMappingRow, FileRole } from "../../app/types";
import { normalizeHeader } from "./normalizeHeader";

/**
 * Shared mapping-row derivation for the tools whose Column Mapping rows are
 * seeded from a static fixture (BOM Compare and Failure Rate) rather than
 * the FMEA canonical-metadata builder.
 *
 * Bug fix: those fixtures hard-code dropdown options ("Reference Designator",
 * "Component Group", ...) and a pre-filled `mappedTo` regardless of the real
 * workbook the user loaded. On a real file the dropdown then offered headers
 * that may not exist, and a mismatch only surfaced as an execute-time
 * `ColumnMappingError`. This helper rebuilds each fixture row from the
 * workbook headers the backend actually inspected for that row's file role —
 * mirroring `buildFmeaMappingRows` at the appropriate scale.
 *
 * Matching is case/punctuation-insensitive via `normalizeHeader` (the same
 * comparison the FMEA builder uses), so "Ref Des" matches "ref des" etc.
 *
 * Behavior per row:
 *   - Role has inspected columns AND an exact (normalized) match for the
 *     fixture's default `mappedTo`: auto-map. `options` become the real
 *     headers (the matched header hoisted to the front, mirroring the FMEA
 *     builder), `mappedTo` is the real header verbatim, status `mapped`.
 *   - Role has inspected columns but NO match: leave unmapped. `options`
 *     become the real headers, `mappedTo` is "", status `attention` so the
 *     row reads as needs-attention in MappingTable.
 *   - Role has NO inspected columns yet (nothing browsed, including the whole
 *     browser-mock preview): return the fixture row UNCHANGED so the demo
 *     preview and existing tests are unaffected.
 *
 * The returned rows preserve every other fixture field (canonical,
 * recommendation, help, ...) so the run request keeps sending the same
 * canonical set — only `mappedTo`/`status`/`options` move to real headers.
 */
export function deriveMappingRows(
  fixtureRows: readonly ColumnMappingRow[],
  canonicalToRole: Readonly<Record<string, FileRole>>,
  columnsByRole: Partial<Record<FileRole, string[]>>,
): ColumnMappingRow[] {
  return fixtureRows.map((row) => {
    const role = canonicalToRole[row.canonical];
    const inspectedColumns = role ? columnsByRole[role] ?? [] : [];

    // No file inspected for this row's role yet — keep the fixture verbatim.
    if (inspectedColumns.length === 0) {
      return row;
    }

    const exactMap = new Map(
      inspectedColumns.map((column) => [normalizeHeader(column), column] as const),
    );
    const exactMatch = exactMap.get(normalizeHeader(row.mappedTo));

    // Hoist the matched header to the front of the options list so it reads as
    // the active selection, mirroring buildFmeaMappingRows.
    const options = Array.from(
      new Set(exactMatch ? [exactMatch, ...inspectedColumns] : [...inspectedColumns]),
    );

    if (exactMatch) {
      return {
        ...row,
        mappedTo: exactMatch,
        status: "mapped",
        options,
      };
    }

    return {
      ...row,
      mappedTo: "",
      status: "attention",
      options,
    };
  });
}
