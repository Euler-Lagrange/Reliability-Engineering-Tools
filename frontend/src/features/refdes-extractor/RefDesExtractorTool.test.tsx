import { render, screen } from "@testing-library/react";
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
}));

vi.mock("../../shared/backend/client", () => ({
  backendClient: {
    runtimeMode: "desktop-bridge",
    validateRun: backendMocks.validateRun,
    executeRun: backendMocks.executeRun,
    cancelRun: backendMocks.cancelRun,
    openExcelFile: vi.fn(),
    openPdfFile: backendMocks.openPdfFile,
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
});
