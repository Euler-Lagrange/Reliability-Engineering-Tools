import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { NumberField } from "./NumberField";

describe("NumberField", () => {
  test("renders the label, hint and current value", () => {
    render(
      <NumberField
        id="batch"
        label="Geometry batch size"
        value={10}
        hint="Pages per geometry batch"
        onChange={vi.fn()}
      />,
    );
    const input = screen.getByRole("spinbutton", { name: "Geometry batch size" });
    expect(input).toHaveValue(10);
    expect(screen.getByText("Pages per geometry batch")).toBeInTheDocument();
  });

  test("emits the parsed numeric value on change", () => {
    const onChange = vi.fn();
    render(
      <NumberField id="batch" label="Geometry batch size" value={10} onChange={onChange} />,
    );
    const input = screen.getByRole("spinbutton", { name: "Geometry batch size" });
    fireEvent.change(input, { target: { value: "7" } });
    expect(onChange).toHaveBeenCalledWith(7);
  });

  test("keeps the previous value when input is cleared / NaN (NaN guard)", () => {
    const onChange = vi.fn();
    render(
      <NumberField id="batch" label="Geometry batch size" value={10} onChange={onChange} />,
    );
    const input = screen.getByRole("spinbutton", { name: "Geometry batch size" });
    fireEvent.change(input, { target: { value: "" } });
    expect(onChange).not.toHaveBeenCalled();
  });

  test("clamps a below-min value up to min", () => {
    const onChange = vi.fn();
    render(
      <NumberField id="batch" label="Geometry batch size" value={10} min={1} onChange={onChange} />,
    );
    const input = screen.getByRole("spinbutton", { name: "Geometry batch size" });
    fireEvent.change(input, { target: { value: "0" } });
    expect(onChange).toHaveBeenCalledWith(1);
  });

  test("does not clamp when value is at or above min", () => {
    const onChange = vi.fn();
    render(
      <NumberField id="batch" label="Geometry batch size" value={10} min={1} onChange={onChange} />,
    );
    const input = screen.getByRole("spinbutton", { name: "Geometry batch size" });
    fireEvent.change(input, { target: { value: "3" } });
    expect(onChange).toHaveBeenCalledWith(3);
  });

  test("forwards min/max/step and disabled to the input", () => {
    render(
      <NumberField
        id="batch"
        label="Geometry batch size"
        value={10}
        min={1}
        max={50}
        step={1}
        disabled
        onChange={vi.fn()}
      />,
    );
    const input = screen.getByRole("spinbutton", { name: "Geometry batch size" });
    expect(input).toBeDisabled();
    expect(input).toHaveAttribute("min", "1");
    expect(input).toHaveAttribute("max", "50");
    expect(input).toHaveAttribute("step", "1");
  });
});
