import type { RunEvent, RunMode, RunResult } from "../app/types";
import { LIVE_PHASES } from "../shared/backend/runLifecycle";
import { OPEN_FOLDER_LABEL } from "../shared/backend/fileManager";
import { HoldButton } from "./primitives/HoldButton";

interface RunStatePanelProps {
  runMode: RunMode;
  progress: number;
  timeline: RunEvent[];
  result: RunResult | null;
  onStart: () => void;
  onCancel: () => void;
  cancelledNotice: string | null;
  logLines?: string[];
  /** Number of log lines that were dropped from the start of the buffer. */
  truncatedLogCount?: number;
  startLabel?: string;
  runId?: string | null;
  statusMessage?: string | null;
  /** Stable error code from the backend (typically the exception type). */
  errorCode?: string | null;
  /** Full Python traceback for the error, if available. */
  errorTraceback?: string | null;
  /**
   * Known completion percentage 0..100. When undefined (and the run is
   * active) the progress bar switches to an indeterminate sliding stripe
   * with a "Working…" caption instead of a static empty bar.
   */
  percent?: number;
  /** Optional estimated seconds remaining hint. */
  etaSeconds?: number;
  /** Optional human-readable stage label, e.g. "Parsing BOM". */
  stageLabel?: string;
  /**
   * Extra gate that disables the Start button on top of the usual
   * busy-state logic. When set, the caller is declaring that the tool
   * cannot legally kick off a run (e.g. a required config field is
   * empty). Paired with {@link startDisabledReason} so the UI can
   * surface *why* the button is unreachable.
   */
  startDisabled?: boolean;
  /** Caption shown below the Start button when {@link startDisabled} is true. */
  startDisabledReason?: string;
  onRevealOutput?: (path: string) => void;
}

/** Sentence-case a status enum word ("completed" → "Completed"). */
function statusWord(status: string): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function formatEta(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return "";
  }
  if (seconds < 60) {
    return `~${Math.round(seconds)}s remaining`;
  }
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  if (remainder === 0) {
    return `~${minutes}m remaining`;
  }
  return `~${minutes}m ${remainder}s remaining`;
}

