import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { useBackendBusyReset } from "./useBackendBusyReset";
import { useRunStore, type ActiveRunState } from "../../stores/runStore";
import { useShellStore } from "../../stores/shellStore";
import type { ToolId } from "../../stores/shellStore";

// Phase B4 regression tests.
//
// The shell is supposed to release the "Backend busy" chip whenever the
// active run reaches a terminal phase (cancelled / success / failure).
// Previously every tool owned its own effect keyed on
// `phase === "cancelled"`, which missed some paths.
//
// Fix B1: "idle" used to also be in the terminal phase set, which
// raced with handleStartRun — flipping the chip to "Validating..." was
// instantly reverted because activeRun was still null. The idle case
// is now handled by per-tool safety-net resets instead.

function makeActiveRun(overrides: Partial<ActiveRunState>): ActiveRunState {
  return {
    runId: "run_test_001",
    toolId: "dark_star_fmea" as ToolId,
    phase: "running",
    progress: 0,
    stage: null,
    statusMessage: null,
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

beforeEach(() => {
  useRunStore.setState({ activeRun: null });
  useShellStore.setState({
    activeToolId: "dark_star_fmea",
    backendStatus: "connecting",
    backendMode: "unknown",
    backendMessage: null,
    lastBackendCheckAt: null,
  });
});

afterEach(() => {
  useRunStore.setState({ activeRun: null });
});

describe("useBackendBusyReset", () => {
  it("does NOT clear busy when phase is idle (Fix B1)", () => {
    // Fix B1: during handleStartRun, the tool flips the chip to "busy"
    // with a "Validating..." message before the async validateRun call
    // creates an activeRun. In that window phase reads as "idle".
    // The hook must NOT clear the busy state — that raced with the
    // validation flow and made the "Validating..." chip flicker away
    // instantly on every run.
    act(() => {
      useShellStore.setState({
        backendStatus: "busy",
        backendMessage: "Validating...",
      });
    });

    renderHook(() => useBackendBusyReset());

    const state = useShellStore.getState();
    expect(state.backendStatus).toBe("busy");
    expect(state.backendMessage).toBe("Validating...");
  });

  it("does NOT clear busy when transitioning from running to idle (no active run)", () => {
    // Related scenario: if some code path later drops the active run
    // entirely (setting it to null), the hook still should not clear
    // busy based on the resulting idle state.
    act(() => {
      useRunStore.setState({ activeRun: makeActiveRun({ phase: "running" }) });
      useShellStore.setState({
        backendStatus: "busy",
        backendMessage: "Running...",
      });
    });

    const { rerender } = renderHook(() => useBackendBusyReset());

    expect(useShellStore.getState().backendStatus).toBe("busy");

    act(() => {
      useRunStore.setState({ activeRun: null });
    });
    rerender();

    // Phase now reads idle (activeRun is null). Hook should leave busy alone.
    expect(useShellStore.getState().backendStatus).toBe("busy");
  });

  it("clears busy when the active run transitions to cancelled", () => {
    act(() => {
      useRunStore.setState({ activeRun: makeActiveRun({ phase: "running" }) });
      useShellStore.setState({ backendStatus: "busy", backendMessage: "Running..." });
    });

    const { rerender } = renderHook(() => useBackendBusyReset());

    // Still running — should NOT clear.
    expect(useShellStore.getState().backendStatus).toBe("busy");

    act(() => {
      useRunStore.setState({ activeRun: makeActiveRun({ phase: "cancelled" }) });
    });
    rerender();

    expect(useShellStore.getState().backendStatus).toBe("ready");
  });

  it("clears busy when the active run transitions to success", () => {
    act(() => {
      useRunStore.setState({ activeRun: makeActiveRun({ phase: "running" }) });
      useShellStore.setState({ backendStatus: "busy" });
    });

    const { rerender } = renderHook(() => useBackendBusyReset());

    act(() => {
      useRunStore.setState({ activeRun: makeActiveRun({ phase: "success" }) });
    });
    rerender();

    expect(useShellStore.getState().backendStatus).toBe("ready");
  });

  it("clears busy when the active run transitions to failure", () => {
    act(() => {
      useRunStore.setState({ activeRun: makeActiveRun({ phase: "running" }) });
      useShellStore.setState({ backendStatus: "busy" });
    });

    const { rerender } = renderHook(() => useBackendBusyReset());

    act(() => {
      useRunStore.setState({ activeRun: makeActiveRun({ phase: "failure" }) });
    });
    rerender();

    expect(useShellStore.getState().backendStatus).toBe("ready");
  });

  it("does not touch backendStatus when it is not busy", () => {
    act(() => {
      useRunStore.setState({ activeRun: makeActiveRun({ phase: "failure" }) });
      useShellStore.setState({ backendStatus: "error", backendMessage: "Backend crashed" });
    });

    renderHook(() => useBackendBusyReset());

    // error should not be reset by this hook — it's only responsible
    // for releasing the busy lock.
    const state = useShellStore.getState();
    expect(state.backendStatus).toBe("error");
    expect(state.backendMessage).toBe("Backend crashed");
  });

  it("does not clear busy while the run is still in flight", () => {
    act(() => {
      useRunStore.setState({ activeRun: makeActiveRun({ phase: "running" }) });
      useShellStore.setState({ backendStatus: "busy" });
    });

    renderHook(() => useBackendBusyReset());

    expect(useShellStore.getState().backendStatus).toBe("busy");
  });

  it("does NOT clear busy on the SECOND run after the tool resets the stale activeRun (Fix R2-C1)", () => {
    // Fix R2-C1 regression: previously, on the second run of the same session,
    // the previous run's terminal phase ("success"/"cancelled"/"failure") was
    // still in the store when handleStartRun flipped backendStatus to "busy".
    // The hook would then see (terminal phase + busy) and instantly clear the
    // "Validating..." chip. The fix is in each tool's handleStartRun: call
    // resetDesktopRunSession() BEFORE setBackendState({busy}). This test
    // asserts the expected post-fix flow works correctly.
    //
    // Step 1: simulate the end-state of a previous run.
    act(() => {
      useRunStore.setState({ activeRun: makeActiveRun({ phase: "success" }) });
      useShellStore.setState({ backendStatus: "ready", backendMessage: null });
    });

    renderHook(() => useBackendBusyReset());

    // Step 2: user clicks Run again. The tool first resets the active run
    // (Fix R2-C1 line), THEN flips busy. Both updates happen synchronously.
    act(() => {
      useRunStore.setState({ activeRun: null });
      useShellStore.setState({
        backendStatus: "busy",
        backendMessage: "Validating run configuration...",
      });
    });

    // The busy chip should PERSIST — phase reads "idle" (activeRun is null),
    // idle is not a terminal phase, so the hook leaves busy alone.
    const state = useShellStore.getState();
    expect(state.backendStatus).toBe("busy");
    expect(state.backendMessage).toBe("Validating run configuration...");
  });

  it("regression: without the R2-C1 reset, a stale terminal phase clears busy on second run", () => {
    // Negative control for Fix R2-C1: if a caller forgets to reset activeRun
    // before flipping busy, the hook WILL clear the chip. This test pins that
    // behavior so if somebody later changes the hook to be more permissive,
    // they notice and update the tool resets consistently.
    act(() => {
      useRunStore.setState({ activeRun: makeActiveRun({ phase: "success" }) });
      useShellStore.setState({ backendStatus: "ready", backendMessage: null });
    });

    renderHook(() => useBackendBusyReset());

    // Simulate a buggy tool that flips busy WITHOUT resetting the active run.
    act(() => {
      useShellStore.setState({
        backendStatus: "busy",
        backendMessage: "Validating...",
      });
    });

    // The hook reads (phase="success" + busy) and clears busy. This is the
    // bug path the R2-C1 fix avoids by resetting activeRun first.
    expect(useShellStore.getState().backendStatus).toBe("ready");
  });
});
