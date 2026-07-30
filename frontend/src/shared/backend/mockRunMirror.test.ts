import { beforeEach, describe, expect, test } from "vitest";
import type { RunEventTemplate, RunResult } from "../../app/types";
import { useGlobalLogStore } from "../../stores/globalLogStore";
import { useNotificationStore } from "../../stores/notificationStore";
import { useRunStore } from "../../stores/runStore";
import {
  mirrorMockRunCancelled,
  mirrorMockRunEvent,
  mirrorMockRunStart,
  mirrorMockRunTerminal,
} from "./mockRunMirror";

const template: RunEventTemplate = {
  id: "e1",
  title: "Run comparison",
  detail: "Comparing RefDes coverage between files.",
  progress: 60,
  logs: ["Compared 216 base RefDes — 3 missing in BOM, 1 extra."],
};

const successResult: RunResult = {
  status: "success",
  title: "BOM comparison complete",
  summary: "3 missing in BOM, 1 extra in BOM.",
  outputFile: "BomCompare_Group_20260406.xlsx",
  primaryMetric: "3 missing",
  secondaryMetric: "1 warning",
  notes: [],
};

beforeEach(() => {
  useRunStore.getState().clear();
  useGlobalLogStore.getState().clear();
  useNotificationStore.getState().dismissAll();
});

describe("mockRunMirror", () => {
  test("start mirrors a running run into the shared store (Review drawer source)", () => {
    const runId = mirrorMockRunStart("bom_compare");
    const activeRun = useRunStore.getState().activeRun;
    expect(activeRun?.runId).toBe(runId);
    expect(activeRun?.toolId).toBe("bom_compare");
    expect(activeRun?.phase).toBe("running");
  });

  test("events patch progress/stage and stream fixture logs to the Global Log", () => {
    const runId = mirrorMockRunStart("bom_compare");
    mirrorMockRunEvent("bom_compare", runId, template);

    const activeRun = useRunStore.getState().activeRun;
    expect(activeRun?.progress).toBe(60);
    expect(activeRun?.stage).toBe("Run comparison");

    const entries = useGlobalLogStore.getState().entries;
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({
      toolId: "bom_compare",
      runId,
      level: "info",
      line: "Compared 216 base RefDes — 3 missing in BOM, 1 extra.",
    });
  });

  test("a stale runId never patches a newer run", () => {
    const oldRunId = mirrorMockRunStart("bom_compare");
    const newRunId = mirrorMockRunStart("bom_compare");
    mirrorMockRunEvent("bom_compare", oldRunId, template);
    const activeRun = useRunStore.getState().activeRun;
    expect(activeRun?.runId).toBe(newRunId);
    expect(activeRun?.progress).toBe(0);
  });

  test("a stale runId is fully silent at terminal — no patch, log, or toast", () => {
    // QA sweep 2026-07-30 finding #2: the terminal mirror used to guard
    // only the store patch, so an evicted run still toasted its
    // completion while its cancel stayed silent. All three mirrors are
    // now symmetric.
    const oldRunId = mirrorMockRunStart("bom_compare");
    const newRunId = mirrorMockRunStart("bom_compare");
    mirrorMockRunTerminal("bom_compare", oldRunId, successResult);

    const activeRun = useRunStore.getState().activeRun;
    expect(activeRun?.runId).toBe(newRunId);
    expect(activeRun?.phase).toBe("running");
    expect(useNotificationStore.getState().notifications).toHaveLength(0);
    expect(useGlobalLogStore.getState().entries).toHaveLength(0);
  });

  test("terminal success settles the run, logs a closing line, and toasts", () => {
    const runId = mirrorMockRunStart("bom_compare");
    mirrorMockRunTerminal("bom_compare", runId, successResult);

    const activeRun = useRunStore.getState().activeRun;
    expect(activeRun?.phase).toBe("success");
    expect(activeRun?.finishedAt).not.toBeNull();

    const toasts = useNotificationStore.getState().notifications;
    expect(toasts).toHaveLength(1);
    expect(toasts[0]).toMatchObject({
      tone: "success",
      title: "BOM comparison complete",
      detail: "BomCompare_Group_20260406.xlsx",
    });
  });

  test("warnings qualify the success toast detail, never the tone", () => {
    const runId = mirrorMockRunStart("failure_rate");
    mirrorMockRunTerminal("failure_rate", runId, {
      ...successResult,
      title: "Failure rate linking complete",
      outputFile: "FailureRate_Link.xlsx",
      warningCount: 12,
    });

    const toasts = useNotificationStore.getState().notifications;
    expect(toasts[0]).toMatchObject({
      tone: "success",
      detail: "FailureRate_Link.xlsx — 12 warning(s) captured in the output workbook",
    });
  });

  test("failure results toast as errors with the summary", () => {
    const runId = mirrorMockRunStart("dark_star_fmea");
    mirrorMockRunTerminal("dark_star_fmea", runId, {
      ...successResult,
      status: "failure",
      title: "Planner review required",
      summary: "A protected sheet blocks automated insertion.",
    });

    expect(useRunStore.getState().activeRun?.phase).toBe("failure");
    const toasts = useNotificationStore.getState().notifications;
    expect(toasts[0]).toMatchObject({
      tone: "error",
      title: "Planner review required",
      detail: "A protected sheet blocks automated insertion.",
    });
  });

  test("cancel settles the run as cancelled without a toast", () => {
    const runId = mirrorMockRunStart("refdes_extractor");
    mirrorMockRunCancelled("refdes_extractor", runId);

    expect(useRunStore.getState().activeRun?.phase).toBe("cancelled");
    expect(useNotificationStore.getState().notifications).toHaveLength(0);
    // The cancellation itself is logged.
    const entries = useGlobalLogStore.getState().entries;
    expect(entries.at(-1)?.line).toBe("Run cancelled by the operator.");
  });
});
