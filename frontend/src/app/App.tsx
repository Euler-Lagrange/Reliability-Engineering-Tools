import { Suspense } from "react";
import { Command, Desktop, MoonStars, Sparkle, Sun, WarningCircle } from "@phosphor-icons/react";
import styles from "./AppShell.module.css";
import { toolDefinitions } from "./toolRegistry";
import { ErrorBoundary } from "../shared/errors/ErrorBoundary";
import { useBackendBootstrap } from "../shared/backend/useBackendBootstrap";
import { useAppShortcuts } from "../shared/hooks/useAppShortcuts";
import { NotificationCenter } from "../shared/notifications/NotificationCenter";
import { ThemeController, useResolvedTheme } from "../shared/theme/ThemeController";
import { useShellStore } from "../stores/shellStore";
import { useThemeStore } from "../stores/themeStore";

const themeButtons = [
  { id: "system", label: "Sys", icon: Desktop },
  { id: "light_precision", label: "Light", icon: Sun },
  { id: "dark_precision", label: "Dark", icon: MoonStars },
  { id: "signal_slate", label: "Slate", icon: Sparkle },
] as const;

const backendStatusTone = {
  connecting: "pending",
  ready: "success",
  busy: "warning",
  disconnected: "warning",
  error: "failure",
} as const;

const backendStatusLabel = {
  connecting: "Connecting backend...",
  ready: "Backend ready",
  busy: "Backend busy",
  disconnected: "Backend disconnected",
  error: "Backend error",
} as const;

const backendModeLabel = {
  unknown: "Backend pending",
  "browser-mock": "Browser preview",
  "desktop-bridge": "Desktop bridge",
} as const;

export function App() {
  useAppShortcuts();
  useBackendBootstrap();

  const activeToolId = useShellStore((state) => state.activeToolId);
  const setActiveToolId = useShellStore((state) => state.setActiveToolId);
  const backendStatus = useShellStore((state) => state.backendStatus);
  const backendMode = useShellStore((state) => state.backendMode);
  const backendMessage = useShellStore((state) => state.backendMessage);
  const themeMode = useThemeStore((state) => state.mode);
  const setThemeMode = useThemeStore((state) => state.setMode);
  const resolvedTheme = useResolvedTheme();

  const activeTool = toolDefinitions.find((tool) => tool.id === activeToolId) ?? toolDefinitions[0];
  const ActiveToolComponent = activeTool.component;

  return (
    <>
      <ThemeController />
      <ErrorBoundary
        title="Desktop shell failed to render"
        detail="The new Tauri shell hit an application-level error. Reload after checking the desktop logs."
      >
        <div className={styles.shell}>
          <aside className={styles.rail} aria-label="Suite navigation">
            <div className={styles.brand}>
              <div className={styles.brandGlyph}>
                <Sparkle size={20} weight="fill" />
              </div>
              <p className={styles.brandLabel}>Dark Star</p>
            </div>

            <nav className={styles.toolList} aria-label="Desktop tools">
              {toolDefinitions.map((tool, index) => {
                const Icon = tool.icon;
                const isActive = tool.id === activeToolId;

                return (
                  <button
                    key={tool.id}
                    type="button"
                    className={styles.toolButton}
                    data-active={isActive}
                    onClick={() => setActiveToolId(tool.id)}
                    aria-current={isActive ? "page" : undefined}
                    aria-label={`${tool.label} (${index + 1})`}
                    title={`${tool.label} (Ctrl+${index + 1})`}
                  >
                    <Icon size={20} weight={isActive ? "fill" : "regular"} />
                    <span className={styles.toolLabel}>{tool.label}</span>
                  </button>
                );
              })}
            </nav>

            <div className={styles.footer}>
              <div className={styles.themeGroup}>
                <p className={styles.themeLabel}>Theme</p>
                <div className={styles.themeButtons}>
                  {themeButtons.map((theme) => {
                    const Icon = theme.icon;
                    return (
                      <button
                        key={theme.id}
                        type="button"
                        className={styles.themeButton}
                        data-active={themeMode === theme.id}
                        onClick={() => setThemeMode(theme.id)}
                        aria-label={`Switch to ${theme.label.toLowerCase()} theme`}
                      >
                        <Icon size={14} weight="bold" />
                        {theme.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </aside>

          <div className={styles.main}>
            <header className={styles.topbar}>
              <div className={styles.titleGroup}>
                <p className="eyebrow">{activeTool.eyebrow}</p>
                <h1 className={styles.title}>{activeTool.label}</h1>
                <p className={styles.subtitle}>{activeTool.description}</p>
              </div>

              <div className={styles.statusRow}>
                <span className={`status-chip status-chip--${backendStatusTone[backendStatus]}`}>
                  {backendStatusLabel[backendStatus]}
                </span>
                <span className="status-chip status-chip--info" title={backendMessage ?? undefined}>
                  {backendModeLabel[backendMode]}
                </span>
                <span className="status-chip status-chip--info">
                  {resolvedTheme === "dark_precision"
                    ? "Dark Precision"
                    : resolvedTheme === "signal_slate"
                      ? "Signal Slate"
                      : "Light Precision"}
                </span>
                <span className="status-chip status-chip--pending">
                  <Command size={12} weight="bold" />
                  Ctrl+[ / Ctrl+]
                </span>
                {activeTool.status === "placeholder" ? (
                  <span className="status-chip status-chip--warning">
                    <WarningCircle size={12} weight="fill" />
                    Placeholder
                  </span>
                ) : null}
              </div>
            </header>

            <main className={styles.content}>
              <ErrorBoundary
                title={`${activeTool.label} failed to render`}
                detail="This tool boundary caught an error so the rest of the suite shell can keep running."
                onReset={() => setActiveToolId(activeTool.id)}
              >
                <Suspense
                  fallback={
                    <section className={styles.loading}>
                      <p className="eyebrow">Loading</p>
                      <h2>Preparing {activeTool.label}</h2>
                      <p className="section-card__description">
                        The suite shell uses lazy-loaded tool modules so inactive tools stay lightweight.
                      </p>
                    </section>
                  }
                >
                  <ActiveToolComponent />
                </Suspense>
              </ErrorBoundary>
            </main>
          </div>
        </div>
      </ErrorBoundary>
      <NotificationCenter />
    </>
  );
}
