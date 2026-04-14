import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRunStore, MAX_LOG_LINES } from "../../stores/runStore";
import { backendClient } from "./client";
import { useBackendRunLifecycle } from "./runLifecycle";

// Mock the Tauri-bound subscribe / sessionStatus calls so the hook can mount
// in a jsdom environment without a real Rust runtime.
vi.mock("./client", () => {
  return {
    backendClient: {
      runtimeMode: "browser-mock",
      subscribeToRunEvents: vi.fn(async () => () => {}),
      subscribeToSessionEvents: vi.fn(async () => () => {}),
      sessionStatus: vi.fn(async () => ({
        connected: true,
        backend: "python-sidecar-session",
        mode: "desktop-bridge" as const,
        session_generation: 1,
      })),
    },
  };
});

beforeEach(() => {
  // Reset the global store between tests so leakage cannot pollute later cases.
  useRunStore.setState({ activeRun: null });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("useBackendRunLifecycle (runStore-backed)", () => {
  it("returns an idle session when there is no active run", () => {
    const { result } = renderHook(() =>
      useBackendRunLifecycle("dark_star_fmea", "browser-mock", (x) => x),
    );

    expect(result.current.session.runId).toBeNull();
    expect(result.current.session.phase).toBe("idle");
    expect(result.current.session.logs).toEqual([]);
  });

  it("retains run state across hook unmount and remount for the same tool", () => {
    const { result, unmount } = renderHook(() =>
      useBackendRunLifecycle("dark_star_fmea", "browser-mock", (x) => x),
    );

    act(() => {
      result.current.beginAcceptedRun({
        run_id: "run_persistent_001",
        mode: "desktop-bridge",
        session_generation: 1,
      });
    });

    expect(result.current.session.runId).toBe("run_persistent_001");
    expect(result.current.session.phase).toBe("starting");

    unmount();

    // Re-mount the same hook (simulates the user switching tabs and returning).
    const { result: result2 } = renderHook(() =>
      useBackendRunLifecycle("dark_star_fmea", "browser-mock", (x) => x),
    );

    // The session must survive — the whole point of moving state into the
    // global store is so the run handle is not lost on tool switch.
    expect(result2.current.session.runId).toBe("run_persistent_001");
    expect(result2.current.session.phase).toBe("starting");
  });

  it("does not surface another tool's active run", () => {
    // Tool A starts a run.
    const { result: toolA } = renderHook(() =>
      useBackendRunLifecycle("dark_star_fmea", "browser-mock", (x) => x),
    );
    act(() => {
      toolA.current.beginAcceptedRun({
        run_id: "run_owned_by_fmea",
        mode: "desktop-bridge",
        session_generation: 1,
      });
    });
    expect(toolA.current.session.runId).toBe("run_owned_by_fmea");

    // Tool B mounts. It must NOT see tool A's run.
    const { result: toolB } = renderHook(() =>
      useBackendRunLifecycle("bom_compare", "browser-mock", (x) => x),
    );
    expect(toolB.current.session.runId).toBeNull();
    expect(toolB.current.session.phase).toBe("idle");

    // Meanwhile tool A still sees its own run.
    expect(toolA.current.session.runId).toBe("run_owned_by_fmea");
  });

  it("resetSession only clears state when the active run belongs to the calling tool", () => {
    const { result: toolA } = renderHook(() =>
      useBackendRunLifecycle("dark_star_fmea", "browser-mock", (x) => x),
    );
    act(() => {
      toolA.current.beginAcceptedRun({
        run_id: "run_belongs_to_a",
        mode: "desktop-bridge",
        session_generation: 1,
      });
    });

    const { result: toolB } = renderHook(() =>
      useBackendRunLifecycle("bom_compare", "browser-mock", (x) => x),
    );

    // Tool B's reset must not nuke tool A's run.
    act(() => {
      toolB.current.resetSession();
    });
    expect(useRunStore.getState().activeRun?.runId).toBe("run_belongs_to_a");

    // Tool A's reset clears it.
    act(() => {
      toolA.current.resetSession();
    });
    expect(useRunStore.getState().activeRun).toBeNull();
  });

  it("appendLog tracks truncation count beyond MAX_LOG_LINES", () => {
    const { result } = renderHook(() =>
      useBackendRunLifecycle("dark_star_fmea", "browser-mock", (x) => x),
    );

    act(() => {
      result.current.beginAcceptedRun({
        run_id: "run_log_truncation",
        mode: "desktop-bridge",
        session_generation: 1,
      });
    });

    // Append more than MAX_LOG_LINES log lines via the store directly
    // (the hook intercepts only sidecar-event logs, not direct calls).
    act(() => {
      const append = useRunStore.getState().appendLog;
      for (let i = 0; i < MAX_LOG_LINES + 50; i++) {
        append(`line ${i}`);
      }
    });

    const state = useRunStore.getState().activeRun!;
    expect(state.logs).toHaveLength(MAX_LOG_LINES);
    expect(state.truncatedLogCount).toBe(50);
    // Most-recent line should be present; earliest should be gone.
    expect(state.logs[state.logs.length - 1]).toBe(`line ${MAX_LOG_LINES + 50 - 1}`);
    expect(state.logs[0]).toBe(`line 50`);
  });

  it("markDisconnected preserves run state and sets the disconnected flag", () => {
    const { result } = renderHook(() =>
      useBackendRunLifecycle("dark_star_fmea", "browser-mock", (x) => x),
    );

    act(() => {
      result.current.beginAcceptedRun({
        run_id: "run_disconnect_test",
        mode: "desktop-bridge",
        session_generation: 1,
      });
    });

    act(() => {
      useRunStore.getState().markDisconnected("Sidecar crashed");
    });

    const state = useRunStore.getState().activeRun!;
    // Run id is preserved so cancel could still work in theory after reconnect.
    expect(state.runId).toBe("run_disconnect_test");
    expect(state.phase).toBe("disconnected");
    expect(state.isDisconnected).toBe(true);
    expect(state.statusMessage).toBe("Sidecar crashed");
  });

  it("markDisconnected leaves terminal runs untouched", () => {
    const { result } = renderHook(() =>
      useBackendRunLifecycle("dark_star_fmea", "browser-mock", (x) => x),
    );

    act(() => {
      result.current.beginAcceptedRun({
        run_id: "run_already_succeeded",
        mode: "desktop-bridge",
        session_generation: 1,
      });
      // Force the run to a terminal state.
      useRunStore.getState().patchActiveRun({ phase: "success", finishedAt: new Date().toISOString() });
    });

    act(() => {
      useRunStore.getState().markDisconnected("Sidecar crashed");
    });

    const state = useRunStore.getState().activeRun!;
    // A finished run should not be flipped into disconnected.
    expect(state.phase).toBe("success");
    expect(state.isDisconnected).toBe(false);
  });

  it("markReconnected clears the disconnected flag", () => {
    const { result } = renderHook(() =>
      useBackendRunLifecycle("dark_star_fmea", "browser-mock", (x) => x),
    );

    act(() => {
      result.current.beginAcceptedRun({
        run_id: "run_reconnect_test",
        mode: "desktop-bridge",
        session_generation: 1,
      });
      useRunStore.getState().markDisconnected("Temporary glitch");
    });
    expect(useRunStore.getState().activeRun?.isDisconnected).toBe(true);

    act(() => {
      useRunStore.getState().markReconnected();
    });
    expect(useRunStore.getState().activeRun?.isDisconnected).toBe(false);
    // Run id and progress preserved through the disconnect/reconnect.
    expect(useRunStore.getState().activeRun?.runId).toBe("run_reconnect_test");
  });

  it("clears a disconnected run when reconnect lands on a new session generation", async () => {
    let sessionHandler: ((event: { kind: "connected" | "disconnected"; connected: boolean; backend: string; message: string }) => void) | null = null;
    vi.mocked(backendClient.subscribeToSessionEvents).mockImplementationOnce(async (handler) => {
      sessionHandler = handler;
      return () => {};
    });
    vi.mocked(backendClient.sessionStatus).mockResolvedValueOnce({
      connected: true,
      backend: "python-sidecar-session",
      mode: "desktop-bridge",
      session_generation: 2,
    });

    const { result } = renderHook(() =>
      useBackendRunLifecycle("dark_star_fmea", "desktop-bridge", (x) => x),
    );

    act(() => {
      result.current.beginAcceptedRun({
        run_id: "run_stale_after_restart",
        mode: "desktop-bridge",
        session_generation: 1,
      });
      useRunStore.getState().markDisconnected("Sidecar restarted");
    });

    await act(async () => {
      sessionHandler?.({
        kind: "connected",
        connected: true,
        backend: "python-sidecar-session",
        message: "Sidecar restarted",
      });
      await Promise.resolve();
    });

    expect(useRunStore.getState().activeRun).toBeNull();
  });
});
