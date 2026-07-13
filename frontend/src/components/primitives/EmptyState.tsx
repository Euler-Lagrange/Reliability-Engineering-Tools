import type { ReactNode } from "react";
import type { Icon as PhosphorIcon } from "@phosphor-icons/react";

/**
 * EmptyState — reusable onboarding / empty-result card.
 *
 * Renders a centered icon, headline, optional body copy, and up to two
 * actions (primary filled + secondary ghost). Used by every tool's
 * pristine state and by the command palette's "no matches" fallback.
 *
 * The compact variant tightens padding and shrinks the icon for inline
 * contexts (e.g. inside a `SectionCard` rather than as the main canvas).
 */

export interface EmptyStateAction {
  label: string;
  onClick: () => void;
  icon?: PhosphorIcon;
  disabled?: boolean;
  disabledReason?: string;
}

export interface EmptyStateProps {
  /** Phosphor icon component rendered above the headline. */
  icon: PhosphorIcon;
  headline: string;
  body?: ReactNode;
  primaryAction?: EmptyStateAction;
  secondaryAction?: EmptyStateAction;
  /** Compact variant uses smaller icon and padding for inline contexts. */
  compact?: boolean;
}

export function EmptyState({
  icon: Icon,
  headline,
  body,
  primaryAction,
  secondaryAction,
  compact = false,
}: EmptyStateProps) {
  const wrapperClassName = compact ? "empty-state empty-state--compact" : "empty-state";
  const iconSize = compact ? 16 : 32;
  const hasActions = Boolean(primaryAction || secondaryAction);

  return (
    <div className={wrapperClassName}>
      <div className="empty-state__icon" aria-hidden="true">
        <Icon size={iconSize} weight="regular" />
      </div>
      <h3 className="empty-state__headline">{headline}</h3>
      {body ? <p className="empty-state__body">{body}</p> : null}
      {hasActions ? (
        <div className="empty-state__actions">
          {primaryAction ? (
            <button
              type="button"
              className="empty-state__action empty-state__action--primary"
              onClick={primaryAction.onClick}
              disabled={primaryAction.disabled}
              aria-disabled={primaryAction.disabled}
              title={primaryAction.disabledReason}
            >
              {primaryAction.icon ? (
                <primaryAction.icon size={14} weight="bold" aria-hidden="true" />
              ) : null}
              {primaryAction.label}
            </button>
          ) : null}
          {secondaryAction ? (
            <button
              type="button"
              className="empty-state__action empty-state__action--secondary"
              onClick={secondaryAction.onClick}
              disabled={secondaryAction.disabled}
              aria-disabled={secondaryAction.disabled}
              title={secondaryAction.disabledReason}
            >
              {secondaryAction.icon ? (
                <secondaryAction.icon size={14} weight="bold" aria-hidden="true" />
              ) : null}
              {secondaryAction.label}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
