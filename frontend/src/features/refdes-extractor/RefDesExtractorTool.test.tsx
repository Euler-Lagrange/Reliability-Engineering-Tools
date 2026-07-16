import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RefDesExtractorTool } from "./RefDesExtractorTool";
import { buildActiveRunFromAccepted, useRunStore } from "../../stores/runStore";
import { useShellStore } from "../../stores/shellStore";
import { useNotificationStore } from "../../stores/notificationStore";

const backendMocks = vi.hoisted(() => ({
  validateRun: vi.fn(),
  executeRun: vi.fn(),
  cancelRun: vi.fn(),
  openPdfFile: vi.fn(),
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
    activeToolId: "refdes_extractor",
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
  backendMocks.openPdfFile.mockReset();
  backendMocks.openExcelFile.mockReset();
  backendMocks.listSheets.mockReset();
  backendMocks.inspectInput.mockReset();
  backendMocks.validateRun.mockReset();
  backendMocks.executeRun.mockReset();
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

describe("RefDesExtractorTool piece-part mode", () => {
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
    render(<RefDesExtractorTool />);

    const browse = screen.getByRole("button", { name: "Browse for schematic" });
    expect(browse).toBeDisabled();
    expect(browse).toHaveAttribute(
      "title",
      "File inspection is paused while a run is active.",
    );
  });

  // Regression: refdesInputs.pinlist existed in the mocks but was never
  // seeded into the demo scenario, so piece_part mode computed roles
  // ["pdf", "bom", "pinlist"] yet the pinlist picker never rendered —
  // there was no way to attach a pinlist from the UI. The pinlist must be
  // reachable in Piece-Part mode once the user engages (browses a file);
  // the mode toggle itself keeps the onboarding EmptyState in BOTH modes.
  it("shows the pinlist slot in Piece-Part mode after the first browse", async () => {
    backendMocks.openPdfFile.mockResolvedValue("C:\\real\\Schematic.pdf");
    const user = userEvent.setup();
    render(<RefDesExtractorTool />);

    // Pristine first contact shows the empty state, no pinlist yet.
    expect(screen.getByText("Extract reference designators")).toBeInTheDocument();

    // Toggling the extraction mode is a light option choice, NOT
    // engagement — the pretty EmptyState must persist in Piece-Part too.
    await user.click(screen.getByRole("radio", { name: "Piece-Part" }));
    expect(screen.getByText("Extract reference designators")).toBeInTheDocument();

    // Browsing the schematic is engagement: the grid appears with all
    // three piece-part slots, including the pinlist.
    await user.click(screen.getByRole("button", { name: "Browse for schematic" }));
    expect(await screen.findByText("Schematic PDF")).toBeInTheDocument();
    expect(screen.getByText("BOM workbook (optional)")).toBeInTheDocument();
    expect(screen.getByText("Pinlist file (optional)")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Browse" })).toHaveLength(3);
  });

  // Regression: the browse handlers never cleared `isExample`, so after
  // loading a real PDF `isPristine` stayed true and the EmptyState never
  // yielded to the InputGrid — the BOM slot was unreachable.
  it("keeps the pinlist slot hidden in Functional mode after browsing a PDF", async () => {
    backendMocks.openPdfFile.mockResolvedValue("C:\\real\\Schematic.pdf");
    const user = userEvent.setup();
    render(<RefDesExtractorTool />);

    await user.click(screen.getByRole("button", { name: "Browse for schematic" }));

    expect(await screen.findByText("Schematic PDF")).toBeInTheDocument();
    expect(screen.getByText("BOM workbook (optional)")).toBeInTheDocument();
    expect(screen.queryByText("Pinlist file (optional)")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Browse" })).toHaveLength(2);
  });

  // Regression (BUG 1): the pinlist is filtered out of `visibleInputs` in
  // Functional mode. `isPristine` evaluated against `visibleInputs` lost
  // pinlist engagement on toggle-back, replacing the InputGrid with the
  // pristine EmptyState even though no data was lost. The pinlist's loaded
  // state must survive a Piece-Part -> Functional -> Piece-Part round-trip.
  it("keeps pinlist state across a mode round-trip", async () => {
    backendMocks.openPdfFile.mockResolvedValue("C:\\real\\Schematic.pdf");
    backendMocks.openExcelFile.mockResolvedValue("C:\\real\\Pinlist.xlsx");
    backendMocks.listSheets.mockResolvedValue({
      path: "C:\\real\\Pinlist.xlsx",
      sheets: ["Sheet1"],
      mode: "desktop-bridge",
    });
    const user = userEvent.setup();
    render(<RefDesExtractorTool />);

    // Engage in Piece-Part mode: browse the schematic via the EmptyState,
    // which reveals the grid with the pinlist slot.
    await user.click(screen.getByRole("radio", { name: "Piece-Part" }));
    await user.click(screen.getByRole("button", { name: "Browse for schematic" }));
    const pinlistCard = (await screen.findByText("Pinlist file (optional)")).closest(
      "article",
    ) as HTMLElement;
    expect(pinlistCard).not.toBeNull();

    // Browse the pinlist (Excel branch -> listSheets resolution).
    await user.click(within(pinlistCard).getByRole("button", { name: "Browse" }));

    // BUG 3: the Excel listSheets success branch never set `status`, so the
    // pinlist kept its seeded `status: "optional"` and InputGrid never gave it
    // the "loaded" classification. v2 N6: the tag chip became the row
    // indicator — loaded state is carried by data-state + the ✓ glyph.
    await waitFor(() => expect(pinlistCard).toHaveAttribute("data-state", "loaded"));
    expect(within(pinlistCard).getByText("✓")).toBeInTheDocument();

    // Toggle back to Functional: the pinlist is filtered out of the visible
    // inputs, but it remains loaded engagement — the InputGrid must stay.
    await user.click(screen.getByRole("radio", { name: "Functional" }));
    expect(screen.getByText("Schematic PDF")).toBeInTheDocument();
    expect(
      screen.queryByText("Extract reference designators"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Pinlist file (optional)")).not.toBeInTheDocument();

    // Round-trip forward: the pinlist card returns still loaded.
    await user.click(screen.getByRole("radio", { name: "Piece-Part" }));
    const pinlistCardAgain = (await screen.findByText("Pinlist file (optional)")).closest(
      "article",
    ) as HTMLElement;
    expect(pinlistCardAgain).toHaveAttribute("data-state", "loaded");
  });

  // Regression (#17): a finished run's terminal phase lingers in the store, so
  // browsing the BOM (the Excel path, AFTER the pdf early-return) flips the busy
  // chip and useBackendBusyReset would wipe it. handleBrowse must clear the stale
  // terminal run first (guarded, so a live sibling run survives). This covers the
  // post-pdf-return placement that is unique to this tool.
  it("clears a lingering terminal run when browsing the BOM", async () => {
    backendMocks.openExcelFile.mockResolvedValue("C:\\real\\BOM.xlsx");
    backendMocks.listSheets.mockResolvedValue({
      path: "C:\\real\\BOM.xlsx",
      sheets: ["Main BOM"],
      mode: "desktop-bridge",
    });
    backendMocks.inspectInput.mockResolvedValue({
      mode: "desktop-bridge",
      sheet: "Main BOM",
      columns: ["RefDes"],
    });

    const user = userEvent.setup();
    render(<RefDesExtractorTool />);

    // A finished run lingers (terminal phase, owned by this tool).
    act(() => {
      useRunStore.getState().setActiveRun(
        buildActiveRunFromAccepted({
          runId: "done_rd_run",
          toolId: "refdes_extractor",
          sessionGeneration: 1,
        }),
      );
      useRunStore.getState().patchActiveRun({ phase: "success" });
    });

    // Non-pristine now, so the InputGrid renders; browse the BOM (Excel) card.
    const bomCard = (await screen.findByText("BOM workbook (optional)")).closest(
      "article",
    ) as HTMLElement;
    await user.click(within(bomCard).getByRole("button", { name: "Browse" }));

    await waitFor(() => expect(useRunStore.getState().activeRun).toBeNull());
  });
});

describe("RefDesExtractorTool dispatch with no browsed files", () => {
  // Regression (Family 1): the tool seeded inputStates with the example PDF
  // ("DRIVE\inputs\...") unconditionally, so a desktop run with nothing
  // browsed would ship that fake path to the backend — where the example
  // PDF hard-fails on fitz.open and the example BOM silently degrades the
  // output. buildRunRequest filters on Boolean(path), so empty seeds mean
  // NO inputs are sent until the user browses real files.
  it("sends no inputs when nothing was browsed", async () => {
    const user = userEvent.setup();
    render(<RefDesExtractorTool />);
    await user.click(screen.getByRole("button", { name: "Extract" }));

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    const request = backendMocks.executeRun.mock.calls[0][0];
    expect(request.inputs).toEqual([]);
  });
});

describe("RefDesExtractorTool numeric tuning fields", () => {
  it("renders the three tuning fields with their defaults", () => {
    render(<RefDesExtractorTool />);

    expect(
      screen.getByRole("spinbutton", { name: "Geometry batch size" }),
    ).toHaveValue(10);
    expect(
      screen.getByRole("spinbutton", { name: "Max pin label length" }),
    ).toHaveValue(4);
    expect(
      screen.getByRole("spinbutton", { name: "Provenance distance" }),
    ).toHaveValue(15);
  });

  it("dispatches the edited geometry batch size in the run request options", async () => {
    const user = userEvent.setup();
    render(<RefDesExtractorTool />);

    // fireEvent.change delivers one change event with the final value —
    // matching a paste or spinner step. userEvent.type would key in
    // character-by-character against the controlled value, appending to the
    // existing 10.
    const batch = screen.getByRole("spinbutton", { name: "Geometry batch size" });
    fireEvent.change(batch, { target: { value: "25" } });
    expect(batch).toHaveValue(25);
    await user.click(screen.getByRole("button", { name: "Extract" }));

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    const request = backendMocks.executeRun.mock.calls[0][0];
    expect(request.options.geometry_batch_size).toBe(25);
  });

  it("dispatches the edited provenance distance in the run request options", async () => {
    const user = userEvent.setup();
    render(<RefDesExtractorTool />);

    const prov = screen.getByRole("spinbutton", { name: "Provenance distance" });
    fireEvent.change(prov, { target: { value: "12.5" } });
    expect(prov).toHaveValue(12.5);
    await user.click(screen.getByRole("button", { name: "Extract" }));

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    const request = backendMocks.executeRun.mock.calls[0][0];
    expect(request.options.prov_distance).toBe(12.5);
  });

  // Wave R follow-up (wiring invariant #1): annotation_page_timeout_seconds
  // shipped as the backend's 17th validated option with no UI control. It
  // lives with the other engine-tuning fields in the Advanced panel.
  it("renders the annotation page timeout in the advanced panel with its default", async () => {
    const user = userEvent.setup();
    render(<RefDesExtractorTool />);

    await user.click(screen.getByRole("button", { name: /Advanced controls/i }));

    expect(
      screen.getByRole("spinbutton", { name: "Annotation page timeout (s)" }),
    ).toHaveValue(30);
  });

  it("dispatches the edited annotation page timeout in the run request options", async () => {
    const user = userEvent.setup();
    render(<RefDesExtractorTool />);

    await user.click(screen.getByRole("button", { name: /Advanced controls/i }));
    const timeout = screen.getByRole("spinbutton", {
      name: "Annotation page timeout (s)",
    });
    fireEvent.change(timeout, { target: { value: "60" } });
    expect(timeout).toHaveValue(60);
    await user.click(screen.getByRole("button", { name: "Extract" }));

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    const request = backendMocks.executeRun.mock.calls[0][0];
    expect(request.options.annotation_page_timeout_seconds).toBe(60);
  });

  it("disables the geometry batch size field when geometry analysis is off", async () => {
    const user = userEvent.setup();
    render(<RefDesExtractorTool />);

    const batch = screen.getByRole("spinbutton", { name: "Geometry batch size" });
    const maxPin = screen.getByRole("spinbutton", { name: "Max pin label length" });
    const prov = screen.getByRole("spinbutton", { name: "Provenance distance" });
    const geometry = screen.getByRole("checkbox", { name: "Enable geometry analysis" });

    // Default: geometry on -> batch size enabled.
    expect(batch).toBeEnabled();

    await user.click(geometry);
    expect(batch).toBeDisabled();
    // Max pin length and provenance distance are read on every extraction
    // path, so they stay enabled regardless of geometry analysis.
    expect(maxPin).toBeEnabled();
    expect(prov).toBeEnabled();

    await user.click(geometry);
    expect(batch).toBeEnabled();
  });
});

describe("RefDesExtractorTool advanced engine controls", () => {
  // Every control carries a hover-tooltip affordance (InfoTip = role="img"
  // whose accessible name is the tooltip copy). This proves the main-area
  // controls expose one without opening the advanced disclosure.
  it("exposes a hover tooltip on the primary controls", () => {
    render(<RefDesExtractorTool />);

    expect(
      screen.getByRole("img", { name: /Functional groups components/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /Use vector geometry/i }),
    ).toBeInTheDocument();
  });

  it("keeps the advanced controls collapsed by default and reveals them on expand", async () => {
    const user = userEvent.setup();
    render(<RefDesExtractorTool />);

    // Collapsed by default: the toggle reports its collapsed state and none of
    // the advanced fields are mounted.
    const toggle = screen.getByRole("button", { name: /Advanced controls/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByRole("spinbutton", { name: "Pin assignment threshold (pt)" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("checkbox", { name: "Geometry subprocess isolation" }),
    ).not.toBeInTheDocument();

    // Expand -> the advanced fields mount and the toggle flips.
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByRole("spinbutton", { name: "Pin assignment threshold (pt)" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "Geometry subprocess isolation" }),
    ).toBeInTheDocument();
  });

  it("ships untouched advanced defaults in the run request options", async () => {
    const user = userEvent.setup();
    render(<RefDesExtractorTool />);

    // Never open the advanced section: because the whole options object is
    // spread into the payload, the defaults must still ride along.
    await user.click(screen.getByRole("button", { name: "Extract" }));

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    const request = backendMocks.executeRun.mock.calls[0][0];
    expect(request.options.geometry_subprocess_enabled).toBe(false);
    expect(request.options.geometry_batch_timeout_seconds).toBe(240);
    // Batch 5: checkpoints write JSON into the user's output folder, so
    // they are opt-in — the default must ship OFF.
    expect(request.options.geometry_batch_checkpoint_enabled).toBe(false);
    expect(request.options.pin_assignment_threshold).toBe(50);
    expect(request.options.refdes_search_radius).toBe(100);
    expect(request.options.adaptive_orphan_threshold).toBe(5);
    expect(request.options.adaptive_orphan_ratio).toBe(0.3);
    expect(request.options.adaptive_max_pages).toBe(10);
    expect(request.options.pinlist_prefers_annotation_mode).toBe(true);
  });

  it("dispatches edited advanced params in the run request options", async () => {
    const user = userEvent.setup();
    render(<RefDesExtractorTool />);

    await user.click(screen.getByRole("button", { name: /Advanced controls/i }));

    const pinThreshold = screen.getByRole("spinbutton", {
      name: "Pin assignment threshold (pt)",
    });
    fireEvent.change(pinThreshold, { target: { value: "75" } });
    expect(pinThreshold).toHaveValue(75);

    const searchRadius = screen.getByRole("spinbutton", {
      name: "RefDes search radius (pt)",
    });
    fireEvent.change(searchRadius, { target: { value: "150" } });
    expect(searchRadius).toHaveValue(150);

    const subprocess = screen.getByRole("checkbox", {
      name: "Geometry subprocess isolation",
    });
    await user.click(subprocess);
    expect(subprocess).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Extract" }));

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    const request = backendMocks.executeRun.mock.calls[0][0];
    expect(request.options.pin_assignment_threshold).toBe(75);
    expect(request.options.refdes_search_radius).toBe(150);
    expect(request.options.geometry_subprocess_enabled).toBe(true);
  });
});

describe("RefDesExtractorTool adaptive geometry gating", () => {
  // Regression (BUG 2): the backend returns from the annotation-only branch
  // before reading `adaptive_geometry_enabled` when geometry analysis is off,
  // so the adaptive checkbox is silently inert. It must be disabled to match.
  it("disables the adaptive geometry checkbox when geometry analysis is off", async () => {
    const user = userEvent.setup();
    render(<RefDesExtractorTool />);

    const geometry = screen.getByRole("checkbox", { name: "Enable geometry analysis" });
    const adaptive = screen.getByRole("checkbox", {
      name: "Adaptive geometry (smart page gating)",
    });

    // Default state: geometry analysis on -> adaptive enabled.
    expect(geometry).toBeChecked();
    expect(adaptive).toBeEnabled();

    // Turn geometry analysis off -> adaptive must become inert.
    await user.click(geometry);
    expect(geometry).not.toBeChecked();
    expect(adaptive).toBeDisabled();

    // Turn it back on -> adaptive re-enabled.
    await user.click(geometry);
    expect(geometry).toBeChecked();
    expect(adaptive).toBeEnabled();
  });
});
