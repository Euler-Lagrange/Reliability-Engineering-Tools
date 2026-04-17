import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { useShellStore } from "../../stores/shellStore";
import { useThemeStore } from "../../stores/themeStore";
import { useAppShortcuts } from "./useAppShortcuts";

const originalPlatform = window.navigator.platform;

function setNavigatorPlatform(platform: string) {
  Object.defineProperty(window.navigator, "platform", {
    configurable: true,
    value: platform,
  });
}

beforeEach(() => {
  useShellStore.setState({
    activeToolId: "dark_star_fmea",
    backendStatus: "ready",
    backendMode: "browser-mock",
    backendMessage: null,
    lastBackendCheckAt: null,
  });
  useThemeStore.setState({ mode: "system" });
});

afterEach(() => {
  setNavigatorPlatform(originalPlatform);
});

describe("useAppShortcuts", () => {
  it("uses the macOS primary modifier when switching tools", () => {
    setNavigatorPlatform("MacIntel");
    renderHook(() => useAppShortcuts());

    act(() => {
      window.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "2",
          metaKey: true,
          bubbles: true,
        }),
      );
    });

    expect(useShellStore.getState().activeToolId).toBe("bom_compare");
  });

  it("does not trigger shortcuts while typing in an input", () => {
    setNavigatorPlatform("Win32");
    renderHook(() => useAppShortcuts());

    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();

    act(() => {
      input.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "2",
          ctrlKey: true,
          bubbles: true,
        }),
      );
    });

    expect(useShellStore.getState().activeToolId).toBe("dark_star_fmea");
    input.remove();
  });
});
