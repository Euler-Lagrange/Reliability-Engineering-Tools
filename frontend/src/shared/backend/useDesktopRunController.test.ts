import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SidecarRunEvent } from "../../contracts/sidecar";
import { useNotificationStore } from "../../stores/notificationStore";
import { useRunStore } from "../../stores/runStore";
import { useShellStore } from "../../stores/shellStore";

let capturedHandler: ((event: SidecarRunEvent) => void) | null = null;

vi.mock("./client", () => ({
  backendClient: {
    runtimeMode: "desktop-bridge",
    subscribeToRunEvents: vi.fn((handler: (event: SidecarRunEvent) => void) => {
      capturedHandler = handler;
      return Promise.resolve(() => {
        capturedHandler = null;
      });
    }),
    cancelRun: vi.fn(),
  },
}));

// Imported AFTER the mock so the hooks bind to the mocked client.
import { useBackendRunSubscription } from "./useBackendRunSubscription";
import { useDesktopRunController } from "./useDesktopRunController";

const options = {
  successMessage: (file: string) => `Report written to ${file}.`,
  successTitle: "BOM comparison complete",
  failureTitle: "BOM comparison failed",
  cancelledTitle: "BOM comparison cancelled",
  mockRunMode: "idle" as const,
  mockTimeline: [],
  mockProgress: 0,
  mockRunResult: null,
  mockLogLines: [],
  mockCancelledNotice: null,
};

function renderController() {
  return renderHook(() => {
    useBackendRunSubscription();
    return useDesktopRunController("bom_compare", options);
  });
}

function successResultEvent(runId: string): SidecarRunEvent {
  return {
    kind: "result",
    run_id: runId,
    payload: {
      status: "success",
      title: "BOM comparison complete",
      summary: "Compared.",
      output_file: "C:\\out\\r.xlsx",
      primary_metric: "1 difference",
      secondary_metric: "ok",
      notes: [],
      log_lines: [],
      row_count: 1,
      warning_count: 0,
      no_match_count: 0,
      mode: "desktop-bridge",
    },
  } as unknown as SidecarRunEvent;
}

function successStatusEvent(runId: string): SidecarRunEvent {
  return {
    kind: "status",
    run_id: runId,
    payload: { status: "success", stage: "Complete", message: "Run completed successfully." },
  } as unknown as SidecarRunEvent;
}

beforeEach(() => {
  capturedHandler = null;
  useRunStore.setState({ activeRun: null });
  useNotificationStore.setState({ notifications: [] });
  useShellStore.setState({ backendStatus: "ready", backendMessage: null } as never);
});

