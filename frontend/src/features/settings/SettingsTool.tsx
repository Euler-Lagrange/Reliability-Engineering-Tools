import { useState } from "react";
import { ArrowClockwise, FolderOpen, Heart } from "@phosphor-icons/react";
import { SectionCard } from "../../components/SectionCard";
import { protocolVersion } from "../../contracts/sidecar";
import { OPEN_FOLDER_LABEL } from "../../shared/backend/fileManager";
import { ErrorBoundary } from "../../shared/errors/ErrorBoundary";
import { useThemeStore } from "../../stores/themeStore";
import { useResolvedTheme } from "../../shared/theme/ThemeController";
import { THEME_REGISTRY } from "../../shared/theme/themeRegistry";
import { useShellStore } from "../../stores/shellStore";
import { backendClient } from "../../shared/backend/client";
import { describeBackendError } from "../../shared/backend/cancelError";
import { useNotificationStore } from "../../stores/notificationStore";
import styles from "./SettingsTool.module.css";

// Fallback label when the sidecar has not reported its real log directory
// yet (first paint, browser-mock mode, or older sidecar protocol). Once a
// successful ``health_check`` returns ``log_directory``, the UI swaps to
// the real absolute path.
const LOG_DIRECTORY_PLACEHOLDER = "~/.reliability_tools/logs/";

function classifyLatency(latencyMs: number | null): {
  dotClass: string;
  display: string;
} {
  if (latencyMs === null) {
    return { dotClass: "settings__health-dot settings__health-dot--warning", display: "—" };
  }
  if (latencyMs < 100) {
    return { dotClass: "settings__health-dot settings__health-dot--green", display: `${latencyMs} ms` };
  }
  if (latencyMs < 500) {
    return { dotClass: "settings__health-dot settings__health-dot--warning", display: `${latencyMs} ms` };
  }
  return { dotClass: "settings__health-dot settings__health-dot--danger", display: `${latencyMs} ms` };
}

// Settings exposes every theme in the registry, including the four that the
// shell rail does not. The registry is the single source of truth — do not
// duplicate this list.
const themeOptions = THEME_REGISTRY;

