import type { ColumnMappingRow } from "../app/types";
import { CustomSelect } from "./CustomSelect";

interface MappingTableProps {
  rows: ColumnMappingRow[];
  overrides: Record<string, string>;
  onOverride: (canonical: string, mappedTo: string) => void;
}

export function MappingTable({
  rows,
  overrides,
  onOverride,
}: MappingTableProps) {
  return (
    <div className="table-shell">
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

            return (
              <tr key={row.canonical}>
                <td>
                  <div className="mapping-field">
                    <span className="mapping-field__name">{row.canonical}</span>
                  </div>
                </td>
                <td>
                  <CustomSelect
                    label={`${row.canonical} mapping`}
                    value={mappedValue}
                    options={row.options.map((option) => ({ value: option, label: option }))}
                    onChange={(value) => onOverride(row.canonical, value)}
                    compact
                  />
                </td>
                <td>
                  <span className={`status-chip status-chip--${row.status}`}>
                    {row.status}
                  </span>
                </td>
                <td>{row.recommendation}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
