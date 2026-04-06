import { useEffect } from "react";
import { X } from "@phosphor-icons/react";
import { useNotificationStore } from "../../stores/notificationStore";
import styles from "./NotificationCenter.module.css";

export function NotificationCenter() {
  const notifications = useNotificationStore((state) => state.notifications);
  const dismiss = useNotificationStore((state) => state.dismiss);

  useEffect(() => {
    if (notifications.length === 0) {
      return;
    }

    const timers = notifications.map((notification) =>
      window.setTimeout(() => dismiss(notification.id), 3200),
    );

    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [dismiss, notifications]);

  return (
    <div className={styles.viewport} aria-live="polite" aria-label="Desktop notifications">
      {notifications.map((notification) => (
        <article key={notification.id} className={styles.toast} data-tone={notification.tone}>
          <div className={styles.header}>
            <p className={styles.title}>{notification.title}</p>
            <button
              type="button"
              className={styles.dismiss}
              onClick={() => dismiss(notification.id)}
              aria-label={`Dismiss ${notification.title}`}
            >
              <X size={12} weight="bold" />
            </button>
          </div>
          {notification.detail ? <p className={styles.detail}>{notification.detail}</p> : null}
        </article>
      ))}
    </div>
  );
}
