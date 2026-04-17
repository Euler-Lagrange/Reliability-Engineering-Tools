import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { RunStatePanel } from "./RunStatePanel";
import type { RunEvent } from "../app/types";

const noopTimeline: RunEvent[] = [];

function renderPanel(overrides: Partial<React.ComponentProps<typeof RunStatePanel>> = {}) {
  const defaults: React.ComponentProps<typeof RunStatePanel> = {
    runMode: "idle",
    progress: 0,
    timeline: noopTimeline,
    result: null,
    onStart: vi.fn(),
    onCancel: vi.fn(),
    cancelledNotice: null,
    startLabel: "Start demo run",
  };
  return render(<RunStatePanel {...defaults} {...overrides} />);
}

describe("RunStatePanel", () => {
  test("renders the start button with the configured label", () => {
    renderPanel({ startLabel: "Start demo run" });
    expect(screen.getByRole("button", { name: "Start demo run" })).toBeInTheDocument();
  });

  test("renders a determinate progress bar when percent is provided", () => {
    renderPanel({ runMode: "running", percent: 42, stageLabel: "Parsing BOM" });
    const bar = screen.getByRole("progressbar", { name: "Run progress" });
    expect(bar).toHaveAttribute("aria-valuenow", "42");
    // Determinate mode does NOT carry the indeterminate modifier class.
    expect(bar.className).not.toContain("progress-shell--indeterminate");
    // The metadata line surfaces the percent + stage label.
    expect(screen.getByText(/42%/)).toBeInTheDocument();
    expect(screen.getByText(/Parsing BOM/)).toBeInTheDocument();
  });

  test("renders an indeterminate stripe when percent is undefined and run is active", () => {
    renderPanel({ runMode: "running", percent: undefined });
    const bar = screen.getByRole("progressbar", { name: "Run progress" });
    expect(bar.className).toContain("progress-shell--indeterminate");
    // aria-valuenow is intentionally omitted in indeterminate mode.
    expect(bar).not.toHaveAttribute("aria-valuenow");
    expect(screen.getByText(/Working/)).toBeInTheDocument();
  });

  test("renders eta and stage metadata when provided", () => {
    renderPanel({
      runMode: "running",
      percent: 25,
      etaSeconds: 18,
      stageLabel: "Reading sheets",
    });
    expect(screen.getByText(/25%/)).toBeInTheDocument();
    expect(screen.getByText(/~18s remaining/)).toBeInTheDocument();
    expect(screen.getByText(/Reading sheets/)).toBeInTheDocument();
  });

  test("HoldButton is rendered as the cancel control during a run", () => {
    renderPanel({ runMode: "running", percent: 10 });
    const cancelButton = screen.getByRole("button", { name: "Cancel" });
    // The HoldButton renders a regular <button> with the cancel label,
    // not the legacy "Cancel run" / confirm-tap pair.
    expect(cancelButton).toBeInTheDocument();
    expect(cancelButton).not.toBeDisabled();
  });

  test("renders an output folder action for completed runs", async () => {
    const user = userEvent.setup();
    const onRevealOutput = vi.fn();

    renderPanel({
      result: {
        status: "success",
        title: "Workbook written",
        summary: "Created a new workbook successfully.",
        outputFile: "C:\\reports\\output.xlsx",
        primaryMetric: "42 rows",
        secondaryMetric: "0 warnings",
        notes: [],
      },
      onRevealOutput,
    });

    await user.click(screen.getByRole("button", { name: "Open folder" }));

    expect(onRevealOutput).toHaveBeenCalledWith("C:\\reports\\output.xlsx");
  });
});
