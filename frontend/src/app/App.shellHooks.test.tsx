import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Tier-3 #28: the shell-level backend hooks are mounted ONCE in App.tsx and own
// the run-event subscription and the bootstrap/reconnect loop (see the
// "Shell-level run subscription" gotcha in CLAUDE.md). Deleting either call
// from App used to leave the whole suite green because nothing asserted they
// are installed. These spies fail that silent deletion.
const hookMocks = vi.hoisted(() => ({
  useBackendBootstrap: vi.fn(),
  useBackendRunSubscription: vi.fn(),
}));

vi.mock("../shared/backend/useBackendBootstrap", () => ({
  useBackendBootstrap: hookMocks.useBackendBootstrap,
}));
vi.mock("../shared/backend/useBackendRunSubscription", () => ({
  useBackendRunSubscription: hookMocks.useBackendRunSubscription,
}));

import { App } from "./App";

beforeEach(() => {
  window.localStorage.clear();
  hookMocks.useBackendBootstrap.mockClear();
  hookMocks.useBackendRunSubscription.mockClear();
});

describe("App shell-level hook installation", () => {
  it("installs the backend bootstrap and run-subscription hooks on render", () => {
    render(<App />);
    expect(hookMocks.useBackendBootstrap).toHaveBeenCalled();
    expect(hookMocks.useBackendRunSubscription).toHaveBeenCalled();
  });
});
