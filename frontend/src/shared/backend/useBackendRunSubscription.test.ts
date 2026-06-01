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
