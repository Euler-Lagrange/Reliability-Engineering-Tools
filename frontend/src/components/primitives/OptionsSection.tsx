import type { ReactNode } from "react";
import { SectionCard } from "../SectionCard";

/**
 * OptionsSection — thin composition of `SectionCard` + a vertical grid for
 * `OptionsField` and `CheckboxField` children. Every tool's "Options" block
 * routes through this so spacing and structure stay consistent.
 */

export interface OptionsSectionProps {
  title: string;
  description?: string;
  eyebrow?: string;
  actions?: ReactNode;
  children: ReactNode;
}

export function OptionsSection({
  title,
  description,
  eyebrow,
  actions,
  children,
}: OptionsSectionProps) {
  return (
    <SectionCard
      title={title}
      eyebrow={eyebrow}
      description={description}
      actions={actions}
    >
      <div className="options-section__grid">{children}</div>
    </SectionCard>
  );
}
