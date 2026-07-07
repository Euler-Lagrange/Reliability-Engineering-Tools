import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { HoldButton } from "./HoldButton";

describe("HoldButton", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // jsdom doesn't implement HTMLDialogElement's showModal / close. Stub
    // them so the keyboard-fallback path doesn't throw.
    if (!HTMLDialogElement.prototype.showModal) {
      HTMLDialogElement.prototype.showModal = function showModal() {
        this.setAttribute("open", "");
      };
    }
    if (!HTMLDialogElement.prototype.close) {
      HTMLDialogElement.prototype.close = function close() {
        this.removeAttribute("open");
      };
    }
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test("renders the label", () => {
    render(<HoldButton label="Cancel" onConfirm={() => {}} />);
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  test("fires onConfirm after the full hold duration", () => {
    const onConfirm = vi.fn();
    render(<HoldButton label="Cancel" holdMs={600} onConfirm={onConfirm} />);

    const button = screen.getByRole("button", { name: "Cancel" });
    fireEvent.pointerDown(button, { button: 0, pointerType: "mouse" });
    act(() => {
      vi.advanceTimersByTime(600);
    });

    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  test("does not fire onConfirm if released before holdMs", () => {
    const onConfirm = vi.fn();
    render(<HoldButton label="Cancel" holdMs={600} onConfirm={onConfirm} />);

    const button = screen.getByRole("button", { name: "Cancel" });
    fireEvent.pointerDown(button, { button: 0, pointerType: "mouse" });
    act(() => {
      vi.advanceTimersByTime(300);
    });
    fireEvent.pointerUp(button);
    act(() => {
      vi.advanceTimersByTime(600);
    });

    expect(onConfirm).not.toHaveBeenCalled();
  });

  test("pressing Space opens the keyboard-fallback dialog", () => {
    const onConfirm = vi.fn();
    render(<HoldButton label="Cancel" onConfirm={onConfirm} />);

    const button = screen.getByRole("button", { name: "Cancel" });
    fireEvent.keyDown(button, { key: " " });

    // The dialog becomes open and exposes explicit Confirm / Cancel buttons.
    // Space alone must NOT fire onConfirm.
    expect(onConfirm).not.toHaveBeenCalled();
    const confirmButton = screen.getByRole("button", { name: "Confirm" });
    expect(confirmButton).toBeInTheDocument();
  });

  test("does not fire onConfirm if disabled flips true during the hold", () => {
    const onConfirm = vi.fn();
    const { rerender } = render(
      <HoldButton label="Cancel" holdMs={600} onConfirm={onConfirm} />,
    );

    const button = screen.getByRole("button", { name: "Cancel" });
    fireEvent.pointerDown(button, { button: 0, pointerType: "mouse" });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    // The underlying run completes mid-hold, so the parent disables the
    // button before the hold duration elapses.
    rerender(<HoldButton label="Cancel" holdMs={600} disabled onConfirm={onConfirm} />);

    act(() => {
      vi.advanceTimersByTime(600);
    });

    expect(onConfirm).not.toHaveBeenCalled();
  });

  test("disabled prop blocks pointer interaction", () => {
    const onConfirm = vi.fn();
    render(<HoldButton label="Cancel" holdMs={200} disabled onConfirm={onConfirm} />);

    const button = screen.getByRole("button", { name: "Cancel" });
    expect(button).toBeDisabled();

    fireEvent.pointerDown(button, { button: 0, pointerType: "mouse" });
    act(() => {
      vi.advanceTimersByTime(400);
    });

    expect(onConfirm).not.toHaveBeenCalled();
  });
});
