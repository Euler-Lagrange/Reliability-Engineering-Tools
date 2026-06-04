import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BomCompareTool } from "./BomCompareTool";
import { useRunStore } from "../../stores/runStore";
import { useShellStore } from "../../stores/shellStore";
import { useNotificationStore } from "../../stores/notificationStore";

const backendMocks = vi.hoisted(() => ({
  validateRun: vi.fn(),
  executeRun: vi.fn(),
  cancelRun: vi.fn(),
  openExcelFile: vi.fn(),
  listSheets: vi.fn(),
  inspectInput: vi.fn(),
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
    openPdfFile: vi.fn(),
    openDirectory: vi.fn(),
    revealInFileManager: vi.fn(),
  },
}));

function resetStores() {
  useRunStore.setState({ activeRun: null });
  useShellStore.setState({
    activeToolId: "bom_compare",
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
  backendMocks.validateRun.mockReset();
  backendMocks.executeRun.mockReset();
  backendMocks.cancelRun.mockReset();
  backendMocks.openExcelFile.mockReset();
  backendMocks.listSheets.mockReset();
  backendMocks.inspectInput.mockReset();
  backendMocks.validateRun.mockResolvedValue({
    ok: true,
    reason_code: "ready",
    toast_text: "Ready to run.",
    validations: [],
    output_preview: null,
    mode: "desktop-bridge",
  });
  backendMocks.executeRun.mockResolvedValue({
    run_id: "run_test_001",
    mode: "desktop-bridge",
    session_generation: 1,
  });
});

describe("BomCompareTool custom compare workflow", () => {
  // Regression: bomCompareDemoScenarios used to contain only the group
  // scenario, so switching to Custom Compare re-seeded inputStates without
  // bomA/bomB roles and the Input Files card rendered an empty grid — no
  // file slots, nothing to browse into.
  it("shows both file slots after switching to Custom Compare", async () => {
    const user = userEvent.setup();
    render(<BomCompareTool />);

    await user.click(screen.getByRole("button", { name: /Custom Compare/i }));

    expect(screen.getByText("File 1")).toBeInTheDocument();
    expect(screen.getByText("File 2")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Browse" })).toHaveLength(2);
  });

  // Regression: the browse handlers never cleared `isExample`, so after
  // loading a real workbook `isPristine` stayed true and the EmptyState
  // never yielded to the InputGrid — the second file slot (and the sheet
  // pickers) were unreachable in the desktop app.
  it("replaces the empty state with the input grid after browsing a real file", async () => {
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
    render(<BomCompareTool />);

    // Pristine first contact: the empty state is shown instead of the grid.
    expect(screen.getByText("Compare two BOMs")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Browse for first BOM" }));

    // After a real file lands the grid must appear with BOTH slots.
    expect(await screen.findByText("Grouping workbook")).toBeInTheDocument();
    expect(screen.getByText("BOM workbook")).toBeInTheDocument();
    expect(screen.queryByText("Compare two BOMs")).not.toBeInTheDocument();
  });

  it("dispatches bomA/bomB inputs and custom mappings for a custom run", async () => {
    const user = userEvent.setup();
    render(<BomCompareTool />);

    await user.click(screen.getByRole("button", { name: /Custom Compare/i }));
    await user.click(screen.getByRole("tab", { name: /^Run$/i }));
    await user.click(screen.getByRole("button", { name: "Compare" }));

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    const request = backendMocks.executeRun.mock.calls[0][0];
    expect(request).toMatchObject({ workflowId: "bom_compare_custom" });
    expect(request.inputs.map((input: { role: string }) => input.role)).toEqual([
      "bomA",
      "bomB",
    ]);
    expect(
      request.mappings.map((mapping: { canonical: string }) => mapping.canonical),
    ).toEqual(["refdes_col_a", "refdes_col_b"]);
  });

  // Regression (Fix 1): the workflow-change effect used to re-seed inputStates
  // from the demo scenario on EVERY switch, so a round-trip (load a real file
  // in Group → peek at Custom → back to Group) permanently discarded the
  // loaded path. The per-workflow state cache must restore the loaded slice.
  it("preserves a loaded file across a workflow round-trip", async () => {
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
    render(<BomCompareTool />);

    // Load a real grouping file in Group vs BOM mode.
    await user.click(screen.getByRole("button", { name: "Browse for first BOM" }));
    const loadedPath = await screen.findByText("C:\\real\\Grouping.xlsx");
    expect(loadedPath).toBeInTheDocument();
    // Let the post-browse inspect round-trip settle so the slot is fully
    // loaded (tag transitions Inspecting → Desktop → Analyzed) before we
    // switch workflows.
    await waitFor(() => expect(backendMocks.inspectInput).toHaveBeenCalled());
    expect(await screen.findByText("Analyzed")).toBeInTheDocument();

    // Round-trip: peek at Custom Compare, then back to Group vs BOM.
    await user.click(screen.getByRole("button", { name: /Custom Compare/i }));
    await user.click(screen.getByRole("button", { name: /Group vs BOM/i }));

    // The loaded path must survive — without the cache it reverts to the
    // example mock "DRIVE\\inputs\\NavUnit_Grouping.xlsx".
    expect(await screen.findByText("C:\\real\\Grouping.xlsx")).toBeInTheDocument();
    expect(
      screen.queryByText("DRIVE\\inputs\\NavUnit_Grouping.xlsx"),
    ).not.toBeInTheDocument();
  });

  // Regression (Fix 2): a stale validate_run result stranded in the Preview
  // tab after the user changed an input file — the previous run's validation
  // cards kept describing the OLD file. Browsing a new file must clear them.
  it("clears stale validation cards after browsing a new file", async () => {
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
    render(<BomCompareTool />);

    // The seeded "Ready to run" validation card is visible up front.
    expect(screen.getByText("Ready to run")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Browse for first BOM" }));

    // Once the new file lands the stale card is gone (neutral empty state).
    await screen.findByText("C:\\real\\Grouping.xlsx");
    await waitFor(() =>
      expect(screen.queryByText("Ready to run")).not.toBeInTheDocument(),
    );
  });

  // Regression (review finding): switching workflow while a listSheets
  // inspection is still in flight stashed the slot with isResolvingSheets
  // still true. Restoring that slice verbatim left the slot permanently
  // stuck on "Loading..." with Browse and the sheet picker disabled — no
  // in-app recovery. The cache must sanitize busy flags on stash and the
  // per-role tokens must be bumped so the late continuation is dropped.
  it("recovers a slot whose inspection was interrupted by a workflow switch", async () => {
    backendMocks.openExcelFile.mockResolvedValue("C:\\real\\Grouping.xlsx");
    let resolveListSheets: (value: {
      path: string;
      sheets: string[];
      mode: string;
    }) => void = () => {};
    backendMocks.listSheets.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveListSheets = resolve;
        }),
    );

    const user = userEvent.setup();
    render(<BomCompareTool />);

    // Start browsing — listSheets stays pending (isResolvingSheets: true).
    await user.click(screen.getByRole("button", { name: "Browse for first BOM" }));
    expect(await screen.findByRole("button", { name: "Loading..." })).toBeInTheDocument();

    // Switch away while the inspection is still in flight — the outgoing
    // slice is stashed mid-inspection.
    await user.click(screen.getByRole("button", { name: /Custom Compare/i }));

    // The orphaned listSheets continuation fires while Custom is active:
    // its role ("grouping") matches nothing in the bomA/bomB slice, so the
    // resolution is dropped and the stash keeps its busy flags.
    resolveListSheets({
      path: "C:\\real\\Grouping.xlsx",
      sheets: ["Grouping"],
      mode: "desktop-bridge",
    });
    await waitFor(() => expect(backendMocks.listSheets).toHaveBeenCalledTimes(1));

    // Returning restores the stashed slice.
    await user.click(screen.getByRole("button", { name: /Group vs BOM/i }));

    // The restored slot must be recoverable: Browse re-enabled on BOTH
    // slots (no permanently-stuck "Loading..." button).
    await waitFor(() => {
      const browseButtons = screen.getAllByRole("button", { name: "Browse" });
      expect(browseButtons).toHaveLength(2);
      for (const button of browseButtons) {
        expect(button).toBeEnabled();
      }
    });
    expect(screen.queryByRole("button", { name: "Loading..." })).not.toBeInTheDocument();
  });
});
