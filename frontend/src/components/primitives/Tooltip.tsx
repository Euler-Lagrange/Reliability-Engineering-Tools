import type { ReactNode } from "react";
import * as RadixTooltip from "@radix-ui/react-tooltip";

/**
 * Styled hover/focus tooltip for ⓘ info affordances.
 *
 * Replaces native `title` tooltips on the option info icons — native
 * titles appear after a ~1.5s OS delay, cannot be styled, and never
 * show for keyboard users. Radix handles hover + focus triggers,
 * Escape dismissal, and portal positioning; the surface reuses the
 * floating-layer recipe (`--shadow-popover`, `--line-strong` border)
 * shared with the select menu and command palette.
 *
 * The child is the trigger (rendered via `asChild`) — pass a focusable
 * element (e.g. a `<button type="button">`) so keyboard users can reach
 * the tooltip.
 */
export function Tooltip({
  content,
  children,
}: {
  content: string;
  children: ReactNode;
}) {
  return (
    <RadixTooltip.Provider delayDuration={150} skipDelayDuration={300}>
      <RadixTooltip.Root>
        <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
        <RadixTooltip.Portal>
          <RadixTooltip.Content
            className="tooltip-content"
            sideOffset={6}
            collisionPadding={8}
          >
            {content}
          </RadixTooltip.Content>
        </RadixTooltip.Portal>
      </RadixTooltip.Root>
    </RadixTooltip.Provider>
  );
}
