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
  it("clears any active run when reconnect succeeds", async () => {
    // Every reconnect path in the Rust bridge spawns a fresh sidecar
    // session (advance_session_generation always bumps), so a run that
    // predates the reconnect cannot resume. The hook now clears the run
    // unconditionally rather than round-tripping through sessionStatus().
    let onSessionEvent: ((event: BackendSessionEvent) => void) | null = null;
    mockBackendClient.subscribeToSessionEvents.mockImplementation(async (handler: (event: BackendSessionEvent) => void) => {
      onSessionEvent = handler;
      return () => {};
    });

    const { unmount } = renderHook(() => useBackendBootstrap());
    await flushAsyncWork();
    expect(mockBackendClient.subscribeToSessionEvents).toHaveBeenCalledTimes(1);
    expect(onSessionEvent).not.toBeNull();

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
      });
    });

    expect(useRunStore.getState().activeRun?.phase).toBe("disconnected");
    expect(useShellStore.getState().backendStatus).toBe("connecting");

    await act(async () => {
      vi.advanceTimersByTime(2_000);
      await Promise.resolve();
      await Promise.resolve();
    });

    // We no longer call sessionStatus on reconnect — the active run is
    // cleared unconditionally and health_check is the single source of
    // truth for the reconnected-backend notification.
    expect(mockBackendClient.sessionStatus).not.toHaveBeenCalled();
    expect(useRunStore.getState().activeRun).toBeNull();
    expect(useShellStore.getState().backendStatus).toBe("ready");
    expect(
      useNotificationStore
        .getState()
        .notifications.some((notification) => notification.title === "Backend reconnected"),
    ).toBe(true);

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
