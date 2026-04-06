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
});
