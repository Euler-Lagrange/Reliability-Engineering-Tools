import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CaretDown, CaretUp, DownloadSimple, Trash } from "@phosphor-icons/react";
import { toolDefinitions } from "../app/toolRegistry";
import {
  formatGlobalLogEntry,
  useGlobalLogStore,
  type GlobalLogEntry,
  type GlobalLogFilterMode,
} from "../stores/globalLogStore";
import { useShellStore, type ToolId } from "../stores/shellStore";

const TOOL_LABELS: Record<ToolId, string> = toolDefinitions.reduce(
  (acc, tool) => {
    acc[tool.id] = tool.label;
    return acc;
  },
  {} as Record<ToolId, string>,
);

function shortToolLabel(toolId: ToolId): string {
  return TOOL_LABELS[toolId] ?? toolId;
}

// Phase B2: user-resizable log panel. The height is persisted in
// localStorage so the user's preference survives reloads, and the panel
// is clamped to a sane range so it can neither disappear nor take over
// the whole main column. The default matches the previous hardcoded
// 240px max-height so first-run behavior is unchanged.
const LOG_PANEL_HEIGHT_STORAGE_KEY = "reliability-tools.log-panel-height";
const LOG_PANEL_HEIGHT_DEFAULT = 240;
const LOG_PANEL_HEIGHT_MIN = 120;
const LOG_PANEL_HEIGHT_MAX = 640;
const LOG_PANEL_KEYBOARD_STEP = 40;
// Fix F2: minimum vertical chrome we need to leave visible above the
// log panel (top bar + at least a sliver of tool content). Used to
// derive a dynamic upper bound for the panel height when the browser
// window is smaller than LOG_PANEL_HEIGHT_MAX + this.
const LOG_PANEL_MIN_CHROME = 200;
// Fix F2: debounce window resize so we don't re-clamp on every pixel.
const LOG_PANEL_RESIZE_DEBOUNCE_MS = 120;

function clampLogPanelHeight(value: number): number {
  if (!Number.isFinite(value)) {
    return LOG_PANEL_HEIGHT_DEFAULT;
  }
  // Compute a viewport-aware upper bound so the panel never overflows
  // the window on small screens. When window is unavailable (SSR /
  // jsdom before layout), fall back to the static maximum.
  let upperBound = LOG_PANEL_HEIGHT_MAX;
  if (typeof window !== "undefined" && window.innerHeight > 0) {
    upperBound = Math.min(
      LOG_PANEL_HEIGHT_MAX,
      Math.max(LOG_PANEL_HEIGHT_MIN, window.innerHeight - LOG_PANEL_MIN_CHROME),
    );
  }
  return Math.max(LOG_PANEL_HEIGHT_MIN, Math.min(upperBound, Math.round(value)));
}

function readStoredLogPanelHeight(): number {
  if (typeof window === "undefined" || !window.localStorage) {
    return LOG_PANEL_HEIGHT_DEFAULT;
  }
  try {
    const raw = window.localStorage.getItem(LOG_PANEL_HEIGHT_STORAGE_KEY);
    if (raw === null) {
      return LOG_PANEL_HEIGHT_DEFAULT;
    }
    const parsed = Number.parseInt(raw, 10);
    if (Number.isNaN(parsed)) {
      return LOG_PANEL_HEIGHT_DEFAULT;
    }
    return clampLogPanelHeight(parsed);
  } catch {
    return LOG_PANEL_HEIGHT_DEFAULT;
  }
}

function persistLogPanelHeight(value: number): void {
  if (typeof window === "undefined" || !window.localStorage) {
    return;
  }
  try {
    window.localStorage.setItem(LOG_PANEL_HEIGHT_STORAGE_KEY, String(value));
  } catch {
    // Storage quota exceeded or disabled — ignore silently.
  }
}

/**
 * Export the in-memory log entries to a downloadable .log file. Uses the
 * browser blob download API in both desktop and browser preview modes — the
 * canonical full log always lives on disk at `~/.reliability_tools/logs/`.
 * The export is a snapshot of the in-memory ring buffer for sharing.
 */
