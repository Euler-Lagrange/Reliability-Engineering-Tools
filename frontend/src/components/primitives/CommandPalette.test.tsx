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

    const input = await screen.findByRole("combobox", { name: /search command palette/i });
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

  test("exposes combobox semantics wired to the listbox", async () => {
    render(<CommandPalette actions={makeActions()} open={true} onClose={vi.fn()} />);

    const input = await screen.findByRole("combobox", { name: /search command palette/i });
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(input).toHaveAttribute("aria-autocomplete", "list");

    const controls = input.getAttribute("aria-controls");
    expect(controls).toBeTruthy();
    const listbox = screen.getByRole("listbox", { name: /command palette results/i });
    expect(listbox).toHaveAttribute("id", controls);
  });

  test("aria-activedescendant follows arrow-key navigation", async () => {
    const user = userEvent.setup();

    render(<CommandPalette actions={makeActions()} open={true} onClose={vi.fn()} />);

    const input = await screen.findByRole("combobox", { name: /search command palette/i });
    const fmeaOption = screen.getByRole("option", { name: /FMEA Generator/i });
    expect(fmeaOption.id).toBeTruthy();

    // First option is active by default → aria-activedescendant points at it.
    await waitFor(() => {
      expect(input).toHaveAttribute("aria-activedescendant", fmeaOption.id);
    });

    await user.keyboard("{ArrowDown}");
    const themeOption = screen.getByRole("option", { name: /Theme: Dark Precision/i });
    expect(themeOption.id).toBeTruthy();
    expect(themeOption.id).not.toBe(fmeaOption.id);
    expect(input).toHaveAttribute("aria-activedescendant", themeOption.id);

    await user.keyboard("{ArrowUp}");
    expect(input).toHaveAttribute("aria-activedescendant", fmeaOption.id);
  });

  test("aria-activedescendant is absent when no actions match", async () => {
    const user = userEvent.setup();

    render(<CommandPalette actions={makeActions()} open={true} onClose={vi.fn()} />);

    const input = await screen.findByRole("combobox", { name: /search command palette/i });
    await act(async () => {
      await user.type(input, "zzznomatch");
    });

    expect(input).not.toHaveAttribute("aria-activedescendant");
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

    const input = await screen.findByRole("combobox", { name: /search command palette/i });
    await act(async () => {
      await user.type(input, "zzznomatch");
    });

    expect(screen.getByRole("heading", { name: /no matches/i })).toBeInTheDocument();
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });
});
