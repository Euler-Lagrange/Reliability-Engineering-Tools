import { describe, expect, it } from "vitest";
import {
  buildCancelNotification,
  classifyCancelError,
  describeCancelError,
} from "./cancelError";

describe("describeCancelError", () => {
  it("returns a raw string rejection verbatim", () => {
    // Tauri rejects `Result<_, String>` with a raw string — the most
    // important case B3 is fixing.
    expect(describeCancelError("No active run matches 'abc'.")).toBe(
      "No active run matches 'abc'.",
    );
  });

  it("extracts message from an Error instance", () => {
    const err = new Error("boom");
    expect(describeCancelError(err)).toBe("boom");
  });

  it("extracts message from a plain object with a message field", () => {
    expect(describeCancelError({ message: "plain object" })).toBe("plain object");
  });

  it("uses the fallback when the error is null", () => {
    expect(describeCancelError(null, "fallback")).toBe("fallback");
  });

  it("uses the fallback when the error has no usable message", () => {
    expect(describeCancelError({}, "fallback")).toBe("fallback");
  });

  it("uses the fallback when the string is only whitespace", () => {
    expect(describeCancelError("   ", "fallback")).toBe("fallback");
  });
});

describe("classifyCancelError", () => {
  it("tags the sidecar's no-active-run message", () => {
    expect(classifyCancelError("No active run matches 'abc'.")).toBe("no-active-run");
  });

  it("tags a plain English variation of the same error", () => {
    expect(classifyCancelError("the cancel request failed: no active run")).toBe(
      "no-active-run",
    );
  });

  it("returns generic for any other detail", () => {
    expect(classifyCancelError("Python sidecar timed out.")).toBe("generic");
  });
});

describe("buildCancelNotification", () => {
  it("converts a raw Tauri-string no-active-run rejection to the friendlier title", () => {
    // This is the exact production case from B3: the Rust bridge forwards
    // the sidecar's error payload verbatim, and Tauri's invoke rejects
    // the promise with that raw string.
    const notification = buildCancelNotification("No active run matches 'abc'.");
    expect(notification.title).toBe("No active run to cancel");
    expect(notification.tone).toBe("info");
    expect(notification.detail).toBe("No active run matches 'abc'.");
  });

  it("surfaces a real Error instance's message with the generic Cancel failed title", () => {
    const notification = buildCancelNotification(new Error("backend offline"));
    expect(notification.title).toBe("Cancel failed");
    expect(notification.tone).toBe("error");
    expect(notification.detail).toBe("backend offline");
  });

  it("falls back to a non-empty detail even when the error is unintelligible", () => {
    const notification = buildCancelNotification(undefined);
    expect(notification.title).toBe("Cancel failed");
    expect(notification.tone).toBe("error");
    expect(notification.detail.length).toBeGreaterThan(0);
  });
});
