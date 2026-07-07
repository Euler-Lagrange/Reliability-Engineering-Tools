import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { InputGrid } from "./InputGrid";
import type { FileRole, InputFileState } from "../app/types";

function makeInput(overrides: Partial<InputFileState> & { role: FileRole; label: string }): InputFileState {
  return {
    path: "C:/data/file.xlsx",
    helper: "A BOM file.",
    status: "ready",
    sheets: [],
    selectedSheet: "",
    tag: "Loaded",
    ...overrides,
  };
}

describe("InputGrid copy-path buttons", () => {
  const originalClipboard = navigator.clipboard;

  beforeEach(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      writable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  afterEach(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      writable: true,
      value: originalClipboard,
    });
    vi.restoreAllMocks();
  });

  test("copying one card's path does not flip the other card's button", async () => {
    const inputs: InputFileState[] = [
      makeInput({ role: "bomA", label: "First BOM", path: "C:/data/a.xlsx" }),
      makeInput({ role: "bomB", label: "Second BOM", path: "C:/data/b.xlsx" }),
    ];

    render(<InputGrid inputs={inputs} />);

    const firstCopy = screen.getByRole("button", {
      name: "Copy First BOM path to clipboard",
    });
    const secondCopy = screen.getByRole("button", {
      name: "Copy Second BOM path to clipboard",
    });

    // Both start in the idle "Copy path to clipboard" state.
    expect(firstCopy).toHaveAttribute("title", "Copy path to clipboard");
    expect(secondCopy).toHaveAttribute("title", "Copy path to clipboard");

    fireEvent.click(firstCopy);

    // The clicked card flips to "Copied!"...
    await waitFor(() => {
      expect(firstCopy).toHaveAttribute("title", "Copied!");
    });

    // ...while the sibling card retains its own idle state.
    expect(secondCopy).toHaveAttribute("title", "Copy path to clipboard");
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("C:/data/a.xlsx");
  });
});
