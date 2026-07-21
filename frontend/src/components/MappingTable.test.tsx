import { render, screen, fireEvent, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { MappingTable, helpPanelId } from "./MappingTable";
import {
  DO_NOT_MAP_LABEL,
  DO_NOT_MAP_VALUE,
  type ColumnMappingRow,
} from "../app/types";

function rowWithHelp(overrides: Partial<ColumnMappingRow> = {}): ColumnMappingRow {
  return {
    canonical: "Failure Mode",
    mappedTo: "Failure Mode",
    status: "mapped",
    recommendation: "Exact header match",
    options: ["Failure Mode", "Mode"],
    help: "Maps the failure mode column. Required — FMEA cannot generate without it.",
    required: true,
    ...overrides,
  };
}

function rowWithoutHelp(overrides: Partial<ColumnMappingRow> = {}): ColumnMappingRow {
  return {
    canonical: "Part Number",
    mappedTo: "Part Number",
    status: "mapped",
    recommendation: "Exact header match",
    options: ["Part Number", "PN"],
    ...overrides,
  };
}

describe("MappingTable — Phase 2 infrastructure", () => {
  test("renders info icon only when row.help is set", () => {
    const rows: ColumnMappingRow[] = [rowWithHelp(), rowWithoutHelp()];
    render(
      <MappingTable rows={rows} overrides={{}} onOverride={vi.fn()} />,
    );

    // Row with help text exposes an "About {canonical}" button.
    expect(
      screen.getByRole("button", { name: /about failure mode/i }),
    ).toBeInTheDocument();

    // Row without help text does NOT expose a help button — backward
    // compatible for BOM Compare / Failure Rate which don't author help.
    expect(
      screen.queryByRole("button", { name: /about part number/i }),
    ).not.toBeInTheDocument();
  });

  test("clicking the info icon toggles the help panel", async () => {
    const user = userEvent.setup();
    const rows: ColumnMappingRow[] = [rowWithHelp()];
    render(
      <MappingTable rows={rows} overrides={{}} onOverride={vi.fn()} />,
    );

    const helpButton = screen.getByRole("button", { name: /about failure mode/i });
    expect(helpButton).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/ABOUT THIS COLUMN/i)).not.toBeInTheDocument();

    await user.click(helpButton);

    expect(helpButton).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/ABOUT THIS COLUMN/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Maps the failure mode column/i),
    ).toBeInTheDocument();

    // aria-controls must match the rendered panel id.
    expect(helpButton).toHaveAttribute(
      "aria-controls",
      helpPanelId("Failure Mode"),
    );
    expect(document.getElementById(helpPanelId("Failure Mode"))).not.toBeNull();

    // Second click collapses.
    await user.click(helpButton);
    expect(helpButton).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/ABOUT THIS COLUMN/i)).not.toBeInTheDocument();
  });

  test("optional unmapped rows are neutral and excluded from the unmapped badge", () => {
    // UX findings 2026-07-07 #3: an optional row with no mapping is a normal
    // state — no amber Attention chip, no contribution to "N unmapped".
    const rows: ColumnMappingRow[] = [
      rowWithHelp({
        canonical: "Failure Mode",
        mappedTo: "",
        status: "attention",
        required: true,
      }),
      rowWithoutHelp({
        canonical: "Function column",
        mappedTo: "",
        status: "attention",
        recommendation: "Optional. Select a Function column for FR rollup.",
      }),
    ];
    render(<MappingTable rows={rows} overrides={{}} onOverride={vi.fn()} />);

    // Only the REQUIRED unmapped row counts toward the badge.
    expect(screen.getByText("1 unmapped")).toBeInTheDocument();
    // The required row keeps its amber Attention chip...
    expect(screen.getByText("Attention")).toBeInTheDocument();
    // ...while the optional row demotes to the neutral Not mapped chip.
    expect(screen.getByText("Not mapped")).toBeInTheDocument();
  });

  test("a valid explicit override renders and counts as a manual mapping", () => {
    const { container } = render(
      <MappingTable
        rows={[
          rowWithHelp({
            mappedTo: "",
            status: "attention",
            options: ["Failure Mode", "Mode"],
          }),
        ]}
        overrides={{ "Failure Mode": "Mode" }}
        onOverride={vi.fn()}
        onClearAllMappings={vi.fn()}
      />,
    );

    expect(container.querySelector('.state-word[data-status="manual"]')).toHaveTextContent(
      "Manual",
    );
    expect(screen.getByText("1 manual")).toBeInTheDocument();
    expect(screen.queryByText("1 unmapped")).not.toBeInTheDocument();
  });

  test("an orphaned explicit override is unmapped, with optional rows kept neutral", () => {
    const { container } = render(
      <MappingTable
        rows={[
          rowWithHelp({
            mappedTo: "Current Failure Mode",
            status: "mapped",
            options: ["Current Failure Mode"],
          }),
          rowWithoutHelp({
            canonical: "Optional Notes",
            mappedTo: "Current Notes",
            status: "mapped",
            options: ["Current Notes"],
          }),
        ]}
        overrides={{
          "Failure Mode": "Removed Failure Mode",
          "Optional Notes": "Removed Notes",
        }}
        onOverride={vi.fn()}
        onClearAllMappings={vi.fn()}
      />,
    );

    expect(container.querySelector('.state-word[data-status="manual"]')).toBeNull();
    expect(screen.queryByText(/manual$/i)).not.toBeInTheDocument();
    expect(screen.getByText("1 unmapped")).toBeInTheDocument();
    expect(screen.getByText("Attention")).toBeInTheDocument();
    expect(screen.getByText("Not mapped")).toBeInTheDocument();
  });

  test("marks required rows with a required indicator, optional rows unmarked", () => {
    // rowWithHelp carries required: true; rowWithoutHelp has no required flag.
    render(
      <MappingTable
        rows={[rowWithHelp(), rowWithoutHelp()]}
        overrides={{}}
        onOverride={vi.fn()}
      />,
    );

    const marker = screen.getByLabelText("Required column");
    const requiredRow = marker.closest("tr");
    expect(requiredRow).toHaveTextContent("Failure Mode");
    expect(requiredRow).not.toHaveTextContent("Part Number");
    // Exactly one marker — the optional row must not render one.
    expect(screen.getAllByLabelText("Required column")).toHaveLength(1);
  });

  test("only one help panel is expanded at a time", async () => {
    const user = userEvent.setup();
    const rows: ColumnMappingRow[] = [
      rowWithHelp({ canonical: "Failure Mode", help: "Help A" }),
      rowWithHelp({ canonical: "Failure Mode Ratio", help: "Help B" }),
    ];
    render(
      <MappingTable rows={rows} overrides={{}} onOverride={vi.fn()} />,
    );

    const buttonA = screen.getByRole("button", { name: /about failure mode$/i });
    const buttonB = screen.getByRole("button", {
      name: /about failure mode ratio/i,
    });

    await user.click(buttonA);
    expect(buttonA).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Help A")).toBeInTheDocument();

    await user.click(buttonB);
    // Opening B should close A.
    expect(buttonA).toHaveAttribute("aria-expanded", "false");
    expect(buttonB).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByText("Help A")).not.toBeInTheDocument();
    expect(screen.getByText("Help B")).toBeInTheDocument();
  });

  test("Escape collapses the expanded help panel", async () => {
    const user = userEvent.setup();
    const rows: ColumnMappingRow[] = [rowWithHelp({ help: "Help body" })];
    render(
      <MappingTable rows={rows} overrides={{}} onOverride={vi.fn()} />,
    );

    const helpButton = screen.getByRole("button", { name: /about failure mode/i });
    await user.click(helpButton);
    expect(helpButton).toHaveAttribute("aria-expanded", "true");

    fireEvent.keyDown(window, { key: "Escape" });

    expect(helpButton).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Help body")).not.toBeInTheDocument();
  });

  test("Do Not Map option appears at the top of the dropdown", async () => {
    const user = userEvent.setup();
    const rows: ColumnMappingRow[] = [
      rowWithoutHelp({
        canonical: "Part Number",
        options: ["Part Number", "PN", "Component Part Number"],
      }),
    ];
    render(
      <MappingTable rows={rows} overrides={{}} onOverride={vi.fn()} />,
    );

    await user.click(
      screen.getByRole("combobox", { name: /part number mapping/i }),
    );

    const options = await screen.findAllByRole("option");
    expect(options).toHaveLength(4); // DO_NOT_MAP + 3 originals
    expect(options[0]).toHaveTextContent(DO_NOT_MAP_LABEL);
  });

  test("renders source-aware option labels while preserving raw values", async () => {
    const user = userEvent.setup();
    render(
      <MappingTable
        rows={[
          rowWithHelp({
            options: ["Failure Mode", "Mode"],
            optionLabels: {
              "Failure Mode": "Failure Mode - Failure modes workbook",
              Mode: "Mode - Legacy workbook",
            },
          }),
        ]}
        overrides={{}}
        onOverride={vi.fn()}
      />,
    );

    await user.click(
      screen.getByRole("combobox", { name: /failure mode mapping/i }),
    );

    expect(
      await screen.findByRole("option", {
        name: "Failure Mode - Failure modes workbook",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "Mode - Legacy workbook" }),
    ).toBeInTheDocument();
  });

  test("selecting Do Not Map fires onOverride with the sentinel", async () => {
    const user = userEvent.setup();
    const onOverride = vi.fn();
    const rows: ColumnMappingRow[] = [rowWithoutHelp({ canonical: "Part Number" })];
    render(
      <MappingTable rows={rows} overrides={{}} onOverride={onOverride} />,
    );

    await user.click(
      screen.getByRole("combobox", { name: /part number mapping/i }),
    );
    await user.click(
      await screen.findByRole("option", { name: DO_NOT_MAP_LABEL }),
    );

    expect(onOverride).toHaveBeenCalledWith("Part Number", DO_NOT_MAP_VALUE);
  });

  test("rows mapped to DO_NOT_MAP show the italic muted trigger", () => {
    const rows: ColumnMappingRow[] = [
      rowWithoutHelp({ canonical: "Optional Field", mappedTo: "Optional Field" }),
    ];
    const { container } = render(
      <MappingTable
        rows={rows}
        overrides={{ "Optional Field": DO_NOT_MAP_VALUE }}
        onOverride={vi.fn()}
      />,
    );

    const wrapper = container.querySelector(
      ".mapping-table__trigger-wrapper--not-mapped",
    );
    expect(wrapper).not.toBeNull();

    // The resolved status renders as a dot + word carrying the
    // not_mapped state (v2 N7 replaced the chip with .state-word).
    const chip = container.querySelector('.state-word[data-status="not_mapped"]');
    expect(chip).not.toBeNull();
    expect(chip?.textContent).toMatch(/not mapped/i);
  });

  test("mapping state renders 'Derived' when status is derived", () => {
    const rows: ColumnMappingRow[] = [
      {
        canonical: "FMEA Level",
        mappedTo: "",
        status: "derived",
        recommendation: "Always derived from row type",
        options: [],
        origin: "derived",
      },
    ];
    const { container } = render(
      <MappingTable rows={rows} overrides={{}} onOverride={vi.fn()} />,
    );

    const chip = container.querySelector('.state-word[data-status="derived"]');
    expect(chip).not.toBeNull();
    expect(chip?.textContent).toBe("Derived");
  });

  test("Clear all mappings callback fires and consumers can set sentinel", async () => {
    // The MappingTable itself delegates clear semantics to the parent.
    // This test verifies the callback fires with no surprises and the
    // toolbar is enabled once any override exists.
    const user = userEvent.setup();
    const onClear = vi.fn();
    const rows: ColumnMappingRow[] = [rowWithoutHelp()];
    render(
      <MappingTable
        rows={rows}
        overrides={{ "Part Number": "PN" }}
        onOverride={vi.fn()}
        onClearAllMappings={onClear}
      />,
    );

    const clearButton = screen.getByRole("button", { name: /clear all mappings/i });
    expect(clearButton).not.toBeDisabled();
    await user.click(clearButton);
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  test("rows without help have no info button and the canonical label still renders", () => {
    const rows: ColumnMappingRow[] = [rowWithoutHelp({ canonical: "Quantity" })];
    render(
      <MappingTable rows={rows} overrides={{}} onOverride={vi.fn()} />,
    );

    expect(screen.getByText("Quantity")).toBeInTheDocument();
    // Cells rendered — query by canonical text inside the field wrapper.
    const fieldName = screen.getByText("Quantity");
    const row = fieldName.closest("tr");
    expect(row).not.toBeNull();
    if (row) {
      expect(
        within(row).queryByRole("button", { name: /about/i }),
      ).not.toBeInTheDocument();
    }
  });
});
