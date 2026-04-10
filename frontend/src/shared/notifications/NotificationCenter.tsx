import { useEffect, useRef, useState, type CSSProperties } from "react";
import { X } from "@phosphor-icons/react";
import { useNotificationStore, type NotificationTone } from "../../stores/notificationStore";
import styles from "./NotificationCenter.module.css";

/**
 * Phase 4 Task 5: toast dwell tuning.
 *
 * - Per-severity dwell: info/success 5s, warning 8s, error sticky.
 * - 2 px drain bar along the bottom of each toast (CSS `notification-drain`
 *   keyframes in `theme/styles.css`).
 * - Pause on hover, both via CSS (`animation-play-state: paused`) AND the
 *   JS dismiss timer (we clear and restart on mouseenter/mouseleave so the
 *   CSS + JS stay in sync).
 * - Errors never auto-dismiss; the user must click the X button.
 */

const DWELL_MS: Record<NotificationTone, number | null> = {
  info: 5000,
  success: 5000,
  warning: 8000,
  error: null, // never auto-dismisses
};

export function NotificationCenter() {
  const notifications = useNotificationStore((state) => state.notifications);
  const dismiss = useNotificationStore((state) => state.dismiss);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const timersRef = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    const timers = timersRef.current;

    // Start timers for notifications that don't have one yet.
    for (const notification of notifications) {
      if (timers.has(notification.id)) {
        continue;
      }
      const dwell = DWELL_MS[notification.tone];
      if (dwell === null) {
        continue;
      }
      if (hoveredId === notification.id) {
        continue;
      }
      const handle = window.setTimeout(() => {
        dismiss(notification.id);
        timers.delete(notification.id);
      }, dwell);
      timers.set(notification.id, handle);
    }

    // Clear timers for notifications that have been removed.
    const liveIds = new Set(notifications.map((n) => n.id));
    for (const [id, handle] of timers) {
      if (!liveIds.has(id)) {
        window.clearTimeout(handle);
        timers.delete(id);
      }
    }
  }, [dismiss, hoveredId, notifications]);

  // Clear all timers on unmount.
  useEffect(() => {
    return () => {
      for (const handle of timersRef.current.values()) {
        window.clearTimeout(handle);
      }
      timersRef.current.clear();
    };
  }, []);

  function handleMouseEnter(id: string) {
    setHoveredId(id);
    const handle = timersRef.current.get(id);
    if (handle !== undefined) {
      window.clearTimeout(handle);
      timersRef.current.delete(id);
    }
  }

  function handleMouseLeave(id: string) {
    setHoveredId((prev) => (prev === id ? null : prev));
    // The main useEffect will re-arm the timer now that hoveredId cleared.
  }

  return (
    <div className={styles.viewport} aria-live="polite" aria-label="Desktop notifications">
      {notifications.map((notification) => {
        const dwell = DWELL_MS[notification.tone];
        const toastStyle: CSSProperties =
          dwell !== null
            ? ({ "--dwell": `${dwell}ms` } as CSSProperties)
            : {};
        const className = `${styles.toast} notification-toast notification-toast--${notification.tone}`;
        return (
          <article
            key={notification.id}
            className={className}
            data-tone={notification.tone}
            style={toastStyle}
            onMouseEnter={() => handleMouseEnter(notification.id)}
            onMouseLeave={() => handleMouseLeave(notification.id)}
          >
            <div className={styles.header}>
              <p className={styles.title}>{notification.title}</p>
              <button
                type="button"
                className={`${styles.dismiss} notification-toast__dismiss`}
                onClick={() => dismiss(notification.id)}
                aria-label={`Dismiss ${notification.title}`}
              >
                <X size={14} weight="bold" />
              </button>
            </div>
            {notification.detail ? <p className={styles.detail}>{notification.detail}</p> : null}
            {dwell !== null ? (
              <span className="notification-toast__progress" aria-hidden="true" />
            ) : null}
          </article>
        );
      })}
    </div>
  );
}
