import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";
import { useShellStore } from "../stores/shellStore";
import { useThemeStore } from "../stores/themeStore";

function renderApp() {
  window.localStorage.clear();
  useShellStore.setState({
    activeToolId: "dark_star_fmea",
    backendStatus: "connecting",
    backendMode: "unknown",
    backendMessage: "Initializing backend bridge...",
    lastBackendCheckAt: null,
    contextOpen: false,
  });
  useThemeStore.setState({
    mode: "system",
  });
  return render(<App />);
}

async function waitForFmeaTool() {
  // Wait on the FMEA pane's own workflow card, not a heading: the per-tool
  // banner heading was removed (the shell topbar is the single title), and
  // the Suspense fallback renders a transient "Preparing FMEA Generator"
  // heading that a name-based heading query could race against.
  await screen.findByRole("button", { name: /piece-part from grouping file/i });
}

describe("tauri_build shell", () => {
  test("shows the dark star tool by default and switches to BOM Compare", async () => {
    const user = userEvent.setup();
    renderApp();

    await waitForFmeaTool();

    await user.click(screen.getByRole("button", { name: /compare/i }));

    expect(screen.getByRole("button", { name: /compare/i })).toHaveAttribute("aria-current", "page");
    // Label-independent sentinel: the tool's own "Run Setup" section heading.
    expect(await screen.findByRole("heading", { name: /run setup/i })).toBeInTheDocument();
  });

  test("switches theme modes from the shell rail", async () => {
    const user = userEvent.setup();
    renderApp();

    await user.click(screen.getByRole("button", { name: /switch to dark theme/i }));
    expect(document.documentElement.dataset.theme).toBe("dark_precision");

    await user.click(screen.getByRole("button", { name: /switch to light theme/i }));
    expect(document.documentElement.dataset.theme).toBe("light_precision");
  });

  test("default FMEA layout shows generation options first and outputs second", async () => {
    renderApp();
    await waitForFmeaTool();

    const generationHeading = screen.getByRole("heading", {
      name: /^generation options$/i,
      level: 2,
    });
    const outputsHeading = screen.getByRole("heading", {
      name: /outputs/i,
      level: 2,
    });

    const generationSection = generationHeading.closest("section");
    const outputsSection = outputsHeading.closest("section");

    expect(generationSection).not.toBeNull();
    expect(outputsSection).not.toBeNull();

    if (!generationSection || !outputsSection) {
      throw new Error("Expected FMEA setup sections to render.");
    }

    expect(within(generationSection).getByRole("button", { name: /piece-part from grouping file/i })).toBeInTheDocument();
    expect(within(generationSection).getByRole("radio", { name: /fmd-2016/i })).toBeInTheDocument();
    expect(within(generationSection).getByText("Grouping workbook")).toBeInTheDocument();
    expect(within(generationSection).getByText("BOM workbook")).toBeInTheDocument();
    expect(within(generationSection).getByText("Failure modes workbook")).toBeInTheDocument();

    expect(within(outputsSection).getByText("Output Folder")).toBeInTheDocument();
    expect(within(outputsSection).queryByText("Target workbook")).not.toBeInTheDocument();
  });

  test("shows target workbook only for preserve-formatting strategy", async () => {
    const user = userEvent.setup();
    renderApp();
    await waitForFmeaTool();

    const outputsSection = screen.getByRole("heading", { name: /outputs/i, level: 2 }).closest("section");
    if (!outputsSection) {
      throw new Error("Expected Outputs section to render.");
    }

    expect(within(outputsSection).queryByText("Target workbook")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /preserve formatting/i }));

    expect(within(outputsSection).getByText("Target workbook")).toBeInTheDocument();
  });

  test("moves focus into the main workspace after a tool switch", async () => {
    const user = userEvent.setup();
    renderApp();

    await waitForFmeaTool();

    await user.click(screen.getByRole("button", { name: /compare/i }));

    await screen.findByRole("heading", { name: /run setup/i });

    await waitFor(() => {
      const main = document.querySelector("main[aria-label='Cross Compare workspace']");
      expect(main).not.toBeNull();
      expect(document.activeElement).toBe(main);
    });
  });

  test("switches inputs when workflow changes to Merge Piece-Part FMEA", async () => {
    const user = userEvent.setup();
    renderApp();
    await waitForFmeaTool();

    expect(screen.queryByText("Existing FMEA workbook")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /merge piece-part fmea/i }));

    expect(screen.getByText("Existing FMEA workbook")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Functional FMEA" })).not.toBeInTheDocument();
  });

  test("shows CCA identifier field only in BOM-Only mode", async () => {
    const user = userEvent.setup();
    renderApp();
    await waitForFmeaTool();

    // Default mode is piece_part_generate — no CCA input visible.
    expect(screen.queryByLabelText("CCA identifier")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /piece-part from bom only/i }));
    expect(screen.getByLabelText("CCA identifier")).toBeInTheDocument();

    // Switching away hides it again.
    await user.click(screen.getByRole("button", { name: /piece-part from grouping file/i }));
    expect(screen.queryByLabelText("CCA identifier")).not.toBeInTheDocument();
  });

  test("shows HDA file input only when Separate HDA file is selected", async () => {
    const user = userEvent.setup();
    renderApp();
    await waitForFmeaTool();

    // Default is "Inline in BOM" — HDA workbook should be hidden.
    expect(screen.queryByText("HDA workbook")).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: /separate hda file/i }));
    expect(screen.getByText("HDA workbook")).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: /inline in bom/i }));
    expect(screen.queryByText("HDA workbook")).not.toBeInTheDocument();
  });

  test("updates visible inputs when FMEA mode changes between all four workflows", async () => {
    const user = userEvent.setup();
    renderApp();
    await waitForFmeaTool();

    // Start with Merge Functional: functionalFmea shown, existingFmea hidden.
    await user.click(screen.getByRole("button", { name: /merge functional fmea/i }));
    expect(screen.getByText("Functional FMEA workbook")).toBeInTheDocument();
    expect(screen.queryByText("Existing FMEA workbook")).not.toBeInTheDocument();
    expect(screen.getByText("BOM workbook")).toBeInTheDocument();

    // Merge Piece-Part FMEA: existingFmea shown, functionalFmea hidden.
    await user.click(screen.getByRole("button", { name: /merge piece-part fmea/i }));
    expect(screen.getByText("Existing FMEA workbook")).toBeInTheDocument();
    expect(screen.queryByText("Functional FMEA workbook")).not.toBeInTheDocument();

    // Piece-Part from Grouping File: grouping shown, no FMEA sources.
    await user.click(screen.getByRole("button", { name: /piece-part from grouping file/i }));
    expect(screen.getByText("Grouping workbook")).toBeInTheDocument();
    expect(screen.queryByText("Functional FMEA workbook")).not.toBeInTheDocument();
    expect(screen.queryByText("Existing FMEA workbook")).not.toBeInTheDocument();

    // BOM-Only: neither functional nor existing nor grouping visible.
    await user.click(screen.getByRole("button", { name: /piece-part from bom only/i }));
    expect(screen.queryByText("Functional FMEA workbook")).not.toBeInTheDocument();
    expect(screen.queryByText("Existing FMEA workbook")).not.toBeInTheDocument();
    expect(screen.queryByText("Grouping workbook")).not.toBeInTheDocument();
    expect(screen.getByText("BOM workbook")).toBeInTheDocument();
  });

  test("workflow changes do not leave target workbook visible after returning to new workbook", async () => {
    const user = userEvent.setup();
    renderApp();
    await waitForFmeaTool();

    const outputsSection = screen.getByRole("heading", { name: /outputs/i, level: 2 }).closest("section");
    if (!outputsSection) {
      throw new Error("Expected Outputs section to render.");
    }

    await user.click(screen.getByRole("button", { name: /merge piece-part fmea/i }));
    expect(within(outputsSection).queryByText("Target workbook")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /preserve formatting/i }));
    expect(within(outputsSection).getByText("Target workbook")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /new workbook/i }));
    expect(within(outputsSection).queryByText("Target workbook")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /piece-part from grouping file/i }));
    expect(within(outputsSection).queryByText("Target workbook")).not.toBeInTheDocument();
  });

  test("does not open the command palette while focus is inside an input", async () => {
    renderApp();
    await waitForFmeaTool();

    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();

    fireEvent.keyDown(input, { key: "k", ctrlKey: true });

    expect(screen.queryByRole("dialog", { name: /command palette/i })).not.toBeInTheDocument();
    input.remove();
  });
});
