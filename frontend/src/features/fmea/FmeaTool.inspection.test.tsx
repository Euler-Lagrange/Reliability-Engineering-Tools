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
    revealInFileManager: vi.fn(),
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

function inputCard(label: string) {
  const card = screen.getByText(label).closest("article");
  if (!card) {
    throw new Error(`Expected the "${label}" input card to render.`);
  }
  return card;
}

// A blocking validate_run result whose validation card is rendered in the
// Preview tab. Used to seed a stale card that a subsequent browse / sheet
// change must clear (Fix 2).
const STALE_VALIDATION = {
  ok: false as const,
  reason_code: "blocked",
  toast_text: "Resolve the highlighted setup issues before running.",
  validations: [
    {
      id: "stale-1",
      severity: "warning" as const,
      area: "Run State",
      title: "Stale configuration card",
      detail: "This card describes the previously configured workbook.",
    },
  ],
  output_preview: null,
  mode: "desktop-bridge" as const,
};

// Seed a validation card by driving Start -> validate_run in the
// persistent Run rail (v2 N5 — no tabs). A blocking (ok: false) result
// populates `validations`, visible in the sibling Validation card.
async function seedValidationCard(user: ReturnType<typeof userEvent.setup>) {
  mockBackendClient.validateRun.mockResolvedValueOnce(STALE_VALIDATION);
  await user.click(screen.getByRole("button", { name: "Generate FMEA" }));
  expect(await screen.findByText("Stale configuration card")).toBeInTheDocument();
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

    // Fresh desktop state greets with the onboarding EmptyState; the first
    // browse enters through its mode-aware primary action, which reveals
    // the input grid (and this role's card) immediately.
    await user.click(
      screen.getByRole("button", { name: "Browse for functional FMEA" }),
    );
    const card = functionalFmeaCard();

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

    // Enter through the onboarding EmptyState's mode-aware browse.
    await user.click(
      screen.getByRole("button", { name: "Browse for functional FMEA" }),
    );

    expect(await screen.findByText("Workbook inspection capped")).toBeInTheDocument();
    expect(
      screen.getAllByText(/first 20,000 data rows and first 100 columns/i).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText(/Scanned 20,000 rows/i)).toBeInTheDocument();
    expect(screen.getByText(/Scanned 100 columns/i)).toBeInTheDocument();
  }, FMEA_INSPECTION_TEST_TIMEOUT_MS);

  test("warns when preserve-formatting will modify a protected sheet", async () => {
    const user = userEvent.setup();

    mockBackendClient.openExcelFile.mockResolvedValue("C:\\target.xlsx");
    mockBackendClient.listSheets.mockResolvedValue({
      path: "C:\\target.xlsx",
      sheets: ["FMEA"],
      mode: "desktop-bridge",
    });
    mockBackendClient.analyzeTemplate.mockResolvedValue({
      path: "C:\\target.xlsx",
      sheet: "FMEA",
      header_row: 3,
      columns: ["FMEA-ID", "Failure Mode Causes", "Failure Mode"],
      merged_range_count: 2,
      freeze_panes: "A4",
      protected_sheet: true,
      rows_scanned: 0,
      header_rows_scanned: 3,
      columns_scanned: 3,
      row_cap_applied: false,
      column_cap_applied: false,
      header_search_cap_applied: false,
      mode: "desktop-bridge",
    });

    renderTool();
    await user.click(
      screen.getByRole("button", {
        name: /existing workbook \(preserve formatting\)/i,
      }),
    );
    await user.click(
      within(inputCard("Target workbook")).getByRole("button", {
        name: "Browse",
      }),
    );

    const warning = await screen.findByText(
      "Sheet is protected — the merge will modify it without the password.",
    );
    // v2 N8: analysis-card warnings render as a dot + warning-colored
    // note instead of a filled chip.
    expect(warning).toHaveClass("analysis-card__warning");
  }, FMEA_INSPECTION_TEST_TIMEOUT_MS);

  // Fix 2 (parity with BOM Compare / Failure Rate): a stale validate_run
  // result must not survive an input change. FmeaTool previously cleared
  // validations only at init, on workflow-change, and after validate_run, so
  // browsing a new file left the prior run's cards describing the OLD file.
  test("browsing a new file clears stale validation cards", async () => {
    const user = userEvent.setup();
    mockBackendClient.openExcelFile.mockResolvedValue("C:\\grouping.xlsx");
    mockBackendClient.listSheets.mockResolvedValue({
      path: "C:\\grouping.xlsx",
      sheets: ["Grouping"],
      mode: "desktop-bridge",
    });
    mockBackendClient.inspectInput.mockResolvedValue({
      path: "C:\\grouping.xlsx",
      sheet: "Grouping",
      header_row: 1,
      row_count: 10,
      columns: ["Component Group", "Reference Designator"],
      preview_rows: [{ "Component Group": "PSU" }],
      rows_scanned: 10,
      columns_scanned: 2,
      row_cap_applied: false,
      column_cap_applied: false,
      header_search_cap_applied: false,
      mode: "desktop-bridge",
    });

    renderTool();
    // Seed a stale validation card via a blocking validate_run.
    await seedValidationCard(user);

    // Browse a new workbook for the default piece_part_generate Grouping
    // role. A blocked validate_run leaves the run idle and the inputs
    // untouched, so the tool is still pristine — enter via the EmptyState.
    await user.click(
      screen.getByRole("button", { name: "Browse for grouping file" }),
    );

    // The stale card must be gone once the new file lands.
    await waitFor(() =>
      expect(screen.queryByText("Stale configuration card")).not.toBeInTheDocument(),
    );
  }, FMEA_INSPECTION_TEST_TIMEOUT_MS);

  // Family 3 fix: a manual mapping override must not outlive the column it
  // pointed at. The user maps canonical X to column "Orphan Column"; a later
  // file/sheet whose inspected columns no longer contain "Orphan Column"
  // leaves the MappingTable still displaying it, while the backend silently
  // discards the override and auto-detects (map_columns only honours an
  // override when `overrides[std] in df.columns`). The orphaned override must
  // be pruned when the inspected column set changes; overrides whose column
  // still exists must survive.
  test("prunes orphaned mapping overrides when re-inspected columns drop the mapped column", async () => {
    const user = userEvent.setup();
    mockBackendClient.openExcelFile.mockResolvedValue("C:\\grouping.xlsx");
    mockBackendClient.listSheets.mockResolvedValue({
      path: "C:\\grouping.xlsx",
      sheets: ["Grouping"],
      mode: "desktop-bridge",
    });

    // First inspection exposes "Orphan Column" and "Keep Column" as mappable.
    const firstColumns = ["Failure Mode", "Orphan Column", "Keep Column"];
    // Second inspection drops "Orphan Column" (the column an override targets).
    const secondColumns = ["Failure Mode", "Keep Column"];
    let inspectColumns = firstColumns;
    mockBackendClient.inspectInput.mockImplementation((_path: string, sheet: string) =>
      Promise.resolve({
        path: "C:\\grouping.xlsx",
        sheet,
        header_row: 1,
        row_count: 10,
        columns: inspectColumns,
        preview_rows: [{ "Failure Mode": "Open" }],
        rows_scanned: 10,
        columns_scanned: inspectColumns.length,
        row_cap_applied: false,
        column_cap_applied: false,
        header_search_cap_applied: false,
        mode: "desktop-bridge" as const,
      }),
    );

    renderTool();

    // Load the grouping workbook (default piece_part_generate workflow) via
    // the onboarding EmptyState, then wait for the inspection round-trip to
    // settle (Browse re-enabled) so the mapping dropdowns are populated with
    // the inspected columns.
    await user.click(
      screen.getByRole("button", { name: "Browse for grouping file" }),
    );
    const card = inputCard("Grouping workbook");
    await waitFor(() =>
      expect(within(card).getByRole("button", { name: "Browse" })).toBeEnabled(),
    );

    // Override canonical "Failure Mode" -> "Orphan Column" (a column that
    // will disappear on the next inspection).
    await user.click(screen.getByRole("combobox", { name: "Failure Mode mapping" }));
    await user.click(
      await screen.findByRole("option", { name: "Orphan Column - Grouping workbook" }),
    );

    // Override canonical "Failure Mode Ratio" -> "Keep Column" (a column that
    // survives the next inspection — this override must be preserved).
    await user.click(screen.getByRole("combobox", { name: "Failure Mode Ratio mapping" }));
    await user.click(
      await screen.findByRole("option", { name: "Keep Column - Grouping workbook" }),
    );

    // Sanity: both overrides are reflected in the triggers.
    expect(
      screen.getByRole("combobox", { name: "Failure Mode mapping" }),
    ).toHaveTextContent("Orphan Column - Grouping workbook");
    expect(
      screen.getByRole("combobox", { name: "Failure Mode Ratio mapping" }),
    ).toHaveTextContent("Keep Column - Grouping workbook");

    // Re-browse the SAME role with a column set that no longer has
    // "Orphan Column".
    inspectColumns = secondColumns;
    await user.click(within(inputCard("Grouping workbook")).getByRole("button", { name: "Browse" }));

    // The orphaned override is pruned: the "Failure Mode" row reverts to its
    // auto-detected exact-header value.
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: "Failure Mode mapping" }),
      ).toHaveTextContent("Failure Mode - Grouping workbook"),
    );
    expect(
      screen.getByRole("combobox", { name: "Failure Mode mapping" }),
    ).not.toHaveTextContent("Orphan Column");

    // The still-valid override survives — "Keep Column" is still inspected.
    expect(
      screen.getByRole("combobox", { name: "Failure Mode Ratio mapping" }),
    ).toHaveTextContent("Keep Column - Grouping workbook");
  }, FMEA_INSPECTION_TEST_TIMEOUT_MS);

  // Fix 2: a sheet change re-inspects the workbook and likewise invalidates
  // the prior validate_run result.
  test("changing the selected sheet clears stale validation cards", async () => {
    const user = userEvent.setup();
    mockBackendClient.openExcelFile.mockResolvedValue("C:\\grouping.xlsx");
    mockBackendClient.listSheets.mockResolvedValue({
      path: "C:\\grouping.xlsx",
      sheets: ["Grouping", "Alternate"],
      mode: "desktop-bridge",
    });
    mockBackendClient.inspectInput.mockImplementation((_path: string, sheet: string) =>
      Promise.resolve({
        path: "C:\\grouping.xlsx",
        sheet,
        header_row: 1,
        row_count: 10,
        columns: ["Component Group", "Reference Designator"],
        preview_rows: [{ "Component Group": "PSU" }],
        rows_scanned: 10,
        columns_scanned: 2,
        row_cap_applied: false,
        column_cap_applied: false,
        header_search_cap_applied: false,
        mode: "desktop-bridge" as const,
      }),
    );

    renderTool();

    // Load a workbook with two sheets so the sheet picker is interactive —
    // the first browse enters through the onboarding EmptyState.
    await user.click(
      screen.getByRole("button", { name: "Browse for grouping file" }),
    );
    const card = inputCard("Grouping workbook");
    await waitFor(() =>
      expect(within(card).getByRole("button", { name: "Browse" })).toBeEnabled(),
    );

    // Seed a stale validation card AFTER the file is loaded.
    await seedValidationCard(user);

    // Change the selected sheet — this re-inspects and must clear the card.
    await user.click(
      within(inputCard("Grouping workbook")).getByRole("combobox", {
        name: /Grouping workbook sheet/i,
      }),
    );
    await user.click(await screen.findByRole("option", { name: "Alternate" }));

    await waitFor(() =>
      expect(screen.queryByText("Stale configuration card")).not.toBeInTheDocument(),
    );
  }, FMEA_INSPECTION_TEST_TIMEOUT_MS);
});
