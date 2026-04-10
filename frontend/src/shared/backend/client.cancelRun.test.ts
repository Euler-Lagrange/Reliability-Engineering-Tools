import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildCancelNotification } from "./cancelError";

// Phase B3 — integration-ish test for the cancel-error propagation path.
//
// The Tauri bridge's `backend_cancel_run` command is a Rust function with
// signature `Result<CancelRunResponse, String>`. When the Python sidecar
// replies with an `error` envelope, the Rust spawn_stdout_reader extracts
// the inner `payload.message` field and forwards it verbatim into
// `Err(String)`. Tauri surfaces that to the frontend as a rejected
// promise whose rejection value is the raw string — NOT an Error.
//
// We mock `@tauri-apps/api/core#invoke` to simulate exactly that behavior
// and assert that the error text survives end-to-end: into
// backendClient.cancelRun's caller, through buildCancelNotification,
// and out as a user-facing notification.

const invokeMock = vi.fn();

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(async () => () => {}),
}));

// Force the client into desktop-bridge mode so cancelRun does not
// short-circuit the Tauri path.
(globalThis as unknown as { __TAURI_INTERNALS__: object }).__TAURI_INTERNALS__ = {};

beforeEach(() => {
  invokeMock.mockReset();
});

afterEach(() => {
  invokeMock.mockReset();
});

describe("backendClient.cancelRun B3 error propagation", () => {
  it("rejects with the sidecar's raw string message when the run does not exist", async () => {
    invokeMock.mockRejectedValueOnce("No active run matches 'abc'.");

    // Import lazily so the vi.mock above is in effect at module init.
    const { backendClient } = await import("./client");

    await expect(backendClient.cancelRun("abc")).rejects.toBe(
      "No active run matches 'abc'.",
    );
  });

  it("buildCancelNotification turns that raw string into a friendly info notification", async () => {
    invokeMock.mockRejectedValueOnce("No active run matches 'abc'.");

    const { backendClient } = await import("./client");

    let captured: unknown;
    await backendClient.cancelRun("abc").catch((error: unknown) => {
      captured = error;
    });

    const notification = buildCancelNotification(captured);
    expect(notification.title).toBe("No active run to cancel");
    expect(notification.tone).toBe("info");
    expect(notification.detail).toBe("No active run matches 'abc'.");
  });
});
