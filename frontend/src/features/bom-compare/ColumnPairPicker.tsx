import { Plus, Trash } from "@phosphor-icons/react";
import { CustomSelect, type CustomSelectOption } from "../../components/CustomSelect";
import type { ComparePair, CompareRule } from "../../app/types";

/**
 * ColumnPairPicker — repeating-row control for Custom BOM Compare value diffs
 * (Tier-1 #5). Each row pairs a File-1 column with a File-2 column and a
 * comparison rule; the parent collects the rows into `options.compare_columns`
 * for the backend. Rendered ONLY in Custom Compare mode (the Group workflow has
 * no second BOM to pair against), mirroring the `treat_prov_as_covered`
 * hide/disable pattern.
 *
 * Visual idiom matches MappingTable: a `table-shell` container, `CustomSelect`
 * for every dropdown (never a native `<select>`), `ghost-button` for the
 * add/remove affordances, and a muted empty hint when no pairs exist.
 */

const RULE_VALUES: CompareRule[] = [
  "Text (ignore case)",
  "Text (exact)",
  "Numeric",
];

const RULE_OPTIONS: CustomSelectOption[] = RULE_VALUES.map((rule) => ({
  value: rule,
  label: rule,
}));

interface ColumnPairPickerProps {
  pairs: ComparePair[];
  columnsA: string[];
  columnsB: string[];
  onChange: (pairs: ComparePair[]) => void;
}

/**
 * Build the dropdown options for a column select. The currently-selected
 * value is always included even if it is not among the inspected headers, so a
 * user-typed or auto-paired column never silently vanishes from the trigger
 * (CustomSelect would otherwise show the raw value with no option to re-pick).
 */
function columnOptions(columns: string[], current: string): CustomSelectOption[] {
  const seen = new Set<string>();
  const options: CustomSelectOption[] = [];
  for (const column of columns) {
    if (column && !seen.has(column)) {
      seen.add(column);
      options.push({ value: column, label: column });
    }
  }
  if (current && !seen.has(current)) {
    options.push({ value: current, label: current });
  }
  return options;
}

export function ColumnPairPicker({
  pairs,
  columnsA,
  columnsB,
  onChange,
}: ColumnPairPickerProps) {
  function updatePair(index: number, patch: Partial<ComparePair>) {
    onChange(pairs.map((pair, i) => (i === index ? { ...pair, ...patch } : pair)));
  }

  function removePair(index: number) {
    onChange(pairs.filter((_, i) => i !== index));
  }

  function addPair() {
    onChange([
      ...pairs,
      {
        col_a: columnsA[0] ?? "",
        col_b: columnsB[0] ?? "",
        rule: "Text (ignore case)",
      },
    ]);
  }

  return (
    <div className="column-pair-picker">
      {pairs.length === 0 ? (
        <p className="column-pair-picker__empty">
          No column comparisons configured. Matching headers are paired
          automatically once both files are inspected, or add a pair manually
          to diff a column&apos;s values between the two BOMs.
        </p>
      ) : (
        <div className="table-shell">
          <table className="column-pair-picker__table">
            <thead>
              <tr>
                <th>File 1 column</th>
                <th>File 2 column</th>
                <th>Rule</th>
                <th className="column-pair-picker__action-head">
                  <span className="sr-only">Remove</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {pairs.map((pair, index) => (
                <tr key={index}>
                  <td className="column-pair-picker__select-cell">
                    <CustomSelect
                      label={`Compare pair ${index + 1} File 1 column`}
                      value={pair.col_a}
                      options={columnOptions(columnsA, pair.col_a)}
                      onChange={(value) => updatePair(index, { col_a: value })}
                    />
                  </td>
                  <td className="column-pair-picker__select-cell">
                    <CustomSelect
                      label={`Compare pair ${index + 1} File 2 column`}
                      value={pair.col_b}
                      options={columnOptions(columnsB, pair.col_b)}
                      onChange={(value) => updatePair(index, { col_b: value })}
                    />
                  </td>
                  <td className="column-pair-picker__select-cell">
                    <CustomSelect
                      label={`Compare pair ${index + 1} rule`}
                      value={pair.rule}
                      options={RULE_OPTIONS}
                      onChange={(value) =>
                        updatePair(index, { rule: value as CompareRule })
                      }
                    />
                  </td>
                  <td className="column-pair-picker__action-cell">
                    <button
                      type="button"
                      className="column-pair-picker__remove"
                      aria-label={`Remove compare pair ${index + 1}`}
                      onClick={() => removePair(index)}
                    >
                      <Trash size={14} weight="bold" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="column-pair-picker__footer">
        <button
          type="button"
          className="ghost-button"
          onClick={addPair}
        >
          <Plus size={14} weight="bold" />
          Add column pair
        </button>
      </div>
    </div>
  );
}
