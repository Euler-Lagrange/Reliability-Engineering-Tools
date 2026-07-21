import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { useShellStore } from "../stores/shellStore";
import { ValidationPreview } from "./ValidationPreview";
import type { PreviewRow, ValidationMessage } from "../app/types";

const previewRows: PreviewRow[] = [
  {
    id: "row-1",
    refdes: "U14",
    failureMode: "Open circuit",
    localEffect: "Navigation card loses isolated power rail.",
    nextHigherEffect: "Guidance channel enters degraded mode.",
  },
  {
    id: "row-2",
    refdes: "C209",
    failureMode: "Capacitance drift high",
    localEffect: "Hold-up timing margin is reduced below nominal.",
    nextHigherEffect: "Warm restart sensitivity increases during transient load.",
  },
];

const validations: ValidationMessage[] = [
  {
    id: "val-1",
    severity: "info",
    area: "Mapping",
    title: "Ready to run",
    detail: "All inputs loaded and mapped.",
  },
];

beforeEach(() => {
  useShellStore.setState({ contextOpen: false });
});

describe("ValidationPreview", () => {
  it("renders a compact two-column preview (full row lives in the drawer)", () => {
    render(<ValidationPreview validations={validations} previewRows={previewRows} />);

    expect(screen.getByRole("columnheader", { name: "RefDes" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Failure mode" })).toBeInTheDocument();
    // The four-column layout hard-clipped in the ~430px side panel — the
    // trailing effect columns must NOT render here anymore.
    expect(screen.queryByRole("columnheader", { name: /local effect/i })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("columnheader", { name: /next higher effect/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("U14")).toBeInTheDocument();
    expect(screen.getByText("Capacitance drift high")).toBeInTheDocument();
  });

  it("opens the Review drawer from the Full preview affordance", async () => {
    const user = userEvent.setup();
    render(<ValidationPreview validations={validations} previewRows={previewRows} />);

    expect(useShellStore.getState().contextOpen).toBe(false);
    await user.click(screen.getByRole("button", { name: /full preview/i }));
    expect(useShellStore.getState().contextOpen).toBe(true);
  });

  it("shows an EmptyState instead of a dangling header row when there are no preview rows", () => {
    render(<ValidationPreview validations={validations} previewRows={[]} />);

    expect(screen.getByText("No preview rows yet")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /full preview/i })).not.toBeInTheDocument();
  });

  it("does not count an informational validation row as an issue", () => {
    render(<ValidationPreview validations={validations} previewRows={[]} />);

    expect(screen.getByText("Ready to run")).toBeInTheDocument();
    expect(screen.queryByText(/\d+ issues?/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /copy issues/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /export csv/i })).not.toBeInTheDocument();
  });

  it("counts warning and error rows while leaving information visible", () => {
    const mixedValidations: ValidationMessage[] = [
      ...validations,
      {
        id: "val-warning",
        severity: "warning",
        area: "Mapping",
        title: "Review suggested mapping",
        detail: "One optional column has an ambiguous match.",
      },
      {
        id: "val-error",
        severity: "error",
        area: "Inputs",
        title: "Workbook missing",
        detail: "Select the required workbook.",
      },
    ];

    render(<ValidationPreview validations={mixedValidations} previewRows={[]} />);

    expect(
      screen.getByText(
        (_, element) =>
          element?.className === "validation-preview__toolbar-count" &&
          element.textContent === "2 issues",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Ready to run")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy issues/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /export csv/i })).toBeInTheDocument();
  });
});
