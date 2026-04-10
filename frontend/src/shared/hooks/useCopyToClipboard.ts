import { useCallback, useEffect, useRef, useState } from "react";

/**
 * useCopyToClipboard — shared clipboard hook reused across tools.
 *
 * Prefers the async Clipboard API (`navigator.clipboard.writeText`). Falls
 * back to a hidden-textarea `document.execCommand("copy")` path when the
 * Clipboard API is unavailable (e.g. insecure contexts, older Tauri
 * webview configurations).
 *
 * The `copied` flag auto-resets after `resetMs` (default 1500 ms) so
 * consumers can render a transient "Copied!" affordance without extra
 * bookkeeping. The `error` slot captures the failure message when both
 * paths fail.
 */

const DEFAULT_RESET_MS = 1500;

export interface UseCopyToClipboardResult {
  copy: (text: string) => Promise<boolean>;
  copied: boolean;
  error: string | null;
}

export function useCopyToClipboard(resetMs: number = DEFAULT_RESET_MS): UseCopyToClipboardResult {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => {
      clearTimer();
    };
  }, [clearTimer]);

  const copy = useCallback(
    async (text: string): Promise<boolean> => {
      clearTimer();
      setError(null);

      // Preferred path: native Clipboard API.
      if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          timerRef.current = window.setTimeout(() => {
            setCopied(false);
            timerRef.current = null;
          }, resetMs);
          return true;
        } catch (err) {
          // Fall through to the textarea fallback.
          const message = err instanceof Error ? err.message : String(err);
          setError(message);
        }
      }

      // Fallback: hidden textarea + document.execCommand("copy"). Works in
      // insecure contexts and older webviews.
      if (typeof document !== "undefined") {
        try {
          const textarea = document.createElement("textarea");
          textarea.value = text;
          textarea.setAttribute("readonly", "");
          textarea.style.position = "absolute";
          textarea.style.left = "-9999px";
          textarea.style.top = "0";
          document.body.appendChild(textarea);
          textarea.select();
          const ok = document.execCommand("copy");
          document.body.removeChild(textarea);
          if (ok) {
            setCopied(true);
            setError(null);
            timerRef.current = window.setTimeout(() => {
              setCopied(false);
              timerRef.current = null;
            }, resetMs);
            return true;
          }
          setError("Clipboard copy failed");
          return false;
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          setError(message);
          return false;
        }
      }

      setError("Clipboard API unavailable");
      return false;
    },
    [clearTimer, resetMs],
  );

  return { copy, copied, error };
}
