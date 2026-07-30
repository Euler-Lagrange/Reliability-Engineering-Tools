import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FmeaTool } from "./fmea/FmeaTool";
import { FailureRateTool } from "./failure-rate/FailureRateTool";
import { useGlobalLogStore } from "../stores/globalLogStore";
import { useNotificationStore } from "../stores/notificationStore";
import { useRunStore } from "../stores/runStore";

/**
 * Browser-mock run-lifecycle integration (QA sweep 2026-07-30 finding
 * #4: every mirrorMockRun* call site in the tools was exercised only by
 * the mockRunMirror unit test — no test observed a demo run actually
 * driving the shared stores, which is how the cross-tool eviction bug
 * shipped). jsdom has no Tauri globals, so these tools run browser-mock
 * without any backendClient mocking — the same mode the Vite preview
 * uses.
 */

function resetStores() {
  useRunStore.getState().clear();
  useGlobalLogStore.getState().clear();
  useNotificationStore.getState().dismissAll();
}

beforeEach(() => {
  resetStores();
  vi.useFakeTimers();
});

afterEach(() => {
  act(() => {
    vi.runOnlyPendingTimers();
  });
  vi.useRealTimers();
  resetStores();
});

describe("browser-mock run lifecycle", () => {
  it("mirrors a demo run into the shared stores through to success", () => {
    render(<FmeaTool />);

    fireEvent.click(screen.getByRole("button", { name: /Start demo run/i }));

    const started = useRunStore.getState().activeRun;
    expect(started?.toolId).toBe("dark_star_fmea");
    expect(started?.phase).toBe("running");

    // 5 replay events + the result tick, 520 ms apart. Step one tick per
    // act(): each timer's state update must flush so the effect can
    // schedule the NEXT tick — a single big advance fires only the first.
    for (let tick = 0; tick < 8; tick += 1) {
      act(() => {
        vi.advanceTimersByTime(520);
      });
    }

    const settled = useRunStore.getState().activeRun;
    expect(settled?.phase).toBe("success");
    expect(settled?.finishedAt).not.toBeNull();

    // Fixture logs streamed to the Global Log strip.
    expect(useGlobalLogStore.getState().entries.length).toBeGreaterThan(0);

    // Completion toast with the per-workflow output file.
    const toasts = useNotificationStore.getState().notifications;
    expect(
      toasts.some(
        (toast) =>
          toast.tone === "success" &&
          (toast.detail ?? "").includes("PiecePartFMEA_Standard"),
      ),
    ).toBe(true);
  });

  it("blocks a second tool's demo start while a run is live (cross-tool guard)", () => {
    render(
      <>
        <FmeaTool />
        <FailureRateTool />
      </>,
    );

    fireEvent.click(screen.getByRole("button", { name: /Start demo run/i }));
    const firstRunId = useRunStore.getState().activeRun?.runId;
    expect(firstRunId).toBeTruthy();

    // QA sweep 2026-07-30 finding #1: this second start used to evict
    // the FMEA run from the single-slot store, reverting its Review
    // drawer to "No run has started".
    fireEvent.click(screen.getByRole("button", { name: /Link Rates/i }));

    expect(useRunStore.getState().activeRun?.runId).toBe(firstRunId);
    const toasts = useNotificationStore.getState().notifications;
    expect(
      toasts.some((toast) => toast.title === "Another run is active"),
    ).toBe(true);
  });
});
