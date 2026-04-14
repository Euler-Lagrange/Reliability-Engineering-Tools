import { useEffect } from "react";
import { backendClient } from "./client";
import { useNotificationStore } from "../../stores/notificationStore";
import { useRunStore } from "../../stores/runStore";
import { useShellStore } from "../../stores/shellStore";

const RECONNECT_DELAYS = [2_000, 4_000, 8_000, 15_000, 30_000];

export function useBackendBootstrap() {
  const setBackendState = useShellStore((state) => state.setBackendState);
  const pushNotification = useNotificationStore((state) => state.push);
  const markRunDisconnected = useRunStore((state) => state.markDisconnected);
  const markRunReconnected = useRunStore((state) => state.markReconnected);
  const clearActiveRun = useRunStore((state) => state.clear);

  useEffect(() => {
    let active = true;
    let unlistenSession: (() => void) | undefined;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let reconnectAttempt = 0;

    function attemptReconnect() {
      if (!active) return;
      const delay = RECONNECT_DELAYS[Math.min(reconnectAttempt, RECONNECT_DELAYS.length - 1)];
      reconnectAttempt++;

      setBackendState({
        backendStatus: "connecting",
        backendMessage: `Reconnecting to backend (attempt ${reconnectAttempt})...`,
        lastBackendCheckAt: new Date().toISOString(),
      });

      reconnectTimer = setTimeout(() => {
        if (!active) return;
        void backendClient
          .healthCheck()
          .then((result) => {
            if (!active) return;
            reconnectAttempt = 0;
            setBackendState({
              backendStatus: "ready",
              backendMode: result.mode,
              backendMessage: `Desktop backend reconnected (${result.backend})`,
              lastBackendCheckAt: new Date().toISOString(),
            });
            // Reconcile any active run with the sidecar's actual session.
            // A reconnect may have spawned a brand-new sidecar session.
            // If the active run was accepted under an older session
            // generation, it cannot resume and must be cleared.
            void backendClient
              .sessionStatus()
              .then((status) => {
                if (!active) return;
                const activeRun = useRunStore.getState().activeRun;
                if (!activeRun) {
                  return;
                }
                if (
                  !status.connected ||
                  activeRun.sessionGeneration !== status.session_generation
                ) {
                  clearActiveRun();
                  return;
                }
                markRunReconnected();
              })
              .catch(() => {
                // Best-effort reconciliation; nothing to do on failure.
              });
            pushNotification({
              tone: "success",
              title: "Backend reconnected",
              detail: "The desktop backend has been restored.",
            });
          })
          .catch(() => {
            if (!active) return;
            if (reconnectAttempt < RECONNECT_DELAYS.length) {
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

        const detail = error instanceof Error ? error.message : "Unknown backend initialization failure";
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
      void backendClient.subscribeToSessionEvents((event) => {
        if (!active || event.kind !== "disconnected") {
          return;
        }

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
      }).then((dispose) => {
        if (!active) {
          dispose();
          return;
        }

        unlistenSession = dispose;
      });
    }

    return () => {
      active = false;
      unlistenSession?.();
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  }, [
    pushNotification,
    setBackendState,
    markRunDisconnected,
    markRunReconnected,
    clearActiveRun,
  ]);
}
