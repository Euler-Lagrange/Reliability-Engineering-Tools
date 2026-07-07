import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ContextDrawer } from "./ContextDrawer";
import { MappingTable } from "./MappingTable";
import type { ColumnMappingRow } from "../app/types";
import type { OutputPreview } from "../contracts/sidecar";
import { usePreviewStore } from "../stores/previewStore";
import type { ActiveRunState } from "../stores/runStore";
import { useRunStore } from "../stores/runStore";
import { useShellStore } from "../stores/shellStore";

function makeActiveRun(overrides: Partial<ActiveRunState> = {}): ActiveRunState {
  return {
    runId: "run_test",
    toolId: "dark_star_fmea",
    sessionGeneration: 1,
    phase: "running",
    progress: 42,
    stage: "Loading workbook",
    statusMessage: "Working through staged inputs.",
    steps: [],
    logs: [],
    truncatedLogCount: 0,
    result: null,
    errorMessage: null,
    errorCode: null,
    errorTraceback: null,
    startedAt: "2026-04-22T12:30:00.000Z",
    finishedAt: null,
    isDisconnected: false,
    ...overrides,
  };
}

const previewFixture: OutputPreview = {
  columns: ["RefDes", "Part Number", "Description"],
  rows: [["R200", "PN-0000", "Resistor"]],
  truncated: false,
  total_estimated: 1,
};

beforeEach(() => {
  useShellStore.setState({
    activeToolId: "dark_star_fmea",
    backendStatus: "ready",
    backendMode: "browser-mock",
    backendMessage: null,
    lastBackendCheckAt: null,
    contextOpen: false,
  });
  useRunStore.setState({ activeRun: null });
  usePreviewStore.getState().clearAll();
});

describe("ContextDrawer", () => {
  it("renders the active tool's run summary and preview when the global run matches", () => {
    useShellStore.setState({ contextOpen: true });
    useRunStore.setState({
      activeRun: makeActiveRun({
        phase: "success",
        progress: 100,
        stage: "Writing output",
        statusMessage: "Done",
        finishedAt: "2026-04-22T12:45:00.000Z",
      }),
    });
    usePreviewStore.getState().setPreview("dark_star_fmea", previewFixture);

    const { container } = render(<ContextDrawer />);

    const drawer = container.querySelector(".context-drawer");
    expect(drawer).not.toBeNull();
    expect(drawer).toHaveAttribute("aria-hidden", "false");
    expect(drawer).not.toHaveAttribute("inert");

    expect(screen.getByRole("heading", { name: /fmea generator/i })).toBeInTheDocument();
    expect(screen.getByText("success")).toBeInTheDocument();
    expect(screen.getByText("Writing output")).toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(screen.getByText("R200")).toBeInTheDocument();
  });

  it("shows the tool-specific empty run state while keeping the active tool preview", () => {
    useShellStore.setState({
      activeToolId: "bom_compare",
      contextOpen: true,
    });
    useRunStore.setState({
      activeRun: makeActiveRun({
        toolId: "dark_star_fmea",
        phase: "success",
      }),
    });
    usePreviewStore.getState().setPreview("bom_compare", previewFixture);

    render(<ContextDrawer />);

    expect(screen.getByRole("heading", { name: /bom comparison tool/i })).toBeInTheDocument();
    expect(screen.getByText("No run has started for this tool yet.")).toBeInTheDocument();
    expect(screen.getByText("R200")).toBeInTheDocument();
    expect(screen.queryByText("success")).not.toBeInTheDocument();
  });

  it("keeps closed drawer controls out of the tab order", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <div>
        <button type="button">Before</button>
        <ContextDrawer />
        <button type="button">After</button>
      </div>,
    );

    const drawer = container.querySelector(".context-drawer");
    const closeButton = screen.getByRole("button", {
      name: /close review drawer/i,
      hidden: true,
    });
    const before = screen.getByRole("button", { name: "Before" });
    const after = screen.getByRole("button", { name: "After" });

    expect(drawer).not.toBeNull();
    expect(drawer).toHaveAttribute("aria-hidden", "true");
    expect(drawer).toHaveAttribute("inert");
    expect(closeButton).toBeDisabled();
    expect(closeButton).toHaveAttribute("tabindex", "-1");

    before.focus();
    expect(before).toHaveFocus();

    await user.tab();
    expect(after).toHaveFocus();
  });

  it("closes the drawer on Escape when open", async () => {
    const user = userEvent.setup();
    useShellStore.setState({ contextOpen: true });

    const { container } = render(<ContextDrawer />);
    const drawer = container.querySelector(".context-drawer");

    expect(drawer).not.toBeNull();
    expect(drawer).toHaveAttribute("aria-hidden", "false");

    await user.keyboard("{Escape}");

    expect(useShellStore.getState().contextOpen).toBe(false);
    expect(drawer).toHaveAttribute("aria-hidden", "true");
    expect(drawer).toHaveAttribute("inert");
  });

  it("Escape dismisses only the most recent layer (help panel before drawer)", async () => {
    // Stacked window-level Escape handlers previously closed both the drawer
    // AND the mapping help panel on a single Escape. With the shared
    // dismiss-stack, the first Escape closes only the most-recently-opened
    // layer (the help panel); the drawer stays open until a second Escape.
    const user = userEvent.setup();
    useShellStore.setState({ contextOpen: true, activeToolId: "dark_star_fmea" });

    const helpRow: ColumnMappingRow = {
      canonical: "Failure Mode",
      mappedTo: "Failure Mode",
      status: "mapped",
      recommendation: "Exact header match",
      options: ["Failure Mode", "Mode"],
      help: "Maps the failure mode column.",
      required: true,
    };

    render(
      <>
        <ContextDrawer />
        <MappingTable rows={[helpRow]} overrides={{}} onOverride={vi.fn()} />
      </>,
    );

    // The drawer is open (its layer registered first).
    expect(useShellStore.getState().contextOpen).toBe(true);

    // Open the mapping help panel — this becomes the top-most layer.
    await user.click(screen.getByRole("button", { name: /about failure mode/i }));
    expect(screen.getByText(/ABOUT THIS COLUMN/i)).toBeInTheDocument();

    // First Escape closes ONLY the help panel; the drawer remains open.
    await user.keyboard("{Escape}");
    expect(screen.queryByText(/ABOUT THIS COLUMN/i)).not.toBeInTheDocument();
    expect(useShellStore.getState().contextOpen).toBe(true);

    // Second Escape now closes the drawer.
    await user.keyboard("{Escape}");
    expect(useShellStore.getState().contextOpen).toBe(false);
  });
});
