import { useEffect, useMemo, useRef } from "react";
import { X } from "@phosphor-icons/react";
import { toolDefinitions } from "../app/toolRegistry";
import { usePreviewStore } from "../stores/previewStore";
import { useRunStore } from "../stores/runStore";
import { useShellStore } from "../stores/shellStore";

/**
 * Review drawer — design handoff principle D / phase 4.
 *
 * Slide-in panel anchored to the right edge of the main column. Shows:
 *
 * - **Run summary**   (who / what / when, derived from the active tool's run
 *                      when the global run store currently belongs to it)
 * - **Output preview** (rows from the last successful `validate_run`, via
 *                       `previewStore` keyed by active tool)
 *
 * The drawer is informational, not modal — no backdrop, and it does not
 * steal focus on open. Escape and ⌘R / Ctrl+R close it (the shortcut is
 * owned by `useAppShortcuts`; Escape is local to the drawer so users can
 * dismiss without leaving the keyboard).
 */
export function ContextDrawer() {
  const open = useShellStore((state) => state.contextOpen);
  const setContextOpen = useShellStore((state) => state.setContextOpen);
  const activeToolId = useShellStore((state) => state.activeToolId);
  const activeRun = useRunStore((state) => state.activeRun);
  const snapshot = usePreviewStore((state) => state.byTool[activeToolId]);

  const drawerRef = useRef<HTMLElement | null>(null);
  const toolLabel = useMemo(() => {
    return toolDefinitions.find((tool) => tool.id === activeToolId)?.label ?? activeToolId;
  }, [activeToolId]);
  const toolRun = useMemo(() => {
    return activeRun?.toolId === activeToolId ? activeRun : null;
  }, [activeRun, activeToolId]);

  // Local Escape handler — the global shortcut owns ⌘R; Escape stays
  // drawer-local so it doesn't collide with other Escape consumers (the
  // command palette closes on Escape via its own modal layer).
  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setContextOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, setContextOpen]);

  const preview = snapshot?.preview ?? null;
  const totalEstimated =
    preview && typeof preview.total_estimated === "number"
      ? preview.total_estimated
      : null;
  const hasPreview = preview !== null && preview.rows.length > 0;

  return (
    <aside
      ref={drawerRef}
      className="context-drawer"
      data-open={open}
      aria-hidden={!open}
      inert={!open}
      aria-labelledby="context-drawer-title"
    >
      <header className="context-drawer__header">
        <div>
          <p className="eyebrow">Review</p>
          <h2 id="context-drawer-title" className="context-drawer__title">
            {toolLabel}
          </h2>
        </div>
        <button
          type="button"
          className="context-drawer__close"
          onClick={() => setContextOpen(false)}
          aria-label="Close Review drawer"
          title="Close (Esc)"
          disabled={!open}
          tabIndex={open ? undefined : -1}
        >
          <X size={16} weight="bold" />
        </button>
      </header>

      <section className="context-drawer__section">
        <p className="eyebrow">Run summary</p>
        {toolRun ? (
          <dl className="context-drawer__summary">
            <dt>Phase</dt>
            <dd>
              <span
                className={`badge-state badge-state--${phaseToVariant(
                  toolRun.phase,
                )}`}
              >
                {toolRun.phase}
              </span>
            </dd>
            {toolRun.stage ? (
              <>
                <dt>Stage</dt>
                <dd>{toolRun.stage}</dd>
              </>
            ) : null}
            {toolRun.statusMessage ? (
              <>
                <dt>Status</dt>
                <dd>{toolRun.statusMessage}</dd>
              </>
            ) : null}
            <dt>Progress</dt>
            <dd className="context-drawer__progress">
              <span className="hero-metric">{Math.round(toolRun.progress * 100) / 100}</span>
              <span className="context-drawer__progress-unit">%</span>
            </dd>
            {toolRun.startedAt ? (
              <>
                <dt>Started</dt>
                <dd>{formatTimestamp(toolRun.startedAt)}</dd>
              </>
            ) : null}
            {toolRun.finishedAt ? (
              <>
                <dt>Finished</dt>
                <dd>{formatTimestamp(toolRun.finishedAt)}</dd>
              </>
            ) : null}
          </dl>
        ) : (
          <p className="context-drawer__empty">No run has started for this tool yet.</p>
        )}
      </section>

      <section className="context-drawer__section">
        <p className="eyebrow">Preview</p>
        {hasPreview ? (
          <>
            <p className="context-drawer__preview-caption">
              Showing {preview.rows.length}
              {preview.truncated && totalEstimated !== null
                ? ` of ${totalEstimated.toLocaleString()}`
                : ""}{" "}
              {preview.rows.length === 1 ? "row" : "rows"}
              {preview.truncated ? " (truncated)" : ""} from the source data.
            </p>
            <div className="context-drawer__preview-scroll">
              <table className="context-drawer__preview-table">
                <thead>
                  <tr>
                    {preview.columns.map((col) => (
                      <th key={col} scope="col">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      {row.map((cell, cellIndex) => (
                        <td key={cellIndex}>{cell || "—"}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <p className="context-drawer__empty">
            No preview yet. Run validation to populate this panel.
          </p>
        )}
      </section>
    </aside>
  );
}

type RunPhase = string | null | undefined;

function phaseToVariant(phase: RunPhase): "good" | "warn" | "bad" | "idle" {
  if (!phase) return "idle";
  if (phase === "success") return "good";
  if (phase === "failure") return "bad";
  if (phase === "cancelled" || phase === "cancelling" || phase === "disconnected")
    return "warn";
  return "idle";
}

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}
