import { useEffect } from "react";
import { backendClient } from "./client";
import { describeBackendError } from "./cancelError";
import { useNotificationStore } from "../../stores/notificationStore";
import { useRunStore } from "../../stores/runStore";
import { useShellStore } from "../../stores/shellStore";
import { BACKEND_RETRY_DELAYS } from "./retryPolicy";

export function useBackendBootstrap() {
  const setBackendState = useShellStore((state) => state.setBackendState);
  const pushNotification = useNotificationStore((state) => state.push);
  const markRunDisconnected = useRunStore((state) => state.markDisconnected);
  const clearActiveRun = useRunStore((state) => state.clear);

  useEffect(() => {
    let active = true;
    let unlistenSession: (() => void) | undefined;
    let unsubscribeRunStore: (() => void) | undefined;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let reconnectAttempt = 0;
    let reconnectEpoch = 0;
    let reconnectSuperseded = false;
    let disconnectedGeneration: number | null = null;

    function attemptReconnect() {
      if (!active) return;
      // Cancel any reconnect timer still pending from a prior disconnect. A
      // second disconnect (or a burst of them) must not overwrite the timer
      // handle and leave the old timer to fire — that spawned duplicate,
      // overlapping health-check chains and double "Backend reconnected"
      // toasts.
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = undefined;
      }
      const delay =
        BACKEND_RETRY_DELAYS[
          Math.min(reconnectAttempt, BACKEND_RETRY_DELAYS.length - 1)
        ];
      reconnectAttempt++;
      const attemptEpoch = reconnectEpoch;

      setBackendState({
        backendStatus: "connecting",
        backendMessage: `Reconnecting to backend (attempt ${reconnectAttempt})...`,
        lastBackendCheckAt: new Date().toISOString(),
      });

      reconnectTimer = setTimeout(() => {
        reconnectTimer = undefined;
        if (!active || attemptEpoch !== reconnectEpoch || reconnectSuperseded) return;
        void backendClient
          .healthCheck()
          .then((result) => {
            if (
              !active ||
              attemptEpoch !== reconnectEpoch ||
              reconnectSuperseded
            ) {
              return;
            }
            reconnectAttempt = 0;
            setBackendState({
              backendStatus: "ready",
              backendMode: result.mode,
              backendMessage: `Desktop backend reconnected (${result.backend})`,
              lastBackendCheckAt: new Date().toISOString(),
            });
            const activeRun = useRunStore.getState().activeRun;
            if (
              activeRun &&
              disconnectedGeneration !== null &&
              activeRun.sessionGeneration <= disconnectedGeneration
            ) {
              clearActiveRun();
            }
            disconnectedGeneration = null;
            pushNotification({
              tone: "success",
              title: "Backend reconnected",
              detail: "The desktop backend has been restored.",
            });
          })
          .catch(() => {
            if (
              !active ||
              attemptEpoch !== reconnectEpoch ||
              reconnectSuperseded
            ) {
              return;
            }
            if (reconnectAttempt < BACKEND_RETRY_DELAYS.length) {
              attemptReconnect();
            } else {
              setBackendState({
                backendStatus: "error",
                backendMessage: "Backend reconnection failed after multiple attempts.",
                lastBackendCheckAt: new Date().toISOString(),
              });
              pushNotification({
                tone: "error",
                title: "Backend reconnection failed",
                detail: "Could not restore the desktop backend. Restart the application.",
              });
            }
          });
      }, delay);
    }

    setBackendState({
      backendStatus: "connecting",
      backendMode: backendClient.runtimeMode,
      backendMessage:
        backendClient.runtimeMode === "desktop-bridge"
          ? "Connecting to the desktop backend bridge..."
          : "Running in browser preview with mock backend responses.",
    });

    void backendClient
      .healthCheck()
      .then((result) => {
        if (!active) {
          return;
        }

        setBackendState({
          backendStatus: "ready",
          backendMode: result.mode,
          backendMessage:
            result.mode === "desktop-bridge"
              ? `Desktop backend ready (${result.backend})`
              : "Browser preview active. Real file inspection requires the Tauri shell.",
          lastBackendCheckAt: new Date().toISOString(),
        });
      })
      .catch((error: unknown) => {
        if (!active) {
          return;
        }

        const detail = describeBackendError(error, "Unknown backend initialization failure");
        setBackendState({
          backendStatus: "error",
          backendMode: backendClient.runtimeMode,
          backendMessage: detail,
          lastBackendCheckAt: new Date().toISOString(),
        });
        pushNotification({
          tone: "error",
          title: "Backend initialization failed",
          detail,
        });
      });

    if (backendClient.runtimeMode === "desktop-bridge") {
      unsubscribeRunStore = useRunStore.subscribe((state, previousState) => {
        const acceptedRun = state.activeRun;
        const previousRun = previousState.activeRun;
        const isNewRegistration =
          acceptedRun !== null &&
          (previousRun === null ||
            previousRun.runId !== acceptedRun.runId ||
            previousRun.sessionGeneration !== acceptedRun.sessionGeneration);

        if (
          !isNewRegistration ||
          disconnectedGeneration === null ||
          acceptedRun.sessionGeneration <= disconnectedGeneration
        ) {
          return;
        }

        // An accepted run from a newer generation proves that the bridge has
        // already recovered. Prevent a queued retry (or an in-flight failed
        // health check) from starting a stale reconnect chain.
        reconnectSuperseded = true;
        reconnectAttempt = 0;
        if (reconnectTimer) {
          clearTimeout(reconnectTimer);
          reconnectTimer = undefined;
        }
      });

      void backendClient.subscribeToSessionEvents((event) => {
        if (!active || event.kind !== "disconnected") {
          return;
        }

        const activeRun = useRunStore.getState().activeRun;
        if (
          activeRun &&
          event.session_generation !== undefined &&
          activeRun.sessionGeneration > event.session_generation
        ) {
          return;
        }
        disconnectedGeneration =
          event.session_generation ?? activeRun?.sessionGeneration ?? null;
        reconnectEpoch += 1;
        reconnectSuperseded = false;

        setBackendState({
          backendStatus: "disconnected",
          backendMode: "desktop-bridge",
          backendMessage: event.message,
          lastBackendCheckAt: new Date().toISOString(),
        });
        // Mirror the disconnect into the run store so any active run
        // is marked disconnected (the per-tool hook does the same when
        // it observes the event, but doing it here keeps the store
        // consistent even if no tool is currently mounted).
        markRunDisconnected(event.message);
        pushNotification({
          tone: "warning",
          title: "Backend disconnected",
          detail: event.message,
        });
        attemptReconnect();
      })
        .then((dispose) => {
          if (!active) {
            dispose();
            return;
          }

          unlistenSession = dispose;
        })
        .catch((error) => {
          // A rejected listen() would otherwise be an unhandled rejection that
          // silently disables disconnect detection. Surface it for diagnostics;
          // healthCheck independently owns backendStatus, so the UI is not
          // stranded on "connecting". (Holistic-review finding H-B follow-up.)
          console.error("Failed to subscribe to backend session events:", error);
        });
    }

    return () => {
      active = false;
      unlistenSession?.();
      unsubscribeRunStore?.();
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  }, [
    pushNotification,
    setBackendState,
    markRunDisconnected,
    clearActiveRun,
  ]);
}
