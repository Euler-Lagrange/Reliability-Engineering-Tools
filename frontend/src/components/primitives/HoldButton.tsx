import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type SyntheticEvent,
} from "react";

/**
 * HoldButton — press-and-hold confirmation primitive.
 *
 * Replaces the legacy "click once, click again to confirm" double-tap pattern
 * for destructive actions with a single mouse / pointer gesture. The
 * confirmation fires after `holdMs` milliseconds of continuous press.
 *
 * Progress is rendered by a pure CSS transform transition (scaleX 0 -> 1)
 * driven by a CSS custom property on the element — no JS rAF loop, no
 * per-frame state updates, no React re-render thrash.
 *
 * Keyboard fallback: Space / Enter open a native `<dialog>` modal with
 * explicit Confirm / Cancel buttons. Hold gestures don't translate cleanly
 * to keyboards, so we surface a proper two-step confirmation path there.
 */

export interface HoldButtonProps {
  onConfirm: () => void;
  holdMs?: number;
  label: string;
  holdingLabel?: string;
  ariaLabel?: string;
  variant?: "danger" | "default";
  disabled?: boolean;
  className?: string;
}

export function HoldButton({
  onConfirm,
  holdMs = 600,
  label,
  holdingLabel,
  ariaLabel,
  variant = "default",
  disabled = false,
  className,
}: HoldButtonProps) {
  const [holding, setHolding] = useState(false);
  const timerRef = useRef<number | null>(null);
  const firedRef = useRef(false);
  // Synchronous guard that prevents a second beginHold() in the same gesture.
  // React state (`holding`) lags across handlers, so a ref is required: on
  // Chromium/WebView2 a single press can deliver `pointerdown` and
  // `mousedown` (or synthesized click events) before the state commits, and
  // without this guard two overlapping timers could fire.
  const gestureActiveRef = useRef(false);
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const liveRegionId = useId();

  const clearHoldTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const beginHold = useCallback(() => {
    if (disabled) {
      return;
    }
    if (gestureActiveRef.current || holding || firedRef.current) {
      return;
    }
    gestureActiveRef.current = true;
    firedRef.current = false;
    setHolding(true);
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      firedRef.current = true;
      setHolding(false);
      onConfirm();
      window.setTimeout(() => {
        firedRef.current = false;
      }, 0);
    }, holdMs);
  }, [disabled, holding, holdMs, onConfirm]);

  const cancelHold = useCallback(() => {
    clearHoldTimer();
    setHolding(false);
    gestureActiveRef.current = false;
  }, [clearHoldTimer]);

  useEffect(() => {
    return () => {
      clearHoldTimer();
    };
  }, [clearHoldTimer]);

  const openDialog = useCallback(() => {
    const dialog = dialogRef.current;
    if (!dialog || disabled) {
      return;
    }
    // Remember where focus was so we can return it on close (WCAG 2.4.3).
    const active = document.activeElement;
    returnFocusRef.current = active instanceof HTMLElement ? active : null;
    if (typeof dialog.showModal === "function") {
      try {
        dialog.showModal();
      } catch {
        // Already open or unsupported — the dialog element still renders
        // inline via the `open` attribute path below.
      }
    }
  }, [disabled]);

  const closeDialog = useCallback(() => {
    const dialog = dialogRef.current;
    if (dialog && typeof dialog.close === "function" && dialog.open) {
      try {
        dialog.close();
      } catch {
        /* ignore */
      }
    }
    const returnTo = returnFocusRef.current;
    returnFocusRef.current = null;
    if (returnTo && typeof returnTo.focus === "function") {
      try {
        returnTo.focus();
      } catch {
        /* ignore */
      }
    }
  }, []);

  // Native <dialog> emits `cancel` on Escape; intercept to close cleanly and
  // restore focus. Without this, Escape would call default `close()` without
  // triggering our focus-restore path.
  function handleDialogCancel(event: SyntheticEvent<HTMLDialogElement>) {
    event.preventDefault();
    closeDialog();
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLButtonElement>) {
    if (disabled) {
      return;
    }
    if (event.key === " " || event.key === "Enter") {
      // Prevent the native click-synthesis path. Keyboard users get the
      // dialog fallback instead of a pseudo-instant hold.
      event.preventDefault();
      openDialog();
    }
  }

  function handlePointerDown(event: ReactPointerEvent<HTMLButtonElement>) {
    if (disabled) {
      return;
    }
    // Only left button / primary touch counts as a hold. Ignore right-click
    // and middle-click.
    if (event.button !== 0 && event.pointerType === "mouse") {
      return;
    }
    beginHold();
  }

  function handleConfirmClick() {
    closeDialog();
    onConfirm();
  }

  const rootClassName = [
    "hold-button",
    variant === "danger" ? "hold-button--danger" : null,
    holding ? "is-holding" : null,
    className ?? null,
  ]
    .filter(Boolean)
    .join(" ");

  const displayLabel = holding && holdingLabel ? holdingLabel : label;

  return (
    <>
      <button
        type="button"
        className={rootClassName}
        style={{ ["--hold-duration" as string]: `${holdMs}ms` }}
        aria-label={ariaLabel ?? label}
        aria-pressed={holding || undefined}
        aria-describedby={liveRegionId}
        disabled={disabled}
        onPointerDown={handlePointerDown}
        onPointerUp={cancelHold}
        onPointerLeave={cancelHold}
        onPointerCancel={cancelHold}
        onKeyDown={handleKeyDown}
      >
        <span className="hold-button__fill" aria-hidden="true" />
        <span className="hold-button__label">{displayLabel}</span>
      </button>
      <span id={liveRegionId} className="sr-only" aria-live="polite">
        {holding ? "Holding to confirm..." : ""}
      </span>
      <dialog
        ref={dialogRef}
        className="hold-button__dialog"
        aria-modal="true"
        aria-labelledby={`${liveRegionId}-dialog-title`}
        onCancel={handleDialogCancel}
      >
        <p
          id={`${liveRegionId}-dialog-title`}
          className="hold-button__dialog-body"
        >
          {holdingLabel ?? `Confirm "${label}"?`}
        </p>
        <div className="hold-button__dialog-actions">
          <button
            type="button"
            className="ghost-button"
            onClick={closeDialog}
          >
            Cancel
          </button>
          <button
            type="button"
            className={
              variant === "danger"
                ? "primary-button hold-button__dialog-confirm--danger"
                : "primary-button"
            }
            onClick={handleConfirmClick}
          >
            Confirm
          </button>
        </div>
      </dialog>
    </>
  );
}
