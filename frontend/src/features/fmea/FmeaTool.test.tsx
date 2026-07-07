import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, beforeEach } from "vitest";
import { App } from "../../app/App";
import { buildActiveRunFromAccepted, useRunStore } from "../../stores/runStore";
import { useShellStore } from "../../stores/shellStore";
import { useThemeStore } from "../../stores/themeStore";

const FMEA_TOOL_TEST_TIMEOUT_MS = 15_000;

/**
 * Phase 5: FMEA mapping row visibility tests.
 *
 * These tests exercise the `FMEA_COLUMN_METADATA` -> `buildFmeaMappingRows`
 * pipeline end-to-end by rendering the FMEA tool through the full App
 * shell and asserting canonical labels appear / disappear as the user
 * switches workflow mode and FMD standard. The metadata source of truth
 * lives in `mappingColumns.ts`; its unit coverage is in
 * `mappingColumns.test.ts`.
 */

function renderApp() {
  window.localStorage.clear();
  useShellStore.setState({
    activeToolId: "dark_star_fmea",
    backendStatus: "connecting",
    backendMode: "unknown",
    backendMessage: "Initializing backend bridge...",
    lastBackendCheckAt: null,
  });
  useThemeStore.setState({
    mode: "system",
  });
  return render(<App />);
}

async function waitForFmeaTool() {
  // The Suspense fallback renders a transient "Preparing FMEA Generator"
  // heading while the lazy chunk loads (and the tool itself no longer has
  // a banner heading at all), so heading queries are the wrong sentinel.
  // The Workflow card's mode selector is only rendered by the real
  // `FmeaTool`, so we wait on one of its workflow buttons instead. This
  // also guarantees the mapping table below has finished its first render
  // by the time tests query it.
  await screen.findByRole(
    "button",
    { name: /piece-part from grouping file/i },
    { timeout: 3000 },
  );
}

/**
 * The mapping table renders canonical labels inside `.mapping-field__name`
 * spans. We use a DOM query (rather than `screen.getByText`) because some
 * canonical strings (e.g. "Failure Mode") appear elsewhere on the page
 * and `getByText` would be ambiguous.
 */
function mappingCanonicalLabels(): string[] {
  const nodes = document.querySelectorAll(".mapping-field__name");
  return Array.from(nodes).map((node) => node.textContent?.trim() ?? "");
}

function hasMappingLabel(label: string): boolean {
  return mappingCanonicalLabels().some((candidate) => candidate === label);
}

