import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BomCompareTool } from "./bom-compare/BomCompareTool";
import { FailureRateTool } from "./failure-rate/FailureRateTool";
import { FmeaTool } from "./fmea/FmeaTool";
import { RefDesExtractorTool } from "./refdes-extractor/RefDesExtractorTool";
import { useRunStore } from "../stores/runStore";
import { useShellStore } from "../stores/shellStore";
import { useNotificationStore } from "../stores/notificationStore";

const backendMocks = vi.hoisted(() => ({
  validateRun: vi.fn(),
  executeRun: vi.fn(),
  cancelRun: vi.fn(),
  openExcelFile: vi.fn(),
  listSheets: vi.fn(),
  inspectInput: vi.fn(),
}));

vi.mock("../shared/backend/client", () => ({
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

describe("tool run dispatch", () => {
  it("dispatches the BOM Compare group workflow", async () => {
    render(<BomCompareTool />);
    await runTool("Compare");

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    expect(backendMocks.executeRun.mock.calls[0][0]).toMatchObject({
      workflowId: "bom_compare_group",
    });
  });

  it("dispatches Extraction Compare with both roles, no mappings, no options", async () => {
    const user = userEvent.setup();
    render(<BomCompareTool />);
    await user.click(screen.getByRole("button", { name: /extraction compare/i }));
    await runTool("Compare");

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    const body = backendMocks.executeRun.mock.calls[0][0];
    expect(body.workflowId).toBe("extraction_compare");
    expect(body.inputs.map((i: { role: string }) => i.role)).toEqual([
      "extractionA",
      "extractionB",
    ]);
    // Fixed extraction-sheet schema: no mappings, and none of the BOM
    // comparison options are read by the backend, so none are sent.
    expect(body.mappings).toEqual([]);
    expect(body.options).toEqual({});
  });

  it("forwards the six comparison options to the backend (base_match defaults off)", async () => {
    // All six BOM Compare checkboxes must reach the backend in the run body so
    // the runtime adapter can wire them. base_match defaults to FALSE so a
    // default run keeps loose base matching off (byte-identical to pre-wiring).
    render(<BomCompareTool />);
    await runTool("Compare");

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    const body = backendMocks.executeRun.mock.calls[0][0];
    expect(body.options).toEqual({
      base_match: false,
      exact_match: false,
      ignore_dnp: true,
      check_part_usage: true,
      check_fmr: false,
      treat_prov_as_covered: true,
    });
  });

  it("forwards configured Custom Compare column pairs as options.compare_columns", async () => {
    // Tier-1 #5: in Custom Compare, once both files are inspected the
    // auto-pair effect seeds compare pairs from matching headers (excluding
    // the RefDes key). Those pairs must reach the backend payload as
    // options.compare_columns (array of {col_a, col_b, rule}) so the runtime
    // adapter can wire per-column value diffs.
    backendMocks.openExcelFile.mockResolvedValue("C:\\real\\File.xlsx");
    backendMocks.listSheets.mockResolvedValue({
      path: "C:\\real\\File.xlsx",
      sheets: ["Sheet1"],
      mode: "desktop-bridge",
    });
    backendMocks.inspectInput.mockResolvedValue({
      mode: "desktop-bridge",
      sheet: "Sheet1",
      columns: ["Reference Designator", "Part Number", "Description"],
    });

    const user = userEvent.setup();
    render(<BomCompareTool />);

    await user.click(screen.getByRole("button", { name: /Custom Compare/i }));

    // Browse + inspect BOTH files so the auto-pair effect has headers for
    // bomA and bomB.
    const browseButtons = screen.getAllByRole("button", { name: "Browse" });
    await user.click(browseButtons[0]);
    await waitFor(() =>
      expect(backendMocks.inspectInput).toHaveBeenCalledTimes(1),
    );
    await user.click(screen.getAllByRole("button", { name: "Browse" })[1]);
    await waitFor(() =>
      expect(backendMocks.inspectInput).toHaveBeenCalledTimes(2),
    );

    await runTool("Compare");

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    const body = backendMocks.executeRun.mock.calls[0][0];
    // The RefDes key column is excluded; the two shared value columns pair up.
    expect(body.options.compare_columns).toEqual([
      { col_a: "Part Number", col_b: "Part Number", rule: "Text (ignore case)" },
      { col_a: "Description", col_b: "Description", rule: "Text (ignore case)" },
    ]);
  });

  it("never seeds demo validation content into the desktop UI (M9)", async () => {
    // Wiring Invariant #3 extension: the "Example data staged" scenario card
    // is browser-preview content. Rendering it in the desktop runtime reads
    // as leftover state from a previous session.
    const user = userEvent.setup();

    const bomCompare = render(<BomCompareTool />);
    expect(screen.queryByText(/example data staged/i)).toBeNull();
    // The workflow-switch else-branch used to re-seed scenario validations.
    await user.click(screen.getByRole("button", { name: /Custom Compare/i }));
    expect(screen.queryByText(/example data staged/i)).toBeNull();
    bomCompare.unmount();

    const failureRate = render(<FailureRateTool />);
    expect(screen.queryByText(/example data staged/i)).toBeNull();
    failureRate.unmount();

    const refdes = render(<RefDesExtractorTool />);
    expect(screen.queryByText(/example data staged/i)).toBeNull();
    refdes.unmount();
  });

  it("FMEA marks mandatory input roles with a Required chip in desktop mode", () => {
    render(<FmeaTool />);
    // piece_part_generate: grouping, bom, failureModes are backend-required;
    // hda is hidden (inline default), so exactly three chips render.
    expect(screen.getAllByText("Required")).toHaveLength(3);
  });

  it("dispatches the FMEA workflow with the option keys the backend reads", async () => {
    // Regression guard for the hdaSource bug class (Tier-3 #28): the FMEA
    // execute payload's option keys were asserted nowhere frontend-side, so a
    // silently-dropped key — like hdaSource, which the backend now reads to
    // pick the HDA source — could ship again unnoticed. Pin the payload shape.
    render(<FmeaTool />);
    await runTool("Generate FMEA");

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    const body = backendMocks.executeRun.mock.calls[0][0];
    expect(body).toMatchObject({
      workflowId: expect.any(String),
      outputStrategyId: expect.any(String),
      options: {
        hdaSource: expect.any(String),
        failureModesStandard: expect.any(String),
      },
    });
    expect(Array.isArray(body.mappings)).toBe(true);
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
