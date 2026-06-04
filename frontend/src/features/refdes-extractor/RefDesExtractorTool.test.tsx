import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RefDesExtractorTool } from "./RefDesExtractorTool";
import { useRunStore } from "../../stores/runStore";
import { useShellStore } from "../../stores/shellStore";
import { useNotificationStore } from "../../stores/notificationStore";

const backendMocks = vi.hoisted(() => ({
  validateRun: vi.fn(),
  executeRun: vi.fn(),
  cancelRun: vi.fn(),
  openPdfFile: vi.fn(),
  openExcelFile: vi.fn(),
  listSheets: vi.fn(),
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
});

describe("RefDesExtractorTool piece-part mode", () => {
  // Regression: refdesInputs.pinlist existed in the mocks but was never
  // seeded into the demo scenario, so piece_part mode computed roles
  // ["pdf", "bom", "pinlist"] yet the pinlist picker never rendered —
  // there was no way to attach a pinlist from the UI.
  it("reveals the pinlist slot after switching to Piece-Part mode", async () => {
    const user = userEvent.setup();
    render(<RefDesExtractorTool />);

    // Pristine first contact shows the empty state, no pinlist yet.
    expect(screen.getByText("Extract reference designators")).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Piece-Part" }));

    // Switching extraction mode is engagement: the grid must appear with
    // all three piece-part slots, including the pinlist.
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

  // Regression (BUG 1): loading only a pinlist in Piece-Part mode is real
  // engagement, but the pinlist is filtered out of `visibleInputs` in
  // Functional mode. `isPristine` evaluated against `visibleInputs` lost that
  // engagement on toggle-back, replacing the InputGrid with the pristine
  // EmptyState even though no data was lost.
  it("keeps the input grid after loading only a pinlist then toggling back to Functional", async () => {
    backendMocks.openExcelFile.mockResolvedValue("C:\\real\\Pinlist.xlsx");
    backendMocks.listSheets.mockResolvedValue({
      path: "C:\\real\\Pinlist.xlsx",
      sheets: ["Sheet1"],
      mode: "desktop-bridge",
    });
    const user = userEvent.setup();
    render(<RefDesExtractorTool />);

    // Switch to Piece-Part to reveal the pinlist slot (3 Browse buttons).
    await user.click(screen.getByRole("radio", { name: "Piece-Part" }));
    const pinlistCard = (await screen.findByText("Pinlist file (optional)")).closest(
      "article",
    ) as HTMLElement;
    expect(pinlistCard).not.toBeNull();

    // Browse only the pinlist (Excel branch -> listSheets resolution).
    await user.click(within(pinlistCard).getByRole("button", { name: "Browse" }));
    expect(await within(pinlistCard).findByText("Loaded")).toBeInTheDocument();

    // Toggle back to Functional: the pinlist is filtered out of the visible
    // inputs, but it remains loaded engagement — the InputGrid must stay.
    await user.click(screen.getByRole("radio", { name: "Functional" }));

    expect(screen.getByText("Schematic PDF")).toBeInTheDocument();
    expect(
      screen.queryByText("Extract reference designators"),
    ).not.toBeInTheDocument();
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
