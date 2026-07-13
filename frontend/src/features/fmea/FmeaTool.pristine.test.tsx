import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FmeaTool } from "./FmeaTool";
import { useRunStore } from "../../stores/runStore";
import { useShellStore } from "../../stores/shellStore";
import { useNotificationStore } from "../../stores/notificationStore";

/**
 * FMEA onboarding EmptyState — desktop-bridge runtime only.
 *
 * User decision (2026-07-13): every tool card greets a fresh DESKTOP state
 * with the onboarding EmptyState and swaps to the input grid once a real
 * file lands. FMEA's four modes share their input slots, so pristine is
 * MODE-INDEPENDENT (RefDes semantics): the first real file in any mode
 * exits permanently; mode switches never resurrect the panel.
 *
 * Browser-mock deliberately keeps the staged demo instead (UX fix #5,
 * 2026-07-07 seeded the demo mapping columns precisely so the preview
 * shows a working tool) — hence the desktop-bridge client mock here.
 */

const backendMocks = vi.hoisted(() => ({
  validateRun: vi.fn(),
  executeRun: vi.fn(),
  cancelRun: vi.fn(),
  openExcelFile: vi.fn(),
  listSheets: vi.fn(),
  inspectInput: vi.fn(),
  analyzeTemplate: vi.fn(),
}));

vi.mock("../../shared/backend/client", () => ({
  backendClient: {
    runtimeMode: "desktop-bridge",
    validateRun: backendMocks.validateRun,
    executeRun: backendMocks.executeRun,
    cancelRun: backendMocks.cancelRun,
    openExcelFile: backendMocks.openExcelFile,
    listSheets: backendMocks.listSheets,
    inspectInput: backendMocks.inspectInput,
    analyzeTemplate: backendMocks.analyzeTemplate,
    openPdfFile: vi.fn(),
    openDirectory: vi.fn(),
    revealInFileManager: vi.fn(),
  },
}));

function resetStores() {
  useRunStore.setState({ activeRun: null });
  useShellStore.setState({
    activeToolId: "dark_star_fmea",
    backendStatus: "ready",
    backendMode: "desktop-bridge",
    backendMessage: "Python sidecar session ready.",
    lastBackendCheckAt: null,
    fmeaOutputDirectory: null,
    bomCompareOutputDirectory: null,
    failureRateOutputDirectory: null,
    refdesExtractorOutputDirectory: null,
    contextOpen: false,
  });
  useNotificationStore.setState({ notifications: [] });
}

beforeEach(() => {
  window.localStorage.clear();
  resetStores();
  backendMocks.openExcelFile.mockReset();
  backendMocks.listSheets.mockReset();
  backendMocks.inspectInput.mockReset();
  backendMocks.analyzeTemplate.mockReset();
});

const HEADLINE = "Build or merge an FMEA workbook";

describe("FmeaTool desktop onboarding EmptyState", () => {
  it("greets a fresh desktop state in all four modes with mode-aware browse labels", async () => {
    const user = userEvent.setup();
    render(<FmeaTool />);

    // Default mode (piece_part_generate) — pristine panel, grouping-first.
    expect(screen.getByText(HEADLINE)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Browse for grouping file" }),
    ).toBeInTheDocument();
    // M9: the desktop seed carries no example paths anywhere.
    expect(screen.queryByText(/DRIVE\\inputs/)).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /Piece-Part from BOM Only/i }),
    );
    expect(screen.getByText(HEADLINE)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Browse for BOM" }),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /Merge Functional FMEA/i }),
    );
    expect(
      screen.getByRole("button", { name: "Browse for functional FMEA" }),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /Merge Piece-Part FMEA/i }),
    );
    expect(
      screen.getByRole("button", { name: "Browse for existing FMEA" }),
    ).toBeInTheDocument();
  });

  it("exits pristine on the first real file and never resurrects across mode switches", async () => {
    backendMocks.openExcelFile.mockResolvedValue("C:\\real\\Grouping.xlsx");
    backendMocks.listSheets.mockResolvedValue({
      path: "C:\\real\\Grouping.xlsx",
      sheets: ["Grouping"],
      mode: "desktop-bridge",
    });
    backendMocks.inspectInput.mockResolvedValue({
      mode: "desktop-bridge",
      sheet: "Grouping",
      columns: ["Component Group", "Reference Designator"],
    });

    const user = userEvent.setup();
    render(<FmeaTool />);

    await user.click(
      screen.getByRole("button", { name: "Browse for grouping file" }),
    );

    // The grid replaces the panel with the loaded slot visible.
    expect(await screen.findByText("Grouping workbook")).toBeInTheDocument();
    expect(screen.queryByText(HEADLINE)).not.toBeInTheDocument();

    // Mode-independent exit: switching modes shows each mode's grid, never
    // the onboarding panel again (the grouping file was real engagement).
    await user.click(
      screen.getByRole("button", { name: /Merge Functional FMEA/i }),
    );
    expect(screen.getByText("Functional FMEA workbook")).toBeInTheDocument();
    expect(screen.queryByText(HEADLINE)).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /Piece-Part from Grouping File/i }),
    );
    expect(screen.getByText("Grouping workbook")).toBeInTheDocument();
    expect(screen.queryByText(HEADLINE)).not.toBeInTheDocument();
  });

  it("pauses the pristine browse action during a cross-tool live run with a hint", async () => {
    const { buildActiveRunFromAccepted } = await import("../../stores/runStore");
    useRunStore.getState().setActiveRun(
      buildActiveRunFromAccepted({
        runId: "live_bom_run",
        toolId: "bom_compare",
        sessionGeneration: 1,
      }),
    );
    useRunStore.getState().patchActiveRun({ phase: "running" });

    render(<FmeaTool />);

    const browse = screen.getByRole("button", {
      name: "Browse for grouping file",
    });
    expect(browse).toBeDisabled();
    expect(browse).toHaveAttribute(
      "title",
      "File inspection is paused while a run is active.",
    );
  });

  it("shows the coming-soon notice from the Load example secondary action", async () => {
    const user = userEvent.setup();
    render(<FmeaTool />);

    await user.click(screen.getByRole("button", { name: "Load example" }));

    await waitFor(() => {
      expect(
        useNotificationStore
          .getState()
          .notifications.some((n) => n.title === "Example files coming soon"),
      ).toBe(true);
    });
  });
});
