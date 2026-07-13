import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { FileText } from "@phosphor-icons/react";
import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  test("renders headline and body", () => {
    render(
      <EmptyState
        icon={FileText}
        headline="Start a new run"
        body="Browse for a workbook to begin."
      />,
    );
    expect(screen.getByRole("heading", { name: "Start a new run" })).toBeInTheDocument();
    expect(screen.getByText("Browse for a workbook to begin.")).toBeInTheDocument();
  });

  test("renders the primary action and fires onClick", () => {
    const primary = vi.fn();
    render(
      <EmptyState
        icon={FileText}
        headline="Start"
        primaryAction={{ label: "Browse", onClick: primary }}
      />,
    );
    const button = screen.getByRole("button", { name: "Browse" });
    fireEvent.click(button);
    expect(primary).toHaveBeenCalledTimes(1);
  });

  test("renders the secondary action and fires onClick", () => {
    const secondary = vi.fn();
    render(
      <EmptyState
        icon={FileText}
        headline="Start"
        secondaryAction={{ label: "Load example", onClick: secondary }}
      />,
    );
    const button = screen.getByRole("button", { name: "Load example" });
    fireEvent.click(button);
    expect(secondary).toHaveBeenCalledTimes(1);
  });

  test("disables an action and exposes its reason as a title hint", () => {
    const primary = vi.fn();
    const reason = "File inspection is paused while a run is active.";
    render(
      <EmptyState
        icon={FileText}
        headline="Start"
        primaryAction={{
          label: "Browse",
          onClick: primary,
          disabled: true,
          disabledReason: reason,
        }}
      />,
    );

    const button = screen.getByRole("button", { name: "Browse" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAttribute("title", reason);
    fireEvent.click(button);
    expect(primary).not.toHaveBeenCalled();
  });

  test("compact variant applies the modifier class", () => {
    const { container } = render(
      <EmptyState icon={FileText} headline="Compact" compact />,
    );
    const wrapper = container.querySelector(".empty-state");
    expect(wrapper).not.toBeNull();
    expect(wrapper?.classList.contains("empty-state--compact")).toBe(true);
  });

  test("renders an icon node above the headline", () => {
    const { container } = render(
      <EmptyState icon={FileText} headline="Has icon" />,
    );
    const iconWrap = container.querySelector(".empty-state__icon");
    expect(iconWrap).not.toBeNull();
    // The Phosphor component renders an inline svg.
    expect(iconWrap?.querySelector("svg")).not.toBeNull();
  });
});
