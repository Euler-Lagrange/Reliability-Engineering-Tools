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
  it("clears a stale active run when reconnect lands on a new session generation", async () => {
    let onSessionEvent: ((event: BackendSessionEvent) => void) | null = null;
    mockBackendClient.subscribeToSessionEvents.mockImplementation(async (handler: (event: BackendSessionEvent) => void) => {
      onSessionEvent = handler;
      return () => {};
    });
    mockBackendClient.sessionStatus.mockResolvedValue({
      connected: true,
      backend: "python-sidecar",
      mode: "desktop-bridge",
      session_generation: 7,
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
      onSessionEvent?.({ kind: "disconnected", message: "Desktop backend dropped." });
    });

    expect(useRunStore.getState().activeRun?.phase).toBe("disconnected");
    expect(useShellStore.getState().backendStatus).toBe("connecting");

    await act(async () => {
      vi.advanceTimersByTime(2_000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mockBackendClient.sessionStatus).toHaveBeenCalledTimes(1);
    expect(useRunStore.getState().activeRun).toBeNull();
    expect(useShellStore.getState().backendStatus).toBe("ready");
    expect(
      useNotificationStore
        .getState()
        .notifications.some((notification) => notification.title === "Backend reconnected"),
    ).toBe(true);

    unmount();
  });

  it("marks the run reconnected when the backend returns on the same session generation", async () => {
    let onSessionEvent: ((event: BackendSessionEvent) => void) | null = null;
    mockBackendClient.subscribeToSessionEvents.mockImplementation(async (handler: (event: BackendSessionEvent) => void) => {
      onSessionEvent = handler;
      return () => {};
    });
    mockBackendClient.sessionStatus.mockResolvedValue({
      connected: true,
      backend: "python-sidecar",
      mode: "desktop-bridge",
      session_generation: 1,
    });

    const { unmount } = renderHook(() => useBackendBootstrap());
    await flushAsyncWork();
    expect(mockBackendClient.subscribeToSessionEvents).toHaveBeenCalledTimes(1);
    expect(onSessionEvent).not.toBeNull();

    act(() => {
      useRunStore.setState({
        activeRun: makeActiveRun({
          sessionGeneration: 1,
        }),
      });
    });

    act(() => {
      onSessionEvent?.({ kind: "disconnected", message: "Desktop backend dropped." });
    });

    await act(async () => {
      vi.advanceTimersByTime(2_000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mockBackendClient.sessionStatus).toHaveBeenCalledTimes(1);
    expect(useRunStore.getState().activeRun).not.toBeNull();
    expect(useRunStore.getState().activeRun?.sessionGeneration).toBe(1);
    expect(useRunStore.getState().activeRun?.isDisconnected).toBe(false);

    unmount();
  });
});
