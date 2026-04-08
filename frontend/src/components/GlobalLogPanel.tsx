import { useEffect, useMemo, useRef } from "react";
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

  const bodyRef = useRef<HTMLDivElement | null>(null);

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

  const totalLabel =
    visibleEntries.length === entries.length
      ? `${entries.length} ${entries.length === 1 ? "entry" : "entries"}`
      : `${visibleEntries.length} of ${entries.length}`;

  return (
    <section
      className="run-log-panel"
      data-expanded={isVisible}
      aria-label="Cross-tool run log"
    >
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
          <FilterToggle filterMode={filterMode} onChange={setFilterMode} />
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
}

function FilterToggle({ filterMode, onChange }: FilterToggleProps) {
  return (
    <div className="run-log-panel__filter" role="group" aria-label="Filter log entries">
      <button
        type="button"
        className="run-log-panel__filter-option"
        data-active={filterMode === "all"}
        onClick={() => onChange("all")}
      >
        All tools
      </button>
      <button
        type="button"
        className="run-log-panel__filter-option"
        data-active={filterMode === "active"}
        onClick={() => onChange("active")}
      >
        Current only
      </button>
    </div>
  );
}
