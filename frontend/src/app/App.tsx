import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Copy, Eye, Faders, MagnifyingGlass, Moon, Sparkle, Sun, Terminal } from "@phosphor-icons/react";
import styles from "./AppShell.module.css";
import { toolDefinitions } from "./toolRegistry";
import { CommandPalette, type CommandPaletteAction } from "../components/primitives/CommandPalette";
import { ContextDrawer } from "../components/ContextDrawer";
import { GlobalLogPanel } from "../components/GlobalLogPanel";
import { ErrorBoundary } from "../shared/errors/ErrorBoundary";
import { backendClient } from "../shared/backend/client";
import { describeBackendError } from "../shared/backend/cancelError";
import { useBackendBootstrap } from "../shared/backend/useBackendBootstrap";
import { useBackendBusyReset } from "../shared/backend/useBackendBusyReset";
import { useBackendRunSubscription } from "../shared/backend/useBackendRunSubscription";
import { useAppShortcuts } from "../shared/hooks/useAppShortcuts";
import {
  isEditableKeyboardTarget,
  matchesPrimaryShortcut,
  primaryShortcutLabel,
} from "../shared/hooks/shortcutUtils";
import { NotificationCenter } from "../shared/notifications/NotificationCenter";
import { ThemeController } from "../shared/theme/ThemeController";
import { THEME_REGISTRY } from "../shared/theme/themeRegistry";
import { useGlobalLogStore } from "../stores/globalLogStore";
import { useNotificationStore } from "../stores/notificationStore";
import { useShellStore, type ToolId } from "../stores/shellStore";
import { useThemeStore } from "../stores/themeStore";

