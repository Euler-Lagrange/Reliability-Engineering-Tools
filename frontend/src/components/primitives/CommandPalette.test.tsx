import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Cpu, Gear, Palette } from "@phosphor-icons/react";
import { CommandPalette, type CommandPaletteAction } from "./CommandPalette";

function makeActions(
  onFmeaSelect = vi.fn(),
  onThemeSelect = vi.fn(),
  onSettingsSelect = vi.fn(),
): CommandPaletteAction[] {
  return [
    {
      id: "tool/fmea",
      label: "FMEA Generator",
      category: "Tools",
      icon: Cpu,
      shortcut: "Ctrl+1",
      onSelect: onFmeaSelect,
    },
    {
      id: "theme/dark",
      label: "Theme: Dark Precision",
      category: "Themes",
      icon: Palette,
      onSelect: onThemeSelect,
    },
    {
      id: "app/settings",
      label: "Open Settings",
      category: "App",
      icon: Gear,
      onSelect: onSettingsSelect,
    },
  ];
}

describe("CommandPalette", () => {
  test("opens on render when open is true and closes on Escape", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(<CommandPalette actions={makeActions()} open={true} onClose={onClose} />);

    const dialog = await screen.findByRole("dialog", { name: /command palette/i });
    expect(dialog).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test("filters actions by typing in the search input", async () => {
    const user = userEvent.setup();

    render(<CommandPalette actions={makeActions()} open={true} onClose={vi.fn()} />);

    const input = await screen.findByRole("textbox", { name: /search command palette/i });
    await user.type(input, "theme");

    expect(screen.getByRole("option", { name: /Theme: Dark Precision/i })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /FMEA Generator/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Open Settings/i })).not.toBeInTheDocument();
  });

  test("arrow keys navigate the active option", async () => {
    const user = userEvent.setup();

    render(<CommandPalette actions={makeActions()} open={true} onClose={vi.fn()} />);

    // First option is active by default.
    const fmeaOption = await screen.findByRole("option", { name: /FMEA Generator/i });
    await waitFor(() => {
      expect(fmeaOption).toHaveAttribute("aria-selected", "true");
    });

    await user.keyboard("{ArrowDown}");

    const themeOption = screen.getByRole("option", { name: /Theme: Dark Precision/i });
    expect(themeOption).toHaveAttribute("aria-selected", "true");
    expect(fmeaOption).toHaveAttribute("aria-selected", "false");

    await user.keyboard("{ArrowUp}");
    expect(fmeaOption).toHaveAttribute("aria-selected", "true");
  });

  test("Enter triggers onSelect on the active action", async () => {
    const onFmea = vi.fn();
    const onTheme = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(
      <CommandPalette
        actions={makeActions(onFmea, onTheme, vi.fn())}
        open={true}
        onClose={onClose}
      />,
    );

    await screen.findByRole("dialog");
    await user.keyboard("{ArrowDown}");
    await user.keyboard("{Enter}");

    expect(onTheme).toHaveBeenCalledTimes(1);
    expect(onFmea).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test("renders the empty state when no actions match the query", async () => {
    const user = userEvent.setup();

    render(<CommandPalette actions={makeActions()} open={true} onClose={vi.fn()} />);

    const input = await screen.findByRole("textbox", { name: /search command palette/i });
    await act(async () => {
      await user.type(input, "zzznomatch");
    });

    expect(screen.getByRole("heading", { name: /no matches/i })).toBeInTheDocument();
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });
});
