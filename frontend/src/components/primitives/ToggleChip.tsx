import type { ReactNode } from "react";

/**
 * ToggleChip — shared radio/checkbox chip group primitive.
 *
 * Extracted from the FMEA failure-modes selector (the project's gold-standard
 * `role="radiogroup"` + `aria-checked` pattern). Renders a wrapper with the
 * appropriate ARIA role and a `<button>` per option with the matching child
 * role. The visual styling reuses the existing `.toggle-chip` base class plus
 * the new `.toggle-chip-group` namespace classes added in `theme/styles.css`.
 *
 * Backwards-compat: each chip carries BOTH `data-active="true"` (matched by
 * the existing project-wide `.toggle-chip[data-active="true"]` rule) and the
 * `is-selected` modifier class. New consumers can rely on either selector.
 */

export type ToggleChipMode = "radio" | "checkbox";

export interface ToggleChipOption<T extends string = string> {
  value: T;
  label: ReactNode;
  hint?: string;
  disabled?: boolean;
}

export interface ToggleChipProps<T extends string = string> {
  options: ReadonlyArray<ToggleChipOption<T>>;
  value: T | T[];
  onChange: (next: T | T[]) => void;
  mode?: ToggleChipMode;
  ariaLabel: string;
  name?: string;
  disabled?: boolean;
}

function isSelected<T extends string>(value: T | T[], optionValue: T): boolean {
  if (Array.isArray(value)) {
    return value.includes(optionValue);
  }
  return value === optionValue;
}

export function ToggleChip<T extends string = string>({
  options,
  value,
  onChange,
  mode = "radio",
  ariaLabel,
  name,
  disabled = false,
}: ToggleChipProps<T>) {
  const groupRole = mode === "radio" ? "radiogroup" : "group";
  const itemRole = mode === "radio" ? "radio" : "checkbox";

  function handleSelect(option: ToggleChipOption<T>) {
    if (disabled || option.disabled) {
      return;
    }
    if (mode === "radio") {
      onChange(option.value);
      return;
    }
    const current = Array.isArray(value) ? value : [];
    if (current.includes(option.value)) {
      onChange(current.filter((entry) => entry !== option.value));
    } else {
      onChange([...current, option.value]);
    }
  }

  return (
    <div
      role={groupRole}
      aria-label={ariaLabel}
      className="toggle-chip-group"
      aria-disabled={disabled || undefined}
    >
      {options.map((option) => {
        const selected = isSelected(value, option.value);
        const optionDisabled = disabled || option.disabled === true;
        const className = selected
          ? "toggle-chip is-selected"
          : "toggle-chip";
        return (
          <button
            key={option.value}
            type="button"
            className={className}
            role={itemRole}
            aria-checked={selected}
            data-active={selected}
            data-selected={selected}
            data-value={option.value}
            disabled={optionDisabled}
            name={name}
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
