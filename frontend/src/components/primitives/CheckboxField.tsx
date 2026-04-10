import type { ChangeEvent } from "react";

/**
 * CheckboxField — single source of truth for checkbox + label + optional hint.
 *
 * Collapses BOM Compare's dynamic loop, FailureRate's explicit blocks, and
 * RefDes's inline-styled checkbox labels into one shared component.
 *
 * The label wraps the input for proper semantic association even though we
 * also wire `htmlFor` -> `id`.
 */

export interface CheckboxFieldProps {
  id: string;
  label: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  hint?: string;
  disabled?: boolean;
}

export function CheckboxField({
  id,
  label,
  checked,
  onChange,
  hint,
  disabled = false,
}: CheckboxFieldProps) {
  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    onChange(event.target.checked);
  }

  return (
    <label className="checkbox-field" htmlFor={id}>
      <input
        id={id}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={handleChange}
      />
      <span className="checkbox-field__label">
        {label}
        {hint ? <span className="checkbox-field__hint">{hint}</span> : null}
      </span>
    </label>
  );
}
