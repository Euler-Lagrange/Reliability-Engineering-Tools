import { render, screen } from "@testing-library/react";
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
  });
  useThemeStore.setState({
    mode: "system",
  });
  return render(<App />);
}

async function waitForFmeaTool() {
  await screen.findByRole("heading", {
    name: /fmea generator/i,
    level: 2,
  });
}

describe("tauri_build shell", () => {
  test("shows the dark star tool by default and switches to BOM Compare", async () => {
    const user = userEvent.setup();
    renderApp();

    await waitForFmeaTool();

    await user.click(screen.getByRole("button", { name: /compare/i }));

    expect(screen.getByRole("button", { name: /compare/i })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByRole("heading", { name: /bom comparison tool/i })).toBeInTheDocument();
  });

  test("switches theme modes from the shell rail", async () => {
    const user = userEvent.setup();
    renderApp();

    await user.click(screen.getByRole("button", { name: /switch to dark theme/i }));
    expect(document.documentElement.dataset.theme).toBe("dark_precision");

    await user.click(screen.getByRole("button", { name: /switch to light theme/i }));
    expect(document.documentElement.dataset.theme).toBe("light_precision");
  });

  test("shows target workbook only for existing-workbook strategies", async () => {
    const user = userEvent.setup();
    renderApp();
    await waitForFmeaTool();

    expect(screen.queryByText("Target workbook")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /preserve formatting/i }));

    expect(screen.getByText("Target workbook")).toBeInTheDocument();
  });

  test("switches inputs when workflow changes to fill gaps", async () => {
    const user = userEvent.setup();
    renderApp();
    await waitForFmeaTool();

    expect(screen.queryByText("Existing FMEA workbook")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /fill gaps/i }));

    expect(screen.getByText("Existing FMEA workbook")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Functional FMEA" })).not.toBeInTheDocument();
  });
});