function exportEntriesToFile(entries: GlobalLogEntry[]) {
  const lines = entries.map((entry) => formatGlobalLogEntry(entry));
  const body = [
    `# Reliability Tools Desktop — Run Log Export`,
    `# Exported: ${new Date().toISOString()}`,
    `# Entries: ${entries.length}`,
    `# Note: in-memory snapshot. Full log lives at ~/.reliability_tools/logs/`,
    "",
    ...lines,
    "",
  ].join("\n");

  const blob = new Blob([body], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `reliability_tools_run_log_${Date.now()}.log`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

interface FilterCounts {
  total: number;
  errors: number;
  warnings: number;
}

function countSeverities(entries: GlobalLogEntry[]): FilterCounts {
  let errors = 0;
  let warnings = 0;
  for (const entry of entries) {
    if (entry.level === "error") {
      errors += 1;
    } else if (entry.level === "warning") {
      warnings += 1;
    }
  }
  return { total: entries.length, errors, warnings };
}

export function GlobalLogPanel() {
  const entries = useGlobalLogStore((state) => state.entries);
  const truncatedCount = useGlobalLogStore((state) => state.truncatedCount);
  const isVisible = useGlobalLogStore((state) => state.isVisible);
  const filterMode = useGlobalLogStore((state) => state.filterMode);
  const toggleVisible = useGlobalLogStore((state) => state.toggleVisible);
  const setFilterMode = useGlobalLogStore((state) => state.setFilterMode);
  const clear = useGlobalLogStore((state) => state.clear);
  const activeToolId = useShellStore((state) => state.activeToolId);

  const visibleEntries = useMemo(() => {
    if (filterMode === "active") {
      return entries.filter((entry) => entry.toolId === activeToolId);
    }
    return entries;
  }, [entries, filterMode, activeToolId]);

  const allCounts = useMemo(() => countSeverities(entries), [entries]);
  const activeCounts = useMemo(
    () => countSeverities(entries.filter((entry) => entry.toolId === activeToolId)),
    [entries, activeToolId],
  );

  const bodyRef = useRef<HTMLDivElement | null>(null);

  // Phase B2: user-resizable panel height, persisted to localStorage.
  // Lazy initializer reads from storage exactly once per mount so SSR
  // and test environments don't access window before it exists.
  const [panelHeight, setPanelHeight] = useState<number>(() => readStoredLogPanelHeight());
  const [isResizing, setIsResizing] = useState(false);
  const resizeStateRef = useRef<{ startY: number; startHeight: number } | null>(null);
  const pointerCaptureRef = useRef<{ target: HTMLElement; pointerId: number } | null>(null);

  const endResize = useCallback((finalHeight: number) => {
    const clamped = clampLogPanelHeight(finalHeight);
    persistLogPanelHeight(clamped);
    setPanelHeight(clamped);
    setIsResizing(false);
    resizeStateRef.current = null;
    if (pointerCaptureRef.current) {
      const { target, pointerId } = pointerCaptureRef.current;
      try {
        target.releasePointerCapture(pointerId);
      } catch {
        // Target may already have released the capture — ignore.
      }
      pointerCaptureRef.current = null;
    }
  }, []);

  const handleResizePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      // Only primary-button drags trigger a resize — right-click / middle
      // click fall through to the browser.
      if (event.button !== 0) {
        return;
      }
      event.preventDefault();
      resizeStateRef.current = { startY: event.clientY, startHeight: panelHeight };
      setIsResizing(true);
      const target = event.currentTarget;
      try {
        target.setPointerCapture(event.pointerId);
        pointerCaptureRef.current = { target, pointerId: event.pointerId };
      } catch {
        // If pointer capture is unavailable, fall back to document-level
        // listeners installed by the useEffect below.
        pointerCaptureRef.current = null;
      }
    },
    [panelHeight],
  );

  const handleResizePointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      // Gate on the ref rather than the isResizing state so a pointer
      // move that lands before React re-renders the drag-start still
      // updates the panel height.
      if (!resizeStateRef.current) {
        return;
      }
      // Dragging UP should INCREASE the panel height (the panel grows
      // toward the top of the screen), so we subtract the delta.
      const delta = event.clientY - resizeStateRef.current.startY;
      const next = clampLogPanelHeight(resizeStateRef.current.startHeight - delta);
      setPanelHeight(next);
    },
    [],
  );

  const handleResizePointerUp = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (!resizeStateRef.current) {
        return;
      }
      const delta = event.clientY - resizeStateRef.current.startY;
      endResize(resizeStateRef.current.startHeight - delta);
    },
    [endResize],
  );

  const handleResizePointerCancel = useCallback(() => {
    if (!resizeStateRef.current) {
      return;
    }
    // Snap back to the last committed panel height by re-clamping the
    // current panelHeight state.
    endResize(panelHeight);
  }, [endResize, panelHeight]);

  const handleResizeKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key === "ArrowUp") {
        event.preventDefault();
        const next = clampLogPanelHeight(panelHeight + LOG_PANEL_KEYBOARD_STEP);
        setPanelHeight(next);
        persistLogPanelHeight(next);
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        const next = clampLogPanelHeight(panelHeight - LOG_PANEL_KEYBOARD_STEP);
        setPanelHeight(next);
        persistLogPanelHeight(next);
      }
    },
    [panelHeight],
  );

  // Auto-scroll to bottom when new entries arrive (but only if the user
  // is already near the bottom — preserve their scroll position if they
  // have scrolled up to read older logs).
  useEffect(() => {
    if (!isVisible || !bodyRef.current) {
      return;
    }
    const el = bodyRef.current;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceFromBottom < 80) {
      el.scrollTop = el.scrollHeight;
    }
  }, [visibleEntries, isVisible]);

  // Fix F2: re-clamp the panel height whenever the viewport shrinks so a
  // persisted value from a larger window (e.g. user moved the window to
  // a small display, or halved the window height) gets trimmed instead
  // of clipping awkwardly. The clamp is a no-op when the height is
  // already within bounds, so re-clamping is cheap. We debounce resize
  // events to avoid doing the work on every intermediate pixel.
  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    let timer: ReturnType<typeof setTimeout> | null = null;
    const onResize = () => {
      if (timer !== null) {
        clearTimeout(timer);
      }
      timer = setTimeout(() => {
        timer = null;
        setPanelHeight((current) => {
          const clamped = clampLogPanelHeight(current);
          if (clamped !== current) {
            persistLogPanelHeight(clamped);
          }
          return clamped;
        });
      }, LOG_PANEL_RESIZE_DEBOUNCE_MS);
    };
    window.addEventListener("resize", onResize);
    return () => {
      if (timer !== null) {
        clearTimeout(timer);
      }
      window.removeEventListener("resize", onResize);
    };
  }, []);

  const totalLabel =
    visibleEntries.length === entries.length
      ? `${entries.length} ${entries.length === 1 ? "entry" : "entries"}`
      : `${visibleEntries.length} of ${entries.length}`;

  return (
    <section
      className="run-log-panel"
      data-expanded={isVisible}
      aria-label="Cross-tool run log"
      style={{ ["--log-panel-height" as string]: `${panelHeight}px` }}
    >
      {isVisible ? (
        <div
          className="run-log-panel__resize-handle"
          role="separator"
          aria-orientation="horizontal"
          aria-label="Resize log panel"
          aria-valuenow={panelHeight}
          aria-valuemin={LOG_PANEL_HEIGHT_MIN}
          aria-valuemax={LOG_PANEL_HEIGHT_MAX}
          tabIndex={0}
          data-resizing={isResizing ? "true" : undefined}
          onPointerDown={handleResizePointerDown}
          onPointerMove={handleResizePointerMove}
          onPointerUp={handleResizePointerUp}
          onPointerCancel={handleResizePointerCancel}
          onKeyDown={handleResizeKeyDown}
        />
      ) : null}
      <header className="run-log-panel__header">
        <button
          type="button"
          className="run-log-panel__toggle"
          onClick={toggleVisible}
          aria-expanded={isVisible}
          aria-controls="run-log-panel-body"
          title={isVisible ? "Hide run log" : "Show run log"}
        >
          {isVisible ? <CaretDown size={14} weight="bold" /> : <CaretUp size={14} weight="bold" />}
          <span className="run-log-panel__title">Run Log</span>
          <span className="run-log-panel__count">{totalLabel}</span>
          {truncatedCount > 0 ? (
            <span className="run-log-panel__truncated" title="Older entries dropped from the in-memory ring buffer">
              {truncatedCount} dropped
            </span>
          ) : null}
        </button>

        <div className="run-log-panel__controls">
          <FilterToggle
            filterMode={filterMode}
            onChange={setFilterMode}
            allCounts={allCounts}
            activeCounts={activeCounts}
          />
          <button
            type="button"
            className="run-log-panel__action"
            onClick={clear}
            disabled={entries.length === 0}
            title="Clear in-memory log buffer (disk log unaffected)"
          >
            <Trash size={14} weight="bold" />
            Clear
          </button>
          <button
            type="button"
            className="run-log-panel__action"
            onClick={() => void exportEntriesToFile(visibleEntries)}
            disabled={visibleEntries.length === 0}
            title="Export visible log entries to a file"
          >
            <DownloadSimple size={14} weight="bold" />
            Export
          </button>
        </div>
      </header>

      {isVisible ? (
        <div id="run-log-panel-body" className="run-log-panel__body" ref={bodyRef}>
          {visibleEntries.length === 0 ? (
            <p className="run-log-panel__empty">
              {entries.length === 0
                ? "No log entries yet. Run a tool to start streaming logs here."
                : `No entries match the current filter (${shortToolLabel(activeToolId)} only).`}
            </p>
          ) : (
            visibleEntries.map((entry) => (
              <div
                key={entry.id}
                className={`run-log-panel__line run-log-panel__line--${entry.level}`}
              >
                <span className="run-log-panel__time">{entry.timestamp.slice(11, 19)}</span>
                <span className={`run-log-panel__level run-log-panel__level--${entry.level}`}>
                  {entry.level.toUpperCase()}
                </span>
                <span className="run-log-panel__tool" title={shortToolLabel(entry.toolId)}>
                  {shortToolLabel(entry.toolId)}
                </span>
                <span className="run-log-panel__text">{entry.line}</span>
              </div>
            ))
          )}
        </div>
      ) : null}
    </section>
  );
}

