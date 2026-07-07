import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SettingsTool } from "./SettingsTool";

const { mockBackendClient } = vi.hoisted(() => ({
  mockBackendClient: {
    // Mutable so individual tests can flip to browser-mock.
    runtimeMode: "desktop-bridge" as string,
    healthCheck: vi.fn(),
    sessionStatus: vi.fn(),
    listSheets: vi.fn(),
    inspectInput: vi.fn(),
    analyzeTemplate: vi.fn(),
    validateRun: vi.fn(),
    executeRun: vi.fn(),
    cancelRun: vi.fn(),
    readFletConfig: vi.fn(),
    readRefdesPrefixes: vi.fn(),
    writeRefdesPrefixes: vi.fn(),
    revealInFileManager: vi.fn(),
    subscribeToRunEvents: vi.fn(async () => () => {}),
    subscribeToSessionEvents: vi.fn(async () => () => {}),
    openExcelFile: vi.fn(),
    openPdfFile: vi.fn(),
    openDirectory: vi.fn(),
  },
}));

vi.mock("../../shared/backend/client", () => ({
  backendClient: mockBackendClient,
}));

describe("SettingsTool — RefDes Prefixes card", () => {
  beforeEach(() => {
    window.localStorage.clear();
    mockBackendClient.runtimeMode = "desktop-bridge";
    mockBackendClient.readRefdesPrefixes.mockReset();
    mockBackendClient.writeRefdesPrefixes.mockReset();
    mockBackendClient.readRefdesPrefixes.mockResolvedValue({
      defaults: ["C", "R", "U"],
      custom: ["PS"],
      path: "C:\\Users\\test\\.refdes_extractor_config.json",
    });
  });

  it("loads and renders defaults, custom prefixes, and the restart caption", async () => {
    render(<SettingsTool />);

    expect(screen.getByText("RefDes Prefixes")).toBeInTheDocument();
    await waitFor(() =>
      expect(mockBackendClient.readRefdesPrefixes).toHaveBeenCalledTimes(1),
    );
    expect(await screen.findByText("PS")).toBeInTheDocument();
    expect(screen.getByText("IEEE-315 defaults (3)")).toBeInTheDocument();
    expect(screen.getByText("U")).toBeInTheDocument();
    expect(
      screen.getByText("Changes apply after the app restarts."),
    ).toBeInTheDocument();
    // Nothing edited yet — Save stays disabled.
    expect(screen.getByRole("button", { name: /save prefixes/i })).toBeDisabled();
  });

  it("adds, removes, and saves custom prefixes through the write command", async () => {
    mockBackendClient.writeRefdesPrefixes.mockResolvedValue({
      custom: ["PS", "XU"],
      path: "C:\\Users\\test\\.refdes_extractor_config.json",
      restart_required: true,
    });
    const user = userEvent.setup();
    render(<SettingsTool />);
    await screen.findByText("PS");

    // Lowercase input normalizes to uppercase chip.
    await user.type(screen.getByLabelText("New custom prefix"), "xu");
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.getByText("XU")).toBeInTheDocument();

    const save = screen.getByRole("button", { name: /save prefixes/i });
    expect(save).toBeEnabled();
    await user.click(save);
    await waitFor(() =>
      expect(mockBackendClient.writeRefdesPrefixes).toHaveBeenCalledWith(["PS", "XU"]),
    );
    // Saved state adopted — Save disables again.
    expect(screen.getByRole("button", { name: /save prefixes/i })).toBeDisabled();

    // Removing a chip re-dirties the draft.
    await user.click(screen.getByRole("button", { name: "Remove prefix PS" }));
    expect(screen.queryByText("PS")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save prefixes/i })).toBeEnabled();
  });

  it("rejects invalid prefixes client-side without calling the backend", async () => {
    const user = userEvent.setup();
    render(<SettingsTool />);
    await screen.findByText("PS");

    await user.type(screen.getByLabelText("New custom prefix"), "P2S");
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(screen.queryByText("P2S")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save prefixes/i })).toBeDisabled();
    expect(mockBackendClient.writeRefdesPrefixes).not.toHaveBeenCalled();
  });

  it("shows the desktop-required hint in browser preview and never calls the backend", () => {
    mockBackendClient.runtimeMode = "browser-mock";
    render(<SettingsTool />);

    expect(screen.getByText(/desktop runtime required/i)).toBeInTheDocument();
    expect(mockBackendClient.readRefdesPrefixes).not.toHaveBeenCalled();
  });

  it("surfaces a corrupt-config warning returned by the read", async () => {
    // Batch 6 #4a: a corrupt config file loads the defaults but returns a
    // ``warning`` string so the user knows a save will overwrite it.
    mockBackendClient.readRefdesPrefixes.mockResolvedValue({
      defaults: ["C", "R", "U"],
      custom: [],
      path: "C:\\Users\\test\\.refdes_extractor_config.json",
      warning:
        "Your saved prefix file could not be read (invalid JSON); showing defaults. Saving will overwrite it.",
    });
    render(<SettingsTool />);

    expect(
      await screen.findByText(/could not be read \(invalid JSON\)/i),
    ).toBeInTheDocument();
    // The editor still renders (defaults visible) — the warning is non-blocking.
    expect(screen.getByText("IEEE-315 defaults (3)")).toBeInTheDocument();
  });

  it("offers Retry after a failed load and recovers on success", async () => {
    // e.g. Settings opened while the sidecar is still reconnecting — the
    // first read fails; without Retry the card is stuck until app restart.
    mockBackendClient.readRefdesPrefixes
      .mockRejectedValueOnce(new Error("sidecar not connected"))
      .mockResolvedValueOnce({
        defaults: ["C", "R", "U"],
        custom: ["PS"],
        path: "C:\\Users\\test\\.refdes_extractor_config.json",
      });
    const user = userEvent.setup();
    render(<SettingsTool />);

    expect(await screen.findByText(/sidecar not connected/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("PS")).toBeInTheDocument();
    expect(mockBackendClient.readRefdesPrefixes).toHaveBeenCalledTimes(2);
  });
});
