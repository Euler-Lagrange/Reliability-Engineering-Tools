import { DO_NOT_MAP_VALUE, type ColumnMappingRow } from "../../app/types";

/**
 * Bulk "Apply all suggestions": restore every row that has an
 * auto-derived suggestion — or that the user excluded with the
 * Do-Not-Map sentinel — back to its suggested state by dropping the
 * override. The suggestion IS `row.mappedTo`: rows are derived fresh
 * from the inspected headers, so removing the override re-exposes the
 * auto-match (or the derived/blank state for rows without one).
 *
 * Rows the user manually pointed at a real column are reset too — the
 * bulk action is an explicit reset (see the MappingTable prop doc).
 * Rows with no suggestion AND no Do-Not-Map override keep whatever
 * override they carry, because there is no suggestion to apply.
 *
 * 2026-07-28: the previous per-tool implementations guarded on
 * `row.options.includes(row.recommendation)` — but `recommendation` is
 * prose ("Exact header found in BOM workbook."), never a column name,
 * so the loop matched nothing and "Apply all suggestions" was a no-op
 * after "Clear all mappings" (and would have written prose as a column
 * name if it ever matched).
 */
export function applyAllSuggestions(
  overrides: Record<string, string>,
  rows: ColumnMappingRow[],
): Record<string, string> {
  const next = { ...overrides };
  for (const row of rows) {
    if (!Object.prototype.hasOwnProperty.call(next, row.canonical)) {
      continue;
    }
    if (row.mappedTo || next[row.canonical] === DO_NOT_MAP_VALUE) {
      delete next[row.canonical];
    }
  }
  return next;
}

/**
 * Bulk "Clear all mappings": explicit Do-Not-Map override on every row
 * (not the empty string) so the backend sees an intentional "unmap"
 * request rather than a missing mapping.
 */
export function clearAllMappings(
  rows: ColumnMappingRow[],
): Record<string, string> {
  const next: Record<string, string> = {};
  for (const row of rows) {
    next[row.canonical] = DO_NOT_MAP_VALUE;
  }
  return next;
}

/**
 * True when `applyAllSuggestions()` would change at least one row —
 * used to keep the bulk button enabled after "Clear all mappings"
 * (whose overrides carry no quoted-synonym suggestion text).
 */
export function hasRestorableOverride(
  overrides: Record<string, string>,
  rows: ColumnMappingRow[],
): boolean {
  return rows.some((row) => {
    if (!Object.prototype.hasOwnProperty.call(overrides, row.canonical)) {
      return false;
    }
    return Boolean(row.mappedTo) || overrides[row.canonical] === DO_NOT_MAP_VALUE;
  });
}
