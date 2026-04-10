import { Copy } from "@phosphor-icons/react";
import type { FileRole, InputFileState } from "../app/types";
import { useCopyToClipboard } from "../shared/hooks/useCopyToClipboard";
import { CustomSelect } from "./CustomSelect";

interface InputGridProps {
  inputs: InputFileState[];
  onBrowse?: (role: FileRole) => void;
  onSheetChange?: (role: FileRole, sheet: string) => void;
  /**
   * Optional per-input disabled reason for the sheet picker. Returning a
   * string surfaces a muted caption under the disabled select and wires
   * `aria-describedby` so screen readers announce why the control is inert.
   * Returning `undefined` falls back to the select's default disabled
   * behaviour.
   */
  getDisabledSheetReason?: (input: InputFileState) => string | undefined;
}

export function InputGrid({ inputs, onBrowse, onSheetChange, getDisabledSheetReason }: InputGridProps) {
  const { copy, copied } = useCopyToClipboard();

  return (
    <div className="input-grid">
      {inputs.map((input) => {
        const showExampleStyling =
          !!input.isExample && input.source !== "desktop-bridge" && !!input.path;
        const displayPath = showExampleStyling ? `Example: ${input.path}` : input.path;
        const sheetDisabled = !onSheetChange || input.isResolvingSheets || input.sheets.length === 0;
        const sheetDisabledReason = sheetDisabled ? getDisabledSheetReason?.(input) : undefined;
        const canCopyPath = !!input.path;

        return (
          <article key={input.role} className="input-card">
            <div className="input-card__header">
              <div className="input-card__header-text">
                <p className="input-card__label">{input.label}</p>
                <div className="input-card__path-wrap">
                  <span
                    className={`input-card__path${showExampleStyling ? " input-card__path--example" : ""}`}
                    title={input.path || undefined}
                  >
                    {displayPath}
                  </span>
                  {canCopyPath ? (
                    <button
                      type="button"
                      className={`input-card__path-copy${copied ? " input-card__path-copy--copied" : ""}`}
                      aria-label={`Copy ${input.label} path to clipboard`}
                      title={copied ? "Copied!" : "Copy path to clipboard"}
                      onClick={() => {
                        void copy(input.path);
                      }}
                    >
                      <Copy size={14} weight="regular" />
                    </button>
                  ) : null}
                </div>
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
                  disabled={sheetDisabled}
                  disabledReason={sheetDisabledReason}
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
        );
      })}
    </div>
  );
}
