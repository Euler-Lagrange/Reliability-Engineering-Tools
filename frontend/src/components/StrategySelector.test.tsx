import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { StrategySelector } from "./StrategySelector";
import type { OutputStrategy } from "../app/types";

const strategies: OutputStrategy[] = [
  {
    id: "new_workbook_standard",
    title: "New Workbook",
    summary: "Write a brand-new formatted workbook.",
    badge: "New workbook",
  },
  {
    id: "existing_workbook_preserve_formatting",
    title: "Existing Workbook (Preserve Formatting)",
    summary: "Append into an existing workbook, keeping its formatting.",
    badge: "Preserve formatting",
  },
];

describe("StrategySelector", () => {
  test("keeps button role and reflects selection via aria-pressed", () => {
    render(
      <StrategySelector
        strategies={strategies}
        selectedStrategyId="new_workbook_standard"
        onSelect={vi.fn()}
      />,
    );

    const selected = screen.getByRole("button", { name: /new workbook/i });
    const other = screen.getByRole("button", { name: /existing workbook \(preserve formatting\)/i });

    expect(selected).toHaveAttribute("aria-pressed", "true");
    expect(other).toHaveAttribute("aria-pressed", "false");
  });

  test("wraps the cards in a labelled toggle group", () => {
    render(
      <StrategySelector
        strategies={strategies}
        selectedStrategyId="new_workbook_standard"
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByRole("group", { name: /output strategy/i })).toBeInTheDocument();
  });

  test("invokes onSelect with the strategy id on click", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <StrategySelector
        strategies={strategies}
        selectedStrategyId="new_workbook_standard"
        onSelect={onSelect}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: /existing workbook \(preserve formatting\)/i }),
    );
    expect(onSelect).toHaveBeenCalledWith("existing_workbook_preserve_formatting");
  });
});
