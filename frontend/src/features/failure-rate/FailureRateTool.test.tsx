import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FailureRateTool } from "./FailureRateTool";
import { buildActiveRunFromAccepted, useRunStore } from "../../stores/runStore";
import { useShellStore } from "../../stores/shellStore";
import { useNotificationStore } from "../../stores/notificationStore";
import { usePreviewStore } from "../../stores/previewStore";

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
  usePreviewStore.getState().clearAll();
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
  it("pauses pristine Browse while another tool owns a live run", () => {
    act(() => {
      useRunStore.getState().setActiveRun(
        buildActiveRunFromAccepted({
          runId: "live_fmea_run",
          toolId: "dark_star_fmea",
          sessionGeneration: 1,
        }),
      );
      useRunStore.getState().patchActiveRun({ phase: "running" });
    });
    render(<FailureRateTool />);

    const browse = screen.getByRole("button", { name: "Browse for parts list" });
    expect(browse).toBeDisabled();
    expect(browse).toHaveAttribute(
      "title",
      "File inspection is paused while a run is active.",
    );
  });

  // Conformance (app-wide EmptyState consistency, 2026-07-13): every tool
  // greets a fresh desktop state with the onboarding EmptyState.
  it("greets a fresh desktop state with the onboarding EmptyState", () => {
    render(<FailureRateTool />);

    expect(screen.getByText("Link failure rates")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Browse for parts list" }),
    ).toBeInTheDocument();
    // The slot grid stays hidden until a real file lands.
    expect(screen.queryByText("Prediction workbook")).not.toBeInTheDocument();
    expect(screen.queryByText("FMEA workbook")).not.toBeInTheDocument();
  });

  // Conformance: the first real file swaps the panel for the grid with both
  // slots visible.
  it("exits pristine on the first real file and shows both slots", async () => {
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

    await user.click(
      screen.getByRole("button", { name: "Browse for parts list" }),
    );

    expect(await screen.findByText("Prediction workbook")).toBeInTheDocument();
    expect(screen.getByText("FMEA workbook")).toBeInTheDocument();
    expect(screen.queryByText("Link failure rates")).not.toBeInTheDocument();
  });

  // 2026-07-21: in browser preview the demo scenario is staged BEHIND the
  // pristine card, so "Load example" reveals it instead of claiming example
  // files don't exist. Desktop keeps the truthful coming-soon notice.
  it("Load example reveals the staged demo content in browser preview", async () => {
    const { backendClient } = await import("../../shared/backend/client");
    (backendClient as unknown as { runtimeMode: string }).runtimeMode = "browser-mock";
    try {
      const user = userEvent.setup();
      render(<FailureRateTool />);

      await user.click(screen.getByRole("button", { name: "Load example" }));

      // Pristine card gone, demo inputs visible with their Example: labels.
      expect(
        screen.queryByRole("button", { name: "Load example" }),
      ).not.toBeInTheDocument();
      expect(screen.getAllByText(/Example: /).length).toBeGreaterThan(0);
      // No "coming soon" toast — the examples genuinely loaded.
      expect(useNotificationStore.getState().notifications).toHaveLength(0);
    } finally {
      (backendClient as unknown as { runtimeMode: string }).runtimeMode =
        "desktop-bridge";
    }
  });

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

    // A blocked validate populates real validation cards (M9 removed the
    // demo-seeded card this test previously used as its stale fixture).
    backendMocks.validateRun.mockResolvedValue({
      ok: false,
      reason_code: "missing_files",
      toast_text: "Select required files: Parts list.",
      validations: [
        {
          id: "validation-missing_files",
          severity: "error",
          area: "Run State",
          title: "Run is blocked",
          detail: "Select required files: Parts list.",
        },
      ],
      output_preview: null,
      mode: "desktop-bridge",
    });

    const user = userEvent.setup();
    render(<FailureRateTool />);

    // M9: desktop mode seeds NO demo validation card.
    expect(screen.queryByText("Example data staged")).not.toBeInTheDocument();

    // A blocked start leaves real validation cards behind.
    await user.click(screen.getByRole("button", { name: "Link Rates" }));
    // v2 N5-clone: validations render in the always-visible sibling card.
    expect(
      await screen.findByText("Select required files: Parts list."),
    ).toBeInTheDocument();

    usePreviewStore.getState().setPreview("failure_rate", {
      columns: ["Old input"],
      rows: [["stale preview"]],
      truncated: false,
    });
    await user.click(screen.getByRole("button", { name: "Browse for parts list" }));

    // Once the new file lands the stale card is gone (neutral empty state).
    await screen.findByText("C:\\real\\Predictions.xlsx");
    await waitFor(() =>
      expect(
        screen.queryByText("Select required files: Parts list."),
      ).not.toBeInTheDocument(),
    );
    expect(usePreviewStore.getState().byTool.failure_rate).toBeUndefined();
  });
});