export function App() {
  useAppShortcuts();
  useBackendBootstrap();
  useBackendRunSubscription();
  // Phase B4: shell-level guarantee that reaching any terminal run phase
  // (idle / cancelled / success / failure) releases the "busy" chip.
  // Belt-and-suspenders with the per-tool setBackendState calls — the
  // hook fires after the tool has already updated, and re-fires in
  // edge cases (validation failures) where the tool never would.
  useBackendBusyReset();

  const activeToolId = useShellStore((state) => state.activeToolId);
  const setActiveToolId = useShellStore((state) => state.setActiveToolId);
  const contextOpen = useShellStore((state) => state.contextOpen);
  const toggleContext = useShellStore((state) => state.toggleContext);
  const themeMode = useThemeStore((state) => state.mode);
  const setThemeMode = useThemeStore((state) => state.setMode);
  const toolModeLabels = useShellStore((state) => state.toolModeLabels);
  const toggleLogVisible = useGlobalLogStore((state) => state.toggleVisible);
  const pushNotification = useNotificationStore((state) => state.push);

  const activeTool = toolDefinitions.find((tool) => tool.id === activeToolId) ?? toolDefinitions[0];

  // Keep-alive shell: once a tool has been visited we keep it mounted and
  // toggle visibility with the [hidden] attribute instead of swapping the
  // single rendered component. Unmounting a tool on every switch destroyed
  // all of its local useState — loaded input files, sheet selections, column
  // mapping overrides, workflow selection — and orphaned any in-flight run
  // (the per-tool run controller, which owns terminal toasts, unmounted with
  // it). Tools not yet visited are deliberately NOT rendered so their
  // lazy-loaded module isn't fetched until first use. ``activeTool.id`` rather
  // than ``activeToolId`` seeds the set so a stale/unknown persisted id still
  // mounts the fallback tool we actually display.
  const [visitedToolIds, setVisitedToolIds] = useState<Set<ToolId>>(
    () => new Set<ToolId>([activeTool.id]),
  );
  useEffect(() => {
    setVisitedToolIds((current) => {
      if (current.has(activeTool.id)) {
        return current;
      }
      const next = new Set(current);
      next.add(activeTool.id);
      return next;
    });
  }, [activeTool.id]);

  // Phase 4 Task 4: focus management on tool switch.
  // The main element has tabIndex={-1} so it can programmatically receive
  // focus, and aria-live="polite" so screen readers announce the active
  // tool label when focus lands here. We push the focus() into a useEffect
  // keyed on activeToolId to avoid racing React's render cycle from the
  // click handler.
  //
  // Keep-alive note: with the keep-alive shell the just-revealed tool mounts
  // (on first visit) in the same commit as the activeToolId change, and some
  // tools focus their own context heading on mount. Deferring the shell's
  // main.focus() into a rAF ensures it lands AFTER any tool-internal mount
  // focus so the shell announcement still wins — matching the pre-keep-alive
  // behaviour where the outgoing tool unmounted and could not steal focus.
  const mainRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const handle = requestAnimationFrame(() => {
      mainRef.current?.focus();
    });
    return () => cancelAnimationFrame(handle);
  }, [activeToolId]);

  // Phase 4 Task 7: Cmd+K command palette.
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (isEditableKeyboardTarget(event.target)) {
        return;
      }
      if (matchesPrimaryShortcut(event, "k")) {
        event.preventDefault();
        setCommandPaletteOpen((prev) => !prev);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const commandPaletteActions = useMemo<CommandPaletteAction[]>(() => {
    const actions: CommandPaletteAction[] = [];

    // One action per tool.
    toolDefinitions.forEach((tool, index) => {
      actions.push({
        id: `tool/${tool.id}`,
        label: tool.label,
        hint: tool.eyebrow,
        category: "Tools",
        icon: tool.icon,
        shortcut: index < 9 ? primaryShortcutLabel(String(index + 1)) : undefined,
        onSelect: () => setActiveToolId(tool.id as ToolId),
      });
    });

    // One action per theme.
    THEME_REGISTRY.forEach((theme) => {
      actions.push({
        id: `theme/${theme.id}`,
        label: `Theme: ${theme.label}`,
        hint: theme.description,
        category: "Themes",
        icon: theme.icon,
        onSelect: () => setThemeMode(theme.id),
      });
    });

    // Utility actions.
    actions.push({
      id: "app/settings",
      label: "Open Settings",
      category: "App",
      icon: Faders,
      onSelect: () => setActiveToolId("settings"),
    });
    actions.push({
      id: "app/log-toggle",
      label: "Toggle log panel",
      category: "App",
      icon: Terminal,
      onSelect: () => toggleLogVisible(),
    });
    actions.push({
      id: "app/log-path",
      label: "Copy log file path",
      category: "App",
      icon: Copy,
      onSelect: () => {
        // Since 0.4.2 the sidecar reports its real log directory on
        // every ``health_check``. We call it on-demand here rather than
        // caching so a user who switches the ``RELIABILITY_TOOLS_LOG_DIR``
        // env var between launches always copies the live value. Browser
        // preview mode has no sidecar, so we fall back to the placeholder
        // string used in Settings › Logs.
        if (backendClient.runtimeMode !== "desktop-bridge") {
          void navigator.clipboard?.writeText("~/.reliability_tools/logs/").catch(() => {});
          pushNotification({
            tone: "info",
            title: "Log path copied (placeholder)",
            detail: "Desktop runtime required for the real path — copied the default location instead.",
          });
          return;
        }
        void (async () => {
          try {
            const health = await backendClient.healthCheck();
            const path = health.log_directory ?? "~/.reliability_tools/logs/";
            await navigator.clipboard?.writeText(path);
            pushNotification({
              tone: "success",
              title: "Log path copied",
              detail: path,
            });
          } catch (error) {
            const detail = describeBackendError(error, "Health check failed");
            pushNotification({
              tone: "error",
              title: "Could not fetch log path",
              detail,
            });
          }
        })();
      },
    });

    return actions;
  }, [pushNotification, setActiveToolId, setThemeMode, toggleLogVisible]);

  const navigationShortcutLabel = `${primaryShortcutLabel("[")} / ${primaryShortcutLabel("]")}`;

  // Phase 4 Task 9: Tauri native file drop.
  // We lazily import the Tauri webview API so browser-mock dev mode stays
  // functional. When a drop event lands, we surface a notification listing
  // the paths — routing the first path into the active tool's file handler
  // would require exposing tool-internal pickers via the shell store, which
  // the current architecture does not do. TODO: thread dropped paths
  // through a shellStore-level event bus so each tool can pick up the
  // dropped file for its first input role.
  useEffect(() => {
    const isTauri =
      typeof window !== "undefined" &&
      ("__TAURI_INTERNALS__" in window || "__TAURI__" in window);
    if (!isTauri) {
      return;
    }

    let unlisten: (() => void) | undefined;
    let cancelled = false;

    (async () => {
      try {
        const { getCurrentWebview } = await import("@tauri-apps/api/webview");
        const handle = await getCurrentWebview().onDragDropEvent((event) => {
          if (event.payload.type !== "drop") {
            return;
          }
          const paths = event.payload.paths ?? [];
          if (paths.length === 0) {
            return;
          }
          pushNotification({
            tone: "info",
            title: `Received ${paths.length} dropped file${paths.length === 1 ? "" : "s"}`,
            detail: `Route via the tool's browse button. First path: ${paths[0]}`,
          });
        });
        if (cancelled) {
          handle();
        } else {
          unlisten = handle;
        }
      } catch (error) {
        // Tauri API not available or permission denied — silently ignore
        // so browser-mock mode keeps working.
        void error;
      }
    })();

    return () => {
      cancelled = true;
      if (unlisten) {
        unlisten();
      }
    };
  }, [pushNotification]);

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
                <Sparkle size={12} weight="fill" />
              </div>
              <p className={styles.brandLabel}>Dark Star</p>
            </div>

            {/* v2 N2: grouped nav — "Tools" and "System" are the app's only
                uppercase micro-labels. Shortcut digits stay aligned with the
                palette's Ctrl+N actions (index across ALL tools). */}
            <nav className={styles.toolList} aria-label="Desktop tools">
              {(["Tools", "System"] as const).map((group) => (
                <div key={group} style={{ display: "contents" }}>
                  <p className={styles.navLabel}>{group}</p>
                  {toolDefinitions
                    .filter((tool) => (group === "System") === (tool.id === "settings"))
                    .map((tool) => {
                      const index = toolDefinitions.indexOf(tool);
                      const Icon = tool.icon;
                      const isActive = tool.id === activeToolId;

                      return (
                        <button
                          key={tool.id}
                          type="button"
                          className={styles.toolButton}
                          data-selected={isActive}
                          onClick={() => setActiveToolId(tool.id)}
                          aria-current={isActive ? "page" : undefined}
                          aria-label={`${tool.label} (${index + 1})`}
                          title={`${tool.label} (${primaryShortcutLabel(String(index + 1))})`}
                        >
                          <Icon size={16} weight={isActive ? "fill" : "regular"} />
                          <span className={styles.toolLabel}>{tool.label}</span>
                          <span className={styles.toolShortcut} aria-hidden="true">
                            {index + 1}
                          </span>
                        </button>
                      );
                    })}
                </div>
              ))}
            </nav>

            {/* v2 N2: the theme picker left the rail — Settings and the
                command palette carry the full list. The footer is version
                telemetry + a light/dark Precision toggle. */}
            <div className={styles.footer}>
              <span className={styles.version}>v{import.meta.env.VITE_APP_VERSION ?? "dev"}</span>
              <button
                type="button"
                className={styles.themeToggle}
                onClick={() =>
                  setThemeMode(themeMode === "dark_precision" ? "light_precision" : "dark_precision")
                }
                aria-label={
                  themeMode === "dark_precision" ? "Switch to light theme" : "Switch to dark theme"
                }
                title={themeMode === "dark_precision" ? "Light Precision" : "Dark Precision"}
              >
                {themeMode === "dark_precision" ? <Sun size={14} /> : <Moon size={14} />}
              </button>
            </div>
          </aside>

          <div className={styles.main}>
            <header className={styles.topbar}>
              <h1 className={styles.title} title={activeTool.label}>
                {activeTool.label}
              </h1>
              {toolModeLabels[activeTool.id] ? (
                <>
                  <span className={styles.topbarDivider} aria-hidden="true" />
                  <span className={styles.topbarMode}>
                    Mode <b>{toolModeLabels[activeTool.id]}</b>
                  </span>
                </>
              ) : null}

              {/* Deliberately lean: quiet buttons only. Backend health lives
                  in the log strip (v2 N3); keyboard hints live in the command
                  palette and tooltips. */}
              <div className={styles.statusRow}>
                <button
                  type="button"
                  className="topbar__review-toggle"
                  data-selected={contextOpen}
                  onClick={toggleContext}
                  aria-pressed={contextOpen}
                  aria-label={contextOpen ? "Close Review drawer" : "Open Review drawer"}
                  title={`Review drawer (${primaryShortcutLabel("R")}) — switch tools with ${navigationShortcutLabel}`}
                >
                  <Eye size={14} weight={contextOpen ? "fill" : "regular"} />
                  <span>Review</span>
                  <span className="kbd-shortcut">{primaryShortcutLabel("R")}</span>
                </button>
                <button
                  type="button"
                  className="topbar__review-toggle"
                  onClick={() => setCommandPaletteOpen(true)}
                  aria-label="Open command palette"
                  title={`Command palette (${primaryShortcutLabel("K")})`}
                >
                  <MagnifyingGlass size={14} />
                  <span className="kbd-shortcut">{primaryShortcutLabel("K")}</span>
                </button>
              </div>
            </header>

            <main
              ref={mainRef}
              className={styles.content}
              tabIndex={-1}
              aria-live="polite"
              aria-label={`${activeTool.label} workspace`}
            >
              {/* Every visited tool stays mounted; only the active one is
                  visible. Inactive wrappers carry the `hidden` attribute,
                  which the UA stylesheet renders as `display: none` and which
                  also drops them from the accessibility tree and tab order —
                  exactly what we want. Each tool gets its OWN ErrorBoundary
                  and Suspense boundary so one tool's lazy fallback or render
                  error can't blank a sibling. */}
              {toolDefinitions
                .filter((tool) => visitedToolIds.has(tool.id))
                .map((tool) => {
                  const ToolComponent = tool.component;
                  const isActive = tool.id === activeTool.id;
                  return (
                    <div
                      key={tool.id}
                      data-tool-id={tool.id}
                      className={styles.toolPane}
                      hidden={!isActive}
                    >
                      <ErrorBoundary
                        title={`${tool.label} failed to render`}
                        detail="This tool boundary caught an error so the rest of the suite shell can keep running."
                        onReset={() => setActiveToolId(tool.id)}
                      >
                        <Suspense
                          fallback={
                            <section className={styles.loading}>
                              <p className="eyebrow">Loading</p>
                              <h2>Preparing {tool.label}</h2>
                              <p className="section-card__description">
                                The suite shell uses lazy-loaded tool modules so inactive tools stay lightweight.
                              </p>
                            </section>
                          }
                        >
                          <ToolComponent />
                        </Suspense>
                      </ErrorBoundary>
                    </div>
                  );
                })}
            </main>
            <GlobalLogPanel />
          </div>
        </div>
      </ErrorBoundary>
      <ContextDrawer />
      <NotificationCenter />
      <CommandPalette
        actions={commandPaletteActions}
        open={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
      />
    </>
  );
}
