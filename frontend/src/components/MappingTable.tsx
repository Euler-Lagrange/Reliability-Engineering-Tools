import { useCallback, useState } from "react";
import { Info } from "@phosphor-icons/react";
import {
  DO_NOT_MAP_LABEL,
  DO_NOT_MAP_VALUE,
  type ColumnMappingRow,
  type MappingStatus,
} from "../app/types";
import { useEscapeLayer } from "../shared/hooks/useEscapeLayer";
import { CustomSelect } from "./CustomSelect";

interface MappingTableProps {
  rows: ColumnMappingRow[];
  overrides: Record<string, string>;
  onOverride: (canonical: string, mappedTo: string) => void;
  /**
   * Bulk-apply every row's suggestion (when available). The parent wires
   * this to iterate rows and call `onOverride` for each.
   *
   * NOTE: "Apply all suggestions" intentionally OVERRIDES any row the
   * user previously marked "— Do Not Map —". We treat the bulk action
   * as an explicit reset. If the user wants a specific row to stay
   * unmapped, they can re-select it after.
   */
  onApplyAllSuggestions?: () => void;
  /**
   * Clear every row override. Parent tools should wire this to set each
   * row to `DO_NOT_MAP_VALUE` (not the empty string) so the backend sees
   * an explicit "unmap" request rather than a missing mapping.
   */
  onClearAllMappings?: () => void;
  /**
   * Apply a single recommendation for a specific row. Used by the per-row
   * "Use recommendation" inline button.
   */
  onApplyRecommendation?: (canonical: string, suggestedValue: string) => void;
}

/**
 * Heuristic recommendation extractor. `row.recommendation` is a free-form
 * string today (e.g. "Exact header found in BOM sheet."). When a row's
 * recommendation text contains a quoted or parenthesized column name, or
 * when `row.status === "attention"` and there's a clear candidate in
 * `row.options`, we use that. Falling back to null disables the per-row
 * button so we never apply a garbage mapping.
 */
