import { create } from "zustand";

export type NotificationTone = "success" | "info" | "warning" | "error";

export interface NotificationItem {
  id: string;
  tone: NotificationTone;
  title: string;
  detail?: string;
  /**
   * Monotonic count of how many times an equivalent notification has been
   * pushed while the current one is still visible. Bumped by dedup in
   * `push()`. UI can render this as a badge (e.g. "(x3)") on the title.
   */
  count: number;
  /**
   * Timestamp (ms) of the most recent push that resolved to this item. Used
   * by the NotificationCenter to reset dwell timers when a duplicate arrives.
   */
  lastPushedAt: number;
}

interface NotificationState {
  notifications: NotificationItem[];
  push: (notification: Omit<NotificationItem, "id" | "count" | "lastPushedAt">) => void;
  dismiss: (id: string) => void;
  dismissAll: () => void;
}

/**
 * Maximum number of toasts visible at once. Older ones are evicted FIFO.
 * Keeps the UI from drowning when the backend emits a burst of warnings.
 */
export const MAX_VISIBLE_NOTIFICATIONS = 5;

function dedupeKey(tone: NotificationTone, title: string, detail?: string): string {
  return `${tone}::${title}::${detail ?? ""}`;
}

export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [],
  push: (notification) =>
    set((state) => {
      const key = dedupeKey(notification.tone, notification.title, notification.detail);
      const now = Date.now();
      // Dedup: if an equivalent notification already exists, bump its count
      // and refresh its timestamp instead of stacking another copy.
      const existingIndex = state.notifications.findIndex(
        (n) => dedupeKey(n.tone, n.title, n.detail) === key,
      );
      if (existingIndex !== -1) {
        const existing = state.notifications[existingIndex];
        const updated = {
          ...existing,
          count: existing.count + 1,
          lastPushedAt: now,
        };
        const copy = state.notifications.slice();
        copy.splice(existingIndex, 1);
        copy.push(updated);
        return { notifications: copy };
      }

      const incoming: NotificationItem = {
        ...notification,
        id: `note_${now}_${Math.random().toString(16).slice(2)}`,
        count: 1,
        lastPushedAt: now,
      };

      const next = [...state.notifications, incoming];
      // Cap the queue: evict oldest non-errors first, then errors if needed.
      if (next.length > MAX_VISIBLE_NOTIFICATIONS) {
        const overflow = next.length - MAX_VISIBLE_NOTIFICATIONS;
        const nonErrorIndices: number[] = [];
        const errorIndices: number[] = [];
        // Eviction candidates are the EXISTING notifications only — never the
        // just-pushed incoming (appended last, index === state.notifications
        // .length, which is never enumerated here). Otherwise a new non-error
        // toast arriving behind a full queue of sticky errors would select
        // ITSELF as the victim and never display.
        state.notifications.forEach((n, i) => {
          if (n.tone === "error") errorIndices.push(i);
          else nonErrorIndices.push(i);
        });
        const toRemove = new Set<number>();
        for (let i = 0; i < overflow; i += 1) {
          const victim =
            nonErrorIndices.shift() ?? errorIndices.shift() ?? -1;
          if (victim >= 0) toRemove.add(victim);
        }
        return {
          notifications: next.filter((_, i) => !toRemove.has(i)),
        };
      }

      return { notifications: next };
    }),
  dismiss: (id) =>
    set((state) => ({
      notifications: state.notifications.filter((notification) => notification.id !== id),
    })),
  dismissAll: () => set({ notifications: [] }),
}));
