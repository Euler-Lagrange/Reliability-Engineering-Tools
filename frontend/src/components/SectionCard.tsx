import type { ReactNode } from "react";

interface SectionCardProps {
  title: string;
  eyebrow?: string;
  description?: string;
  actions?: ReactNode;
  className?: string;
  children: ReactNode;
}

export function SectionCard({
  title,
  eyebrow,
  description,
  actions,
  className,
  children,
}: SectionCardProps) {
  return (
    <section className={className ? `section-card ${className}` : "section-card"}>
      <header className="section-card__header">
        <div>
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
