import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { MagnifyingGlass, type Icon as PhosphorIcon } from "@phosphor-icons/react";
import { useEscapeLayer } from "../../shared/hooks/useEscapeLayer";
import { EmptyState } from "./EmptyState";

/**
 * CommandPalette — Ctrl+K / Cmd+K global command launcher.
 *
 * A modal overlay (rendered in-place with `position: fixed`) that presents
 * a flat action list, groups by `category`, and filters by a case-
 * insensitive substring match on `label + category + hint`. Arrow keys
 * navigate results, Enter activates the highlighted action, Esc closes the
 * palette, and a backdrop click also closes it.
 *
 * The palette is a controlled component: parents manage `open` via state
 * and a global keyboard shortcut (see `App.tsx`). When no actions match
 * the current query the empty-state falls back to the Phase 3 `EmptyState`
 * primitive in compact form.
 */

export interface CommandPaletteAction {
  id: string;
  label: string;
  /** Optional supporting copy shown next to the label. */
  hint?: string;
  /** Groups actions under a sticky eyebrow heading. */
  category?: string;
  icon?: PhosphorIcon;
  /** Keyboard hint rendered on the right side of the row. */
  shortcut?: string;
  onSelect: () => void;
}

export interface CommandPaletteProps {
  actions: ReadonlyArray<CommandPaletteAction>;
  open: boolean;
  onClose: () => void;
}

interface GroupedActions {
  category: string;
  actions: CommandPaletteAction[];
}

function groupActions(actions: CommandPaletteAction[]): GroupedActions[] {
  const groups = new Map<string, CommandPaletteAction[]>();
  for (const action of actions) {
    const category = action.category ?? "Actions";
    const bucket = groups.get(category) ?? [];
    bucket.push(action);
    groups.set(category, bucket);
  }
  return Array.from(groups.entries()).map(([category, list]) => ({
    category,
    actions: list,
  }));
}

function matchesQuery(action: CommandPaletteAction, query: string): boolean {
  if (!query) {
    return true;
  }
  const haystack = `${action.label} ${action.category ?? ""} ${action.hint ?? ""}`.toLowerCase();
  return haystack.includes(query);
}

