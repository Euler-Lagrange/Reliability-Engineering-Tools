import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";
import { useNotificationStore } from "../stores/notificationStore";
import { useRunStore } from "../stores/runStore";
import { useShellStore } from "../stores/shellStore";
import { useThemeStore } from "../stores/themeStore";

// Regression coverage for the keep-alive shell. Before keep-alive, the shell
// rendered only the active tool, so switching tools unmounted the outgoing
// tool and discarded every piece of its local useState (loaded files, sheet
// selections, mapping overrides, workflow selection). These tests prove that
// tool-local state now survives a tool-switch round-trip.

function renderApp() {
  window.localStorage.clear();
  useRunStore.setState({ activeRun: null });
  useNotificationStore.setState({ notifications: [] });
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

describe("keep-alive shell", () => {
  test("BOM Compare workflow selection survives a tool-switch round-trip", async () => {
    const user = userEvent.setup();
    renderApp();

    // Land on the FMEA tool (the default), then move to BOM Compare. Both
    // waits use tool-internal sentinels — the per-tool banner headings were
    // removed with the banner cards.
    await screen.findByRole("button", { name: /piece-part from grouping file/i });
    await user.click(screen.getByRole("button", { name: /bom comparison tool/i }));
    await screen.findByRole("heading", { name: /^options$/i });

    // Engage with BOM Compare by selecting the non-default "Custom Compare"
    // workflow card. This flips the tool's local workflowId away from its
    // bom_compare_group default — exactly the kind of local state that the
    // pre-keep-alive shell threw away on unmount.
    await user.click(screen.getByRole("button", { name: /custom compare/i }));
    expect(screen.getByRole("button", { name: /custom compare/i })).toHaveAttribute(
      "data-selected",
      "true",
    );

    // Switch away to the FMEA tool. Wait until BOM Compare is no longer in
    // the accessibility tree before continuing — this guarantees the switch
    // fully settled (the inactive tool is hidden) rather than racing a
    // half-committed render, so the round-trip is a real exercise of the
    // keep-alive behaviour.
    await user.click(screen.getByRole("button", { name: /fmea generator/i }));
    await waitFor(() => {
      expect(
        screen.queryByRole("heading", { name: /^options$/i }),
      ).not.toBeInTheDocument();
    });

    // Return to BOM Compare.
    await user.click(screen.getByRole("button", { name: /bom comparison tool/i }));
    await screen.findByRole("heading", { name: /^options$/i });

    // Custom Compare must still be the selected workflow. With the old
    // single-tool shell this fails: BomCompareTool remounted and reset
    // workflowId to its bom_compare_group default, so the Custom Compare
    // card would read data-selected="false".
    expect(screen.getByRole("button", { name: /custom compare/i })).toHaveAttribute(
      "data-selected",
      "true",
    );
  });

  test("only visited tools are mounted; switching keeps the prior tool alive", async () => {
    const user = userEvent.setup();
    renderApp();

    await screen.findByRole("button", { name: /piece-part from grouping file/i });

    // Never visited: the BOM Compare "Options" heading must not exist yet —
    // unvisited tools stay lazy and are not mounted. ("Options" is unique
    // to BOM Compare among the tools this test mounts; v2 N5 renamed the
    // old "Run Setup" section to "Workflow", which FMEA also uses.)
    expect(
      screen.queryByRole("heading", { name: /^options$/i }),
    ).not.toBeInTheDocument();

    // Visit BOM Compare, then return to FMEA. Both are now mounted, but only
    // the active one is exposed to the accessibility tree (the inactive tool
    // lives under [hidden], which the a11y tree skips).
    await user.click(screen.getByRole("button", { name: /bom comparison tool/i }));
    await screen.findByRole("heading", { name: /^options$/i });

    await user.click(screen.getByRole("button", { name: /fmea generator/i }));
    await screen.findByRole("button", { name: /piece-part from grouping file/i });

    // The hidden BOM Compare wrapper is removed from the a11y tree, so a
    // role query no longer finds its heading even though it is still mounted.
    await waitFor(() => {
      expect(
        screen.queryByRole("heading", { name: /^options$/i }),
      ).not.toBeInTheDocument();
    });

    // ...but the DOM node is still present (proving the tool was kept alive,
    // not unmounted) inside a hidden wrapper.
    const hiddenWrapper = document.querySelector("[data-tool-id='bom_compare'][hidden]");
    expect(hiddenWrapper).not.toBeNull();
    expect(
      within(hiddenWrapper as HTMLElement).getByText("Options"),
    ).toBeInTheDocument();
  });
});
