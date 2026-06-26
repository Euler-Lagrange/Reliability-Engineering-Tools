import { beforeEach, describe, expect, it } from "vitest";
import { MAX_VISIBLE_NOTIFICATIONS, useNotificationStore } from "./notificationStore";

beforeEach(() => {
  useNotificationStore.setState({ notifications: [] });
});

describe("notificationStore eviction", () => {
  it("keeps an incoming non-error toast even when the queue is full of sticky errors", () => {
    // Error toasts never auto-dismiss, so 5 pinned errors is a reachable steady
    // state. A new info/success toast must still appear — the bug evicted the
    // just-pushed toast itself.
    const { push } = useNotificationStore.getState();
    for (let i = 0; i < MAX_VISIBLE_NOTIFICATIONS; i += 1) {
      push({ tone: "error", title: `Error ${i}` });
    }
    push({ tone: "info", title: "All caught up" });

    const notes = useNotificationStore.getState().notifications;
    expect(notes).toHaveLength(MAX_VISIBLE_NOTIFICATIONS);
    expect(notes.some((n) => n.tone === "info" && n.title === "All caught up")).toBe(true);
    expect(notes.filter((n) => n.tone === "error")).toHaveLength(MAX_VISIBLE_NOTIFICATIONS - 1);
  });

  it("evicts the oldest non-error first when over capacity", () => {
    const { push } = useNotificationStore.getState();
    for (let i = 0; i < MAX_VISIBLE_NOTIFICATIONS; i += 1) {
      push({ tone: "info", title: `Info ${i}` });
    }
    push({ tone: "info", title: "Newest" });

    const notes = useNotificationStore.getState().notifications;
    expect(notes).toHaveLength(MAX_VISIBLE_NOTIFICATIONS);
    expect(notes.some((n) => n.title === "Info 0")).toBe(false);
    expect(notes[notes.length - 1].title).toBe("Newest");
  });

  it("evicts the oldest error to make room for an incoming error", () => {
    const { push } = useNotificationStore.getState();
    for (let i = 0; i < MAX_VISIBLE_NOTIFICATIONS; i += 1) {
      push({ tone: "error", title: `Error ${i}` });
    }
    push({ tone: "error", title: "Newest error" });

    const notes = useNotificationStore.getState().notifications;
    expect(notes).toHaveLength(MAX_VISIBLE_NOTIFICATIONS);
    expect(notes.some((n) => n.title === "Newest error")).toBe(true);
    expect(notes.some((n) => n.title === "Error 0")).toBe(false);
  });
});
