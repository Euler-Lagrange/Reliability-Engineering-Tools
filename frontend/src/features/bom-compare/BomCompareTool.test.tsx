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
});
