import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

/** Child that throws during render so the boundary catches it. */
function Boom(): never {
  throw new Error("kaboom detonated");
}

describe("ErrorBoundary fallback — inline copy confirmation", () => {
  const originalClipboard = navigator.clipboard;
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    // React logs caught errors via console.error; silence to keep output clean.
    consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      writable: true,
      value: originalClipboard,
    });
  });

  function installClipboard(writeText: (text: string) => Promise<void>) {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      writable: true,
      value: { writeText },
    });
  }

  it("renders the fallback surface when a child throws", () => {
    render(
      <ErrorBoundary title="Something broke" detail="We caught it.">
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /something broke/i }),
    ).toBeInTheDocument();
    // The message shows in both the summary line and the stack <pre>.
    expect(screen.getAllByText(/kaboom detonated/i).length).toBeGreaterThan(0);
  });

  it("flips the copy button to an inline confirmation on success (independent of the toast host)", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    // userEvent.setup() installs its own clipboard stub, so override AFTER it.
    const user = userEvent.setup();
    installClipboard(writeText);

    render(
      <ErrorBoundary title="Something broke" detail="We caught it.">
        <Boom />
      </ErrorBoundary>,
    );

    const copyButton = screen.getByRole("button", {
      name: /copy diagnostic bundle/i,
    });
    await user.click(copyButton);

    expect(writeText).toHaveBeenCalledTimes(1);
    // The confirmation must be visible inside the fallback itself, because the
    // root boundary unmounts the NotificationCenter that would host a toast.
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /copied/i }),
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("button", { name: /^copy diagnostic bundle$/i }),
    ).not.toBeInTheDocument();
  });

  it("shows an inline failure label when the copy fails", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    const user = userEvent.setup();
    installClipboard(writeText);
    // jsdom has no execCommand; define a failing one so the fallback path
    // returns false and the copy is reported as failed.
    const doc = document as Document & { execCommand?: (cmd: string) => boolean };
    const hadExec = typeof doc.execCommand === "function";
    const originalExec = doc.execCommand;
    doc.execCommand = () => false;

    render(
      <ErrorBoundary title="Something broke" detail="We caught it.">
        <Boom />
      </ErrorBoundary>,
    );

    await user.click(
      screen.getByRole("button", { name: /copy diagnostic bundle/i }),
    );

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /copy failed/i }),
      ).toBeInTheDocument();
    });

    if (hadExec) {
      doc.execCommand = originalExec;
    } else {
      Reflect.deleteProperty(doc, "execCommand");
    }
  });
});
