import { useCallback, useEffect, useState } from "react";
import { Info } from "@phosphor-icons/react";
import {
  DO_NOT_MAP_LABEL,
  DO_NOT_MAP_VALUE,
  type ColumnMappingRow,
  type MappingStatus,
} from "../app/types";
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
  return row.status;
}

const STATUS_CHIP_LABELS: Record<MappingStatus, string> = {
  mapped: "Mapped",
  manual: "Manual",
  attention: "Attention",
  derived: "Derived",
  not_mapped: "Not mapped",
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
  useEffect(() => {
    if (expandedHelpRow === null) {
      return;
    }
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setExpandedHelpRow(null);
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [expandedHelpRow]);

  const unmappedCount = rows.filter((row) => {
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

  return (
    <div className="table-shell">
      {showToolbar ? (
        <div className="mapping-table__toolbar">
          {onApplyAllSuggestions ? (
            <button
              type="button"
              className="ghost-button"
              disabled={!hasAnySuggestion}
              onClick={onApplyAllSuggestions}
            >
              Apply all suggestions
            </button>
          ) : null}
          {onClearAllMappings ? (
            <button
              type="button"
              className="ghost-button"
              disabled={!hasAnyOverride}
              onClick={onClearAllMappings}
            >
              Clear all mappings
            </button>
          ) : null}
          <span className="mapping-table__toolbar-spacer" />
          {unmappedCount > 0 ? (
            <span className="mapping-table__unmapped-count">
              {unmappedCount} unmapped
            </span>
          ) : null}
        </div>
      ) : null}
      <table className="mapping-table">
        <thead>
          <tr>
            <th>Canonical field</th>
            <th>Mapped to</th>
            <th>Status</th>
            <th>Recommendation</th>
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
                .map((option) => ({ value: option, label: option })),
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
                    <span className="mapping-field__name">{row.canonical}</span>
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
                    />
                  </div>
                </td>
                <td>
                  <span className={`status-chip status-chip--${displayStatus}`}>
                    {STATUS_CHIP_LABELS[displayStatus] ?? displayStatus}
                  </span>
                </td>
                <td>
                  <div className="mapping-table__recommendation-cell">
                    <span>{row.recommendation}</span>
                    {showUseRecommendation && suggested ? (
                      <button
                        type="button"
                        className="mapping-table__use-recommendation"
                        onClick={() => onApplyRecommendation?.(row.canonical, suggested)}
                      >
                        Use recommendation
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
