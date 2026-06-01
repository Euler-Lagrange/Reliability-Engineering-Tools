import { beforeEach, describe, expect, it, vi } from "vitest";

const listenMock = vi.fn();

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(),
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: (...args: unknown[]) => listenMock(...args),
}));

function requireRunEventCallback(
  callback: ((event: { payload: unknown }) => void) | null,
) {
  if (!callback) {
    throw new Error("Expected test to capture the Tauri run-event callback.");
  }
  return callback;
}

describe("backendClient run-event subscription", () => {
  beforeEach(() => {
    vi.resetModules();
    listenMock.mockReset();
    (globalThis as unknown as { __TAURI_INTERNALS__: object }).__TAURI_INTERNALS__ = {};
  });

  it("parses run events through the production Zod gate before invoking the handler", async () => {
    let tauriCallback: ((event: { payload: unknown }) => void) | null = null;
    listenMock.mockImplementationOnce(async (_eventName, callback) => {
      tauriCallback = callback as (event: { payload: unknown }) => void;
      return () => {};
    });

    const handler = vi.fn();
    const { backendClient } = await import("./client");

    await backendClient.subscribeToRunEvents(handler);
    const emitRunEvent = requireRunEventCallback(tauriCallback);
    emitRunEvent({
      payload: {
        protocol_version: "0.1.0",
        id: "evt_ack_001",
        kind: "ack",
        request_id: "req_001",
        run_id: "run_001",
        timestamp: "2026-05-18T00:00:00Z",
        payload: {
          accepted: true,
          run_id: "run_001",
          mode: "desktop-bridge",
          session_generation: 5,
        },
      },
    });

    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "ack",
        payload: expect.objectContaining({ session_generation: 5 }),
      }),
    );
  });

  it("throws before the handler when a streamed ack is missing session_generation", async () => {
    let tauriCallback: ((event: { payload: unknown }) => void) | null = null;
    listenMock.mockImplementationOnce(async (_eventName, callback) => {
      tauriCallback = callback as (event: { payload: unknown }) => void;
      return () => {};
    });

    const handler = vi.fn();
    const { backendClient } = await import("./client");

    await backendClient.subscribeToRunEvents(handler);
    const emitRunEvent = requireRunEventCallback(tauriCallback);

    expect(() =>
      emitRunEvent({
        payload: {
          protocol_version: "0.1.0",
          id: "evt_ack_001",
          kind: "ack",
          request_id: "req_001",
          run_id: "run_001",
          timestamp: "2026-05-18T00:00:00Z",
          payload: {
            accepted: true,
            run_id: "run_001",
            mode: "desktop-bridge",
          },
        },
      }),
    ).toThrow();
    expect(handler).not.toHaveBeenCalled();
  });
});
