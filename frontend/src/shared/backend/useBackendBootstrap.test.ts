import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useBackendBootstrap } from "./useBackendBootstrap";
import type { BackendSessionEvent } from "../../contracts/sidecar";
import { useNotificationStore } from "../../stores/notificationStore";
import { useRunStore, type ActiveRunState } from "../../stores/runStore";
import { useShellStore, type ToolId } from "../../stores/shellStore";

const { mockBackendClient } = vi.hoisted(() => ({
  mockBackendClient: {
    runtimeMode: "desktop-bridge" as const,
    healthCheck: vi.fn(),
    sessionStatus: vi.fn(),
    listSheets: vi.fn(),
    inspectInput: vi.fn(),
    analyzeTemplate: vi.fn(),
    validateRun: vi.fn(),
    executeRun: vi.fn(),
    cancelRun: vi.fn(),
    readFletConfig: vi.fn(),
    subscribeToRunEvents: vi.fn(async () => () => {}),
    subscribeToSessionEvents: vi.fn(),
    openExcelFile: vi.fn(),
    openPdfFile: vi.fn(),
    openDirectory: vi.fn(),
    revealInFileManager: vi.fn(),
  },
}));

vi.mock("./client", () => ({
  backendClient: mockBackendClient,
}));

function makeActiveRun(overrides: Partial<ActiveRunState>): ActiveRunState {
  return {
    runId: "run_reconnect_001",
    toolId: "dark_star_fmea" as ToolId,
    sessionGeneration: 1,
    phase: "running",
    progress: 42,
    stage: "Crunching",
    statusMessage: "Working...",
    steps: [],
    logs: [],
    truncatedLogCount: 0,
    result: null,
    errorMessage: null,
    errorCode: null,
    errorTraceback: null,
    startedAt: new Date().toISOString(),
    finishedAt: null,
    isDisconnected: false,
    ...overrides,
  };
}

