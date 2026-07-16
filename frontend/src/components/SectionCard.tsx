import type { ReactNode } from "react";

/**
 * SectionCard variant — surface hierarchy per design handoff principle B.
 *
 * - "outlined"  (default) — bordered, surface background. Primary step / choice.
 * - "divided"   — top border only, transparent bg, inline padding zero.
 *                 Use for supporting sections that should feel lighter than
 *                 primaries (options rows, preview panels).
 * - "bare"      — no border, no background, no inline padding. Use for
 *                 free-flow content that just needs the title block.
 */
export type SectionCardVariant = "outlined" | "divided" | "bare";

interface SectionCardProps {
  title: string;
  eyebrow?: string;
  description?: string;
  actions?: ReactNode;
  className?: string;
  variant?: SectionCardVariant;
  /**
   * Workflow-spine position marker (1-based). Extends the InputGrid
   * step-indicator language to section level so each tool page reads as
   * a scannable 1-2-3 flow. Decorative (aria-hidden) — accessible names
   * are unaffected.
   */
  step?: number;
  children: ReactNode;
}

export function SectionCard({
  title,
  eyebrow,
  description,
  actions,
  className,
  variant = "outlined",
  step,
  children,
}: SectionCardProps) {
  const classes = ["section-card", `section-card--${variant}`];
  if (className) classes.push(className);
  return (
    <section className={classes.join(" ")}>
      <header className="section-card__header">
        {typeof step === "number" ? (
          <span className="section-card__step" aria-hidden="true">
            {String(step).padStart(2, "0")}
          </span>
        ) : null}
        <div className="section-card__heading">
          {eyebrow ? <p className="section-card__eyebrow">{eyebrow}</p> : null}
          <h2>{title}</h2>
          {description ? <p className="section-card__description">{description}</p> : null}
        </div>
        {actions ? <div className="section-card__actions">{actions}</div> : null}
      </header>
      {children}
    </section>
  );
}
