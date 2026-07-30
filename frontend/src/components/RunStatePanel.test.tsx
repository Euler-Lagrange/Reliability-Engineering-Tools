import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { RunStatePanel, splitMetric } from "./RunStatePanel";
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

  test("renders readiness rows with their values and tones", () => {
    renderPanel({
      readiness: [
        { label: "Inputs loaded", value: "2 / 2", tone: "ok" },
        { label: "Required mapping", value: "3 / 4", tone: "warn" },
      ],
    });

    const list = screen.getByRole("list", { name: "Run readiness" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Inputs loaded");
    expect(rows[0]).toHaveTextContent("2 / 2");
    expect(rows[0]).toHaveAttribute("data-tone", "ok");
    expect(rows[1]).toHaveTextContent("Required mapping");
    expect(rows[1]).toHaveTextContent("3 / 4");
    expect(rows[1]).toHaveAttribute("data-tone", "warn");
  });

  test("result metrics typeset as stat tiles — figure split from caption", () => {
    renderPanel({
      result: {
        status: "success",
        title: "Prototype run completed",
        summary: "Rows planned.",
        outputFile: "PiecePartFMEA_Standard.xlsx",
        primaryMetric: "216 planned rows",
        secondaryMetric: "10 of 12 auto-mapped",
        notes: [],
      },
    });

    // "216 planned rows" renders as a hero figure plus a small caption
    // instead of one body-size phrase wrapping over three lines.
    const hero = screen.getByText("216");
    expect(hero.className).toContain("hero-metric");
    expect(screen.getByText("planned rows")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("of 12 auto-mapped")).toBeInTheDocument();
  });
});

describe("splitMetric", () => {
  test("splits a leading figure from its caption", () => {
    expect(splitMetric("216 planned rows")).toEqual({ value: "216", caption: "planned rows" });
    expect(splitMetric("92% auto-mapped")).toEqual({ value: "92%", caption: "auto-mapped" });
    expect(splitMetric("3 missing")).toEqual({ value: "3", caption: "missing" });
  });

  test("leaves figureless strings unsplit", () => {
    expect(splitMetric("Changes audited")).toEqual({ value: "Changes audited", caption: "" });
    expect(splitMetric("Recovery path visible")).toEqual({
      value: "Recovery path visible",
      caption: "",
    });
  });
});
