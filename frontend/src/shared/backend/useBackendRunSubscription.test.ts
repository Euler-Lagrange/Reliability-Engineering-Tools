import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useGlobalLogStore } from "../../stores/globalLogStore";
import { useRunStore } from "../../stores/runStore";
import { useBackendRunLifecycle } from "./runLifecycle";
import { useBackendRunSubscription } from "./useBackendRunSubscription";

let runHandler: ((event: unknown) => void) | null = null;

vi.mock("./client", () => ({
  backendClient: {
    runtimeMode: "desktop-bridge" as const,
    subscribeToRunEvents: vi.fn(async (handler: (event: unknown) => void) => {
      runHandler = handler;
      return () => {
        runHandler = null;
      };
    }),
  },
}));

beforeEach(() => {
  useRunStore.setState({ activeRun: null });
  useGlobalLogStore.setState({
    entries: [],
    totalAppended: 0,
    truncatedCount: 0,
    isVisible: false,
    filterMode: "all",
  });
  runHandler = null;
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("useBackendRunSubscription", () => {
  it("registers an unclaimed run from ack and applies its following events", () => {
    renderHook(() => useBackendRunSubscription());

    act(() => {
      runHandler?.({
        protocol_version: "0.1.0",
        id: "evt_ack_fallback",
        kind: "ack",
        request_id: "req_ack_fallback",
        run_id: "run_ack_fallback",
        timestamp: "2026-07-13T18:00:00Z",
        payload: {
          accepted: true,
          run_id: "run_ack_fallback",
          mode: "desktop-bridge",
          session_generation: 8,
          workflow_id: "bom_compare_custom",
        },
      });
    });

    expect(useRunStore.getState().activeRun).toMatchObject({
      runId: "run_ack_fallback",
      toolId: "bom_compare",
      sessionGeneration: 8,
      phase: "starting",
      startedAt: "2026-07-13T18:00:00Z",
    });

    act(() => {
      runHandler?.({
        kind: "status",
        run_id: "run_ack_fallback",
        payload: {
          status: "running",
          stage: "Comparing",
          message: "Comparing BOM rows.",
        },
      });
      runHandler?.({
        kind: "result",
        run_id: "run_ack_fallback",
        payload: {
          status: "success",
          title: "Run complete",
          summary: "Comparison generated",
          output_file: "C:\\output\\comparison.xlsx",
          primary_metric: "42 rows",
          secondary_metric: "0 warnings",
          notes: [],
          log_lines: [],
          row_count: 42,
          warning_count: 0,
          no_match_count: 0,
          mode: "desktop-bridge",
        },
      });
    });

    expect(useRunStore.getState().activeRun).toMatchObject({
      runId: "run_ack_fallback",
      toolId: "bom_compare",
      phase: "success",
      progress: 100,
    });
  });

  it("replaces an inactive run from another tool when a new ack wins the invoke race", () => {
    renderHook(() => useBackendRunSubscription());
    const { result } = renderHook(() => useBackendRunLifecycle("dark_star_fmea"));

    act(() => {
      result.current.beginAcceptedRun({
        run_id: "run_old_fmea",
        mode: "desktop-bridge",
        session_generation: 10,
      });
      useRunStore.getState().patchActiveRun({
        phase: "success",
        progress: 100,
        finishedAt: "2026-07-13T17:59:00Z",
      });
      runHandler?.({
        protocol_version: "0.1.0",
        id: "evt_cross_tool_ack",
        kind: "ack",
        request_id: "req_cross_tool_ack",
        run_id: "run_new_bom",
        timestamp: "2026-07-13T18:03:00Z",
        payload: {
          accepted: true,
          run_id: "run_new_bom",
          mode: "desktop-bridge",
          session_generation: 10,
          workflow_id: "bom_compare_custom",
        },
      });
      runHandler?.({
        kind: "result",
        run_id: "run_new_bom",
        payload: {
          status: "success",
          title: "Run complete",
          summary: "Comparison generated",
          output_file: "C:\\output\\comparison.xlsx",
          primary_metric: "42 rows",
          secondary_metric: "0 warnings",
          notes: [],
          log_lines: [],
          row_count: 42,
          warning_count: 0,
          no_match_count: 0,
          mode: "desktop-bridge",
        },
      });
    });

    expect(useRunStore.getState().activeRun).toMatchObject({
      runId: "run_new_bom",
      toolId: "bom_compare",
      phase: "success",
    });
  });

  it("never lets an ack replace a different live run", () => {
    renderHook(() => useBackendRunSubscription());
    const { result } = renderHook(() => useBackendRunLifecycle("dark_star_fmea"));

    act(() => {
      result.current.beginAcceptedRun({
        run_id: "run_live_fmea",
        mode: "desktop-bridge",
        session_generation: 11,
      });
      useRunStore.getState().patchActiveRun({ phase: "running" });
    });
    const liveRun = useRunStore.getState().activeRun;

    act(() => {
      runHandler?.({
        protocol_version: "0.1.0",
        id: "evt_blocked_ack",
        kind: "ack",
        request_id: "req_blocked_ack",
        run_id: "run_unexpected_bom",
        timestamp: "2026-07-13T18:04:00Z",
        payload: {
          accepted: true,
          run_id: "run_unexpected_bom",
          mode: "desktop-bridge",
          session_generation: 11,
          workflow_id: "bom_compare_custom",
        },
      });
    });

    expect(useRunStore.getState().activeRun).toBe(liveRun);
  });

  it("does not apply a duplicate ack to an already-registered run", () => {
    renderHook(() => useBackendRunSubscription());
    const { result } = renderHook(() => useBackendRunLifecycle("bom_compare"));

    act(() => {
      result.current.beginAcceptedRun({
        run_id: "run_duplicate_ack",
        mode: "desktop-bridge",
        session_generation: 9,
      });
      useRunStore.getState().patchActiveRun({
        phase: "running",
        progress: 31,
        statusMessage: "Work already accumulated.",
      });
      useRunStore.getState().appendLog("Existing log line");
    });
    const beforeAck = useRunStore.getState().activeRun;

    act(() => {
      runHandler?.({
        protocol_version: "0.1.0",
        id: "evt_duplicate_ack",
        kind: "ack",
        request_id: "req_duplicate_ack",
        run_id: "run_duplicate_ack",
        timestamp: "2026-07-13T18:01:00Z",
        payload: {
          accepted: true,
          run_id: "run_duplicate_ack",
          mode: "desktop-bridge",
          session_generation: 9,
          workflow_id: "bom_compare_custom",
        },
      });
    });

    expect(useRunStore.getState().activeRun).toBe(beforeAck);
  });

  it("preserves ack-first phase and logs when the invoke response registers the same run", () => {
    renderHook(() => useBackendRunSubscription());
    const { result } = renderHook(() => useBackendRunLifecycle("bom_compare"));

    act(() => {
      runHandler?.({
        protocol_version: "0.1.0",
        id: "evt_ack_first",
        kind: "ack",
        request_id: "req_ack_first",
        run_id: "run_ack_first",
        timestamp: "2026-07-13T18:02:00Z",
        payload: {
          accepted: true,
          run_id: "run_ack_first",
          mode: "desktop-bridge",
          session_generation: 10,
          workflow_id: "bom_compare_custom",
        },
      });
      runHandler?.({
        kind: "status",
        run_id: "run_ack_first",
        payload: {
          status: "running",
          stage: "Comparing",
          message: "Comparison started.",
        },
      });
      runHandler?.({
        kind: "progress",
        run_id: "run_ack_first",
        payload: {
          stage: "Comparing",
          message: "Comparison is 37% complete.",
          percent: 37,
        },
      });
      runHandler?.({
        kind: "log",
        run_id: "run_ack_first",
        payload: {
          level: "info",
          line: "Accumulated before invoke returned",
        },
      });
    });
    const beforeInvokeRegistration = useRunStore.getState().activeRun;

    act(() => {
      result.current.beginAcceptedRun({
        run_id: "run_ack_first",
        mode: "desktop-bridge",
        session_generation: 10,
      });
    });

    expect(useRunStore.getState().activeRun).toBe(beforeInvokeRegistration);
    expect(useRunStore.getState().activeRun).toMatchObject({
      phase: "running",
      progress: 37,
      stage: "Comparing",
      logs: ["Accumulated before invoke returned"],
      truncatedLogCount: 0,
    });
  });

  it("keeps a run updating after the originating tool unmounts", () => {
    renderHook(() => useBackendRunSubscription());
    const { result: toolA, unmount } = renderHook(() => useBackendRunLifecycle("dark_star_fmea"));

    act(() => {
      toolA.current.beginAcceptedRun({
        run_id: "run_cross_tool_001",
        mode: "desktop-bridge",
        session_generation: 3,
      });
    });

    unmount();

    act(() => {
      runHandler?.({
        kind: "progress",
        run_id: "run_cross_tool_001",
        payload: {
          stage: "Working",
          message: "Halfway there",
          percent: 50,
        },
      });
      runHandler?.({
        kind: "result",
        run_id: "run_cross_tool_001",
        payload: {
          status: "success",
          title: "Run complete",
          summary: "Report generated",
          output_file: "C:\\output\\report.xlsx",
          primary_metric: "42 rows",
          secondary_metric: "0 warnings",
          notes: ["Looks good"],
          log_lines: [],
          row_count: 42,
          warning_count: 0,
          no_match_count: 0,
          mode: "desktop-bridge",
        },
      });
    });

    expect(useRunStore.getState().activeRun?.phase).toBe("success");
    expect(useRunStore.getState().activeRun?.progress).toBe(100);

    const { result: remounted } = renderHook(() => useBackendRunLifecycle("dark_star_fmea"));
    expect(remounted.current.session.phase).toBe("success");
    expect(remounted.current.session.result).toMatchObject({
      output_file: "C:\\output\\report.xlsx",
      status: "success",
    });
  });

  it("still captures global logs through the shell-level subscription", () => {
    renderHook(() => useBackendRunSubscription());
    const { result } = renderHook(() => useBackendRunLifecycle("failure_rate"));

    act(() => {
      result.current.beginAcceptedRun({
        run_id: "run_log_001",
        mode: "desktop-bridge",
        session_generation: 4,
      });
    });

    act(() => {
      runHandler?.({
        kind: "log",
        run_id: "run_log_001",
        payload: {
          level: "warning",
          line: "Normalizing failure-rate workbook",
        },
      });
    });

    expect(useRunStore.getState().activeRun?.logs).toEqual(["Normalizing failure-rate workbook"]);
    expect(useGlobalLogStore.getState().entries).toHaveLength(1);
    expect(useGlobalLogStore.getState().entries[0]).toMatchObject({
      toolId: "failure_rate",
      runId: "run_log_001",
      level: "warning",
      line: "Normalizing failure-rate workbook",
    });
  });

  it("drives the run to failure when a result payload fails schema validation", () => {
    renderHook(() => useBackendRunSubscription());
    const { result } = renderHook(() => useBackendRunLifecycle("dark_star_fmea"));

    act(() => {
      result.current.beginAcceptedRun({
        run_id: "run_bad_result",
        mode: "desktop-bridge",
        session_generation: 7,
      });
    });

    // A result envelope missing required fields (mode, log_lines, row_count, ...)
    // must NOT throw out of the listener and strand the run; it must drive a
    // terminal failure with the validation error surfaced. (Finding H-B.)
    act(() => {
      runHandler?.({
        kind: "result",
        run_id: "run_bad_result",
        payload: {
          status: "success",
          title: "Run complete",
          summary: "Report generated",
        },
      });
    });

    const active = useRunStore.getState().activeRun;
    expect(active?.phase).toBe("failure");
    expect(active?.errorCode).toBe("RESULT_SCHEMA_MISMATCH");
    expect(
      useGlobalLogStore.getState().entries.some((entry) =>
        entry.line.includes("failed validation"),
      ),
    ).toBe(true);
  });
});
