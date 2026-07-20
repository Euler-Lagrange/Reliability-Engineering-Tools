import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SidecarRunEvent } from "../../contracts/sidecar";
import { MAX_LOG_LINES, useRunStore } from "../../stores/runStore";
import { patchFromRunEvent, useBackendRunLifecycle } from "./runLifecycle";

function statusEvent(runId: string, status: string): SidecarRunEvent {
  return {
    kind: "status",
    run_id: runId,
    payload: { status, stage: status, message: `${status}...` },
  } as unknown as SidecarRunEvent;
}

beforeEach(() => {
  useRunStore.setState({ activeRun: null });
});

describe("useBackendRunLifecycle", () => {
  it("returns an idle session when there is no active run", () => {
    const { result } = renderHook(() => useBackendRunLifecycle("dark_star_fmea"));

    expect(result.current.session.runId).toBeNull();
    expect(result.current.session.phase).toBe("idle");
    expect(result.current.session.logs).toEqual([]);
  });

  it("retains run state across hook unmount and remount for the same tool", () => {
    const { result, unmount } = renderHook(() => useBackendRunLifecycle("dark_star_fmea"));

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

    const { result: remounted } = renderHook(() => useBackendRunLifecycle("dark_star_fmea"));
    expect(remounted.current.session.runId).toBe("run_persistent_001");
    expect(remounted.current.session.phase).toBe("starting");
  });

  it("does not surface another tool's active run", () => {
    const { result: toolA } = renderHook(() => useBackendRunLifecycle("dark_star_fmea"));
    act(() => {
      toolA.current.beginAcceptedRun({
        run_id: "run_owned_by_fmea",
        mode: "desktop-bridge",
        session_generation: 1,
      });
    });

    const { result: toolB } = renderHook(() => useBackendRunLifecycle("bom_compare"));

    expect(toolA.current.session.runId).toBe("run_owned_by_fmea");
    expect(toolB.current.session.runId).toBeNull();
    expect(toolB.current.session.phase).toBe("idle");
  });

  it("resetSession only clears state when the active run belongs to the calling tool", () => {
    const { result: toolA } = renderHook(() => useBackendRunLifecycle("dark_star_fmea"));
    act(() => {
      toolA.current.beginAcceptedRun({
        run_id: "run_belongs_to_a",
        mode: "desktop-bridge",
        session_generation: 1,
      });
    });

    const { result: toolB } = renderHook(() => useBackendRunLifecycle("bom_compare"));

    act(() => {
      toolB.current.resetSession();
    });
    expect(useRunStore.getState().activeRun?.runId).toBe("run_belongs_to_a");

    act(() => {
      toolA.current.resetSession();
    });
    expect(useRunStore.getState().activeRun).toBeNull();
  });

  it("appendLog tracks truncation count beyond MAX_LOG_LINES", () => {
    const { result } = renderHook(() => useBackendRunLifecycle("dark_star_fmea"));

    act(() => {
      result.current.beginAcceptedRun({
        run_id: "run_log_truncation",
        mode: "desktop-bridge",
        session_generation: 1,
      });
    });

    act(() => {
      const append = useRunStore.getState().appendLog;
      for (let i = 0; i < MAX_LOG_LINES + 50; i += 1) {
        append(`line ${i}`);
      }
    });

    const state = useRunStore.getState().activeRun;
    expect(state).not.toBeNull();
    expect(state?.logs).toHaveLength(MAX_LOG_LINES);
    expect(state?.truncatedLogCount).toBe(50);
    expect(state!.logs[state!.logs.length - 1]).toBe(`line ${MAX_LOG_LINES + 49}`);
    expect(state!.logs[0]).toBe("line 50");
  });

  it("projects stored failure details into the managed session", () => {
    const { result } = renderHook(() => useBackendRunLifecycle("dark_star_fmea"));

    act(() => {
      result.current.beginAcceptedRun({
        run_id: "run_failure_projection",
        mode: "desktop-bridge",
        session_generation: 1,
      });
      useRunStore.getState().patchActiveRun({
        phase: "failure",
        errorCode: "KeyError",
        errorTraceback: "traceback lines",
      });
    });

    expect(result.current.session.phase).toBe("failure");
    expect(result.current.session.errorCode).toBe("KeyError");
    expect(result.current.session.errorTraceback).toBe("traceback lines");
  });
});

describe("patchFromRunEvent terminal guard", () => {
  function buildCurrent(runId: string, phase: string) {
    const { result } = renderHook(() => useBackendRunLifecycle("dark_star_fmea"));
    act(() => {
      result.current.beginAcceptedRun({
        run_id: runId,
        mode: "desktop-bridge",
        session_generation: 1,
      });
      useRunStore.getState().patchActiveRun({ phase: phase as never });
    });
    return useRunStore.getState().activeRun!;
  }

  it("ignores a late non-terminal status once the run is terminal (cancel-after-finish)", () => {
    const current = buildCurrent("run_cancel_after_finish", "success");
    const patch = patchFromRunEvent(current, statusEvent("run_cancel_after_finish", "cancelling"), (p) => p);
    expect(patch).toBeNull();
  });

  it("still progresses running -> cancelling normally", () => {
    const current = buildCurrent("run_cancelling_ok", "running");
    const patch = patchFromRunEvent(current, statusEvent("run_cancelling_ok", "cancelling"), (p) => p);
    expect(patch?.phase).toBe("cancelling");
  });

  it("keeps cancelling sticky when a late running status arrives", () => {
    const current = buildCurrent("run_sticky_cancelling", "cancelling");
    const patch = patchFromRunEvent(
      current,
      statusEvent("run_sticky_cancelling", "running"),
      (p) => p,
    );
    expect(patch).toBeNull();
  });

  it("rejects every status event after the run is disconnected", () => {
    const current = buildCurrent("run_disconnected", "disconnected");
    const patch = patchFromRunEvent(
      current,
      statusEvent("run_disconnected", "running"),
      (p) => p,
    );
    expect(patch).toBeNull();
  });

  it("does not block a terminal status when the phase is already terminal", () => {
    // terminal current + terminal incoming: the guard must only drop late
    // NON-terminal statuses, so a (duplicate) terminal status still applies.
    const current = buildCurrent("run_terminal_dup", "cancelled");
    const patch = patchFromRunEvent(current, statusEvent("run_terminal_dup", "cancelled"), (p) => p);
    expect(patch?.phase).toBe("cancelled");
  });

  it("keeps the previous phase and logs an unknown forwarded status", () => {
    const current = buildCurrent("run_unknown_status", "running");
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);

    const patch = patchFromRunEvent(
      current,
      statusEvent("run_unknown_status", "paused_by_future_backend"),
      (payload) => payload,
    );

    expect(patch?.phase).toBe("running");
    expect(consoleError).toHaveBeenCalledWith(
      "Ignoring unknown backend run status: paused_by_future_backend",
    );
    consoleError.mockRestore();
  });
});
