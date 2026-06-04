import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FailureRateTool } from "./FailureRateTool";
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
    activeToolId: "failure_rate",
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

describe("FailureRateTool stale validation handling", () => {
  // Regression (Fix 2): a stale validate_run result stranded in the Preview
  // tab after the user changed an input file — the previous run's validation
  // cards kept describing the OLD file. Browsing a new file must clear them.
  it("clears stale validation cards after browsing a new file", async () => {
    backendMocks.openExcelFile.mockResolvedValue("C:\\real\\Predictions.xlsx");
    backendMocks.listSheets.mockResolvedValue({
      path: "C:\\real\\Predictions.xlsx",
      sheets: ["Predictions"],
      mode: "desktop-bridge",
    });
    backendMocks.inspectInput.mockResolvedValue({
      mode: "desktop-bridge",
      sheet: "Predictions",
      columns: ["Reference Designator", "Failure Rate"],
    });

    const user = userEvent.setup();
    render(<FailureRateTool />);

    // The seeded "Ready to run" validation card is visible up front.
    expect(screen.getByText("Ready to run")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Browse for parts list" }));

    // Once the new file lands the stale card is gone (neutral empty state).
    await screen.findByText("C:\\real\\Predictions.xlsx");
    await waitFor(() =>
      expect(screen.queryByText("Ready to run")).not.toBeInTheDocument(),
    );
  });
});