interface FilterToggleProps {
  filterMode: GlobalLogFilterMode;
  onChange: (mode: GlobalLogFilterMode) => void;
  allCounts: FilterCounts;
  activeCounts: FilterCounts;
}

function CountBreakdown({ counts }: { counts: FilterCounts }) {
  const segments: Array<{ key: string; modifier: "error" | "warn" | "info"; label: string }> = [];
  if (counts.errors > 0) {
    segments.push({
      key: "error",
      modifier: "error",
      label: `${counts.errors} error${counts.errors === 1 ? "" : "s"}`,
    });
  }
  if (counts.warnings > 0) {
    segments.push({
      key: "warning",
      modifier: "warn",
      label: `${counts.warnings} warning${counts.warnings === 1 ? "" : "s"}`,
    });
  }
  return (
    <span className="global-log-panel__filter-counts">
      <span className="global-log-panel__filter-total">{counts.total}</span>
      {segments.map((segment) => (
        <span key={segment.key} className="global-log-panel__filter-count">
          <span
            className={`global-log-panel__filter-count-dot global-log-panel__filter-count-dot--${segment.modifier}`}
            aria-hidden="true"
          />
          {segment.label}
        </span>
      ))}
    </span>
  );
}

function FilterToggle({ filterMode, onChange, allCounts, activeCounts }: FilterToggleProps) {
  return (
    <div className="run-log-panel__filter" role="group" aria-label="Filter log entries">
      <button
        type="button"
        className="run-log-panel__filter-option"
        data-active={filterMode === "all"}
        onClick={() => onChange("all")}
      >
        <span>All tools</span>
        <CountBreakdown counts={allCounts} />
      </button>
      <button
        type="button"
        className="run-log-panel__filter-option"
        data-active={filterMode === "active"}
        onClick={() => onChange("active")}
      >
        <span>Current only</span>
        <CountBreakdown counts={activeCounts} />
      </button>
    </div>
  );
}
