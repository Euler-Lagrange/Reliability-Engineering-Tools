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