export function RunStatePanel({
  runMode,
  progress,
  timeline,
  result,
  onStart,
  onCancel,
  cancelledNotice,
  logLines = [],
  truncatedLogCount = 0,
  startLabel = "Start demo run",
  runId = null,
  statusMessage = null,
  errorCode = null,
  errorTraceback = null,
  percent,
  etaSeconds,
  stageLabel,
  startDisabled = false,
  startDisabledReason,
  onRevealOutput,
}: RunStatePanelProps) {
  const isBusy = LIVE_PHASES.some((phase) => phase === runMode);
  const canCancel = isBusy && runMode !== "cancelling";
  const isActiveRun = canCancel;
  const startButtonDisabled = isBusy || startDisabled;
  const showStartDisabledReason =
    !isBusy && startDisabled && typeof startDisabledReason === "string" && startDisabledReason.length > 0;

  // Determinate vs indeterminate progress rendering.
  // When percent is undefined AND the run is active, we show the sliding
  // indeterminate stripe. Otherwise we fall back to the legacy numeric
  // progress prop.
  const hasKnownPercent = typeof percent === "number" && Number.isFinite(percent);
  const indeterminate = !hasKnownPercent && isActiveRun;
  const displayPercent = hasKnownPercent ? Math.max(0, Math.min(100, percent as number)) : progress;

  // Percent and ETA are instrument readouts → .num (v2 N4); the stage
  // label is prose and stays sans.
  const metaParts: { text: string; numeric?: boolean }[] = [];
  if (hasKnownPercent) {
    metaParts.push({ text: `${Math.round(displayPercent)}%`, numeric: true });
  } else if (indeterminate) {
    metaParts.push({ text: "Working…" });
  }
  if (typeof etaSeconds === "number") {
    const etaText = formatEta(etaSeconds);
    if (etaText) {
      metaParts.push({ text: etaText, numeric: true });
    }
  }
  if (stageLabel) {
    metaParts.push({ text: stageLabel });
  }
  const showMeta = metaParts.length > 0;

  const progressShellClassName = indeterminate
    ? "progress-shell progress-shell--indeterminate"
    : "progress-shell";
  const barStyle = indeterminate ? undefined : { width: `${displayPercent}%` };

  return (
    <div className="run-state">
      <div className="run-state__controls">
        <button
          type="button"
          className="primary-button"
          onClick={onStart}
          disabled={startButtonDisabled}
          aria-describedby={showStartDisabledReason ? "run-state-start-disabled-reason" : undefined}
        >
          {isBusy ? (runMode === "cancelling" ? "Cancelling..." : "Running...") : startLabel}
        </button>
        <HoldButton
          label="Cancel"
          holdingLabel="Hold to cancel run..."
          variant="danger"
          disabled={!canCancel}
          onConfirm={onCancel}
        />
      </div>
      {showStartDisabledReason ? (
        <p className="run-state__start-disabled-reason" id="run-state-start-disabled-reason">
          {startDisabledReason}
        </p>
      ) : null}

      {runId || statusMessage ? (
        <div className="analysis-summary">
          {runId ? (
            <strong>
              Run ID: <span className="num">{runId}</span>
            </strong>
          ) : null}
          {statusMessage ? <p>{statusMessage}</p> : null}
        </div>
      ) : null}

      <div
        className={progressShellClassName}
        role="progressbar"
        aria-label="Run progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={indeterminate ? undefined : Math.round(displayPercent)}
      >
        <div className="progress-shell__bar" style={barStyle} />
      </div>
      {showMeta ? (
        <p className="run-state__progress-meta" aria-live="polite">
          {metaParts.map((part, index) => (
            <span key={`${index}-${part.text}`}>
              {index > 0 ? (
                <span className="run-state__progress-meta-dot" aria-hidden="true">
                  {" • "}
                </span>
              ) : null}
              <span className={part.numeric ? "num" : undefined}>{part.text}</span>
            </span>
          ))}
        </p>
      ) : null}

      <div className="timeline">
        {timeline.map((event) => (
          <article key={event.id} className="timeline__item" data-status={event.status}>
            <div className="timeline__dot" />
            <div>
              <p className="timeline__title">{event.title}</p>
              <p className="timeline__detail">{event.detail}</p>
            </div>
            <span className="state-word" data-status={event.status}>
              <i
                className="dot"
                data-tone={event.status === "completed" ? "ok" : event.status === "active" ? "acc" : undefined}
                aria-hidden="true"
              />
              {statusWord(event.status)}
            </span>
          </article>
        ))}
      </div>

      {cancelledNotice ? (
        <p className="run-note" aria-live="polite">
          {cancelledNotice}
        </p>
      ) : null}

      {logLines.length > 0 ? (
        <section className="execution-log" aria-label="Execution log">
          <div className="execution-log__header">
            <strong>Execution log</strong>
            <span>
              <span className="num">{logLines.length}</span> entries
            </span>
          </div>
          {truncatedLogCount > 0 ? (
            <p
              className="execution-log__truncation"
              aria-live="polite"
              title="Earlier lines were dropped from the in-memory buffer; the full log is in ~/.reliability_tools/logs/"
            >
              … {truncatedLogCount} earlier line{truncatedLogCount === 1 ? "" : "s"} hidden — full log in ~/.reliability_tools/logs/
            </p>
          ) : null}
          <div className="execution-log__body">
            {logLines.map((line, index) => (
              <div key={`${index}-${line}`} className="execution-log__line">
                {line}
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {(errorCode || errorTraceback) && runMode === "failure" ? (
        <section className="run-error" aria-label="Run failure details">
          <div className="run-error__header">
            <strong>Backend error</strong>
            {errorCode ? <code className="run-error__code">{errorCode}</code> : null}
          </div>
          {errorTraceback ? (
            <details className="run-error__details">
              <summary>Show traceback</summary>
              <pre className="run-error__traceback">{errorTraceback}</pre>
              <button
                type="button"
                className="ghost-button run-error__copy"
                onClick={() => {
                  void navigator.clipboard?.writeText(errorTraceback);
                }}
              >
                Copy traceback
              </button>
            </details>
          ) : null}
        </section>
      ) : null}

      {result ? (
        <article className="run-result" data-status={result.status}>
          <div className="run-result__header">
            <span className="state-word" data-status={result.status}>
              <i
                className="dot"
                data-tone={result.status === "success" ? "ok" : "bad"}
                aria-hidden="true"
              />
              {statusWord(result.status)}
            </span>
            <p>{result.outputFile}</p>
          </div>
          <div className="run-result__body">
            <h3>{result.title}</h3>
            <p>{result.summary}</p>
            {result.outputFile && onRevealOutput ? (
              <button
                type="button"
                className="ghost-button"
                onClick={() => onRevealOutput(result.outputFile)}
              >
                {OPEN_FOLDER_LABEL}
              </button>
            ) : null}
          </div>
          <div className="run-result__metrics">
            <div className="run-result__metric">
              <span>Primary</span>
              <strong className="hero-metric">{result.primaryMetric}</strong>
            </div>
            <div className="run-result__metric">
              <span>Secondary</span>
              <strong>{result.secondaryMetric}</strong>
            </div>
          </div>
          <ul className="run-result__notes">
            {result.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </article>
      ) : null}
    </div>
  );
}
