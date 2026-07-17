import type { ErrorInfo, ReactNode } from "react";
import { Component, useEffect, useRef, useState } from "react";
import { useShellStore } from "../../stores/shellStore";
import { useThemeStore } from "../../stores/themeStore";
import { useNotificationStore } from "../../stores/notificationStore";

interface ErrorBoundaryProps {
  title: string;
  detail: string;
  onReset?: () => void;
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  componentStack: string | null;
}

const STACK_LINE_LIMIT = 30;

function truncateStack(stack: string | null | undefined): string {
  if (!stack) {
    return "";
  }
  const lines = stack.split("\n");
  if (lines.length <= STACK_LINE_LIMIT) {
    return stack;
  }
  return [...lines.slice(0, STACK_LINE_LIMIT), `... (+${lines.length - STACK_LINE_LIMIT} more lines)`].join("\n");
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  public override state: ErrorBoundaryState = {
    hasError: false,
    error: null,
    componentStack: null,
  };

  public static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error, componentStack: null };
  }

  public override componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Desktop shell boundary caught an error", error);
    this.setState({ componentStack: errorInfo.componentStack ?? null });
  }

  private handleReset = () => {
    this.setState({ hasError: false, error: null, componentStack: null });
    this.props.onReset?.();
  };

  public override render() {
    if (this.state.hasError) {
      return (
        <ErrorBoundaryFallback
          title={this.props.title}
          detail={this.props.detail}
          error={this.state.error}
          componentStack={this.state.componentStack}
          onReset={this.props.onReset ? this.handleReset : null}
        />
      );
    }

    return this.props.children;
  }
}

interface ErrorBoundaryFallbackProps {
  title: string;
  detail: string;
  error: Error | null;
  componentStack: string | null;
  onReset: (() => void) | null;
}

/**
 * Functional fallback so we can use hooks (zustand stores, notifications)
 * inside the recovery surface without dragging the class component into a
 * hook-aware shape.
 */
function ErrorBoundaryFallback({
  title,
  detail,
  error,
  componentStack,
  onReset,
}: ErrorBoundaryFallbackProps) {
  const activeToolId = useShellStore((state) => state.activeToolId);
  const themeMode = useThemeStore((state) => state.mode);
  const pushNotification = useNotificationStore((state) => state.push);

  // Inline copy confirmation. When the ROOT boundary catches, the App (and the
  // NotificationCenter that renders toasts) is unmounted — a pushed toast would
  // never render. So we surface the result on the button itself. The store push
  // is kept too, since nested (non-root) boundaries still have a live toast host.
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const resetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (resetTimerRef.current) {
        clearTimeout(resetTimerRef.current);
      }
    };
  }, []);

  const truncatedStack = truncateStack(error?.stack);

  const handleCopyDiagnostics = async () => {
    const bundle = {
      timestamp: new Date().toISOString(),
      error: {
        name: error?.name ?? "UnknownError",
        message: error?.message ?? "(no message)",
        stack: error?.stack ?? null,
      },
      componentStack: componentStack ?? null,
      // __APP_VERSION__ is the build-time define from vite.config.ts
      // (single source: package.json). The old import.meta.env.VITE_APP_VERSION
      // read was never defined anywhere and always reported "unknown".
      appVersion: __APP_VERSION__,
      activeTool: activeToolId,
      theme: themeMode,
    };
    const json = JSON.stringify(bundle, null, 2);
    let copied = false;
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(json);
        copied = true;
      } catch {
        copied = false;
      }
    }
    if (!copied && typeof document !== "undefined") {
      try {
        const textarea = document.createElement("textarea");
        textarea.value = json;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "absolute";
        textarea.style.left = "-9999px";
        document.body.appendChild(textarea);
        textarea.select();
        copied = document.execCommand("copy");
        document.body.removeChild(textarea);
      } catch {
        copied = false;
      }
    }
    // Inline confirmation on the button itself (survives a root-boundary
    // unmount of the toast host), reverting after a short delay.
    setCopyState(copied ? "copied" : "failed");
    if (resetTimerRef.current) {
      clearTimeout(resetTimerRef.current);
    }
    resetTimerRef.current = setTimeout(() => setCopyState("idle"), 2500);

    pushNotification({
      tone: copied ? "success" : "error",
      title: copied ? "Diagnostic bundle copied" : "Copy failed",
      detail: copied
        ? "Paste into a bug report or chat thread."
        : "Clipboard write failed; open the latest log file instead.",
    });
  };

  const copyButtonLabel =
    copyState === "copied"
      ? "Copied ✓"
      : copyState === "failed"
        ? "Copy failed — see log"
        : "Copy diagnostic bundle";

  const handleOpenLatestLog = () => {
    // No production Tauri command surfaces a "reveal log file" path yet, so
    // we degrade gracefully: tell the user where the log lives. The plan
    // explicitly forbids inventing a new Tauri command in this phase.
    pushNotification({
      tone: "info",
      title: "Latest log location",
      detail: "Logs are written to ~/.reliability_tools/logs/. Open that folder in your file manager.",
    });
  };

  return (
    <section className="error-panel error-boundary" role="alert">
      <div className="error-panel__body">
        <p className="eyebrow">Recovery</p>
        <h2>{title}</h2>
        <p className="section-card__description">{detail}</p>
        {error ? (
          <p className="error-boundary__summary">
            <strong>{error.name}:</strong> {error.message}
          </p>
        ) : null}
        {truncatedStack ? (
          <details className="error-boundary__details">
            <summary>Show stack trace</summary>
            <pre className="error-boundary__stack">{truncatedStack}</pre>
          </details>
        ) : null}
      </div>
      <div className="error-boundary__actions">
        {onReset ? (
          <button
            type="button"
            className="error-boundary__action error-boundary__action--primary"
            onClick={onReset}
          >
            Reload tool
          </button>
        ) : null}
        <button
          type="button"
          className="error-boundary__action error-boundary__action--secondary"
          onClick={() => {
            void handleCopyDiagnostics();
          }}
          aria-live="polite"
          data-copy-state={copyState}
        >
          {copyButtonLabel}
        </button>
        <button
          type="button"
          className="error-boundary__action error-boundary__action--secondary"
          onClick={handleOpenLatestLog}
        >
          Open latest log
        </button>
      </div>
    </section>
  );
}
