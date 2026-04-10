import type { ReactNode } from "react";

/**
 * OptionsField — labeled wrapper for any form control.
 *
 * Replaces the divergent `setup-block` ad-hoc patterns across tools. Renders
 * an eyebrow label, the control children slot, an optional hint and an
 * optional muted "disabled reason" caption. Pure layout — does not impose any
 * input semantics.
 */

export interface OptionsFieldProps {
  label: string;
  hint?: string;
  required?: boolean;
  disabledReason?: string;
  htmlFor?: string;
  children: ReactNode;
}

export function OptionsField({
  label,
  hint,
  required = false,
  disabledReason,
  htmlFor,
  children,
}: OptionsFieldProps) {
  return (
    <div className="options-field">
      <label className="options-field__label" htmlFor={htmlFor}>
        {label}
        {required ? <span aria-hidden="true"> *</span> : null}
      </label>
      {children}
      {hint ? <p className="options-field__hint">{hint}</p> : null}
      {disabledReason ? (
        <p className="options-field__disabled-reason">{disabledReason}</p>
      ) : null}
    </div>
  );
}
