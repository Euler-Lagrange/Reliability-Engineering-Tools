import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { useCopyToClipboard } from "./useCopyToClipboard";

describe("useCopyToClipboard", () => {
  const originalClipboard = navigator.clipboard;
  let originalExecCommand: typeof document.execCommand | undefined;

  beforeEach(() => {
    vi.useFakeTimers();
    // jsdom doesn't implement document.execCommand — stub it so the
    // fallback path exists and can be spied on.
    originalExecCommand = (document as Document & { execCommand?: typeof document.execCommand }).execCommand;
    if (!originalExecCommand) {
      (document as Document & { execCommand: (cmd: string) => boolean }).execCommand = () => true;
    }
  });

  afterEach(() => {
    vi.useRealTimers();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      writable: true,
      value: originalClipboard,
    });
    if (!originalExecCommand) {
      delete (document as Document & { execCommand?: typeof document.execCommand }).execCommand;
    }
  });

  function installClipboard(writeText: (text: string) => Promise<void>) {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      writable: true,
      value: { writeText },
    });
  }

  test("uses navigator.clipboard.writeText and sets copied flag", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    installClipboard(writeText);

    const { result } = renderHook(() => useCopyToClipboard(1500));

    await act(async () => {
      await result.current.copy("hello world");
    });

    expect(writeText).toHaveBeenCalledWith("hello world");
    expect(result.current.copied).toBe(true);
    expect(result.current.error).toBeNull();
  });

  test("resets copied flag after the configured delay", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    installClipboard(writeText);

    const { result } = renderHook(() => useCopyToClipboard(1500));

    await act(async () => {
      await result.current.copy("ping");
    });

    expect(result.current.copied).toBe(true);

    act(() => {
      vi.advanceTimersByTime(1500);
    });

    expect(result.current.copied).toBe(false);
  });

  test("captures error when writeText rejects and no fallback succeeds", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    installClipboard(writeText);
    const execSpy = vi
      .spyOn(document, "execCommand")
      .mockImplementation(() => false);

    const { result } = renderHook(() => useCopyToClipboard());

    let ok = true;
    await act(async () => {
      ok = await result.current.copy("fail");
    });

    expect(ok).toBe(false);
    expect(result.current.copied).toBe(false);
    expect(result.current.error).toBeTruthy();

    execSpy.mockRestore();
  });
});
