import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BomCompareTool } from "./BomCompareTool";
import { buildActiveRunFromAccepted, useRunStore } from "../../stores/runStore";
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
    activeToolId: "bom_compare",
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

describe("BomCompareTool custom compare workflow", () => {
  // Regression: bomCompareDemoScenarios used to contain only the group
  // scenario, so switching to Custom Compare re-seeded inputStates without
  // bomA/bomB roles and the Input Files card rendered an empty grid — no
  // file slots, nothing to browse into.
  it("shows both file slots after switching to Custom Compare", async () => {
    backendMocks.openExcelFile.mockResolvedValue("C:\\real\\BomA.xlsx");
    backendMocks.listSheets.mockResolvedValue({
      path: "C:\\real\\BomA.xlsx",
      sheets: ["Sheet1"],
      mode: "desktop-bridge",
    });
    backendMocks.inspectInput.mockResolvedValue({
      mode: "desktop-bridge",
      sheet: "Sheet1",
      columns: ["Reference Designator"],
    });

    const user = userEvent.setup();
    render(<BomCompareTool />);

    await user.click(screen.getByRole("button", { name: /Custom Compare/i }));
    // Fresh card greets with the per-workflow EmptyState; entering through it
    // must reveal BOTH scenario-seeded slots (the original regression: a
    // missing custom scenario rendered zero slots).
    await user.click(screen.getByRole("button", { name: "Browse for first BOM" }));

    expect(await screen.findByText("File 1")).toBeInTheDocument();
    expect(screen.getByText("File 2")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Browse" })).toHaveLength(2);
  });

  it("Extraction Compare shows its two slots and hides the mapping card", async () => {
    backendMocks.openExcelFile.mockResolvedValue("C:\\real\\ExtractA.xlsx");
    backendMocks.listSheets.mockResolvedValue({
      path: "C:\\real\\ExtractA.xlsx",
      sheets: ["RefDes Extraction"],
      mode: "desktop-bridge",
    });
    backendMocks.inspectInput.mockResolvedValue({
      mode: "desktop-bridge",
      sheet: "RefDes Extraction",
      columns: ["Group", "Failure Mode Causes"],
    });

    const user = userEvent.setup();
    render(<BomCompareTool />);

    await user.click(screen.getByRole("button", { name: /Extraction Compare/i }));

    // Options gating is independent of the onboarding EmptyState: every
    // comparison checkbox is inert here — disabled with a hint (Wiring
    // Invariant #2) — and the mapping card is hidden.
    expect(
      screen.queryByRole("heading", { name: /column mapping/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText(/ignore dnp/i)).toBeDisabled();
    expect(screen.getAllByText("BOM compare modes only").length).toBeGreaterThan(0);

    // Entering through the card's EmptyState reveals both extraction slots.
    await user.click(
      screen.getByRole("button", { name: "Browse for older extraction" }),
    );
    expect(await screen.findByText("Extraction A (older)")).toBeInTheDocument();
    expect(screen.getByText("Extraction B (newer)")).toBeInTheDocument();
  });

  // Regression: the browse handlers never cleared `isExample`, so after
  // loading a real workbook `isPristine` stayed true and the EmptyState
  // never yielded to the InputGrid — the second file slot (and the sheet
  // pickers) were unreachable in the desktop app.
  it("replaces the empty state with the input grid after browsing a real file", async () => {
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
    render(<BomCompareTool />);

    // Pristine first contact: the empty state is shown instead of the grid,
    // with the GROUP workflow's own copy (per-workflow EmptyState, 2026-07-13).
    expect(
      screen.getByText("Compare a grouping file against a BOM"),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Browse for grouping file" }),
    );

    // After a real file lands the grid must appear with BOTH slots.
    expect(await screen.findByText("Grouping workbook")).toBeInTheDocument();
    expect(screen.getByText("BOM workbook")).toBeInTheDocument();
    expect(
      screen.queryByText("Compare a grouping file against a BOM"),
    ).not.toBeInTheDocument();
  });

  // User decision (2026-07-13): EVERY workflow card greets fresh with the
  // onboarding EmptyState — the old `workflowId === default` gate made only
  // Group vs BOM show the panel while equally-empty Custom/Extraction cards
  // rendered the slot grid ("one upload look, two menu boxes").
  it("shows workflow-specific empty-state copy on each fresh card", async () => {
    const user = userEvent.setup();
    render(<BomCompareTool />);

    expect(
      screen.getByText("Compare a grouping file against a BOM"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Browse for grouping file" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Custom Compare/i }));
    expect(screen.getByText("Compare two BOMs")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Browse for first BOM" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Extraction Compare/i }));
    expect(
      screen.getByText("Compare two extraction reports"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Browse for older extraction" }),
    ).toBeInTheDocument();
  });

  // Per-workflow independence: a real file loaded in one workflow exits
  // pristine for THAT card only. The per-workflow input cache keeps every
  // other card's onboarding EmptyState intact, and returning to the loaded
  // card never resurrects the panel.
  it("keeps an untouched workflow's empty state after another workflow loads a real file", async () => {
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
    render(<BomCompareTool />);

    await user.click(
      screen.getByRole("button", { name: "Browse for grouping file" }),
    );
    expect(await screen.findByText("Grouping workbook")).toBeInTheDocument();

    // Custom Compare is untouched — still greets with ITS empty state.
    await user.click(screen.getByRole("button", { name: /Custom Compare/i }));
    expect(screen.getByText("Compare two BOMs")).toBeInTheDocument();

    // Back on Group vs BOM: the grid persists; pristine never resurrects.
    await user.click(screen.getByRole("button", { name: /Group vs BOM/i }));
    expect(await screen.findByText("Grouping workbook")).toBeInTheDocument();
    expect(
      screen.queryByText("Compare a grouping file against a BOM"),
    ).not.toBeInTheDocument();
  });

  // Regression (Family 1): in desktop mode the tool used to seed inputStates
  // with cloneInputs(scenario.inputs) UNCONDITIONALLY, leaking the fake
  // example path "DRIVE\inputs\NavUnit_Grouping.xlsx" (non-empty path + a
  // sheet) into real runs. Such un-browsed slots passed validation then
  // crashed mid-run with FileNotFoundError naming a path the user never
  // typed. Desktop seeding must produce empty paths.
  it("does not leak the example grouping path on first render in desktop mode", () => {
    render(<BomCompareTool />);

    // The fake example path must not appear anywhere on first contact.
    expect(
      screen.queryByText("DRIVE\\inputs\\NavUnit_Grouping.xlsx"),
    ).not.toBeInTheDocument();
  });

  // Regression (Family 1): after dispatching a group run with no browsed
  // files, every input the backend receives must carry an empty path —
  // never a seeded example path.
  it("sends empty input paths when no file was browsed (group run)", async () => {
    const user = userEvent.setup();
    render(<BomCompareTool />);

    await user.click(screen.getByRole("tab", { name: /^Run$/i }));
    await user.click(screen.getByRole("button", { name: "Compare" }));

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    const request = backendMocks.executeRun.mock.calls[0][0];
    for (const input of request.inputs as Array<{ path: string }>) {
      expect(input.path).toBe("");
    }
  });

  // treat_prov_as_covered reads the grouping file's group-name column,
  // which custom compare (two plain BOMs) does not have — the backend never
  // consumes it on the custom path, so the checkbox must read as inert there.
  it("disables the group-only prov checkbox in Custom Compare", async () => {
    const user = userEvent.setup();
    render(<BomCompareTool />);

    expect(screen.getByRole("checkbox", { name: /treat prov as covered/i })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: /Custom Compare/i }));
    expect(screen.getByRole("checkbox", { name: /treat prov as covered/i })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /Group vs BOM/i }));
    expect(screen.getByRole("checkbox", { name: /treat prov as covered/i })).toBeEnabled();
  });

  // Batch 6 #2: base_match is a no-op when exact_match is on and its raw
  // key ("base match") misleads — base-RefDes matching is ALWAYS on. Give it a
  // truthful label + a hint (Wiring Invariant #2: never a silently-ignored /
  // mislabelled control).
  it("labels base_match truthfully and shows a prefix-matching hint", () => {
    render(<BomCompareTool />);

    // Truthful label replaces the misleading "base match".
    expect(
      screen.getByRole("checkbox", { name: /loose prefix base match/i }),
    ).toBeInTheDocument();
    // The hint explains base matching is always on and this is prefix-only.
    expect(
      screen.getByText(/Base-RefDes matching is always on/i),
    ).toBeInTheDocument();
  });

  // Batch 6 #2 (extended): the five previously-mechanical option checkboxes
  // used to render lowercase, hint-less labels straight from the option key
  // ("exact match", "ignore dnp", "check part usage", "check fmr", "treat prov
  // as covered"). They now show human-cased labels with descriptive hints.
  // Case-SENSITIVE anchored name regexes assert the human-casing (a lowercase
  // "exact match" no longer matches), and the descriptive hint text asserts the
  // hint renders (there was no hint at all before).
  it("renders human-cased option labels with descriptive hints", () => {
    render(<BomCompareTool />);

    // Human-cased labels (default Group vs BOM mode — all enabled).
    expect(
      screen.getByRole("checkbox", { name: /^Exact match/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: /^Ignore DNP rows/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: /^Check Part Usage/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: /^Check Failure Mode Ratios/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: /^Treat PROV as covered/ }),
    ).toBeInTheDocument();

    // Descriptive hints render alongside their labels.
    expect(
      screen.getByText("Compare RefDes tokens verbatim — no base-RefDes reduction."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Skip Do-Not-Populate parts before comparing."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Validate Part Usage against instance counts and add a warnings sheet.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Verify each part's ratios sum to 1.0 and add a check sheet."),
    ).toBeInTheDocument();
  });

  it("dispatches bomA/bomB inputs and custom mappings for a custom run", async () => {
    const user = userEvent.setup();
    render(<BomCompareTool />);

    await user.click(screen.getByRole("button", { name: /Custom Compare/i }));
    await user.click(screen.getByRole("tab", { name: /^Run$/i }));
    await user.click(screen.getByRole("button", { name: "Compare" }));

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    const request = backendMocks.executeRun.mock.calls[0][0];
    expect(request).toMatchObject({ workflowId: "bom_compare_custom" });
    expect(request.inputs.map((input: { role: string }) => input.role)).toEqual([
      "bomA",
      "bomB",
    ]);
    expect(
      request.mappings.map((mapping: { canonical: string }) => mapping.canonical),
    ).toEqual(["refdes_col_a", "refdes_col_b"]);
  });

  // Regression (Fix 1): the workflow-change effect used to re-seed inputStates
  // from the demo scenario on EVERY switch, so a round-trip (load a real file
  // in Group → peek at Custom → back to Group) permanently discarded the
  // loaded path. The per-workflow state cache must restore the loaded slice.
  it("preserves a loaded file across a workflow round-trip", async () => {
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
    render(<BomCompareTool />);

    // Load a real grouping file in Group vs BOM mode.
    await user.click(screen.getByRole("button", { name: "Browse for grouping file" }));
    const loadedPath = await screen.findByText("C:\\real\\Grouping.xlsx");
    expect(loadedPath).toBeInTheDocument();
    // Let the post-browse inspect round-trip settle so the slot is fully
    // loaded (tag transitions Inspecting → Desktop → Analyzed) before we
    // switch workflows.
    await waitFor(() => expect(backendMocks.inspectInput).toHaveBeenCalled());
    // v2 N6: the tag chip became the row indicator's tooltip.
    expect(await screen.findByTitle("Analyzed")).toBeInTheDocument();

    // Round-trip: peek at Custom Compare, then back to Group vs BOM.
    await user.click(screen.getByRole("button", { name: /Custom Compare/i }));
    await user.click(screen.getByRole("button", { name: /Group vs BOM/i }));

    // The loaded path must survive — without the cache it reverts to the
    // example mock "DRIVE\\inputs\\NavUnit_Grouping.xlsx".
    expect(await screen.findByText("C:\\real\\Grouping.xlsx")).toBeInTheDocument();
    expect(
      screen.queryByText("DRIVE\\inputs\\NavUnit_Grouping.xlsx"),
    ).not.toBeInTheDocument();
  });

  // Regression (Family 2): the Start/Compare button was not disabled during
  // the async validateRun roundtrip, so a second handleStartRun could fire.
  // The second executeRun was rejected by Python's single-active-run guard,
  // landed in the catch, and unconditionally called resetDesktopRunSession() —
  // clearing the FIRST (live) run's session from the store, dropping its
  // events and result. The re-entrancy guard must make the second click a
  // no-op so executeRun fires exactly once.
  it("does not start a second run when Compare is double-clicked during validation", async () => {
    let resolveValidate: (value: {
      ok: boolean;
      reason_code: string;
      toast_text: string;
      validations: never[];
      output_preview: null;
      mode: string;
    }) => void = () => {};
    backendMocks.validateRun.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveValidate = resolve;
        }),
    );

    const user = userEvent.setup();
    render(<BomCompareTool />);

    await user.click(screen.getByRole("tab", { name: /^Run$/i }));
    const compareButton = screen.getByRole("button", { name: "Compare" });

    // Two clicks while validateRun is still pending. The guard must swallow
    // the second so only ONE validate→execute pipeline runs.
    await user.click(compareButton);
    await user.click(compareButton);

    // Only one validate roundtrip should have started.
    expect(backendMocks.validateRun).toHaveBeenCalledTimes(1);

    // Resolve the single validate; the (single) executeRun then fires.
    resolveValidate({
      ok: true,
      reason_code: "ready",
      toast_text: "Ready to run.",
      validations: [],
      output_preview: null,
      mode: "desktop-bridge",
    });

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    // Crucially, executeRun must NOT have been called twice (which would have
    // wiped the live run via the rejected second run's catch path).
    expect(backendMocks.executeRun).toHaveBeenCalledTimes(1);
  });

  // Regression (Fix 2): a stale validate_run result stranded in the Preview
  // tab after the user changed an input file — the previous run's validation
  // cards kept describing the OLD file. Browsing a new file must clear them.
  it("clears stale validation cards after browsing a new file", async () => {
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

    // A blocked validate populates real validation cards (M9 removed the
    // demo-seeded card this test previously used as its stale fixture).
    backendMocks.validateRun.mockResolvedValue({
      ok: false,
      reason_code: "missing_files",
      toast_text: "Select required files: Second BOM.",
      validations: [
        {
          id: "validation-missing_files",
          severity: "error",
          area: "Run State",
          title: "Run is blocked",
          detail: "Select required files: Second BOM.",
        },
      ],
      output_preview: null,
      mode: "desktop-bridge",
    });

    const user = userEvent.setup();
    render(<BomCompareTool />);

    // M9: desktop mode seeds NO demo validation card.
    expect(screen.queryByText("Example data staged")).not.toBeInTheDocument();

    // A blocked start leaves real validation cards behind.
    await user.click(screen.getByRole("tab", { name: /^Run$/i }));
    await user.click(screen.getByRole("button", { name: "Compare" }));
    await user.click(screen.getByRole("tab", { name: /preview/i }));
    expect(
      await screen.findByText("Select required files: Second BOM."),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Browse for grouping file" }));

    // Once the new file lands the stale card is gone (neutral empty state).
    await screen.findByText("C:\\real\\Grouping.xlsx");
    await waitFor(() =>
      expect(
        screen.queryByText("Select required files: Second BOM."),
      ).not.toBeInTheDocument(),
    );
  });

  // Regression (Bug 1): Tauri v2 rejects `Result<_, String>` with a RAW
  // STRING, not an Error instance. The legacy `error instanceof Error
  // ? error.message : <generic fallback>` discarded the backend's real
  // message for every string rejection, so the input card's resolution note
  // read the generic "Unknown sheet inspection failure" instead of the
  // sidecar's actual explanation. describeBackendError must surface the raw
  // string verbatim.
  it("surfaces a raw-string sheet inspection rejection in the input card note", async () => {
    const backendMessage =
      "Could not locate a non-empty header row within the first 1000 scanned rows.";
    backendMocks.openExcelFile.mockResolvedValue("C:\\real\\Grouping.xlsx");
    // Reject with a RAW STRING — exactly how Tauri surfaces a
    // `Result<_, String>` error to the frontend.
    backendMocks.listSheets.mockRejectedValue(backendMessage);

    const user = userEvent.setup();
    render(<BomCompareTool />);

    await user.click(screen.getByRole("button", { name: "Browse for grouping file" }));

    // The backend's real message must appear verbatim in the resolution note.
    expect(await screen.findByText(backendMessage)).toBeInTheDocument();
    // And the generic fallback must NOT have replaced it.
    expect(
      screen.queryByText("Unknown sheet inspection failure"),
    ).not.toBeInTheDocument();
  });

  // Bug fix (adversarially verified): the Column Mapping dropdowns used to be
  // static fixtures (bomCompareGroupMappings) that were never rebuilt from the
  // real workbook's inspected headers — inspectRole discarded inspection.columns
  // (only .length was read). On a real file the dropdown then offered fixture
  // strings ("Component Group", "Reference Designator") that may not exist, the
  // mappedTo defaults were pre-filled regardless, and a mismatch only surfaced
  // at execute time as a ColumnMappingError. Now the grouping rows are derived
  // from the inspected columns for the "grouping" role.
  it("rebuilds the grouping mapping dropdowns from the inspected workbook headers", async () => {
    backendMocks.openExcelFile.mockResolvedValue("C:\\real\\Grouping.xlsx");
    backendMocks.listSheets.mockResolvedValue({
      path: "C:\\real\\Grouping.xlsx",
      sheets: ["Grouping"],
      mode: "desktop-bridge",
    });
    // Real headers: "Reference Designator" matches the refdes fixture default
    // (auto-fill), but the group fixture default "Component Group" is absent
    // (no match → unmapped/attention).
    backendMocks.inspectInput.mockResolvedValue({
      mode: "desktop-bridge",
      sheet: "Grouping",
      columns: ["Circuit Block", "Reference Designator"],
    });

    const user = userEvent.setup();
    render(<BomCompareTool />);

    await user.click(screen.getByRole("button", { name: "Browse for grouping file" }));
    await screen.findByText("C:\\real\\Grouping.xlsx");
    await waitFor(() => expect(backendMocks.inspectInput).toHaveBeenCalled());

    // The grouping group dropdown now offers the REAL headers, not the stale
    // fixture options. Open the combobox and inspect its options.
    const groupCombobox = await screen.findByRole("combobox", {
      name: /grouping_group_col mapping/i,
    });
    await user.click(groupCombobox);
    expect(
      await screen.findByRole("option", { name: "Circuit Block" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "Reference Designator" }),
    ).toBeInTheDocument();
    // The fixture-only default that does NOT exist in this workbook is gone.
    expect(
      screen.queryByRole("option", { name: "Component Group" }),
    ).not.toBeInTheDocument();
  });

  // Bug fix (continued): exact-name auto-fill on a real header match and
  // needs-attention on a no-match must be reflected in the run request that is
  // dispatched — the backend must receive the real header (or empty), never a
  // stale fixture default for the inspected role.
  it("dispatches real inspected headers (and empty for no-match) for the grouping role", async () => {
    backendMocks.openExcelFile.mockResolvedValue("C:\\real\\Grouping.xlsx");
    backendMocks.listSheets.mockResolvedValue({
      path: "C:\\real\\Grouping.xlsx",
      sheets: ["Grouping"],
      mode: "desktop-bridge",
    });
    backendMocks.inspectInput.mockResolvedValue({
      mode: "desktop-bridge",
      sheet: "Grouping",
      columns: ["Circuit Block", "Reference Designator"],
    });

    const user = userEvent.setup();
    render(<BomCompareTool />);

    await user.click(screen.getByRole("button", { name: "Browse for grouping file" }));
    await screen.findByText("C:\\real\\Grouping.xlsx");
    await waitFor(() => expect(backendMocks.inspectInput).toHaveBeenCalled());
    // Wait for the inspected slot to settle (tag transitions to "Analyzed",
    // carried by the v2 row indicator's tooltip) so the derived mapping rows
    // reflect the real headers before we run.
    await screen.findByTitle("Analyzed");

    await user.click(screen.getByRole("tab", { name: /^Run$/i }));
    await user.click(screen.getByRole("button", { name: "Compare" }));

    await waitFor(() => expect(backendMocks.executeRun).toHaveBeenCalledTimes(1));
    const request = backendMocks.executeRun.mock.calls[0][0];
    const mappingByCanonical = Object.fromEntries(
      (request.mappings as Array<{ canonical: string; mappedTo: string }>).map(
        (mapping) => [mapping.canonical, mapping.mappedTo],
      ),
    );

    // refdes row auto-filled to the real header (exact match).
    expect(mappingByCanonical.grouping_refdes_col).toBe("Reference Designator");
    // group row has no matching header in this workbook — empty, NOT the stale
    // fixture default "Component Group".
    expect(mappingByCanonical.grouping_group_col).toBe("");
  });

  // Regression (review finding): switching workflow while a listSheets
  // inspection is still in flight stashed the slot with isResolvingSheets
  // still true. Restoring that slice verbatim left the slot permanently
  // stuck on "Loading..." with Browse and the sheet picker disabled — no
  // in-app recovery. The cache must sanitize busy flags on stash and the
  // per-role tokens must be bumped so the late continuation is dropped.
  it("recovers a slot whose inspection was interrupted by a workflow switch", async () => {
    backendMocks.openExcelFile.mockResolvedValue("C:\\real\\Grouping.xlsx");
    let resolveListSheets: (value: {
      path: string;
      sheets: string[];
      mode: string;
    }) => void = () => {};
    backendMocks.listSheets.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveListSheets = resolve;
        }),
    );

    const user = userEvent.setup();
    render(<BomCompareTool />);

    // Start browsing — listSheets stays pending (isResolvingSheets: true).
    await user.click(screen.getByRole("button", { name: "Browse for grouping file" }));
    expect(await screen.findByRole("button", { name: "Loading..." })).toBeInTheDocument();

    // Switch away while the inspection is still in flight — the outgoing
    // slice is stashed mid-inspection.
    await user.click(screen.getByRole("button", { name: /Custom Compare/i }));

    // The orphaned listSheets continuation fires while Custom is active:
    // its role ("grouping") matches nothing in the bomA/bomB slice, so the
    // resolution is dropped and the stash keeps its busy flags.
    resolveListSheets({
      path: "C:\\real\\Grouping.xlsx",
      sheets: ["Grouping"],
      mode: "desktop-bridge",
    });
    await waitFor(() => expect(backendMocks.listSheets).toHaveBeenCalledTimes(1));

    // Returning restores the stashed slice.
    await user.click(screen.getByRole("button", { name: /Group vs BOM/i }));

    // The restored slot must be recoverable: Browse re-enabled on BOTH
    // slots (no permanently-stuck "Loading..." button).
    await waitFor(() => {
      const browseButtons = screen.getAllByRole("button", { name: "Browse" });
      expect(browseButtons).toHaveLength(2);
      for (const button of browseButtons) {
        expect(button).toBeEnabled();
      }
    });
    expect(screen.queryByRole("button", { name: "Loading..." })).not.toBeInTheDocument();
  });

  // Regression (#16): switching workflow MID-RUN must not orphan the backend
  // job. The change-effect used the unguarded resetDesktopRunSession, which
  // cleared a live run from the store (dropping its events/result and blocking
  // the next run). The guarded variant must leave a live run untouched.
  it("disables workflow changes without clobbering the owning live run", async () => {
    const user = userEvent.setup();
    render(<BomCompareTool />);

    // A run is live (running) and owned by this tool.
    act(() => {
      useRunStore.getState().setActiveRun(
        buildActiveRunFromAccepted({
          runId: "live_bc_run",
          toolId: "bom_compare",
          sessionGeneration: 1,
        }),
      );
      useRunStore.getState().patchActiveRun({ phase: "running" });
    });

    const selected = screen.getByRole("button", { name: /Group vs BOM/i });
    const other = screen.getByRole("button", { name: /Custom Compare/i });
    expect(selected).toBeDisabled();
    expect(other).toBeDisabled();
    expect(selected).toHaveAttribute("aria-pressed", "true");
    expect(other).toHaveAttribute("aria-pressed", "false");
    await user.click(other);

    expect(useRunStore.getState().activeRun?.runId).toBe("live_bc_run");
    expect(useRunStore.getState().activeRun?.phase).toBe("running");
  });

  it("pauses pristine Browse app-wide without locking this tool's workflow selector", () => {
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
    render(<BomCompareTool />);

    const browse = screen.getByRole("button", { name: "Browse for grouping file" });
    expect(browse).toBeDisabled();
    expect(browse).toHaveAttribute(
      "title",
      "File inspection is paused while a run is active.",
    );
    expect(screen.getByRole("button", { name: /Custom Compare/i })).toBeEnabled();
  });

  // Regression (#17): a finished run's terminal phase lingers in the store, so
  // when Browse flips the busy chip, useBackendBusyReset sees (terminal phase +
  // busy) and wipes the "Inspecting..." chip. handleBrowse must clear the stale
  // terminal run first (guarded, so a live sibling run is never clobbered).
  it("clears a lingering terminal run when browsing a new file", async () => {
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
    render(<BomCompareTool />);

    // A finished run lingers (terminal phase, owned by this tool).
    act(() => {
      useRunStore.getState().setActiveRun(
        buildActiveRunFromAccepted({
          runId: "done_bc_run",
          toolId: "bom_compare",
          sessionGeneration: 1,
        }),
      );
      useRunStore.getState().patchActiveRun({ phase: "success" });
    });

    // A terminal run makes the tool non-pristine, so the InputGrid (with
    // "Browse" buttons) renders in place of the pristine EmptyState.
    await user.click(screen.getAllByRole("button", { name: "Browse" })[0]);

    await waitFor(() => expect(useRunStore.getState().activeRun).toBeNull());
  });

  // Tier-1 #5: enter Custom Compare and inspect BOTH files so the column-pair
  // picker has real headers to auto-pair from.
  async function enterCustomAndInspectBothFiles(
    user: ReturnType<typeof userEvent.setup>,
  ) {
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
    await user.click(screen.getByRole("button", { name: /Custom Compare/i }));
    // A fresh Custom card greets with its per-workflow EmptyState; the first
    // browse enters through it, which reveals the grid for the second slot.
    await user.click(screen.getByRole("button", { name: "Browse for first BOM" }));
    await waitFor(() => expect(backendMocks.inspectInput).toHaveBeenCalledTimes(1));
    await user.click(screen.getAllByRole("button", { name: "Browse" })[1]);
    await waitFor(() => expect(backendMocks.inspectInput).toHaveBeenCalledTimes(2));
  }

  // Tier-1 #5: the picker auto-pairs matching headers (RefDes excluded) in
  // Custom Compare and is hidden entirely in Group mode (no second BOM to pair).
  it("auto-pairs matching columns in Custom Compare and hides the picker in Group mode", async () => {
    const user = userEvent.setup();
    render(<BomCompareTool />);
    await enterCustomAndInspectBothFiles(user);

    expect(screen.getByText("Column Value Comparison")).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: /Remove compare pair/i }),
    ).toHaveLength(2); // Part Number + Description; Reference Designator excluded

    await user.click(screen.getByRole("button", { name: /Group vs BOM/i }));
    expect(screen.queryByText("Column Value Comparison")).not.toBeInTheDocument();
  });

  // Regression: removing the LAST auto-paired row must leave the picker empty —
  // the auto-pair seed is one-shot per inspected file set, so it must not
  // re-fire just because the array returned to empty.
  it("does not re-seed after the user removes the last compare pair", async () => {
    const user = userEvent.setup();
    render(<BomCompareTool />);
    await enterCustomAndInspectBothFiles(user);

    await user.click(screen.getAllByRole("button", { name: /Remove compare pair/i })[1]);
    await user.click(screen.getAllByRole("button", { name: /Remove compare pair/i })[0]);

    expect(
      screen.queryByRole("button", { name: /Remove compare pair/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/No column comparisons configured/i)).toBeInTheDocument();
  });

  // Regression: a trimmed pair set must survive a Custom->Group->Custom
  // round-trip (the per-workflow cache restores it and the auto-pair seed must
  // not re-fire over the restored value).
  it("preserves a trimmed compare-pair set across a Custom->Group->Custom round-trip", async () => {
    const user = userEvent.setup();
    render(<BomCompareTool />);
    await enterCustomAndInspectBothFiles(user);

    await user.click(screen.getAllByRole("button", { name: /Remove compare pair/i })[1]);
    expect(
      screen.getAllByRole("button", { name: /Remove compare pair/i }),
    ).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: /Group vs BOM/i }));
    await user.click(screen.getByRole("button", { name: /Custom Compare/i }));

    expect(
      screen.getAllByRole("button", { name: /Remove compare pair/i }),
    ).toHaveLength(1);
  });
});
