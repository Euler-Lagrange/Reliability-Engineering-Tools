import { useEffect, useRef } from "react";

/**
 * useEscapeLayer — a shared, single-listener Escape dismiss stack.
 *
 * Problem: multiple dismissible surfaces (the mapping help panel, the Review
 * drawer, the command palette) each installed their own `window` keydown
 * listener for Escape. Because they all listen on the same target, a single
 * Escape fired every listener at once — closing multiple layers in one press.
 *
 * Solution: layers register a dismiss callback here while they are open. ONE
 * module-level `window` keydown listener handles Escape and dismisses only the
 * top-of-stack (most-recently-registered) layer. Registration is keyed to the
 * layer's *active* state, so the stack reflects open order, not mount order.
 *
 * Usage:
 *   useEscapeLayer(isOpen, () => setOpen(false));
 *
 * The dismiss callback is read through a ref, so the latest closure is always
 * invoked without churning the stack on every render.
 */

interface EscapeLayer {
  id: symbol;
  dismiss: () => void;
}

const layerStack: EscapeLayer[] = [];
let listenerAttached = false;

function handleWindowKeyDown(event: KeyboardEvent): void {
  if (event.key !== "Escape") {
    return;
  }
  const top = layerStack[layerStack.length - 1];
  if (!top) {
    return;
  }
  // A single listener guarantees only the top layer is dismissed. We still
  // stop propagation so any not-yet-migrated Escape consumers on the same
  // target don't also fire for this press.
  event.preventDefault();
  event.stopPropagation();
  top.dismiss();
}

function ensureListener(): void {
  if (!listenerAttached && typeof window !== "undefined") {
    window.addEventListener("keydown", handleWindowKeyDown);
    listenerAttached = true;
  }
}

function maybeDetachListener(): void {
  if (listenerAttached && layerStack.length === 0 && typeof window !== "undefined") {
    window.removeEventListener("keydown", handleWindowKeyDown);
    listenerAttached = false;
  }
}

export function useEscapeLayer(active: boolean, onDismiss: () => void): void {
  const dismissRef = useRef(onDismiss);
  dismissRef.current = onDismiss;

  useEffect(() => {
    if (!active) {
      return undefined;
    }
    const layer: EscapeLayer = {
      id: Symbol("escape-layer"),
      dismiss: () => dismissRef.current(),
    };
    layerStack.push(layer);
    ensureListener();
    return () => {
      const index = layerStack.findIndex((entry) => entry.id === layer.id);
      if (index !== -1) {
        layerStack.splice(index, 1);
      }
      maybeDetachListener();
    };
  }, [active]);
}
