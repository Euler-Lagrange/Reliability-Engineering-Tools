import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { WorkflowSelector } from "./WorkflowSelector";
import type { WorkflowOption } from "../app/types";

const workflows: WorkflowOption[] = [
  {
    id: "piece_part_generate",
    title: "Piece-Part from Grouping File",
    summary: "Generate a piece-part FMEA from a grouping workbook.",
    eyebrow: "Generate",
    badge: "A",
  },
  {
    id: "bom_only",
    title: "Piece-Part from BOM Only",
    summary: "Generate a piece-part FMEA directly from a BOM.",
    eyebrow: "Generate",
    badge: "B",
  },
];

describe("WorkflowSelector", () => {
  test("keeps button role and reflects selection via aria-pressed", () => {
    render(
      <WorkflowSelector
        workflows={workflows}
        selectedWorkflowId="piece_part_generate"
        onSelect={vi.fn()}
      />,
    );

    const selected = screen.getByRole("button", { name: /piece-part from grouping file/i });
    const other = screen.getByRole("button", { name: /piece-part from bom only/i });

    expect(selected).toHaveAttribute("aria-pressed", "true");
    expect(other).toHaveAttribute("aria-pressed", "false");
  });

  test("wraps the cards in a labelled toggle group", () => {
    render(
      <WorkflowSelector
        workflows={workflows}
        selectedWorkflowId="piece_part_generate"
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByRole("group", { name: /workflow/i })).toBeInTheDocument();
  });

  test("invokes onSelect with the workflow id on click", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <WorkflowSelector
        workflows={workflows}
        selectedWorkflowId="piece_part_generate"
        onSelect={onSelect}
      />,
    );

    await user.click(screen.getByRole("button", { name: /piece-part from bom only/i }));
    expect(onSelect).toHaveBeenCalledWith("bom_only");
  });

  test("disables every card without changing aria-pressed selection", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <WorkflowSelector
        workflows={workflows}
        selectedWorkflowId="piece_part_generate"
        onSelect={onSelect}
        disabled
      />,
    );

    const selected = screen.getByRole("button", { name: /piece-part from grouping file/i });
    const other = screen.getByRole("button", { name: /piece-part from bom only/i });

    expect(selected).toBeDisabled();
    expect(other).toBeDisabled();
    expect(selected).toHaveAttribute("aria-disabled", "true");
    expect(other).toHaveAttribute("aria-disabled", "true");
    expect(selected).toHaveAttribute("aria-pressed", "true");
    expect(other).toHaveAttribute("aria-pressed", "false");
    expect(other).toHaveAttribute(
      "title",
      "Workflow cannot be changed while this tool has an active run.",
    );

    await user.click(other);
    expect(onSelect).not.toHaveBeenCalled();
  });
});
