import { useEffect } from "react";
import { useRunStore } from "../../stores/runStore";
import { useShellStore } from "../../stores/shellStore";
import { SETTLED_PHASES } from "./runLifecycle";

/**
 * Phase B4 — release the shell's "Backend busy" chip whenever the active
 * run reaches a terminal phase.
 *
 * Background: every tool used to own its own `useEffect` keyed on
 * `phase === "cancelled"` that reset `backendStatus` back to "ready".
 * That effect never fired when validation failed (phase transitions
 * idle -> idle without ever entering "cancelled"), so the shell chip
 * stayed stuck on "busy" forever even though the sidecar was idle.
 *
 * The fix hoists the reset into a single shell-level hook that watches
 * the store-backed run phase directly and covers every terminal path:
 * cancelled, success, failure.
 *
 * Fix B1: "idle" was REMOVED from the terminal phase set. During
 * handleStartRun, each tool flips backendStatus to "busy" with a
 * "Validating..." message, then awaits the async validateRun call.
 * Between the flip and the first status event, activeRun is still null
 * (so this hook reads phase="idle") and on the previous version this
 * hook raced in and cleared the busy status instantly — the user saw
 * the status flicker but never settle on "Validating...". Same race for
 * file inspection flows ("Inspecting workbook for ${role}...").
 *
 * Fix R2-C1: on the SECOND run of the same session, the previous run's
 * terminal phase (success/cancelled/failure) is still sitting in the
 * runStore when the tool flips backendStatus to "busy" again. Without
 * a reset, this hook sees (terminal phase + busy) and instantly clears
 * the busy status, making "Validating..." flicker away on every second
 * run. The fix is in each tool's handleStartRun: call
 * resetDesktopRunSession() BEFORE setBackendState({busy}) so the hook
 * reads phase="idle" when the busy flip arrives.
 *
 * The idle-on-validation-failure case (debugger H1) is now handled by
 * the per-tool `setBackendState({ backendStatus: "ready" })` calls that
 * the plan explicitly kept as "redundant-but-harmless safety nets" in
 * each tool component's catch-on-validation-error path.
 */
export function useBackendBusyReset() {
  const activeRunPhase = useRunStore((state) => state.activeRun?.phase ?? "idle");
  const backendStatus = useShellStore((state) => state.backendStatus);
  const setBackendState = useShellStore((state) => state.setBackendState);

  useEffect(() => {
    if (
      SETTLED_PHASES.some((phase) => phase === activeRunPhase) &&
      backendStatus === "busy"
    ) {
      setBackendState({
        backendStatus: "ready",
        backendMessage: null,
        lastBackendCheckAt: new Date().toISOString(),
      });
    }
  }, [activeRunPhase, backendStatus, setBackendState]);
}