export function SettingsTool() {
  const themeMode = useThemeStore((state) => state.mode);
  const setThemeMode = useThemeStore((state) => state.setMode);
  const resolvedTheme = useResolvedTheme();
  const backendStatus = useShellStore((state) => state.backendStatus);
  const backendMode = useShellStore((state) => state.backendMode);
  const backendMessage = useShellStore((state) => state.backendMessage);
  const lastBackendCheckAt = useShellStore((state) => state.lastBackendCheckAt);
  const setBackendState = useShellStore((state) => state.setBackendState);
  const pushNotification = useNotificationStore((state) => state.push);
  const [isCheckingHealth, setIsCheckingHealth] = useState(false);
  // Phase 4 Task 8: last-ping latency displayed with a colored dot.
  // Stored locally because the shell store does not track latency today.
  const [lastLatencyMs, setLastLatencyMs] = useState<number | null>(null);
  // Real sidecar log directory, populated by the most recent successful
  // health_check. Null until the first check or when in browser-mock.
  const [logDirectory, setLogDirectory] = useState<string | null>(null);
  const displayedLogPath = logDirectory ?? LOG_DIRECTORY_PLACEHOLDER;
  const latency = classifyLatency(lastLatencyMs);

  async function handleHealthCheck() {
    setIsCheckingHealth(true);
    const startedAt = performance.now();
    try {
      const result = await backendClient.healthCheck();
      const latencyMs = Math.round(performance.now() - startedAt);
      setLastLatencyMs(latencyMs);
      if (result.log_directory) {
        setLogDirectory(result.log_directory);
      }
      setBackendState({
        backendStatus: "ready",
        backendMode: result.mode,
        backendMessage: `Backend healthy (${result.backend}, protocol ${result.protocol_version})`,
        lastBackendCheckAt: new Date().toISOString(),
      });
      pushNotification({
        tone: "success",
        title: "Health check passed",
        detail: `${result.backend} is responsive (${latencyMs} ms).`,
      });
    } catch (error: unknown) {
      const detail = describeBackendError(error, "Health check failed");
      setLastLatencyMs(null);
      setBackendState({
        backendStatus: "error",
        backendMessage: detail,
        lastBackendCheckAt: new Date().toISOString(),
      });
      pushNotification({ tone: "error", title: "Health check failed", detail });
    } finally {
      setIsCheckingHealth(false);
    }
  }

  function handleCopyLogPath() {
    void navigator.clipboard?.writeText(displayedLogPath).catch(() => {});
    pushNotification({
      tone: "info",
      title: "Log path copied",
      detail: `Path: ${displayedLogPath}`,
    });
  }

  async function handleOpenLogDir() {
    if (backendClient.runtimeMode !== "desktop-bridge") {
      pushNotification({
        tone: "info",
        title: "Desktop runtime required",
        detail:
          "Opening the log folder uses the native OS file manager — run the Tauri desktop shell.",
      });
      return;
    }
    if (!logDirectory) {
      pushNotification({
        tone: "info",
        title: "Log directory unknown",
        detail:
          "Run a health check first so the sidecar can report its real log directory.",
      });
      return;
    }
    try {
      await backendClient.revealInFileManager(logDirectory);
    } catch (error) {
      const detail = describeBackendError(error, "Failed to open log folder");
      pushNotification({ tone: "error", title: "Open log folder failed", detail });
    }
  }

  return (
    <ErrorBoundary title="Settings error" detail="An error occurred in the Settings panel.">
      <div className="tool-workspace">
        <section className="workspace-grid workspace-grid--single">
          <div className="workspace-grid__main">
            <SectionCard title="Theme" eyebrow="Appearance">
              <div className={styles.themeGrid}>
                {themeOptions.map((option) => {
                  const isSelected = themeMode === option.id;
                  const Icon = option.icon;
                  return (
                    <button
                      key={option.id}
                      type="button"
                      className={styles.themeOption}
                      data-selected={isSelected || undefined}
                      onClick={() => setThemeMode(option.id)}
                    >
                      <Icon size={20} weight={isSelected ? "fill" : "regular"} />
                      <span className={styles.themeOptionLabel}>{option.label}</span>
                      <span className={styles.themeOptionDesc}>{option.description}</span>
                    </button>
                  );
                })}
              </div>
              <p className={styles.activeNote}>
                Active theme: <strong>{resolvedTheme.replace(/_/g, " ")}</strong>
                {themeMode === "system" ? " (following system)" : ""}
              </p>
            </SectionCard>

            <SectionCard title="Logs" eyebrow="Diagnostics">
              <div className={styles.diagnosticStack}>
                <div className="settings__logs-path">
                  <code title={displayedLogPath}>{displayedLogPath}</code>
                  <button
                    type="button"
                    className="ghost-button"
                    onClick={handleCopyLogPath}
                  >
                    Copy path
                  </button>
                  <button
                    type="button"
                    className="ghost-button"
                    onClick={() => {
                      void handleOpenLogDir();
                    }}
                  >
                    <FolderOpen size={14} weight="bold" />
                    {OPEN_FOLDER_LABEL}
                  </button>
                </div>
              </div>
            </SectionCard>

            <SectionCard title="Backend Diagnostics" eyebrow="Connection">
              <div className={styles.diagnosticStack}>
                <div className={styles.diagnosticGrid}>
                  <div className={styles.diagnosticField}>
                    <p className={styles.diagnosticLabel}>Status</p>
                    <p className={styles.diagnosticValue}>{backendStatus}</p>
                  </div>
                  <div className={styles.diagnosticField}>
                    <p className={styles.diagnosticLabel}>Mode</p>
                    <p className={styles.diagnosticValue}>{backendMode}</p>
                  </div>
                  <div className={styles.diagnosticField}>
                    <p className={styles.diagnosticLabel}>Last ping latency</p>
                    <p className={`${styles.diagnosticValue} ${styles.diagnosticValueInline}`}>
                      <span className={latency.dotClass} aria-hidden="true" />
                      {latency.display}
                    </p>
                  </div>
                  <div className={styles.diagnosticFieldWide}>
                    <p className={styles.diagnosticLabel}>Message</p>
                    <p className={styles.diagnosticMessage}>{backendMessage ?? "No message"}</p>
                  </div>
                  {lastBackendCheckAt && (
                    <div className={styles.diagnosticFieldWide}>
                      <p className={styles.diagnosticLabel}>Last check</p>
                      <p className={styles.diagnosticMessage}>{new Date(lastBackendCheckAt).toLocaleString()}</p>
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  className="ghost-button"
                  onClick={handleHealthCheck}
                  disabled={isCheckingHealth}
                >
                  <ArrowClockwise size={16} className={isCheckingHealth ? "spin" : ""} />
                  {isCheckingHealth ? "Checking..." : "Run health check"}
                </button>
              </div>
            </SectionCard>

            <SectionCard title="About" eyebrow="Application">
              <div className={styles.aboutStack}>
                <div className={styles.aboutGrid}>
                  <div className={styles.diagnosticField}>
                    <p className={styles.diagnosticLabel}>Application</p>
                    <p className={styles.diagnosticValue}>Reliability Tools Desktop</p>
                  </div>
                  <div className={styles.diagnosticField}>
                    <p className={styles.diagnosticLabel}>Platform</p>
                    <p className={styles.diagnosticValue}>Tauri + React</p>
                  </div>
                  <div className={styles.diagnosticField}>
                    <p className={styles.diagnosticLabel}>Shell version</p>
                    <p className={styles.diagnosticValue}>{__APP_VERSION__}</p>
                  </div>
                  <div className={styles.diagnosticField}>
                    <p className={styles.diagnosticLabel}>Protocol</p>
                    <p className={styles.diagnosticValue}>NDJSON v{protocolVersion}</p>
                  </div>
                </div>
                <p className={styles.aboutFooter}>
                  <Heart size={12} weight="fill" style={{ color: "var(--accent)" }} />
                  Built by Reliability Engineering
                </p>
              </div>
            </SectionCard>
          </div>
        </section>
      </div>
    </ErrorBoundary>
  );
}
