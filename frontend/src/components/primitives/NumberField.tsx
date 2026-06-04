import type { ChangeEvent } from "react";

/**
 * NumberField — labeled controlled numeric input.
 *
 * Mirrors `CheckboxField`'s standalone-in-grid API ({ id, label, value,
 * onChange, hint?, disabled? }) plus numeric `min`/`max`/`step`. The label is
 * wired to the input via `htmlFor` -> `id` for semantic association.
 *
 * Input sanitisation is intentionally minimal: an empty / non-numeric entry is
 * a NaN, which we swallow (keep the previous value) so the parent never has to
 * store `NaN` in its options. Values below `min` are clamped up to `min`. The
 * backend clamps defensively too, so we do not do aggressive on-blur rewriting.
 */

export interface NumberFieldProps {
  id: string;
  label: string;
  value: number;
  onChange: (next: number) => void;
  min?: number;
  max?: number;
  step?: number;
  hint?: string;
  disabled?: boolean;
}

export function NumberField({
  id,
  label,
  value,
  onChange,
  min,
  max,
  step,
  hint,
  disabled = false,
}: NumberFieldProps) {
  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    const parsed = event.target.valueAsNumber;
    // NaN guard: empty or non-numeric input keeps the previous value so the
    // parent never persists NaN (which would serialise to null in the run
    // request and trip the backend's int()/float() coercion).
    if (Number.isNaN(parsed)) {
      return;
    }
    if (min !== undefined && parsed < min) {
      onChange(min);
      return;
    }
    onChange(parsed);
  }

  return (
    <div className="number-field">
      <label className="number-field__label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        type="number"
        className="number-field__input"
        value={value}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={handleChange}
      />
      {hint ? <p className="number-field__hint">{hint}</p> : null}
    </div>
  );
}