describe("FailureRateTool inspected-column mapping derivation", () => {
  // Bug fix (adversarially verified): the Column Mapping dropdowns used to be a
  // static fixture (failureRateMappings) that was never rebuilt from the real
  // workbook's inspected headers — inspectRole discarded inspection.columns.
  // On a real file the dropdown offered fixture strings ("Reference
  // Designator", "Failure Rate") that may not exist, the mappedTo defaults were
  // pre-filled regardless, and a mismatch only surfaced at execute time as a
  // ColumnMappingError. Now the prediction rows are derived from the inspected
  // columns for the "prediction" role.
  it("rebuilds the prediction mapping dropdowns from the inspected headers and dispatches them", async () => {
    backendMocks.openExcelFile.mockResolvedValue("C:\\real\\Predictions.xlsx");
    backendMocks.listSheets.mockResolvedValue({
      path: "C:\\real\\Predictions.xlsx",
      sheets: ["Predictions"],
      mode: "desktop-bridge",
    });
    // Real headers: "Failure Rate" matches the pred_fr fixture default
    // (auto-fill), but the pred_ref default "Reference Designator" is absent
    // (no match → unmapped/empty).
    backendMocks.inspectInput.mockResolvedValue({
      mode: "desktop-bridge",
      sheet: "Predictions",
      columns: ["Component", "Failure Rate"],
    });

    const user = userEvent.setup();
    render(<FailureRateTool />);

    await user.click(screen.getByRole("button", { name: "Browse for parts list" }));
    await screen.findByText("C:\\real\\Predictions.xlsx");
    await waitFor(() => expect(backendMocks.inspectInput).toHaveBeenCalled());
    // v2 N6: the tag chip became the row indicator's tooltip.
    await screen.findByTitle("Analyzed");

    // The prediction RefDes dropdown now offers the REAL headers, not the
    // stale fixture options.
    const predRefCombobox = await screen.findByRole("combobox", {
      name: /pred_ref mapping/i,
    });
    await user.click(predRefCombobox);
    expect(await screen.findByRole("option", { name: "Component" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Failure Rate" })).toBeInTheDocument();
    // The fixture-only default that does NOT exist in this workbook is gone.
    expect(
      screen.queryByRole("option", { name: "Reference Designator" }),
    ).not.toBeInTheDocument();
    // Close the menu before dispatching the run.
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Link Rates" }));

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    const request = backendMocks.executeRun.mock.calls[0][0];
    const mappingByCanonical = Object.fromEntries(
      (request.mappings as Array<{ canonical: string; mappedTo: string }>).map(
        (mapping) => [mapping.canonical, mapping.mappedTo],
      ),
    );

    // pred_fr auto-filled to the real header (exact match).
    expect(mappingByCanonical.pred_fr).toBe("Failure Rate");
    // pred_ref has no matching header in this workbook — empty, NOT the stale
    // fixture default "Reference Designator".
    expect(mappingByCanonical.pred_ref).toBe("");
  });
});
