import type { FileRole, InputFileState } from "../app/types";
import { CustomSelect } from "./CustomSelect";

interface InputGridProps {
  inputs: InputFileState[];
  onBrowse?: (role: FileRole) => void;
  onSheetChange?: (role: FileRole, sheet: string) => void;
}

export function InputGrid({ inputs, onBrowse, onSheetChange }: InputGridProps) {
  return (
    <div className="input-grid">
      {inputs.map((input) => (
        <article key={input.role} className="input-card">
          <div className="input-card__header">
            <div>
              <p className="input-card__label">{input.label}</p>
              <p className="input-card__path">{input.path}</p>
            </div>
            <span className={`status-chip status-chip--${input.status}`}>{input.tag}</span>
          </div>
          <p className="input-card__helper">{input.helper}</p>
          <div className="input-card__footer">
            <div className="sheet-picker">
              <label>Sheet</label>
              <CustomSelect
                label={`${input.label} sheet`}
                value={input.selectedSheet}
                options={input.sheets.map((sheet) => ({ value: sheet.label, label: sheet.label }))}
                disabled={!onSheetChange || input.isResolvingSheets || input.sheets.length === 0}
                compact
              onChange={(sheet) => onSheetChange?.(input.role, sheet)}
              />
            </div>
            <button
              type="button"
              className="ghost-button"
              onClick={() => onBrowse?.(input.role)}
              disabled={!onBrowse || input.isResolvingSheets || input.isAnalyzing}
            >
              {input.isResolvingSheets ? "Loading..." : input.isAnalyzing ? "Analyzing..." : "Browse"}
            </button>
          </div>
          {input.resolutionError ? <p className="input-card__note">{input.resolutionError}</p> : null}
          {!input.resolutionError && input.isAnalyzing ? (
            <p className="input-card__note">Inspecting the selected sheet through the desktop backend bridge.</p>
          ) : null}
          {!input.resolutionError && input.source === "desktop-bridge" ? (
            <p className="input-card__note">Sheets loaded from the desktop backend bridge.</p>
          ) : null}
        </article>
      ))}
    </div>
  );
}
