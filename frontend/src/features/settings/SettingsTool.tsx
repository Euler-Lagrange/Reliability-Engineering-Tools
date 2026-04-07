import { useState } from "react";
import {
  Desktop,
  MoonStars,
  Sun,
  Sparkle,
  ArrowClockwise,
  Heart,
  Airplane,
  CircleHalf,
  Lightning,
  Broadcast,
} from "@phosphor-icons/react";
import { SectionCard } from "../../components/SectionCard";
import { ErrorBoundary } from "../../shared/errors/ErrorBoundary";
import { useThemeStore, type ThemeMode } from "../../stores/themeStore";
import { useResolvedTheme } from "../../shared/theme/ThemeController";
import { useShellStore } from "../../stores/shellStore";
import { backendClient } from "../../shared/backend/client";
import { useNotificationStore } from "../../stores/notificationStore";
import styles from "./SettingsTool.module.css";

const themeOptions: Array<{ id: ThemeMode; label: string; description: string; icon: typeof Sun }> = [
  { id: "system", label: "System", description: "Follow your OS preference.", icon: Desktop },
  { id: "light_precision", label: "Light Precision", description: "Clean light theme for bright environments.", icon: Sun },
  { id: "dark_precision", label: "Dark Precision", description: "Professional dark theme.", icon: MoonStars },
  { id: "signal_slate", label: "Signal Slate", description: "High-contrast engineering theme.", icon: Sparkle },
  { id: "midnight_blue", label: "Midnight Blue", description: "Deep navy + ice blue. Aerospace engineering aesthetic.", icon: Airplane },
  { id: "high_contrast", label: "High Contrast", description: "Pure black and white with yellow accents. WCAG AAA.", icon: CircleHalf },
  { id: "synthwave", label: "Synthwave", description: "Neon pink and purple. Retro-futurist vibes.", icon: Lightning },
  { id: "mission_control", label: "Mission Control", description: "Monospaced instrument panel. Dimmed readouts, cyan accents.", icon: Broadcast },
];

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

  async function handleHealthCheck() {
    setIsCheckingHealth(true);
    try {
      const result = await backendClient.healthCheck();
      setBackendState({
        backendStatus: "ready",
        backendMode: result.mode,
        backendMessage: `Backend healthy (${result.backend}, protocol ${result.protocol_version})`,
        lastBackendCheckAt: new Date().toISOString(),
      });
      pushNotification({ tone: "success", title: "Health check passed", detail: `${result.backend} is responsive.` });
    } catch (error: unknown) {
      const detail = error instanceof Error ? error.message : "Health check failed";
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

  return (
    <ErrorBoundary title="Settings error" detail="An error occurred in the Settings panel.">
      <div className="tool-workspace">
        <header className="tool-banner">
          <p className="tool-banner__eyebrow">Platform</p>
          <h1 className="tool-banner__title">Settings</h1>
        </header>

        <section className="workspace-grid workspace-grid--single">
          <div className="workspace-grid__main">
            <SectionCard title="Theme" eyebrow="Appearance">
              <div className={styles.themeGrid}>
                {themeOptions.map((option) => {
                  const isSelected = themeMode === option.id;
                  const Icon = option.icon;
                  const classes = isSelected
                    ? `${styles.themeOption} ${styles.themeOptionSelected}`
                    : styles.themeOption;
                  return (
                    <button key={option.id} type="button" className={classes} onClick={() => setThemeMode(option.id)}>
                      <Icon
                        size={20}
                        weight={isSelected ? "fill" : "regular"}
                        style={{ color: isSelected ? "var(--accent)" : "var(--text-secondary)" }}
                      />
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
                  className={styles.healthButton}
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
                    <p className={styles.diagnosticValue}>0.1.0</p>
                  </div>
                  <div className={styles.diagnosticField}>
                    <p className={styles.diagnosticLabel}>Protocol</p>
                    <p className={styles.diagnosticValue}>NDJSON v0.1.0</p>
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
