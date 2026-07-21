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
          workflow_id: "bom_compare_custom",
        },
      },
    });

    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "ack",
        payload: expect.objectContaining({
          session_generation: 5,
          workflow_id: "bom_compare_custom",
        }),
      }),
    );
  });

  it("does not throw on a schema-drifted event; forwards the raw payload (Tier-2 #21)", async () => {
    // Schema drift (a newer sidecar, an older bundled frontend) must NOT throw
    // inside the listen callback and drop the event — that stranded a run in
    // "running" forever if it was the terminal event. The client now logs and
    // forwards the raw payload so the subscription's own result guard can still
    // terminate the run.
    let tauriCallback: ((event: { payload: unknown }) => void) | null = null;
    listenMock.mockImplementationOnce(async (_eventName, callback) => {
      tauriCallback = callback as (event: { payload: unknown }) => void;
      return () => {};
    });

    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const handler = vi.fn();
    const { backendClient } = await import("./client");

    await backendClient.subscribeToRunEvents(handler);
    const emitRunEvent = requireRunEventCallback(tauriCallback);

    const driftedEvent = {
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
          // session_generation missing -> fails the strict envelope schema
        },
      },
    };

    expect(() => emitRunEvent(driftedEvent)).not.toThrow();
    // Best-effort: the raw payload is forwarded so the run can still terminate.
    expect(handler).toHaveBeenCalledWith(driftedEvent.payload);
    expect(consoleErrorSpy).toHaveBeenCalled();

    consoleErrorSpy.mockRestore();
  });
});

describe("backendClient session-event subscription", () => {
  beforeEach(() => {
    vi.resetModules();
    listenMock.mockReset();
    (globalThis as unknown as { __TAURI_INTERNALS__: object }).__TAURI_INTERNALS__ = {};
  });

  it("parses valid session events and invokes the handler", async () => {
    let tauriCallback: ((event: { payload: unknown }) => void) | null = null;
    listenMock.mockImplementationOnce(async (_eventName, callback) => {
      tauriCallback = callback as (event: { payload: unknown }) => void;
      return () => {};
    });

    const handler = vi.fn();
    const { backendClient } = await import("./client");

    await backendClient.subscribeToSessionEvents(handler);
    const emitSessionEvent = requireRunEventCallback(tauriCallback);
    emitSessionEvent({
      payload: {
        kind: "disconnected",
        connected: false,
        backend: "python-sidecar-session",
        message: "Desktop backend dropped.",
        session_generation: 7,
      },
    });

    expect(handler).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "disconnected", session_generation: 7 }),
    );
  });

  it("drops a malformed session event without throwing (log-and-skip)", async () => {
    // Session events drive the backend-status store, so — unlike run events,
    // where the raw payload is forwarded to let the terminal guard fire — a
    // malformed status event is safely SKIPPED: the next heartbeat refreshes
    // the state, while forwarding garbage could poison the store. The parse
    // must never throw inside the Tauri listen callback.
    let tauriCallback: ((event: { payload: unknown }) => void) | null = null;
    listenMock.mockImplementationOnce(async (_eventName, callback) => {
      tauriCallback = callback as (event: { payload: unknown }) => void;
      return () => {};
    });

    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const handler = vi.fn();
    const { backendClient } = await import("./client");

    await backendClient.subscribeToSessionEvents(handler);
    const emitSessionEvent = requireRunEventCallback(tauriCallback);

    expect(() =>
      emitSessionEvent({
        payload: { kind: "exploded", connected: "maybe" },
      }),
    ).not.toThrow();
    expect(handler).not.toHaveBeenCalled();
    expect(consoleErrorSpy).toHaveBeenCalled();

    consoleErrorSpy.mockRestore();
  });
});
