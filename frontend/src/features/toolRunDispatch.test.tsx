import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BomCompareTool } from "./bom-compare/BomCompareTool";
import { FailureRateTool } from "./failure-rate/FailureRateTool";
import { FmeaTool } from "./fmea/FmeaTool";
import { RefDesExtractorTool } from "./refdes-extractor/RefDesExtractorTool";
import { buildActiveRunFromAccepted, useRunStore } from "../stores/runStore";
import { useShellStore } from "../stores/shellStore";
import { useNotificationStore } from "../stores/notificationStore";
import { usePreviewStore } from "../stores/previewStore";

const backendMocks = vi.hoisted(() => ({
  validateRun: vi.fn(),
  executeRun: vi.fn(),
  cancelRun: vi.fn(),
  openExcelFile: vi.fn(),
  openPdfFile: vi.fn(),
  listSheets: vi.fn(),
  inspectInput: vi.fn(),
}));

const EXECUTE_RUN_TIMEOUT_ERROR =
  "The 'execute_run' command timed out after 60s. An input file may be on a disconnected or slow network drive — check the path and try again.";
const ACCEPTANCE_UNKNOWN_TITLE = "Backend is still preparing the run";
const ACCEPTANCE_UNKNOWN_DETAIL =
  "Validation is taking unusually long (large or cloud-synced files). The run will attach automatically if the backend accepts it.";

