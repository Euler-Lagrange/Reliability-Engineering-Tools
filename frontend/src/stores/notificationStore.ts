import { create } from "zustand";

export type NotificationTone = "success" | "info" | "warning" | "error";

export interface NotificationItem {
  id: string;
  tone: NotificationTone;
  title: string;
  detail?: string;
}

interface NotificationState {
  notifications: NotificationItem[];
  push: (notification: Omit<NotificationItem, "id">) => void;
  dismiss: (id: string) => void;
}

export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [],
  push: (notification) =>
    set((state) => ({
      notifications: [
        ...state.notifications,
        { ...notification, id: `note_${Date.now()}_${Math.random().toString(16).slice(2)}` },
      ],
    })),
  dismiss: (id) =>
    set((state) => ({
      notifications: state.notifications.filter((notification) => notification.id !== id),
    })),
}));
