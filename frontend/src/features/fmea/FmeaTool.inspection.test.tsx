import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { FmeaTool } from "./FmeaTool";
import { useShellStore } from "../../stores/shellStore";

const FMEA_INSPECTION_TEST_TIMEOUT_MS = 15_000;

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const { mockBackendClient } = vi.hoisted(() => ({
  mockBackendClient: {
    runtimeMode: "desktop-bridge" as const,
    healthCheck: vi.fn(),
    sessionStatus: vi.fn(async () => ({
      connected: true,
      backend: "python-sidecar-session",
      mode: "desktop-bridge" as const,
      session_generation: 1,
    })),
    listSheets: vi.fn(),
    inspectInput: vi.fn(),
    analyzeTemplate: vi.fn(),
    validateRun: vi.fn(),
    executeRun: vi.fn(),
    cancelRun: vi.fn(),
    readFletConfig: vi.fn(),
    subscribeToRunEvents: vi.fn(async () => () => {}),
    subscribeToSessionEvents: vi.fn(async () => () => {}),
    openExcelFile: vi.fn(),
    openPdfFile: vi.fn(),
    openDirectory: vi.fn(),
  },
}));

vi.mock("../../shared/backend/client", () => ({
  backendClient: mockBackendClient,
}));

function renderTool() {
  useShellStore.setState({
    activeToolId: "dark_star_fmea",
    backendStatus: "ready",
    backendMode: "desktop-bridge",
    backendMessage: "Desktop backend ready",
    lastBackendCheckAt: null,
    fmeaOutputDirectory: null,
  });
  return render(<FmeaTool />);
}

function functionalFmeaCard() {
  const card = screen.getByText("Functional FMEA workbook").closest("article");
  if (!card) {
    throw new Error("Expected Functional FMEA input card to render.");
  }
  return card;
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
});

describe("FmeaTool inspection flow", () => {
  test("selected sheet becomes usable before background workbook aggregation finishes", async () => {
    const user = userEvent.setup();
    const secondarySheet = deferred<{
      path: string;
      sheet: string;
      header_row: number;
      row_count: number;
      columns: string[];
      preview_rows: Array<Record<string, string>>;
      rows_scanned: number;
      columns_scanned: number;
      row_cap_applied: boolean;
      column_cap_applied: boolean;
      header_search_cap_applied: boolean;
      mode: "desktop-bridge";
    }>();

    mockBackendClient.openExcelFile.mockResolvedValue("C:\\functional.xlsx");
    mockBackendClient.listSheets.mockResolvedValue({
      path: "C:\\functional.xlsx",
      sheets: ["Main", "Notes"],
      mode: "desktop-bridge",
    });
    mockBackendClient.inspectInput.mockImplementation((_path: string, sheet: string) => {
      if (sheet === "Main") {
        return Promise.resolve({
          path: "C:\\functional.xlsx",
          sheet: "Main",
          header_row: 1,
          row_count: 25,
          columns: ["Failure Mode", "Local Effect"],
          preview_rows: [{ "Failure Mode": "Open" }],
          rows_scanned: 25,
          columns_scanned: 2,
          row_cap_applied: false,
          column_cap_applied: false,
          header_search_cap_applied: false,
          mode: "desktop-bridge" as const,
        });
      }
      return secondarySheet.promise;
    });

    renderTool();
    await user.click(screen.getByRole("button", { name: /merge functional fmea/i }));

    const card = functionalFmeaCard();
    await user.click(within(card).getByRole("button", { name: "Browse" }));

    await waitFor(() => {
      expect(within(card).getByRole("button", { name: "Browse" })).toBeEnabled();
    });
    expect(within(card).queryByText(/Inspecting the selected sheet/i)).not.toBeInTheDocument();

    secondarySheet.resolve({
      path: "C:\\functional.xlsx",
      sheet: "Notes",
      header_row: 1,
      row_count: 3,
      columns: ["Next Higher Effect"],
      preview_rows: [{ "Next Higher Effect": "System degraded" }],
      rows_scanned: 3,
      columns_scanned: 1,
      row_cap_applied: false,
      column_cap_applied: false,
      header_search_cap_applied: false,
      mode: "desktop-bridge",
    });

    await waitFor(() => {
      expect(mockBackendClient.inspectInput).toHaveBeenCalledWith(
        "C:\\functional.xlsx",
        "Notes",
        "functionalFmea",
      );
    });
  }, FMEA_INSPECTION_TEST_TIMEOUT_MS);

  test("shows a warning note when selected-sheet inspection is capped", async () => {
    const user = userEvent.setup();

    mockBackendClient.openExcelFile.mockResolvedValue("C:\\functional.xlsx");
    mockBackendClient.listSheets.mockResolvedValue({
      path: "C:\\functional.xlsx",
      sheets: ["Main"],
      mode: "desktop-bridge",
    });
    mockBackendClient.inspectInput.mockResolvedValue({
      path: "C:\\functional.xlsx",
      sheet: "Main",
      header_row: 1,
      row_count: 20_000,
      columns: ["Failure Mode", "Local Effect"],
      preview_rows: [{ "Failure Mode": "Open" }],
      rows_scanned: 20_000,
      columns_scanned: 100,
      row_cap_applied: true,
      column_cap_applied: true,
      header_search_cap_applied: false,
      mode: "desktop-bridge",
    });

    renderTool();
    await user.click(screen.getByRole("button", { name: /merge functional fmea/i }));

    const card = functionalFmeaCard();
    await user.click(within(card).getByRole("button", { name: "Browse" }));

    expect(await screen.findByText("Workbook inspection capped")).toBeInTheDocument();
    expect(
      screen.getAllByText(/first 20,000 data rows and first 100 columns/i).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText(/Scanned 20,000 rows/i)).toBeInTheDocument();
    expect(screen.getByText(/Scanned 100 columns/i)).toBeInTheDocument();
  }, FMEA_INSPECTION_TEST_TIMEOUT_MS);
});
