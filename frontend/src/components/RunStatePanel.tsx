import type { RunEvent, RunMode, RunResult } from "../app/types";

interface RunStatePanelProps {
  runMode: RunMode;
  progress: number;
  timeline: RunEvent[];
  result: RunResult | null;
  onStart: () => void;
  onCancel: () => void;
  cancelledNotice: string | null;
  cancelPending: boolean;
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
}

export function RunStatePanel({
  runMode,
  progress,
  timeline,
  result,
  onStart,
  onCancel,
  cancelledNotice,
  cancelPending,
  logLines = [],
  truncatedLogCount = 0,
  startLabel = "Start demo run",
  runId = null,
  statusMessage = null,
  errorCode = null,
  errorTraceback = null,
}: RunStatePanelProps) {
  const isBusy = runMode === "starting" || runMode === "running" || runMode === "cancelling";
  const canCancel = runMode === "starting" || runMode === "running";

  return (
    <div className="run-state">
      <div className="run-state__controls">
        <button type="button" className="primary-button" onClick={onStart} disabled={isBusy}>
          {isBusy ? (runMode === "cancelling" ? "Cancelling..." : "Running...") : startLabel}
        </button>
        <button type="button" className="ghost-button" onClick={onCancel} disabled={!canCancel}>
          {cancelPending ? "Confirm cancel" : "Cancel"}
        </button>
      </div>

      {runId || statusMessage ? (
        <div className="analysis-summary">
          {runId ? <strong>Run ID: {runId}</strong> : null}
          {statusMessage ? <p>{statusMessage}</p> : null}
        </div>
      ) : null}

      <div
        className="progress-shell"
        role="progressbar"
        aria-label="Run progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress}
      >
        <div className="progress-shell__bar" style={{ width: `${progress}%` }} />
      </div>

      <div className="timeline">
        {timeline.map((event) => (
          <article key={event.id} className="timeline__item" data-status={event.status}>
            <div className="timeline__dot" />
            <div>
              <p className="timeline__title">{event.title}</p>
              <p className="timeline__detail">{event.detail}</p>
            </div>
            <span className={`status-chip status-chip--${event.status}`}>{event.status}</span>
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
            <span>{logLines.length} entries</span>
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
            <span className={`status-chip status-chip--${result.status}`}>{result.status}</span>
            <p>{result.outputFile}</p>
          </div>
          <div className="run-result__body">
            <h3>{result.title}</h3>
            <p>{result.summary}</p>
          </div>
          <div className="run-result__metrics">
            <div className="run-result__metric">
              <span>Primary</span>
              <strong>{result.primaryMetric}</strong>
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