describe("useDesktopRunController terminal handling", () => {
  it("fires the success toast + shell message once, on the result event (status:success arrives first)", () => {
    const { result } = renderController();

    act(() => {
      result.current.armTerminalHandler();
      result.current.beginAcceptedRun({
        run_id: "run_t1",
        mode: "desktop-bridge",
        session_generation: 1,
      });
    });

    // The backend emits status:success FIRST (result still null).
    act(() => {
      capturedHandler?.(successStatusEvent("run_t1"));
    });
    // No toast yet — the controller must wait for the result event.
    expect(useNotificationStore.getState().notifications).toHaveLength(0);

    // The result event arrives second and carries the payload.
    act(() => {
      capturedHandler?.(successResultEvent("run_t1"));
    });

    const notes = useNotificationStore.getState().notifications;
    expect(notes).toHaveLength(1);
    expect(notes[0].tone).toBe("success");
    expect(notes[0].title).toBe("BOM comparison complete");
    expect(notes[0].detail).toBe("C:\\out\\r.xlsx");
    expect(useShellStore.getState().backendMessage).toBe("Report written to C:\\out\\r.xlsx.");
  });

  it("maps warning counts into the run result and qualifies the success toast", () => {
    const { result } = renderController();

    act(() => {
      result.current.armTerminalHandler();
      result.current.beginAcceptedRun({
        run_id: "run_w1",
        mode: "desktop-bridge",
        session_generation: 1,
      });
    });

    act(() => {
      capturedHandler?.(successStatusEvent("run_w1"));
    });
    act(() => {
      const event = successResultEvent("run_w1");
      (event.payload as Record<string, unknown>).warning_count = 5;
      (event.payload as Record<string, unknown>).no_match_count = 2;
      capturedHandler?.(event);
    });

    // The run result carries structured counts for the panel...
    expect(result.current.panelRunResult?.warningCount).toBe(5);
    expect(result.current.panelRunResult?.noMatchCount).toBe(2);
    // ...and the success toast is no longer an unqualified file path.
    const notes = useNotificationStore.getState().notifications;
    expect(notes).toHaveLength(1);
    expect(notes[0].tone).toBe("success");
    expect(notes[0].detail).toContain("C:\\out\\r.xlsx");
    expect(notes[0].detail).toMatch(/5 warning/i);
  });

  it("fires once across separate status/result events and ignores a duplicate result", () => {
    const { result } = renderController();

    act(() => {
      result.current.armTerminalHandler();
      result.current.beginAcceptedRun({
        run_id: "run_t2",
        mode: "desktop-bridge",
        session_generation: 1,
      });
    });

    // status:success first (no toast yet), then the result event fires it once.
    // Separate acts are deliberate: a single batched act collapses the two into
    // one render where result is already present, masking the bug.
    act(() => {
      capturedHandler?.(successStatusEvent("run_t2"));
    });
    act(() => {
      capturedHandler?.(successResultEvent("run_t2"));
    });
    expect(useNotificationStore.getState().notifications).toHaveLength(1);

    // A duplicate result event must not re-fire (handled-key idempotency).
    act(() => {
      capturedHandler?.(successResultEvent("run_t2"));
    });
    expect(useNotificationStore.getState().notifications).toHaveLength(1);
  });

  it("truthfully qualifies a completed run whose result payload cannot be displayed", () => {
    const { result } = renderController();

    act(() => {
      result.current.armTerminalHandler();
      result.current.beginAcceptedRun({
        run_id: "run_bad_result",
        mode: "desktop-bridge",
        session_generation: 1,
      });
    });

    act(() => {
      capturedHandler?.(successStatusEvent("run_bad_result"));
    });
    expect(useRunStore.getState().activeRun?.phase).toBe("success");
    expect(useNotificationStore.getState().notifications).toHaveLength(0);

    act(() => {
      capturedHandler?.({
        kind: "result",
        run_id: "run_bad_result",
        payload: {
          status: "success",
          title: "BOM comparison complete",
          summary: "Compared.",
        },
      } as unknown as SidecarRunEvent);
    });

    expect(useRunStore.getState().activeRun).toMatchObject({
      phase: "failure",
      errorCode: "RESULT_SCHEMA_MISMATCH",
    });
    expect(result.current.panelErrorCode).toBe("RESULT_SCHEMA_MISMATCH");
    const notes = useNotificationStore.getState().notifications;
    expect(notes).toHaveLength(1);
    expect(notes[0].tone).toBe("error");
    expect(notes[0].title).toBe("Run completed, but the result could not be displayed");
    expect(notes[0].detail).toBe(
      "Run finished, but the result could not be read; check the run log.",
    );
  });

  it("resetSessionUnlessLive preserves a cancelling run", () => {
    const { result } = renderController();

    act(() => {
      result.current.beginAcceptedRun({
        run_id: "run_cancelling",
        mode: "desktop-bridge",
        session_generation: 1,
      });
      useRunStore.getState().patchActiveRun({ phase: "cancelling" });
    });

    act(() => {
      result.current.resetSessionUnlessLive();
    });

    expect(useRunStore.getState().activeRun?.runId).toBe("run_cancelling");
    expect(useRunStore.getState().activeRun?.phase).toBe("cancelling");
  });
});
