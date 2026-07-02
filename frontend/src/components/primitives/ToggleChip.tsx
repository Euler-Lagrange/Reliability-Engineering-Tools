import type { ReactNode } from "react";

/**
 * ToggleChip — shared single-select radio chip group primitive.
 *
 * Extracted from the FMEA failure-modes selector (the project's gold-standard
 * `role="radiogroup"` + `aria-checked` pattern). Renders a `radiogroup`
 * wrapper and a `<button role="radio">` per option. The visual styling reuses
 * the existing `.toggle-chip` base class plus the `.toggle-chip-group`
 * namespace classes added in `theme/styles.css`.
 *
 * Selection state: each chip carries `data-selected` (matched by the
 * project-wide `.toggle-chip[data-selected="true"]` rule) and the
 * `is-selected` modifier class. New consumers can rely on either selector.
 */

export interface ToggleChipOption<T extends string = string> {
  value: T;
  label: ReactNode;
  hint?: string;
  disabled?: boolean;
}

export interface ToggleChipProps<T extends string = string> {
  options: ReadonlyArray<ToggleChipOption<T>>;
  value: T;
  onChange: (next: T) => void;
  ariaLabel: string;
  disabled?: boolean;
}

export function ToggleChip<T extends string = string>({
  options,
  value,
  onChange,
  ariaLabel,
  disabled = false,
}: ToggleChipProps<T>) {
  function handleSelect(option: ToggleChipOption<T>) {
    if (disabled || option.disabled) {
      return;
    }
    onChange(option.value);
  }

  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className="toggle-chip-group"
      aria-disabled={disabled || undefined}
    >
      {options.map((option) => {
        const selected = value === option.value;
        const optionDisabled = disabled || option.disabled === true;
        const className = selected
          ? "toggle-chip is-selected"
          : "toggle-chip";
        return (
          <button
            key={option.value}
            type="button"
            className={className}
            role="radio"
            aria-checked={selected}
            data-selected={selected}
            data-value={option.value}
            disabled={optionDisabled}
            title={option.hint}
            onClick={() => handleSelect(option)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
