/**
 * Phase B3 — cancel error helpers.
 *
 * The Tauri bridge's `backend_cancel_run` command returns `Result<_, String>`.
 * When the sidecar replies with an `error` frame (e.g. no active run matches
 * the supplied `run_id`), Rust forwards `payload.message` verbatim into the
 * `Err(String)` side, which Tauri surfaces to the frontend as a raw string
 * rejection — NOT an `Error` instance.
 *
 * The previous pattern used `error instanceof Error ? error.message : <generic
 * fallback>`, which lost the sidecar's specific error text for every failure
 * path because string rejections short-circuit to the fallback. This helper
 * extracts the most informative string it can find from whatever Tauri /
 * fetch / a real Error threw at us so the user notification can actually
 * explain what went wrong.
 */

/**
 * Normalise an unknown thrown value into a user-facing detail string.
 *
 * The priority order is:
 *   1. Raw string rejections (Tauri's default for `Result<_, String>`).
 *   2. `Error` instances — use `error.message`.
 *   3. Objects with a `message` field.
 *   4. Final fallback string passed in by the caller.
 */
export function describeCancelError(
  error: unknown,
  fallback = "Cancel request did not return a detail message.",
): string {
  if (typeof error === "string") {
    return error.trim() || fallback;
  }
  if (error instanceof Error) {
    return error.message || fallback;
  }
  if (error !== null && typeof error === "object" && "message" in error) {
    const message = (error as { message: unknown }).message;
    if (typeof message === "string" && message.trim().length > 0) {
      return message;
    }
  }
  return fallback;
}

/**
 * Classify a cancel error so the caller can pick a more specific notification
 * title than the generic "Cancel failed". The sidecar emits
 * ``"No active run matches '{run_id}'."`` when the run has already finished
 * before the cancel request arrived, which is a common "not actually broken"
 * case we surface with its own friendlier title.
 */
export type CancelErrorKind = "no-active-run" | "generic";

export function classifyCancelError(detail: string): CancelErrorKind {
  const lower = detail.toLowerCase();
  if (lower.includes("no active run")) {
    return "no-active-run";
  }
  return "generic";
}

/**
 * Convenience helper that bundles a normalised detail string with a
 * matching notification title, so tool cancel handlers can call a single
 * function and forward the result straight to `pushNotification`.
 */
export interface CancelNotificationParts {
  title: string;
  detail: string;
  tone: "error" | "info";
}

export function buildCancelNotification(error: unknown): CancelNotificationParts {
  const detail = describeCancelError(error);
  const kind = classifyCancelError(detail);
  if (kind === "no-active-run") {
    return {
      tone: "info",
      title: "No active run to cancel",
      detail,
    };
  }
  return {
    tone: "error",
    title: "Cancel failed",
    detail,
  };
}