async function flushAsyncWork() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  window.localStorage.clear();
  useRunStore.setState({ activeRun: null });
  useNotificationStore.setState({ notifications: [] });
  useShellStore.setState({
    activeToolId: "dark_star_fmea",
    backendStatus: "connecting",
    backendMode: "unknown",
    backendMessage: null,
    lastBackendCheckAt: null,
    fmeaOutputDirectory: null,
    bomCompareOutputDirectory: null,
    failureRateOutputDirectory: null,
    refdesExtractorOutputDirectory: null,
  });
  mockBackendClient.healthCheck.mockResolvedValue({
    status: "ok",
    backend: "python-sidecar",
    protocol_version: "0.1.0",
    mode: "desktop-bridge",
    log_directory: "C:\\logs",
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useBackendBootstrap", () => {
  it("preserves a fresh-generation run when an in-flight reconnect succeeds", async () => {
    let onSessionEvent: ((event: BackendSessionEvent) => void) | null = null;
    mockBackendClient.subscribeToSessionEvents.mockImplementation(async (handler: (event: BackendSessionEvent) => void) => {
      onSessionEvent = handler;
      return () => {};
    });

    const { unmount } = renderHook(() => useBackendBootstrap());
    await flushAsyncWork();
    expect(mockBackendClient.subscribeToSessionEvents).toHaveBeenCalledTimes(1);
    expect(onSessionEvent).not.toBeNull();

    let resolveReconnect: ((value: {
      status: "ok";
      backend: string;
      protocol_version: string;
      mode: "desktop-bridge";
      log_directory: string;
    }) => void) | undefined;
    mockBackendClient.healthCheck.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveReconnect = resolve;
        }),
    );

    act(() => {
      useRunStore.setState({
        activeRun: makeActiveRun({ sessionGeneration: 1 }),
      });
    });

    act(() => {
      onSessionEvent?.({
        kind: "disconnected",
        connected: false,
        backend: "python-sidecar",
        message: "Desktop backend dropped.",
        session_generation: 1,
      });
    });

    expect(useRunStore.getState().activeRun?.phase).toBe("disconnected");
    expect(useShellStore.getState().backendStatus).toBe("connecting");

    act(() => {
      vi.advanceTimersByTime(2_000);
    });
    expect(mockBackendClient.healthCheck).toHaveBeenCalledTimes(2);

    act(() => {
      useShellStore.getState().setBackendState({
        backendStatus: "busy",
        backendMessage: "Run in progress.",
      });
      useRunStore.setState({
        activeRun: makeActiveRun({
          runId: "run_reconnect_002",
          sessionGeneration: 2,
          phase: "running",
        }),
      });
    });

    await act(async () => {
      resolveReconnect?.({
        status: "ok",
        backend: "python-sidecar",
        protocol_version: "0.1.0",
        mode: "desktop-bridge",
        log_directory: "C:\\logs",
      });
      await Promise.resolve();
    });

    expect(mockBackendClient.sessionStatus).not.toHaveBeenCalled();
    expect(useRunStore.getState().activeRun?.runId).toBe("run_reconnect_002");
    expect(useRunStore.getState().activeRun?.sessionGeneration).toBe(2);
    expect(useShellStore.getState().backendStatus).toBe("busy");
    expect(
      useNotificationStore
        .getState()
        .notifications.some((notification) => notification.title === "Backend reconnected"),
    ).toBe(false);

    unmount();
  });

  it("still clears a stale run from the disconnected generation", async () => {
    let onSessionEvent: ((event: BackendSessionEvent) => void) | null = null;
    mockBackendClient.subscribeToSessionEvents.mockImplementation(
      async (handler: (event: BackendSessionEvent) => void) => {
        onSessionEvent = handler;
        return () => {};
      },
    );

    const { unmount } = renderHook(() => useBackendBootstrap());
    await flushAsyncWork();

    act(() => {
      useRunStore.setState({
        activeRun: makeActiveRun({ sessionGeneration: 1 }),
      });
      onSessionEvent?.({
        kind: "disconnected",
        connected: false,
        backend: "python-sidecar",
        message: "Desktop backend dropped.",
        session_generation: 1,
      });
    });

    await act(async () => {
      vi.advanceTimersByTime(2_000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(useRunStore.getState().activeRun).toBeNull();
    expect(useShellStore.getState().backendStatus).toBe("ready");

    unmount();
  });

  it("cancels a pending reconnect timer when a newer-generation run is accepted", async () => {
    let onSessionEvent: ((event: BackendSessionEvent) => void) | null = null;
    mockBackendClient.subscribeToSessionEvents.mockImplementation(
      async (handler: (event: BackendSessionEvent) => void) => {
        onSessionEvent = handler;
        return () => {};
      },
    );

    const { unmount } = renderHook(() => useBackendBootstrap());
    await flushAsyncWork();
    expect(mockBackendClient.healthCheck).toHaveBeenCalledTimes(1);

    act(() => {
      useRunStore.setState({
        activeRun: makeActiveRun({ sessionGeneration: 1 }),
      });
      onSessionEvent?.({
        kind: "disconnected",
        connected: false,
        backend: "python-sidecar",
        message: "Desktop backend dropped.",
        session_generation: 1,
      });
      useRunStore.setState({
        activeRun: makeActiveRun({
          runId: "run_reconnect_002",
          sessionGeneration: 2,
          phase: "starting",
        }),
      });
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(mockBackendClient.healthCheck).toHaveBeenCalledTimes(1);
    expect(useRunStore.getState().activeRun?.runId).toBe("run_reconnect_002");

    unmount();
  });

  it("ignores a stale disconnect delivered after a newer run is registered", async () => {
    let onSessionEvent: ((event: BackendSessionEvent) => void) | null = null;
    mockBackendClient.subscribeToSessionEvents.mockImplementation(
      async (handler: (event: BackendSessionEvent) => void) => {
        onSessionEvent = handler;
        return () => {};
      },
    );

    const { unmount } = renderHook(() => useBackendBootstrap());
    await flushAsyncWork();

    act(() => {
      useShellStore.getState().setBackendState({
        backendStatus: "busy",
        backendMessage: "Run in progress.",
      });
      useRunStore.setState({
        activeRun: makeActiveRun({
          runId: "run_reconnect_002",
          sessionGeneration: 2,
          phase: "running",
        }),
      });
      onSessionEvent?.({
        kind: "disconnected",
        connected: false,
        backend: "python-sidecar",
        message: "Late disconnect from generation 1.",
        session_generation: 1,
      });
    });

    expect(useRunStore.getState().activeRun?.phase).toBe("running");
    expect(useShellStore.getState().backendStatus).toBe("busy");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(mockBackendClient.healthCheck).toHaveBeenCalledTimes(1);
    expect(
      useNotificationStore
        .getState()
        .notifications.some((notification) => notification.title === "Backend disconnected"),
    ).toBe(false);

    unmount();
  });

  it("does not schedule overlapping reconnect chains on repeated disconnects", async () => {
    // Two disconnect events arriving before the first reconnect timer fires
    // must NOT leave two pending timers — the overlapping-chain bug fired
    // two health-check loops (and two reconnected toasts) for a single
    // recovery.
    let onSessionEvent: ((event: BackendSessionEvent) => void) | null = null;
    mockBackendClient.subscribeToSessionEvents.mockImplementation(
      async (handler: (event: BackendSessionEvent) => void) => {
        onSessionEvent = handler;
        return () => {};
      },
    );

    const { unmount } = renderHook(() => useBackendBootstrap());
    await flushAsyncWork();
    // Initial bootstrap health check.
    expect(mockBackendClient.healthCheck).toHaveBeenCalledTimes(1);

    act(() => {
      onSessionEvent?.({
        kind: "disconnected",
        connected: false,
        backend: "python-sidecar",
        message: "Desktop backend dropped once.",
      });
    });
    act(() => {
      onSessionEvent?.({
        kind: "disconnected",
        connected: false,
        backend: "python-sidecar",
        message: "Desktop backend dropped twice.",
      });
    });

    // Advance past every reconnect delay and flush the health-check chain.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    // Only ONE reconnect chain runs → exactly one additional health check
    // (two with the bug), and the single deduped "Backend reconnected" toast
    // carries count 1 (it was pushed twice with the bug).
    expect(mockBackendClient.healthCheck).toHaveBeenCalledTimes(2);
    const reconnectToasts = useNotificationStore
      .getState()
      .notifications.filter((notification) => notification.title === "Backend reconnected");
    expect(reconnectToasts).toHaveLength(1);
    expect(reconnectToasts[0]?.count).toBe(1);

    unmount();
  });

  it("is a no-op on reconnect when no run is active", async () => {
    let onSessionEvent: ((event: BackendSessionEvent) => void) | null = null;
    mockBackendClient.subscribeToSessionEvents.mockImplementation(async (handler: (event: BackendSessionEvent) => void) => {
      onSessionEvent = handler;
      return () => {};
    });

    const { unmount } = renderHook(() => useBackendBootstrap());
    await flushAsyncWork();

    act(() => {
      onSessionEvent?.({
        kind: "disconnected",
        connected: false,
        backend: "python-sidecar",
        message: "Desktop backend dropped.",
      });
    });

    await act(async () => {
      vi.advanceTimersByTime(2_000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mockBackendClient.sessionStatus).not.toHaveBeenCalled();
    expect(useRunStore.getState().activeRun).toBeNull();
    expect(useShellStore.getState().backendStatus).toBe("ready");

    unmount();
  });
});