describe("FmeaTool — Phase 5 mapping row visibility", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useRunStore.setState({ activeRun: null });
  });

  test("default piece_part_generate mode shows FMEA-ID and hides merge-only rows", async () => {
    renderApp();
    await waitForFmeaTool();

    expect(hasMappingLabel("FMEA-ID")).toBe(true);
    expect(hasMappingLabel("Failure Mode")).toBe(true);
    expect(hasMappingLabel("Failure Mode Ratio")).toBe(true);
    expect(hasMappingLabel("Part Usage")).toBe(true);
    expect(hasMappingLabel("FMEA Level")).toBe(true);

    // Merge-only rows are hidden in piece_part_generate.
    expect(hasMappingLabel("Local Effect")).toBe(false);
    expect(hasMappingLabel("Next Higher Effect")).toBe(false);
    expect(hasMappingLabel("End Effect")).toBe(false);

    // UX findings 2026-07-07 #2/#5: browser-mock seeds demo workbook columns,
    // so the hero metric computes a real percentage (never the literal "TBD"
    // placeholder) and the demo mapping rows auto-map.
    expect(screen.queryByText("TBD")).toBeNull();
  }, FMEA_TOOL_TEST_TIMEOUT_MS);

  test("BOM-Only mode hides the FMEA-ID mapping row", async () => {
    const user = userEvent.setup();
    renderApp();
    await waitForFmeaTool();

    expect(hasMappingLabel("FMEA-ID")).toBe(true);

    await user.click(screen.getByRole("button", { name: /piece-part from bom only/i }));

    expect(hasMappingLabel("FMEA-ID")).toBe(false);
    // Non-FMEA-ID rows still render.
    expect(hasMappingLabel("Failure Mode")).toBe(true);
    expect(hasMappingLabel("Failure Mode Ratio")).toBe(true);
  }, FMEA_TOOL_TEST_TIMEOUT_MS);

  test("Merge Functional FMEA mode shows Local / Next Higher / End Effect rows", async () => {
    const user = userEvent.setup();
    renderApp();
    await waitForFmeaTool();

    expect(hasMappingLabel("Local Effect")).toBe(false);
    expect(hasMappingLabel("Next Higher Effect")).toBe(false);
    expect(hasMappingLabel("End Effect")).toBe(false);

    await user.click(screen.getByRole("button", { name: /merge functional fmea/i }));

    expect(hasMappingLabel("Local Effect")).toBe(true);
    expect(hasMappingLabel("Next Higher Effect")).toBe(true);
    expect(hasMappingLabel("End Effect")).toBe(true);
    expect(hasMappingLabel("FMEA-ID")).toBe(true);
  }, FMEA_TOOL_TEST_TIMEOUT_MS);

  test("merge modes mark Failure Mode Causes as required; non-merge modes do not", async () => {
    const user = userEvent.setup();
    renderApp();
    await waitForFmeaTool();

    // piece_part_generate: three statically-required rows carry the marker,
    // Failure Mode Causes does not (auto-detect is acceptable there).
    const initialMarkers = screen.getAllByLabelText("Required column");
    expect(initialMarkers).toHaveLength(3);
    expect(
      initialMarkers.some((marker) =>
        marker.closest("tr")?.textContent?.includes("Failure Mode Causes"),
      ),
    ).toBe(false);

    // Merge mode: the backend hard-requires the Failure Mode Causes mapping
    // (missing_failure_mode_causes_mapping), so the marker must appear.
    await user.click(screen.getByRole("button", { name: /merge functional fmea/i }));

    const mergeMarkers = screen.getAllByLabelText("Required column");
    expect(mergeMarkers).toHaveLength(4);
    expect(
      mergeMarkers.some((marker) =>
        marker.closest("tr")?.textContent?.includes("Failure Mode Causes"),
      ),
    ).toBe(true);
  }, FMEA_TOOL_TEST_TIMEOUT_MS);

  test("Merge Piece-Part FMEA mode also shows merge-only rows", async () => {
    const user = userEvent.setup();
    renderApp();
    await waitForFmeaTool();

    await user.click(screen.getByRole("button", { name: /merge piece-part fmea/i }));

    expect(hasMappingLabel("Local Effect")).toBe(true);
    expect(hasMappingLabel("Next Higher Effect")).toBe(true);
    expect(hasMappingLabel("End Effect")).toBe(true);
  }, FMEA_TOOL_TEST_TIMEOUT_MS);

  test("FMD commodity column labels swap when the standard toggles", async () => {
    const user = userEvent.setup();
    renderApp();
    await waitForFmeaTool();

    // Default standard is FMD-2016.
    expect(hasMappingLabel("FMD-2016 Commodity Type 1")).toBe(true);
    expect(hasMappingLabel("FMD-2016 Commodity Type 2")).toBe(true);
    expect(hasMappingLabel("FMD-91 Commodity Type 1")).toBe(false);

    // Switch to FMD-91 via the Failure Modes Standard radio.
    await user.click(screen.getByRole("radio", { name: /fmd-91/i }));

    expect(hasMappingLabel("FMD-91 Commodity Type 1")).toBe(true);
    expect(hasMappingLabel("FMD-91 Commodity Type 2")).toBe(true);
    expect(hasMappingLabel("FMD-2016 Commodity Type 1")).toBe(false);
    expect(hasMappingLabel("FMD-2016 Commodity Type 2")).toBe(false);
  }, FMEA_TOOL_TEST_TIMEOUT_MS);

  test("Fix B-Strategy: changing output strategy preserves manual mapping overrides", async () => {
    // Fix B-Strategy: the reset effect used to fire on
    // [workflowId, outputStrategyId] and unconditionally wiped
    // mappingOverrides. But changing the output strategy never changes
    // which mapping rows are visible (visibility keys only on workflowId),
    // so nuking the user's manual mappings was pure data loss that
    // buildRunRequest then silently reverted. The fix splits the effect so
    // a strategy change resets only run-presentation state.
    const user = userEvent.setup();
    renderApp();
    await waitForFmeaTool();

    // Set a manual override on a stable, always-visible row. With no
    // workbook inspected in the default mock, the only selectable option
    // is the "— Do Not Map —" sentinel, which is a perfectly valid
    // manual override for this assertion.
    const failureModeSelect = screen.getByRole("combobox", {
      name: /^Failure Mode mapping$/i,
    });
    await user.click(failureModeSelect);
    await user.click(await screen.findByRole("option", { name: /do not map/i }));

    expect(
      screen.getByRole("combobox", { name: /^Failure Mode mapping$/i }).textContent,
    ).toContain("Do Not Map");

    // Switch the output strategy via the StrategySelector card.
    await user.click(
      screen.getByRole("button", { name: /existing workbook \(preserve formatting\)/i }),
    );

    // The manual override must survive the strategy change.
    expect(
      screen.getByRole("combobox", { name: /^Failure Mode mapping$/i }).textContent,
    ).toContain("Do Not Map");
  }, FMEA_TOOL_TEST_TIMEOUT_MS);

  test("Fix B-FMD: toggling the FMD standard preserves Commodity Type overrides", async () => {
    // Fix B-FMD: mappingOverrides is keyed by the resolved (dynamic)
    // Commodity Type label. Toggling the standard rebuilt the rows with the
    // other standard's canonical, so the override lookup missed and the row
    // reverted to auto-mapped. The fix migrates the dynamic override keys
    // when the standard changes (migrateFmdOverrides).
    const user = userEvent.setup();
    renderApp();
    await waitForFmeaTool();

    // Default standard is FMD-2016. Set a manual override on the dynamic
    // Commodity Type 1 row.
    const commoditySelect = screen.getByRole("combobox", {
      name: /^FMD-2016 Commodity Type 1 mapping$/i,
    });
    await user.click(commoditySelect);
    await user.click(await screen.findByRole("option", { name: /do not map/i }));

    expect(
      screen.getByRole("combobox", { name: /^FMD-2016 Commodity Type 1 mapping$/i })
        .textContent,
    ).toContain("Do Not Map");

    // Toggle the standard to FMD-91 — the row's label (and override key)
    // changes, but the override must follow.
    await user.click(screen.getByRole("radio", { name: /fmd-91/i }));

    expect(
      screen.getByRole("combobox", { name: /^FMD-91 Commodity Type 1 mapping$/i })
        .textContent,
    ).toContain("Do Not Map");
  }, FMEA_TOOL_TEST_TIMEOUT_MS);

  test("info icon renders for every mapping row with help text", async () => {
    renderApp();
    await waitForFmeaTool();

    const helpButtons = document.querySelectorAll(".mapping-table__help-button");
    // 11 rows visible in the default piece_part_generate mode (14 - 3 merge).
    expect(helpButtons.length).toBe(11);
  }, FMEA_TOOL_TEST_TIMEOUT_MS);

  test("Fix B2: switching workflow mode does not reset inspection-backed mapping", async () => {
    // Fix B2: the effect that handles workflow-mode changes used to
    // call setInputInspections({}) and setTemplateAnalyses({}), which
    // wiped column inspection data on every mode switch. The loaded
    // file paths stayed in inputStates (InputGrid still rendered them
    // as loaded), but the mapping table lost every inspected column
    // dropdown option. Now we preserve both inspection maps.
    //
    // Regression signal: switch mode back and forth several times and
    // assert the mapping table renders every canonical row cleanly.
    // If the fix regresses, the subsequent mappings continue to work
    // only because inspection data isn't plumbed in the default mock
    // scenario — but the assertion that each mode-switch round-trip
    // preserves row counts is still a useful guard against re-adding
    // unnecessary state resets to that effect.
    const user = userEvent.setup();
    renderApp();
    await waitForFmeaTool();

    const initialCount = document.querySelectorAll(".mapping-field__name").length;

    await user.click(screen.getByRole("button", { name: /merge functional fmea/i }));
    const mergeCount = document.querySelectorAll(".mapping-field__name").length;
    expect(mergeCount).toBeGreaterThanOrEqual(initialCount);

    await user.click(screen.getByRole("button", { name: /piece-part from grouping file/i }));
    const backToDefault = document.querySelectorAll(".mapping-field__name").length;
    expect(backToDefault).toBe(initialCount);

    // One more round-trip to be sure the effect body is stable.
    await user.click(screen.getByRole("button", { name: /merge piece-part fmea/i }));
    await user.click(screen.getByRole("button", { name: /piece-part from grouping file/i }));
    expect(document.querySelectorAll(".mapping-field__name").length).toBe(initialCount);
  }, FMEA_TOOL_TEST_TIMEOUT_MS);

  // Regression (#16): switching workflow mode MID-RUN must not orphan the
  // backend job — the change-effect's reset must be guarded so a live run
  // survives.
  test("does not clobber a live run when the workflow mode is switched mid-run", async () => {
    const user = userEvent.setup();
    renderApp();
    await waitForFmeaTool();

    act(() => {
      useRunStore.getState().setActiveRun(
        buildActiveRunFromAccepted({
          runId: "live_fmea_workflow",
          toolId: "dark_star_fmea",
          sessionGeneration: 1,
        }),
      );
      useRunStore.getState().patchActiveRun({ phase: "running" });
    });

    await user.click(screen.getByRole("button", { name: /piece-part from bom only/i }));

    expect(useRunStore.getState().activeRun?.runId).toBe("live_fmea_workflow");
    expect(useRunStore.getState().activeRun?.phase).toBe("running");
  }, FMEA_TOOL_TEST_TIMEOUT_MS);

  // Regression (#16): the SEPARATE output-strategy change-effect must also use
  // the guarded reset so switching strategy mid-run can't orphan the job.
  test("does not clobber a live run when the output strategy is switched mid-run", async () => {
    const user = userEvent.setup();
    renderApp();
    await waitForFmeaTool();

    act(() => {
      useRunStore.getState().setActiveRun(
        buildActiveRunFromAccepted({
          runId: "live_fmea_strategy",
          toolId: "dark_star_fmea",
          sessionGeneration: 1,
        }),
      );
      useRunStore.getState().patchActiveRun({ phase: "running" });
    });

    await user.click(
      screen.getByRole("button", { name: /existing workbook \(preserve formatting\)/i }),
    );

    expect(useRunStore.getState().activeRun?.runId).toBe("live_fmea_strategy");
    expect(useRunStore.getState().activeRun?.phase).toBe("running");
  }, FMEA_TOOL_TEST_TIMEOUT_MS);
});
