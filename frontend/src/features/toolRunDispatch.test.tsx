import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BomCompareTool } from "./bom-compare/BomCompareTool";
import { FailureRateTool } from "./failure-rate/FailureRateTool";
import { RefDesExtractorTool } from "./refdes-extractor/RefDesExtractorTool";
import { useRunStore } from "../stores/runStore";
import { useShellStore } from "../stores/shellStore";
import { useNotificationStore } from "../stores/notificationStore";

const backendMocks = vi.hoisted(() => ({
  validateRun: vi.fn(),
  executeRun: vi.fn(),
  cancelRun: vi.fn(),
}));

vi.mock("../shared/backend/client", () => ({
  backendClient: {
    runtimeMode: "desktop-bridge",
    validateRun: backendMocks.validateRun,
    executeRun: backendMocks.executeRun,
    cancelRun: backendMocks.cancelRun,
    openExcelFile: vi.fn(),
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

async function runTool(startLabel: string) {
  const user = userEvent.setup();
  await user.click(screen.getByRole("tab", { name: /^Run$/i }));
  await user.click(screen.getByRole("button", { name: startLabel }));
}

beforeEach(() => {
  window.localStorage.clear();
  resetStores();
  backendMocks.validateRun.mockReset();
  backendMocks.executeRun.mockReset();
  backendMocks.cancelRun.mockReset();
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

describe("tool run dispatch", () => {
  it("dispatches the BOM Compare group workflow", async () => {
    render(<BomCompareTool />);
    await runTool("Compare");

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    expect(backendMocks.executeRun.mock.calls[0][0]).toMatchObject({
      workflowId: "bom_compare_group",
    });
  });

  it("dispatches the Failure Rate workflow", async () => {
    render(<FailureRateTool />);
    await runTool("Link Rates");

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    expect(backendMocks.executeRun.mock.calls[0][0]).toMatchObject({
      workflowId: "failure_rate_link",
    });
  });

  it("dispatches the RefDes Extractor workflow", async () => {
    render(<RefDesExtractorTool />);
    await runTool("Extract");

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    expect(backendMocks.executeRun.mock.calls[0][0]).toMatchObject({
      workflowId: "refdes_extract",
    });
  });

  it("blocks the run and skips execute_run when validation fails", async () => {
    // validateRun reports the run is NOT runnable. The tool must surface a
    // 'Run blocked' notification and must NOT proceed to execute_run.
    backendMocks.validateRun.mockResolvedValue({
      ok: false,
      reason_code: "blocked",
      toast_text: "Resolve the highlighted setup issues before running.",
      validations: [
        {
          id: "v1",
          severity: "error",
          area: "Run State",
          title: "Run is blocked",
          detail: "Map the prediction RefDes column before running.",
        },
      ],
      output_preview: null,
      mode: "desktop-bridge",
    });

    render(<FailureRateTool />);
    await runTool("Link Rates");

    // validateRun was consulted...
    await waitFor(() => expect(backendMocks.validateRun).toHaveBeenCalledTimes(1));
    // ...and a 'Run blocked' warning was raised.
    await waitFor(() => {
      const notifications = useNotificationStore.getState().notifications;
      expect(
        notifications.some(
          (n) => n.title === "Run blocked" && n.tone === "warning",
        ),
      ).toBe(true);
    });
    // The failing validation must short-circuit before execute_run.
    expect(backendMocks.executeRun).not.toHaveBeenCalled();
  });
});