function extractSuggestedValue(row: ColumnMappingRow, mappedValue: string): string | null {
  // If the row's recommendation is an exact option, prefer that.
  if (row.recommendation && row.options.includes(row.recommendation)) {
    if (row.recommendation !== mappedValue) {
      return row.recommendation;
    }
    return null;
  }
  // Look for a quoted column name in the recommendation text.
  const quoted = row.recommendation?.match(/["“]([^"”]+)["”]/);
  if (quoted && row.options.includes(quoted[1]) && quoted[1] !== mappedValue) {
    return quoted[1];
  }
  return null;
}

/**
 * Resolve the effective status used for chip rendering. When the user
 * explicitly selects "— Do Not Map —" we override the upstream status
 * with `not_mapped`. When the row's origin is `derived`, we show the
 * "derived" chip regardless of mapping state.
 */
function resolveDisplayStatus(row: ColumnMappingRow, mappedValue: string): MappingStatus {
  if (mappedValue === DO_NOT_MAP_VALUE) {
    return "not_mapped";
  }
  if (row.origin === "derived") {
    return "derived";
  }
  // UX findings 2026-07-07 #3: an OPTIONAL row that simply has no mapping
  // is not a warning state — demote the amber "attention" chip to the
  // neutral "Not mapped" so users aren't sent chasing a non-issue. Rows
  // marked required keep their fixture status untouched.
  if (row.required !== true && !mappedValue && row.status === "attention") {
    return "not_mapped";
  }
  return row.status;
}

/* v2 N7: status renders as a 6px dot + word (one colored pixel-cluster
   per row instead of a filled pill — 12 rows stop looking like an alarm
   panel while the color-column scan pattern survives). */
const STATUS_META: Record<MappingStatus, { label: string; tone?: string }> = {
  mapped: { label: "Mapped", tone: "ok" },
  manual: { label: "Manual", tone: "acc" },
  attention: { label: "Attention", tone: "warn" },
  derived: { label: "Derived", tone: "hollow" },
  not_mapped: { label: "Not mapped" },
};

/**
 * Helper used by the DOM to compute the "About this column" panel id.
 * Exported so consumers / tests can assert the aria-controls wiring.
 */
export function helpPanelId(canonical: string): string {
  return `mapping-help-${canonical}`;
}

export function MappingTable({
  rows,
  overrides,
  onOverride,
  onApplyAllSuggestions,
  onClearAllMappings,
  onApplyRecommendation,
}: MappingTableProps) {
  // One-at-a-time expand: only one help panel is open at any moment.
  const [expandedHelpRow, setExpandedHelpRow] = useState<string | null>(null);

  const toggleHelp = useCallback((canonical: string) => {
    setExpandedHelpRow((current) => (current === canonical ? null : canonical));
  }, []);

  // Escape collapses the currently-open panel regardless of focus target.
  // Registered through the shared dismiss-stack so a single Escape only closes
  // this (top-most) layer, not other open surfaces (e.g. the Review drawer).
  useEscapeLayer(expandedHelpRow !== null, () => setExpandedHelpRow(null));

  // Only REQUIRED rows count toward the amber "N unmapped" badge — an
  // optional row without a mapping is a normal state, not a to-do (UX
  // findings 2026-07-07 #3). All three tools' fixture/metadata rows carry
  // explicit `required` flags.
  const unmappedCount = rows.filter((row) => {
    if (row.required !== true) {
      return false;
    }
    const mapped = overrides[row.canonical] ?? row.mappedTo;
    const status = resolveDisplayStatus(row, mapped);
    return status !== "mapped" && status !== "derived";
  }).length;
  const hasAnySuggestion = rows.some((row) => {
    const mapped = overrides[row.canonical] ?? row.mappedTo;
    return extractSuggestedValue(row, mapped) !== null;
  });
  const hasAnyOverride = Object.keys(overrides).length > 0;
  const showToolbar =
    !!onApplyAllSuggestions || !!onClearAllMappings || unmappedCount > 0;

  // v2 N7: the toolbar counts are the table's telemetry — the amber
  // "N unmapped" pill becomes just another count. `unmapped` keeps the
  // required-only semantics (UX findings 2026-07-07 #3: an optional row
  // with no mapping is a normal state, not a to-do).
  const statusTotals = rows.reduce(
    (acc, row) => {
      const mapped = overrides[row.canonical] ?? row.mappedTo;
      const status = resolveDisplayStatus(row, mapped);
      acc[status] = (acc[status] ?? 0) + 1;
      return acc;
    },
    {} as Partial<Record<MappingStatus, number>>,
  );
  const countSegments: string[] = [];
  if (statusTotals.mapped) countSegments.push(`${statusTotals.mapped} mapped`);
  if (statusTotals.manual) countSegments.push(`${statusTotals.manual} manual`);
  if (statusTotals.derived) countSegments.push(`${statusTotals.derived} derived`);
  if (unmappedCount > 0) countSegments.push(`${unmappedCount} unmapped`);

  return (
    <div className="table-shell">
      {showToolbar ? (
        <div className="mapping-table__toolbar">
          <span className="mapping-table__counts" aria-label="Mapping status counts">
            {countSegments.map((segment, index) => (
              <span key={segment}>
                {index > 0 ? <span aria-hidden="true"> · </span> : null}
                <span>{segment}</span>
              </span>
            ))}
          </span>
          <span className="mapping-table__toolbar-spacer" />
          {onApplyAllSuggestions ? (
            <button
              type="button"
              className="ghost-button ghost-button--sm"
              disabled={!hasAnySuggestion}
              onClick={onApplyAllSuggestions}
            >
              Apply all suggestions
            </button>
          ) : null}
          {onClearAllMappings ? (
            <button
              type="button"
              className="ghost-button ghost-button--sm"
              disabled={!hasAnyOverride}
              onClick={onClearAllMappings}
            >
              Clear all mappings
            </button>
          ) : null}
        </div>
      ) : null}
      <table className="mapping-table">
        <thead>
          <tr>
            <th>Field</th>
            <th>Source column</th>
            <th>Status</th>
            <th>Note</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const mappedValue = overrides[row.canonical] ?? row.mappedTo;
            const suggested = extractSuggestedValue(row, mappedValue);
            const displayStatus = resolveDisplayStatus(row, mappedValue);
            const showUseRecommendation =
              !!onApplyRecommendation &&
              suggested !== null &&
              displayStatus !== "mapped" &&
              displayStatus !== "derived";

            // Prepend the "Do Not Map" sentinel so it sits at the top of
            // every dropdown. We strip any upstream duplicates first so
            // tools that still carry a literal "Do Not Map" string don't
            // double up.
            const dropdownOptions = [
              { value: DO_NOT_MAP_VALUE, label: DO_NOT_MAP_LABEL },
              ...row.options
                .filter(
                  (option) =>
                    option !== DO_NOT_MAP_VALUE && option !== DO_NOT_MAP_LABEL,
                )
                .map((option) => ({
                  value: option,
                  label: row.optionLabels?.[option] ?? option,
                })),
            ];

            const isExpanded = expandedHelpRow === row.canonical;
            const hasHelp = !!row.help;
            const isNotMapped = mappedValue === DO_NOT_MAP_VALUE;
            const triggerWrapperClass = isNotMapped
              ? "mapping-table__trigger-wrapper mapping-table__trigger-wrapper--not-mapped"
              : "mapping-table__trigger-wrapper";

            return (
              <tr key={row.canonical}>
                <td>
                  <div className="mapping-field">
                    <span className="mapping-field__name">{row.displayLabel ?? row.canonical}</span>
                    {row.required ? (
                      <span
                        className="mapping-field__required"
                        role="img"
                        aria-label="Required column"
                        title="Required — selecting 'Do Not Map' for this column blocks the run."
                      >
                        *
                      </span>
                    ) : null}
                    {hasHelp ? (
                      <button
                        type="button"
                        className="mapping-table__help-button"
                        aria-expanded={isExpanded}
                        aria-controls={helpPanelId(row.canonical)}
                        aria-label={`About ${row.canonical}`}
                        onClick={() => toggleHelp(row.canonical)}
                      >
                        <Info size={14} weight="regular" />
                      </button>
                    ) : null}
                  </div>
                  {hasHelp && isExpanded ? (
                    <div
                      className="mapping-table__help-panel"
                      id={helpPanelId(row.canonical)}
                      role="region"
                      aria-label={`About ${row.canonical}`}
                    >
                      <p className="mapping-table__help-eyebrow">
                        ABOUT THIS COLUMN
                      </p>
                      <p className="mapping-table__help-body">{row.help}</p>
                    </div>
                  ) : null}
                </td>
                <td className="mapping-table__select-cell">
                  <div className={triggerWrapperClass}>
                    <CustomSelect
                      label={`${row.canonical} mapping`}
                      value={mappedValue}
                      options={dropdownOptions}
                      onChange={(value) => onOverride(row.canonical, value)}
                      placeholder="Select column…"
                      variant="quiet"
                    />
                  </div>
                </td>
                <td>
                  <span className="state-word" data-status={displayStatus}>
                    <i
                      className="dot"
                      data-tone={STATUS_META[displayStatus]?.tone}
                      aria-hidden="true"
                    />
                    {STATUS_META[displayStatus]?.label ?? displayStatus}
                  </span>
                </td>
                <td>
                  <div className="mapping-table__recommendation-cell">
                    <span className="mapping-table__note" title={row.recommendation || undefined}>
                      {row.recommendation}
                    </span>
                    {showUseRecommendation && suggested ? (
                      <button
                        type="button"
                        className="mapping-table__use-recommendation"
                        onClick={() => onApplyRecommendation?.(row.canonical, suggested)}
                      >
                        Apply match
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
