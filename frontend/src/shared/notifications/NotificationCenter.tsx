import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { X } from "@phosphor-icons/react";
import { useNotificationStore, type NotificationTone } from "../../stores/notificationStore";
import styles from "./NotificationCenter.module.css";

/**
 * Toast dwell tuning.
 *
 * - Per-severity dwell: info/success 5s, warning 8s, error sticky.
 * - 2 px drain bar along the bottom of each toast (CSS `notification-drain`
 *   keyframes in `theme/styles.css`).
 * - Pause on hover, both via CSS (`animation-play-state: paused`) AND the
 *   JS dismiss timer (we clear and restart on mouseenter/mouseleave so the
 *   CSS + JS stay in sync).
 * - Errors never auto-dismiss; the user must click the X button.
 * - Dedup: identical pushes bump a `count` and refresh the dwell timer.
 * - Errors use role="alert" + aria-live="assertive" so screen readers
 *   interrupt; non-errors stay on a polite region.
 */

const DWELL_MS: Record<NotificationTone, number | null> = {
  info: 5000,
  success: 5000,
  warning: 8000,
  error: null,
};

export function NotificationCenter() {
  const notifications = useNotificationStore((state) => state.notifications);
  const dismiss = useNotificationStore((state) => state.dismiss);
  const dismissAll = useNotificationStore((state) => state.dismissAll);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const timersRef = useRef<Map<string, number>>(new Map());
  // Track the last push timestamp we armed a timer for, keyed by notification
  // id. When a dedup bumps `lastPushedAt`, we re-arm the timer.
  const timerStampRef = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    const timers = timersRef.current;
    const stamps = timerStampRef.current;

    for (const notification of notifications) {
      const dwell = DWELL_MS[notification.tone];
      if (dwell === null) continue;
      if (hoveredId === notification.id) continue;
      const existingStamp = stamps.get(notification.id);
      if (
        timers.has(notification.id) &&
        existingStamp === notification.lastPushedAt
      ) {
        continue;
      }
      const prevHandle = timers.get(notification.id);
      if (prevHandle !== undefined) window.clearTimeout(prevHandle);
      const handle = window.setTimeout(() => {
        dismiss(notification.id);
        timers.delete(notification.id);
        stamps.delete(notification.id);
      }, dwell);
      timers.set(notification.id, handle);
      stamps.set(notification.id, notification.lastPushedAt);
    }

    const liveIds = new Set(notifications.map((n) => n.id));
    for (const [id, handle] of timers) {
      if (!liveIds.has(id)) {
        window.clearTimeout(handle);
        timers.delete(id);
        stamps.delete(id);
      }
    }
  }, [dismiss, hoveredId, notifications]);

  useEffect(() => {
    return () => {
      for (const handle of timersRef.current.values()) {
        window.clearTimeout(handle);
      }
      timersRef.current.clear();
      timerStampRef.current.clear();
    };
  }, []);

  function handleMouseEnter(id: string) {
    setHoveredId(id);
    const handle = timersRef.current.get(id);
    if (handle !== undefined) {
      window.clearTimeout(handle);
      timersRef.current.delete(id);
      timerStampRef.current.delete(id);
    }
  }

  function handleMouseLeave(id: string) {
    setHoveredId((prev) => (prev === id ? null : prev));
  }

  const { polite, assertive } = useMemo(() => {
    const p = notifications.filter((n) => n.tone !== "error");
    const a = notifications.filter((n) => n.tone === "error");
    return { polite: p, assertive: a };
  }, [notifications]);

  const hasMultiple = notifications.length > 1;

  function renderToast(notification: (typeof notifications)[number]) {
    const dwell = DWELL_MS[notification.tone];
    const toastStyle: CSSProperties =
      dwell !== null ? ({ "--dwell": `${dwell}ms` } as CSSProperties) : {};
    const className = `${styles.toast} notification-toast notification-toast--${notification.tone}`;
    const isError = notification.tone === "error";
    const titleWithCount =
      notification.count > 1
        ? `${notification.title} (x${notification.count})`
        : notification.title;
    return (
      <article
        key={notification.id}
        className={className}
        data-tone={notification.tone}
        style={toastStyle}
        role={isError ? "alert" : undefined}
        onMouseEnter={() => handleMouseEnter(notification.id)}
        onMouseLeave={() => handleMouseLeave(notification.id)}
      >
        <div className={styles.header}>
          <p className={styles.title}>{titleWithCount}</p>
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
  }

  return (
    <div className={styles.viewport} aria-label="Desktop notifications">
      {hasMultiple ? (
        <div className={styles.dismissAllRow}>
          <button
            type="button"
            className={`${styles.dismissAll} ghost-button`}
            onClick={() => dismissAll()}
          >
            Dismiss all
          </button>
        </div>
      ) : null}
      <div aria-live="assertive" aria-atomic="false">
        {assertive.map(renderToast)}
      </div>
      <div aria-live="polite" aria-atomic="false">
        {polite.map(renderToast)}
      </div>
    </div>
  );
}