export function CommandPalette({ actions, open, onClose }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  // Stable base id for the results listbox + its option rows, so the search
  // input can advertise a combobox relationship (aria-controls) and point
  // `aria-activedescendant` at the highlighted option.
  const listboxId = useId();
  const optionId = useCallback(
    (indexInFlat: number) => `${listboxId}-option-${indexInFlat}`,
    [listboxId],
  );
  const inputRef = useRef<HTMLInputElement>(null);
  const backdropRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  // Element that had focus when the palette opened; we restore focus here
  // on close to preserve keyboard navigation flow (WCAG 2.4.3).
  const returnFocusRef = useRef<HTMLElement | null>(null);

  const filteredActions = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return actions.filter((action) => matchesQuery(action, needle));
  }, [actions, query]);

  const groupedActions = useMemo(() => groupActions(filteredActions.slice()), [filteredActions]);

  // Reset state when the palette opens / restore focus on close.
  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIndex(0);
      // Capture the element that had focus before we opened, so we can
      // return it on close. Guard against the palette itself being the
      // active element in dev double-renders.
      const active = document.activeElement;
      returnFocusRef.current =
        active instanceof HTMLElement && active !== inputRef.current
          ? active
          : returnFocusRef.current;
      const handle = window.setTimeout(() => {
        inputRef.current?.focus();
      }, 0);
      return () => window.clearTimeout(handle);
    }
    // Closed: restore focus.
    const returnTo = returnFocusRef.current;
    returnFocusRef.current = null;
    if (returnTo && typeof returnTo.focus === "function") {
      try {
        returnTo.focus();
      } catch {
        /* ignore */
      }
    }
    return undefined;
  }, [open]);

  // Keep activeIndex in bounds when the filter narrows.
  useEffect(() => {
    if (activeIndex >= filteredActions.length) {
      setActiveIndex(filteredActions.length === 0 ? 0 : filteredActions.length - 1);
    }
  }, [activeIndex, filteredActions.length]);

  const activateAction = useCallback(
    (action: CommandPaletteAction) => {
      action.onSelect();
      onClose();
    },
    [onClose],
  );

  // Escape closes the palette through the shared dismiss-stack so it only ever
  // dismisses the top-most layer (see useEscapeLayer). Tab / Arrow / Enter stay
  // local to the dialog's own keydown handler below.
  useEscapeLayer(open, onClose);

  const handleKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLDivElement>) => {
      // Focus trap: Tab inside the palette cycles between focusable
      // descendants without escaping to the shell behind the overlay.
      if (event.key === "Tab") {
        const container = dialogRef.current;
        if (!container) return;
        const focusables = Array.from(
          container.querySelectorAll<HTMLElement>(
            'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
          ),
        ).filter((el) => !el.hasAttribute("aria-hidden"));
        if (focusables.length === 0) {
          event.preventDefault();
          return;
        }
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const current = document.activeElement as HTMLElement | null;
        if (event.shiftKey) {
          if (current === first || !container.contains(current)) {
            event.preventDefault();
            last.focus();
          }
        } else {
          if (current === last || !container.contains(current)) {
            event.preventDefault();
            first.focus();
          }
        }
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActiveIndex((prev) => {
          if (filteredActions.length === 0) {
            return 0;
          }
          return (prev + 1) % filteredActions.length;
        });
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setActiveIndex((prev) => {
          if (filteredActions.length === 0) {
            return 0;
          }
          return (prev - 1 + filteredActions.length) % filteredActions.length;
        });
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        const target = filteredActions[activeIndex];
        if (target) {
          activateAction(target);
        }
      }
    },
    [activateAction, activeIndex, filteredActions],
  );

  const handleBackdropClick = useCallback(
    (event: ReactMouseEvent<HTMLDivElement>) => {
      if (event.target === backdropRef.current) {
        onClose();
      }
    },
    [onClose],
  );

  if (!open) {
    return null;
  }

  // Map each grouped action back to its index in `filteredActions` so the
  // active-row highlight and Enter-key activation share one source of
  // truth.
  let cursor = 0;
  // Only advertise an active descendant when a real option is highlighted;
  // an empty result set must leave the attribute absent (WAI-ARIA combobox
  // pattern) so assistive tech doesn't reference a non-existent id.
  const activeOptionId =
    filteredActions.length > 0 && activeIndex < filteredActions.length
      ? optionId(activeIndex)
      : undefined;
  return (
    <div
      ref={backdropRef}
      className="command-palette-backdrop"
      role="presentation"
      onClick={handleBackdropClick}
      onKeyDown={handleKeyDown}
    >
      <div
        ref={dialogRef}
        className="command-palette"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
      >
        <div className="command-palette__search">
          <MagnifyingGlass
            size={16}
            weight="regular"
            className="command-palette__search-icon"
            aria-hidden="true"
          />
          <input
            ref={inputRef}
            type="text"
            className="command-palette__input"
            placeholder="Search tools, themes, and actions…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Search command palette"
            role="combobox"
            aria-expanded="true"
            aria-controls={listboxId}
            aria-autocomplete="list"
            aria-activedescendant={activeOptionId}
          />
        </div>
        <div
          id={listboxId}
          className="command-palette__results"
          role="listbox"
          aria-label="Command palette results"
        >
          {filteredActions.length === 0 ? (
            <div className="command-palette__empty">
              <EmptyState
                icon={MagnifyingGlass}
                headline="No matches"
                body="Try a different search term."
                compact
              />
            </div>
          ) : (
            groupedActions.map((group) => (
              <div key={group.category}>
                <p className="command-palette__category">{group.category}</p>
                {group.actions.map((action) => {
                  const indexInFlat = cursor;
                  cursor += 1;
                  const isActive = indexInFlat === activeIndex;
                  const className = isActive
                    ? "command-palette__action is-active"
                    : "command-palette__action";
                  const Icon = action.icon;
                  return (
                    <button
                      key={action.id}
                      id={optionId(indexInFlat)}
                      type="button"
                      className={className}
                      role="option"
                      aria-selected={isActive}
                      onMouseEnter={() => setActiveIndex(indexInFlat)}
                      onClick={() => activateAction(action)}
                    >
                      {Icon ? (
                        <Icon
                          size={16}
                          weight={isActive ? "bold" : "regular"}
                          className="command-palette__action-icon"
                          aria-hidden="true"
                        />
                      ) : null}
                      <span className="command-palette__action-label">{action.label}</span>
                      {action.shortcut ? (
                        <span className="command-palette__action-shortcut">{action.shortcut}</span>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