vi.mock("../shared/backend/client", () => ({
  backendClient: {
    runtimeMode: "desktop-bridge",
    validateRun: backendMocks.validateRun,
    executeRun: backendMocks.executeRun,
    cancelRun: backendMocks.cancelRun,
    openExcelFile: backendMocks.openExcelFile,
    openPdfFile: backendMocks.openPdfFile,
    listSheets: backendMocks.listSheets,
    inspectInput: backendMocks.inspectInput,
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
  usePreviewStore.getState().clearAll();
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

async function runTool(startLabel: string) {
  const user = userEvent.setup();
  // v2 N5: FMEA's Run rail is persistent (no tab); the other tools keep
  // their Preview/Run tabs until the rail pattern is cloned to them.
  const runTab = screen.queryByRole("tab", { name: /^Run$/i });
  if (runTab) {
    await user.click(runTab);
  }
  await user.click(screen.getByRole("button", { name: startLabel }));
}

afterEach(async () => {
  // Test-isolation drain (debugger finding): tests await only "executeRun was
  // called", but handleStartRun CONTINUES past that await — its resolved
  // executeRun promise runs beginAcceptedRun, which writes the shared
  // runStore singleton. Without draining here, that continuation can land in
  // a LATER test and clobber its seeded activeRun (defeating e.g. the
  // cross-tool guard test). Flush pending micro/macrotasks inside act while
  // the component is still mounted, so continuations settle in their own test.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
});

beforeEach(() => {
  window.localStorage.clear();
  resetStores();
  backendMocks.validateRun.mockReset();
  backendMocks.executeRun.mockReset();
  backendMocks.cancelRun.mockReset();
  backendMocks.openExcelFile.mockReset();
  backendMocks.openPdfFile.mockReset();
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
  it.each([
    ["FMEA", "dark_star_fmea", FmeaTool],
    ["BOM Compare", "bom_compare", BomCompareTool],
    ["Failure Rate", "failure_rate", FailureRateTool],
    ["RefDes Extractor", "refdes_extractor", RefDesExtractorTool],
  ] as const)("wires numeric backend progress into the %s Run rail", (_label, toolId, Tool) => {
    render(<Tool />);

    act(() => {
      useRunStore.getState().setActiveRun(
        buildActiveRunFromAccepted({
          runId: `run_progress_${toolId}`,
          toolId,
          sessionGeneration: 1,
        }),
      );
      useRunStore.getState().patchActiveRun({
        phase: "running",
        progress: 37,
        statusMessage: "Processing workbook rows.",
      });
    });

    expect(screen.getByRole("progressbar", { name: "Run progress" })).toHaveAttribute(
      "aria-valuenow",
      "37",
    );
    expect(screen.getByText("37%")).toBeInTheDocument();
    expect(screen.queryByText("Working…")).not.toBeInTheDocument();
  });

  it.each([
    {
      tool: "FMEA",
      toolId: "dark_star_fmea" as const,
      Tool: FmeaTool,
      startLabel: "Generate FMEA",
      browseLabel: "Browse for grouping file",
    },
    {
      tool: "BOM Compare",
      toolId: "bom_compare" as const,
      Tool: BomCompareTool,
      startLabel: "Compare",
      browseLabel: "Browse for grouping file",
    },
    {
      tool: "Failure Rate",
      toolId: "failure_rate" as const,
      Tool: FailureRateTool,
      startLabel: "Link Rates",
      browseLabel: "Browse for parts list",
    },
    {
      tool: "RefDes Extractor",
      toolId: "refdes_extractor" as const,
      Tool: RefDesExtractorTool,
      startLabel: "Extract",
      browseLabel: "Browse for schematic",
    },
  ])(
    "$tool ignores a late validation after configuration changes and permits a fresh run",
    async ({ toolId, Tool, startLabel, browseLabel }) => {
      const firstValidation = deferred<{
        ok: boolean;
        reason_code: string;
        toast_text: string;
        validations: never[];
        output_preview: {
          columns: string[];
          rows: string[][];
          truncated: boolean;
        };
        mode: "desktop-bridge";
      }>();
      backendMocks.validateRun.mockImplementationOnce(() => firstValidation.promise);
      backendMocks.openExcelFile.mockResolvedValue("C:\\changed\\input.xlsx");
      backendMocks.openPdfFile.mockResolvedValue("C:\\changed\\schematic.pdf");
      backendMocks.listSheets.mockResolvedValue({
        path: "C:\\changed\\input.xlsx",
        sheets: ["Sheet1"],
        mode: "desktop-bridge",
      });
      backendMocks.inspectInput.mockResolvedValue({
        mode: "desktop-bridge",
        sheet: "Sheet1",
        columns: ["Reference Designator", "Part Number"],
      });

      const user = userEvent.setup();
      render(<Tool />);
      usePreviewStore.getState().setPreview(toolId, {
        columns: ["Original"],
        rows: [["current preview"]],
        truncated: false,
      });

      await user.click(screen.getByRole("button", { name: startLabel }));
      await waitFor(() => expect(backendMocks.validateRun).toHaveBeenCalledTimes(1));

      await user.click(screen.getByRole("button", { name: browseLabel }));
      await waitFor(() =>
        expect(usePreviewStore.getState().byTool[toolId]).toBeUndefined(),
      );

      await act(async () => {
        firstValidation.resolve({
          ok: true,
          reason_code: "ready",
          toast_text: "Ready to run.",
          validations: [],
          output_preview: {
            columns: ["Stale"],
            rows: [["must not return"]],
            truncated: false,
          },
          mode: "desktop-bridge",
        });
        await firstValidation.promise;
      });

      expect(backendMocks.executeRun).not.toHaveBeenCalled();
      expect(usePreviewStore.getState().byTool[toolId]).toBeUndefined();

      await user.click(screen.getByRole("button", { name: startLabel }));
      await waitFor(() => expect(backendMocks.validateRun).toHaveBeenCalledTimes(2));
      await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    },
  );

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
    // bomA and bomB. A fresh Custom card greets with its per-workflow
    // EmptyState, so the first browse enters through it.
    await user.click(
      screen.getByRole("button", { name: "Browse for first BOM" }),
    );
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

  it("FMEA marks mandatory input roles with a Required chip in desktop mode", async () => {
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

    // A fresh desktop FMEA greets with the onboarding EmptyState; enter
    // through it (loading the grouping role) to reveal the input grid.
    await user.click(
      screen.getByRole("button", { name: "Browse for grouping file" }),
    );
    await screen.findByText("Grouping workbook");

    // piece_part_generate: grouping, bom, failureModes are backend-required;
    // hda is hidden (inline default). v2 N6: the amber chip became a danger
    // asterisk that marks EVERY required role (loaded state is carried by
    // the row indicator instead), so all three required rows show it while
    // the just-loaded grouping row reads data-state="loaded".
    expect(
      screen.getAllByTitle("Required — the run is blocked until this file is loaded."),
    ).toHaveLength(3);
  });

  it("blocks starting a run while another tool's run is live (cross-tool guard)", async () => {
    // Holistic-review follow-up #1: the backend rejects a second concurrent
    // run, but the rejection path used to clobber the OTHER tool's live run
    // UI handle. The frontend must gate the start with a friendly toast and
    // never send the request.
    useRunStore.setState({
      activeRun: {
        ...buildActiveRunFromAccepted({
          runId: "run_live_bom",
          toolId: "bom_compare",
          sessionGeneration: 1,
        }),
        phase: "running",
      },
    });

    render(<FmeaTool />);
    await runTool("Generate FMEA");

    expect(backendMocks.validateRun).not.toHaveBeenCalled();
    expect(backendMocks.executeRun).not.toHaveBeenCalled();
    const notes = useNotificationStore.getState().notifications;
    expect(notes).toHaveLength(1);
    expect(notes[0].detail).toMatch(/BOM Comparison Tool/i);
    // The other tool's live run handle is untouched.
    expect(useRunStore.getState().activeRun?.runId).toBe("run_live_bom");
    expect(useRunStore.getState().activeRun?.toolId).toBe("bom_compare");
  });

  it("allows a new run when the other tool's run is already terminal", async () => {
    useRunStore.setState({
      activeRun: {
        ...buildActiveRunFromAccepted({
          runId: "run_done_bom",
          toolId: "bom_compare",
          sessionGeneration: 1,
        }),
        phase: "success",
      },
    });

    render(<FmeaTool />);
    await runTool("Generate FMEA");

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
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

  it.each([
    {
      tool: "FMEA",
      renderTool: () => render(<FmeaTool />),
      startLabel: "Generate FMEA",
    },
    {
      tool: "BOM Compare",
      renderTool: () => render(<BomCompareTool />),
      startLabel: "Compare",
    },
    {
      tool: "Failure Rate",
      renderTool: () => render(<FailureRateTool />),
      startLabel: "Link Rates",
    },
    {
      tool: "RefDes Extractor",
      renderTool: () => render(<RefDesExtractorTool />),
      startLabel: "Extract",
    },
  ])(
    "$tool treats an execute timeout as acceptance-unknown without resetting the run",
    async ({ renderTool, startLabel }) => {
      backendMocks.executeRun.mockRejectedValueOnce(EXECUTE_RUN_TIMEOUT_ERROR);
      renderTool();

      await runTool(startLabel);

      await waitFor(() => {
        expect(useNotificationStore.getState().notifications).toEqual([
          expect.objectContaining({
            tone: "warning",
            title: ACCEPTANCE_UNKNOWN_TITLE,
            detail: ACCEPTANCE_UNKNOWN_DETAIL,
          }),
        ]);
      });
      expect(useRunStore.getState().activeRun).toBeNull();
      expect(useShellStore.getState().backendStatus).toBe("ready");
      expect(screen.getByRole("button", { name: startLabel })).toBeEnabled();
    },
  );

  it("preserves a late-ack run registered before the timeout rejection is handled", async () => {
    const lateAckRun = buildActiveRunFromAccepted({
      runId: "run_late_ack",
      toolId: "dark_star_fmea",
      sessionGeneration: 1,
    });
    backendMocks.executeRun.mockImplementationOnce(async () => {
      // Model the narrow race that Wave 3 Task 3.3 closes: the streamed ack
      // registers the run just before the timed-out invoke rejects in React.
      useRunStore.setState({ activeRun: lateAckRun });
      throw EXECUTE_RUN_TIMEOUT_ERROR;
    });
    render(<FmeaTool />);

    await runTool("Generate FMEA");

    await waitFor(() => {
      expect(useNotificationStore.getState().notifications).toEqual([
        expect.objectContaining({
          tone: "warning",
          title: ACCEPTANCE_UNKNOWN_TITLE,
        }),
      ]);
    });
    expect(useRunStore.getState().activeRun).toEqual(lateAckRun);
  });

  it("keeps a validate_run timeout on the ordinary error path", async () => {
    const validationTimeout = EXECUTE_RUN_TIMEOUT_ERROR.replace(
      "'execute_run'",
      "'validate_run'",
    );
    backendMocks.validateRun.mockRejectedValueOnce(validationTimeout);
    render(<FmeaTool />);

    await runTool("Generate FMEA");

    await waitFor(() => {
      expect(useNotificationStore.getState().notifications).toEqual([
        expect.objectContaining({
          tone: "error",
          title: "FMEA run failed",
          detail: validationTimeout,
        }),
      ]);
    });
    expect(backendMocks.executeRun).not.toHaveBeenCalled();
    expect(useShellStore.getState().backendStatus).toBe("error");
  });
});
