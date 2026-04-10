import type { ReactNode } from "react";

/**
 * ContextTabs — replaces the inline `style={{ display: "flex", gap: "0.25rem" }}`
 * pattern that appears in BOM Compare, Failure Rate and RefDes preview/run
 * tab toggles. Provides proper `role="tablist"` semantics with one
 * `<button role="tab" aria-selected>` per entry.
 */

export interface ContextTab<T extends string = string> {
  id: T;
  label: string;
  icon?: ReactNode;
}

export interface ContextTabsProps<T extends string = string> {
  tabs: ReadonlyArray<ContextTab<T>>;
  activeId: T;
  onChange: (id: T) => void;
  ariaLabel: string;
}

export function ContextTabs<T extends string = string>({
  tabs,
  activeId,
  onChange,
  ariaLabel,
}: ContextTabsProps<T>) {
  return (
    <div role="tablist" aria-label={ariaLabel} className="context-tabs">
      {tabs.map((tab) => {
        const active = tab.id === activeId;
        const className = active
          ? "context-tabs__tab is-active"
          : "context-tabs__tab";
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={active}
            className={className}
            onClick={() => onChange(tab.id)}
          >
            {tab.icon}
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
