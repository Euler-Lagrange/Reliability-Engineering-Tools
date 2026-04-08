import { afterEach, beforeEach, describe, expect, test } from "vitest";
import {
  MAX_GLOBAL_LOG_ENTRIES,
  formatGlobalLogEntry,
  useGlobalLogStore,
} from "./globalLogStore";

describe("globalLogStore", () => {
  beforeEach(() => {
    useGlobalLogStore.setState({
      entries: [],
      totalAppended: 0,
      truncatedCount: 0,
      isVisible: false,
      filterMode: "all",
    });
  });

  afterEach(() => {
    useGlobalLogStore.setState({
      entries: [],
      totalAppended: 0,
      truncatedCount: 0,
      isVisible: false,
      filterMode: "all",
    });
  });

  test("appendLog stamps the entry with id, timestamp, and pushes onto the buffer", () => {
    useGlobalLogStore.getState().appendLog({
      toolId: "dark_star_fmea",
      runId: "run-abc",
      level: "info",
      line: "hello",
    });

    const state = useGlobalLogStore.getState();
    expect(state.entries).toHaveLength(1);
    expect(state.entries[0]).toMatchObject({
      toolId: "dark_star_fmea",
      runId: "run-abc",
      level: "info",
      line: "hello",
    });
    expect(state.entries[0].id).toBeGreaterThan(0);
    expect(state.entries[0].timestamp).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(state.totalAppended).toBe(1);
    expect(state.truncatedCount).toBe(0);
  });

  test("ring buffer caps at MAX_GLOBAL_LOG_ENTRIES and tracks truncatedCount", () => {
    const append = useGlobalLogStore.getState().appendLog;
    const overflow = 10;
    for (let i = 0; i < MAX_GLOBAL_LOG_ENTRIES + overflow; i += 1) {
      append({
        toolId: "bom_compare",
        runId: null,
        level: "debug",
        line: `line ${i}`,
      });
    }
    const state = useGlobalLogStore.getState();
    expect(state.entries).toHaveLength(MAX_GLOBAL_LOG_ENTRIES);
    expect(state.totalAppended).toBe(MAX_GLOBAL_LOG_ENTRIES + overflow);
    expect(state.truncatedCount).toBe(overflow);
    // Buffer is FIFO: oldest entries dropped first.
    expect(state.entries[0].line).toBe(`line ${overflow}`);
    expect(state.entries[state.entries.length - 1].line).toBe(
      `line ${MAX_GLOBAL_LOG_ENTRIES + overflow - 1}`,
    );
  });

  test("clear empties the buffer and resets counters", () => {
    const append = useGlobalLogStore.getState().appendLog;
    append({ toolId: "failure_rate", runId: null, level: "info", line: "a" });
    append({ toolId: "failure_rate", runId: null, level: "warning", line: "b" });

    useGlobalLogStore.getState().clear();
    const state = useGlobalLogStore.getState();
    expect(state.entries).toHaveLength(0);
    expect(state.totalAppended).toBe(0);
    expect(state.truncatedCount).toBe(0);
  });

  test("toggleVisible flips the visibility flag", () => {
    expect(useGlobalLogStore.getState().isVisible).toBe(false);
    useGlobalLogStore.getState().toggleVisible();
    expect(useGlobalLogStore.getState().isVisible).toBe(true);
    useGlobalLogStore.getState().toggleVisible();
    expect(useGlobalLogStore.getState().isVisible).toBe(false);
  });

  test("setFilterMode switches between all and active", () => {
    expect(useGlobalLogStore.getState().filterMode).toBe("all");
    useGlobalLogStore.getState().setFilterMode("active");
    expect(useGlobalLogStore.getState().filterMode).toBe("active");
    useGlobalLogStore.getState().setFilterMode("all");
    expect(useGlobalLogStore.getState().filterMode).toBe("all");
  });

  test("formatGlobalLogEntry produces a stable, scannable line format", () => {
    const formatted = formatGlobalLogEntry({
      id: 42,
      toolId: "refdes_extractor",
      runId: "run-1234abcd-ef56",
      level: "warning",
      line: "Pin variant U200-X inherited from U200",
      timestamp: "2026-04-08T12:34:56.789Z",
    });
    // Format: HH:MM:SS LEVEL [tool] (run-prefix) message
    expect(formatted).toContain("12:34:56");
    expect(formatted).toContain("WARNING");
    expect(formatted).toContain("[refdes_extractor]");
    expect(formatted).toContain("(run-1234)");
    expect(formatted).toContain("Pin variant U200-X inherited from U200");
  });
});
