import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OutputFolderPicker } from "./OutputFolderPicker";
import { useNotificationStore } from "../stores/notificationStore";

const backendMocks = vi.hoisted(() => ({
  openDirectory: vi.fn(),
}));

vi.mock("../shared/backend/client", () => ({
  backendClient: {
    runtimeMode: "desktop-bridge",
    openDirectory: backendMocks.openDirectory,
  },
}));

beforeEach(() => {
  useNotificationStore.setState({ notifications: [] });
  backendMocks.openDirectory.mockReset();
});

// Wiring Invariant #5 / Tier-3 #26: the folder-picker catch block must route
// the thrown value through describeBackendError. Tauri v2 rejects a
// Result<_, String> command with a RAW STRING (not an Error), so the old
// ``error instanceof Error ? error.message : <fallback>`` ternary discarded
// every real backend message and showed only the generic fallback.
describe("OutputFolderPicker backend-error surfacing", () => {
  it("surfaces a raw string rejection from the native dialog verbatim", async () => {
    backendMocks.openDirectory.mockRejectedValue(
      "OS denied access to \\\\server\\share",
    );

    const user = userEvent.setup();
    render(<OutputFolderPicker value={null} onChange={() => {}} />);
    await user.click(screen.getByRole("button", { name: /change/i }));

    await waitFor(() =>
      expect(useNotificationStore.getState().notifications).toHaveLength(1),
    );
    const note = useNotificationStore.getState().notifications[0];
    expect(note.tone).toBe("error");
    // The real message — NOT the generic "Unknown folder picker failure".
    expect(note.detail).toBe("OS denied access to \\\\server\\share");
  });

  it("uses an Error's message when the rejection is a real Error", async () => {
    backendMocks.openDirectory.mockRejectedValue(new Error("dialog crashed"));

    const user = userEvent.setup();
    render(<OutputFolderPicker value={null} onChange={() => {}} />);
    await user.click(screen.getByRole("button", { name: /change/i }));

    await waitFor(() =>
      expect(useNotificationStore.getState().notifications).toHaveLength(1),
    );
    expect(useNotificationStore.getState().notifications[0].detail).toBe(
      "dialog crashed",
    );
  });
});
