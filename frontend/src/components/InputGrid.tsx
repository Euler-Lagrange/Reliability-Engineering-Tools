import { Copy } from "@phosphor-icons/react";
import type { FileRole, InputFileState } from "../app/types";
import { useCopyToClipboard } from "../shared/hooks/useCopyToClipboard";
import { CustomSelect } from "./CustomSelect";

interface InputGridProps {
  inputs: InputFileState[];
  onBrowse?: (role: FileRole) => void;
  onSheetChange?: (role: FileRole, sheet: string) => void;
  /** When present, all file-inspection controls are disabled with this hint. */
  browseDisabledReason?: string;
  /**
   * Optional per-input disabled reason for the sheet picker. Returning a
   * string surfaces a muted caption under the disabled select and wires
   * `aria-describedby` so screen readers announce why the control is inert.
   * Returning `undefined` falls back to the select's default disabled
   * behaviour.
   */
  getDisabledSheetReason?: (input: InputFileState) => string | undefined;
}

type InputCardState = "pending" | "active" | "loaded";

export const FILE_INSPECTION_PAUSED_REASON =
  "File inspection is paused while a run is active.";

/**
 * Per-card copy-to-clipboard button. Each instance owns its own
 * `useCopyToClipboard()` hook so the transient "Copied!" affordance is
 * scoped to the card the user actually clicked — a single shared hook at
 * the grid level flipped every card's button at once.
 */
function CopyPathButton({ path, label }: { path: string; label: string }) {
  const { copy, copied } = useCopyToClipboard();
  return (
    <button
      type="button"
      className={`input-card__path-copy${copied ? " input-card__path-copy--copied" : ""}`}
      aria-label={`Copy ${label} path to clipboard`}
      title={copied ? "Copied!" : "Copy path to clipboard"}
      onClick={() => {
        void copy(path);
      }}
    >
      <Copy size={14} weight="regular" />
    </button>
  );
}

/**
 * Design handoff principle J (stepper) — classify each input card so CSS can
 * collapse unstarted and completed rows while the single actionable card
 * stays fully expanded. The first card without a path is the "active" step;
 * later unstarted cards read as "pending" and fully-loaded cards read as
 * "loaded". Tests continue to query these cards by role/label, so every
 * control stays in the DOM regardless of state.
 */
function classifyInputStates(inputs: InputFileState[]): InputCardState[] {
  let activeClaimed = false;
  return inputs.map((input) => {
    const hasPath = !!input.path;
    const ready =
      hasPath &&
      input.status === "ready" &&
      !input.isResolvingSheets &&
      !input.isAnalyzing;
    if (ready) return "loaded";
    if (!hasPath && !activeClaimed) {
      activeClaimed = true;
      return "active";
    }
    if (!hasPath) return "pending";
    // Has a path but is resolving / attention / optional — treat as the
    // active card if nothing has claimed it yet; otherwise leave pending.
    if (!activeClaimed) {
      activeClaimed = true;
      return "active";
    }
    return "pending";
  });
}

export function InputGrid({
  inputs,
  onBrowse,
  onSheetChange,
  browseDisabledReason,
  getDisabledSheetReason,
}: InputGridProps) {
  const states = classifyInputStates(inputs);

  return (
    <div className="input-grid">
      {inputs.map((input, index) => {
        const showExampleStyling =
          !!input.isExample && input.source !== "desktop-bridge" && !!input.path;
        const displayPath = showExampleStyling ? `Example: ${input.path}` : input.path;
        const inspectionPaused = !!browseDisabledReason;
        const sheetDisabled =
          inspectionPaused || !onSheetChange || input.isResolvingSheets || input.sheets.length === 0;
        const sheetDisabledReason = inspectionPaused
          ? browseDisabledReason
          : sheetDisabled
            ? getDisabledSheetReason?.(input)
            : undefined;
        const canCopyPath = !!input.path;
        const state = states[index];

        return (
          <article
            key={input.role}
            className="input-card"
            data-state={state}
            data-step={index + 1}
          >
            {/* v2 N6: the leading indicator carries the stepper — hollow
                ring = pending, accent ring + dot = active step, green ✓ =
                loaded. Text never dims (the v1 opacity fade dropped rows
                below AA). Tooltip carries the tag ("Loaded") that used to
                render as a chip. */}
            <span className="input-card__indicator" title={input.tag || undefined} aria-hidden="true">
              {state === "loaded" ? "✓" : ""}
            </span>
            <p className="input-card__label" title={input.helper || undefined}>
              <span className="input-card__label-text">{input.label}</span>
              {input.required ? (
                <span
                  className="input-card__required"
                  title="Required — the run is blocked until this file is loaded."
                >
                  {" "}
                  *
                </span>
              ) : null}
            </p>
            <div className="input-card__path-wrap">
              {canCopyPath ? (
                <>
                  <span
                    className={`input-card__path${showExampleStyling ? " input-card__path--example" : ""}`}
                    title={input.path || undefined}
                  >
                    {displayPath}
                  </span>
                  <CopyPathButton path={input.path} label={input.label} />
                </>
              ) : (
                <span className="input-card__path input-card__path--empty">No file selected</span>
              )}
            </div>
            <div className="sheet-picker">
              <label>Sheet</label>
              <CustomSelect
                label={`${input.label} sheet`}
                value={input.selectedSheet}
                options={input.sheets.map((sheet) => ({ value: sheet.label, label: sheet.label }))}
                disabled={sheetDisabled}
                disabledReason={sheetDisabledReason}
                variant="quiet"
                onChange={(sheet) => onSheetChange?.(input.role, sheet)}
              />
            </div>
            <button
              type="button"
              className="ghost-button ghost-button--sm"
              onClick={() => onBrowse?.(input.role)}
              disabled={inspectionPaused || !onBrowse || input.isResolvingSheets || input.isAnalyzing}
              title={browseDisabledReason}
            >
              {input.isResolvingSheets ? "Loading..." : input.isAnalyzing ? "Analyzing..." : "Browse"}
            </button>
            {input.resolutionError ? (
              <p className="input-card__note input-card__note--danger">{input.resolutionError}</p>
            ) : null}
            {!input.resolutionError && input.isAnalyzing ? (
              <p className="input-card__note">Inspecting the selected sheet through the desktop backend bridge.</p>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}
