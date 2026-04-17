import { useNotificationStore } from "../../stores/notificationStore";

/**
 * Install window-level handlers for errors that escape React's render tree.
 *
 * ``ErrorBoundary`` (in ``shared/errors/ErrorBoundary.tsx``) only catches
 * errors thrown during React rendering. It does NOT catch:
 *   - Uncaught exceptions from event handlers, ``setTimeout`` callbacks,
 *     or microtasks.
 *   - Unhandled promise rejections from fire-and-forget async work
 *     (``void somePromise()``, ``.then(...)`` without ``.catch``).
 *
 * Without these listeners such failures would vanish into the devtools
 * console with no user-visible indication anything was wrong — classic
 * "the app feels broken but there's no error message" territory.
 *
 * The handlers here surface a non-dismissible-by-default error toast via
 * the notification store so the user at least knows something went wrong,
 * and always forward the error to ``console.error`` so developers and
 * crash-dump collectors keep a structured record. We intentionally avoid
 * calling ``event.preventDefault()`` — the browser default (log to
 * console) stays on top of our notification, not instead of it.
 *
 * Call this once from ``main.tsx`` before rendering. Safe to call
 * multiple times: a module-level flag prevents double-install.
 */

let installed = false;

function asDetail(value: unknown): string {
  if (value instanceof Error) {
    return value.message || value.name || "Unknown error";
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function installGlobalErrorHandlers(): void {
  if (installed) {
    return;
  }
  installed = true;

  if (typeof window === "undefined") {
    return;
  }

  window.addEventListener("error", (event: ErrorEvent) => {
    console.error("[global-error]", event.error ?? event.message, {
      source: event.filename,
      line: event.lineno,
      column: event.colno,
    });
    useNotificationStore.getState().push({
      tone: "error",
      title: "Unexpected error",
      detail: asDetail(event.error ?? event.message),
    });
  });

  window.addEventListener("unhandledrejection", (event: PromiseRejectionEvent) => {
    console.error("[unhandled-rejection]", event.reason);
    useNotificationStore.getState().push({
      tone: "error",
      title: "Unhandled promise rejection",
      detail: asDetail(event.reason),
    });
  });
}
