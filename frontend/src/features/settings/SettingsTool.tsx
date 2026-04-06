import { useState } from "react";
import { Desktop, MoonStars, Sun, Sparkle, ArrowClockwise, Heart } from "@phosphor-icons/react";
import { SectionCard } from "../../components/SectionCard";
import { ErrorBoundary } from "../../shared/errors/ErrorBoundary";
import { useThemeStore, type ThemeMode } from "../../stores/themeStore";
import { useResolvedTheme } from "../../shared/theme/ThemeController";
import { useShellStore } from "../../stores/shellStore";
import { backendClient } from "../../shared/backend/client";
import { useNotificationStore } from "../../stores/notificationStore";

const themeOptions: Array<{ id: ThemeMode; label: string; description: string; icon: typeof Sun }> = [
  { id: "system", label: "System", description: "Follow your OS preference.", icon: Desktop },
  { id: "light_precision", label: "Light Precision", description: "Clean light theme for bright environments.", icon: Sun },
  { id: "dark_precision", label: "Dark Precision", description: "Professional dark theme.", icon: MoonStars },
  { id: "signal_slate", label: "Signal Slate", description: "High-contrast engineering theme.", icon: Sparkle },
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
              <div className="setup-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "0.75rem" }}>
                {themeOptions.map((option) => {
                  const isSelected = themeMode === option.id;
                  const Icon = option.icon;
                  return (
                    <button
                      key={option.id}
                      type="button"
                      onClick={() => setThemeMode(option.id)}
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "flex-start",
                        gap: "0.5rem",
                        padding: "1rem",
                        border: isSelected ? "2px solid var(--color-accent)" : "1px solid var(--color-border)",
                        borderRadius: "0.5rem",
                        background: isSelected ? "var(--color-surface-raised)" : "var(--color-surface)",
                        cursor: "pointer",
                        textAlign: "left",
                        transition: "border-color 0.15s, background 0.15s",
                      }}
                    >
                      <Icon size={20} weight={isSelected ? "fill" : "regular"} style={{ color: isSelected ? "var(--color-accent)" : "var(--color-text-secondary)" }} />
                      <span style={{ fontWeight: 600, fontSize: "0.875rem", color: "var(--color-text-primary)" }}>{option.label}</span>
                      <span style={{ fontSize: "0.75rem", color: "var(--color-text-secondary)" }}>{option.description}</span>
                    </button>
                  );
                })}
              </div>
              <p style={{ marginTop: "0.75rem", fontSize: "0.75rem", color: "var(--color-text-tertiary)" }}>
                Active theme: <strong>{resolvedTheme.replace(/_/g, " ")}</strong>
                {themeMode === "system" ? " (following system)" : ""}
              </p>
            </SectionCard>

            <SectionCard title="Backend Diagnostics" eyebrow="Connection">
              <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.5rem" }}>
                  <div>
                    <p style={{ fontSize: "0.7rem", color: "var(--color-text-tertiary)", marginBottom: "0.25rem" }}>Status</p>
                    <p style={{ fontSize: "0.875rem", fontWeight: 600, color: "var(--color-text-primary)" }}>{backendStatus}</p>
                  </div>
                  <div>
                    <p style={{ fontSize: "0.7rem", color: "var(--color-text-tertiary)", marginBottom: "0.25rem" }}>Mode</p>
                    <p style={{ fontSize: "0.875rem", fontWeight: 600, color: "var(--color-text-primary)" }}>{backendMode}</p>
                  </div>
                  <div style={{ gridColumn: "1 / -1" }}>
                    <p style={{ fontSize: "0.7rem", color: "var(--color-text-tertiary)", marginBottom: "0.25rem" }}>Message</p>
                    <p style={{ fontSize: "0.8rem", color: "var(--color-text-secondary)" }}>{backendMessage ?? "No message"}</p>
                  </div>
                  {lastBackendCheckAt && (
                    <div style={{ gridColumn: "1 / -1" }}>
                      <p style={{ fontSize: "0.7rem", color: "var(--color-text-tertiary)", marginBottom: "0.25rem" }}>Last check</p>
                      <p style={{ fontSize: "0.8rem", color: "var(--color-text-secondary)" }}>{new Date(lastBackendCheckAt).toLocaleString()}</p>
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  onClick={handleHealthCheck}
                  disabled={isCheckingHealth}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    padding: "0.5rem 1rem",
                    border: "1px solid var(--color-border)",
                    borderRadius: "0.375rem",
                    background: "var(--color-surface)",
                    color: "var(--color-text-primary)",
                    cursor: isCheckingHealth ? "wait" : "pointer",
                    fontSize: "0.8rem",
                    fontWeight: 500,
                    alignSelf: "flex-start",
                  }}
                >
                  <ArrowClockwise size={16} className={isCheckingHealth ? "spin" : ""} />
                  {isCheckingHealth ? "Checking..." : "Run health check"}
                </button>
              </div>
            </SectionCard>

            <SectionCard title="About" eyebrow="Application">
              <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.5rem" }}>
                  <div>
                    <p style={{ fontSize: "0.7rem", color: "var(--color-text-tertiary)", marginBottom: "0.25rem" }}>Application</p>
                    <p style={{ fontSize: "0.875rem", fontWeight: 600, color: "var(--color-text-primary)" }}>Reliability Tools Desktop</p>
                  </div>
                  <div>
                    <p style={{ fontSize: "0.7rem", color: "var(--color-text-tertiary)", marginBottom: "0.25rem" }}>Platform</p>
                    <p style={{ fontSize: "0.875rem", fontWeight: 600, color: "var(--color-text-primary)" }}>Tauri + React</p>
                  </div>
                  <div>
                    <p style={{ fontSize: "0.7rem", color: "var(--color-text-tertiary)", marginBottom: "0.25rem" }}>Shell version</p>
                    <p style={{ fontSize: "0.875rem", color: "var(--color-text-primary)" }}>0.1.0</p>
                  </div>
                  <div>
                    <p style={{ fontSize: "0.7rem", color: "var(--color-text-tertiary)", marginBottom: "0.25rem" }}>Protocol</p>
                    <p style={{ fontSize: "0.875rem", color: "var(--color-text-primary)" }}>NDJSON v0.1.0</p>
                  </div>
                </div>
                <p style={{ fontSize: "0.75rem", color: "var(--color-text-tertiary)", display: "flex", alignItems: "center", gap: "0.25rem", marginTop: "0.5rem" }}>
                  <Heart size={12} weight="fill" style={{ color: "var(--color-accent)" }} />
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
