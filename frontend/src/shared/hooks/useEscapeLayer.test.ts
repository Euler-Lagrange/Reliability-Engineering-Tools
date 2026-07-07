import { createElement, Fragment, type ReactNode } from "react";
import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useEscapeLayer } from "./useEscapeLayer";

/**
 * Minimal harness: a component that registers one dismiss layer while
 * `active` is true. We render several of these to exercise the shared
 * top-of-stack dismissal behavior.
 */
function Layer({ active, onDismiss }: { active: boolean; onDismiss: () => void }): null {
  useEscapeLayer(active, onDismiss);
  return null;
}

function pressEscape() {
  fireEvent.keyDown(window, { key: "Escape" });
}

describe("useEscapeLayer", () => {
  it("dismisses only the most recently registered (top) layer per Escape", () => {
    const outer = vi.fn();
    const inner = vi.fn();

    render(
      createElement(
        Fragment,
        null,
        createElement(Layer, { active: true, onDismiss: outer }),
        createElement(Layer, { active: true, onDismiss: inner }),
      ) as ReactNode,
    );

    pressEscape();

    // The last-registered layer is the top of the stack.
    expect(inner).toHaveBeenCalledTimes(1);
    expect(outer).not.toHaveBeenCalled();
  });

  it("unregisters a layer on unmount so Escape falls through to the layer below", () => {
    const outer = vi.fn();
    const inner = vi.fn();

    function Harness({ innerActive }: { innerActive: boolean }) {
      return createElement(
        Fragment,
        null,
        createElement(Layer, { active: true, onDismiss: outer }),
        innerActive ? createElement(Layer, { active: true, onDismiss: inner }) : null,
      );
    }

    const { rerender } = render(createElement(Harness, { innerActive: true }));

    // First Escape hits the inner (top) layer.
    pressEscape();
    expect(inner).toHaveBeenCalledTimes(1);
    expect(outer).not.toHaveBeenCalled();

    // Unmount the inner layer; it must unregister.
    rerender(createElement(Harness, { innerActive: false }));

    // Now the outer layer is on top and receives the Escape.
    pressEscape();
    expect(inner).toHaveBeenCalledTimes(1);
    expect(outer).toHaveBeenCalledTimes(1);
  });

  it("does nothing when no layer is active", () => {
    const dismiss = vi.fn();
    render(createElement(Layer, { active: false, onDismiss: dismiss }));
    pressEscape();
    expect(dismiss).not.toHaveBeenCalled();
  });

  it("only reacts to the Escape key", () => {
    const dismiss = vi.fn();
    render(createElement(Layer, { active: true, onDismiss: dismiss }));
    fireEvent.keyDown(window, { key: "Enter" });
    fireEvent.keyDown(window, { key: "a" });
    expect(dismiss).not.toHaveBeenCalled();
  });
});
