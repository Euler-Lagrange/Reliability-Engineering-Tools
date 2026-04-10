import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GlobalLogPanel } from "./GlobalLogPanel";
import { useGlobalLogStore } from "../stores/globalLogStore";

// Phase B2: verify the resizable log panel drag handle, localStorage
// persistence, and keyboard resize controls.
//
// The panel is collapsed by default (isVisible = false), so each test
// first flips the store to visible before querying the handle.

const STORAGE_KEY = "reliability-tools.log-panel-height";

beforeEach(() => {
  window.localStorage.clear();
  // Reset the global log store to a known state: visible, no entries.
  useGlobalLogStore.setState({
    entries: [],
    totalAppended: 0,
    truncatedCount: 0,
    isVisible: true,
    filterMode: "all",
  });
});

afterEach(() => {
  window.localStorage.clear();
});

function readHandleAriaValueNow(): number {
  const handle = screen.getByRole("separator", { name: /resize log panel/i });
  const value = handle.getAttribute("aria-valuenow");
  if (!value) {
    throw new Error("resize handle has no aria-valuenow");
  }
  return Number.parseInt(value, 10);
}

describe("GlobalLogPanel resize handle", () => {
  it("initialises the panel height from localStorage when a stored value is present", () => {
    window.localStorage.setItem(STORAGE_KEY, "360");

    render(<GlobalLogPanel />);

    expect(readHandleAriaValueNow()).toBe(360);
  });

  it("defaults the panel height to 240 when localStorage is empty", () => {
    render(<GlobalLogPanel />);

    expect(readHandleAriaValueNow()).toBe(240);
  });

  it("clamps a persisted value below the minimum back up to the minimum", () => {
    window.localStorage.setItem(STORAGE_KEY, "40");

    render(<GlobalLogPanel />);

    expect(readHandleAriaValueNow()).toBe(120);
  });

  it("clamps a persisted value above the maximum back down to the maximum", () => {
    // Fix F2: the clamp is now viewport-aware so the upper bound is
    // min(LOG_PANEL_HEIGHT_MAX, window.innerHeight - 200). Force a
    // window tall enough that the static 640 ceiling wins.
    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: 1080,
    });
    window.localStorage.setItem(STORAGE_KEY, "9999");

    render(<GlobalLogPanel />);

    expect(readHandleAriaValueNow()).toBe(640);
  });

  it("falls back to the default when the persisted value is not an integer", () => {
    window.localStorage.setItem(STORAGE_KEY, "not-a-number");

    render(<GlobalLogPanel />);

    expect(readHandleAriaValueNow()).toBe(240);
  });

  it("ArrowUp increases the panel height by the keyboard step and persists it", () => {
    render(<GlobalLogPanel />);
    const handle = screen.getByRole("separator", { name: /resize log panel/i });

    act(() => {
      fireEvent.keyDown(handle, { key: "ArrowUp" });
    });

    expect(readHandleAriaValueNow()).toBe(280); // 240 + 40
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("280");
  });

  it("ArrowDown decreases the panel height by the keyboard step and persists it", () => {
    render(<GlobalLogPanel />);
    const handle = screen.getByRole("separator", { name: /resize log panel/i });

    act(() => {
      fireEvent.keyDown(handle, { key: "ArrowDown" });
    });

    expect(readHandleAriaValueNow()).toBe(200); // 240 - 40
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("200");
  });

  it("ArrowDown clamps at the minimum and does not persist a sub-minimum value", () => {
    window.localStorage.setItem(STORAGE_KEY, "120");

    render(<GlobalLogPanel />);
    const handle = screen.getByRole("separator", { name: /resize log panel/i });

    act(() => {
      fireEvent.keyDown(handle, { key: "ArrowDown" });
    });

    expect(readHandleAriaValueNow()).toBe(120);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("120");
  });

  it("ArrowUp clamps at the maximum and does not persist a supra-maximum value", () => {
    // Fix F2: needs a tall viewport so the static 640 ceiling wins
    // over the viewport-aware clamp (window.innerHeight - 200).
    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: 1080,
    });
    window.localStorage.setItem(STORAGE_KEY, "640");

    render(<GlobalLogPanel />);
    const handle = screen.getByRole("separator", { name: /resize log panel/i });

    act(() => {
      fireEvent.keyDown(handle, { key: "ArrowUp" });
    });

    expect(readHandleAriaValueNow()).toBe(640);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("640");
  });

  it("does not render the resize handle when the panel is collapsed", () => {
    useGlobalLogStore.setState({ isVisible: false });

    render(<GlobalLogPanel />);

    expect(screen.queryByRole("separator", { name: /resize log panel/i })).toBeNull();
  });

  it("re-clamps the panel height when the viewport shrinks below the persisted value", () => {
    // Fix F2: start with a tall viewport so a persisted 500px survives
    // the initial mount, then shrink the viewport and dispatch a
    // `resize` event. The effect should re-clamp the panel to the new
    // viewport-aware upper bound (innerHeight - 200) and persist that
    // value back to localStorage. Use vi.useFakeTimers so we can
    // advance past the 120ms debounce without waiting for real time.
    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: 1000,
    });
    window.localStorage.setItem(STORAGE_KEY, "500");

    vi.useFakeTimers();
    try {
      render(<GlobalLogPanel />);
      expect(readHandleAriaValueNow()).toBe(500);

      // Shrink viewport to 500px total. New upper bound = 500 - 200 = 300.
      // The 500px panel should clamp down to 300.
      Object.defineProperty(window, "innerHeight", {
        configurable: true,
        value: 500,
      });
      act(() => {
        window.dispatchEvent(new Event("resize"));
      });
      // Advance past the debounce window.
      act(() => {
        vi.advanceTimersByTime(200);
      });

      expect(readHandleAriaValueNow()).toBe(300);
      expect(window.localStorage.getItem(STORAGE_KEY)).toBe("300");
    } finally {
      vi.useRealTimers();
      // Reset the viewport for the next test — jsdom's default is 768.
      Object.defineProperty(window, "innerHeight", {
        configurable: true,
        value: 768,
      });
    }
  });

  it("leaves panelHeight unchanged when the viewport is still tall enough", () => {
    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: 1080,
    });
    window.localStorage.setItem(STORAGE_KEY, "320");

    vi.useFakeTimers();
    try {
      render(<GlobalLogPanel />);
      expect(readHandleAriaValueNow()).toBe(320);

      // Shrink viewport but keep it well above 320 + 200.
      Object.defineProperty(window, "innerHeight", {
        configurable: true,
        value: 900,
      });
      act(() => {
        window.dispatchEvent(new Event("resize"));
      });
      act(() => {
        vi.advanceTimersByTime(200);
      });

      // Panel still fits; no clamp.
      expect(readHandleAriaValueNow()).toBe(320);
      expect(window.localStorage.getItem(STORAGE_KEY)).toBe("320");
    } finally {
      vi.useRealTimers();
      Object.defineProperty(window, "innerHeight", {
        configurable: true,
        value: 768,
      });
    }
  });

  it("persists a new height to localStorage when a pointer drag ends", () => {
    render(<GlobalLogPanel />);
    const handle = screen.getByRole("separator", { name: /resize log panel/i });

    // Pointer down at Y=500, then move up by 80px (Y=420), then release.
    // Dragging up INCREASES the panel height, so 240 + 80 = 320.
    //
    // jsdom does not support native PointerEvent, so we construct raw
    // MouseEvent-based events with the pointer fields on the init dict
    // and dispatch them directly. React's synthetic pointer event
    // wrapper reads clientY / button / pointerId from the underlying
    // native event when it is dispatched this way.
    act(() => {
      const down = new MouseEvent("pointerdown", {
        bubbles: true,
        cancelable: true,
        button: 0,
        clientY: 500,
      });
      Object.defineProperty(down, "pointerId", { value: 1 });
      handle.dispatchEvent(down);
    });
    act(() => {
      const move = new MouseEvent("pointermove", {
        bubbles: true,
        cancelable: true,
        clientY: 420,
      });
      Object.defineProperty(move, "pointerId", { value: 1 });
      handle.dispatchEvent(move);
    });
    act(() => {
      const up = new MouseEvent("pointerup", {
        bubbles: true,
        cancelable: true,
        clientY: 420,
      });
      Object.defineProperty(up, "pointerId", { value: 1 });
      handle.dispatchEvent(up);
    });

    expect(readHandleAriaValueNow()).toBe(320);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("320");
  });
});
