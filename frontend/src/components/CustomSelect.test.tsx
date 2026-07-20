import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CustomSelect } from "./CustomSelect";

describe("CustomSelect", () => {
  test("opens and selects an option", async () => {
    const user = userEvent.setup();
    const selections: string[] = [];

    render(
      <CustomSelect
        label="Mapping select"
        value="A"
        options={[
          { value: "A", label: "Alpha" },
          { value: "B", label: "Beta" },
        ]}
        onChange={(value) => selections.push(value)}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Mapping select" }));
    await user.click(await screen.findByRole("option", { name: /beta/i }));

    expect(selections).toEqual(["B"]);
  });

  test("shows the opt-in placeholder when the value is empty", () => {
    render(
      <CustomSelect
        label="Mapping select"
        value=""
        options={[{ value: "A", label: "Alpha" }]}
        placeholder="Select column…"
      />,
    );

    expect(screen.getByText("Select column…")).toBeInTheDocument();
  });

  test("open menu viewport carries the scroll class", async () => {
    // Long option lists (a wide BOM's 30+ headers in "Select column") must
    // scroll. The CSS caps .custom-select__menu height and un-hides the
    // native scrollbar on .custom-select__viewport — Radix injects a rule
    // that hides it otherwise. This pins the class wiring the CSS targets;
    // jsdom cannot verify the visual scrollbar itself.
    const user = userEvent.setup();
    render(
      <CustomSelect
        label="Mapping select"
        value="A"
        options={Array.from({ length: 40 }, (_, i) => ({
          value: `C${i}`,
          label: `Column ${i}`,
        }))}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "Mapping select" }));
    const listbox = await screen.findByRole("listbox");
    const viewport = listbox.closest(".custom-select__menu")?.querySelector(
      ".custom-select__viewport[data-radix-select-viewport]",
    );
    expect(viewport).toBeTruthy();
  });

  test("renders an empty trigger without a placeholder unless opted in", () => {
    render(
      <CustomSelect
        label="Sheet select"
        value=""
        options={[{ value: "A", label: "Alpha" }]}
      />,
    );

    // Input-card sheet pickers legitimately render empty while sheets
    // resolve — no placeholder text may leak in without the opt-in prop.
    expect(screen.queryByText("Select column…")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Sheet select" })).toHaveTextContent("");
  });
});
