import { Table } from "@phosphor-icons/react";
import { EmptyState } from "./primitives/EmptyState";
import { useCopyToClipboard } from "../shared/hooks/useCopyToClipboard";
import { useNotificationStore } from "../stores/notificationStore";
import { useShellStore } from "../stores/shellStore";
import type { AnalysisContextCard, PreviewRow, ValidationMessage, ValidationSeverity } from "../app/types";

/* v2 N8: severity renders as a 6px dot, not a filled chip. */
const SEVERITY_TONE: Record<ValidationSeverity, string | undefined> = {
  error: "bad",
  warning: "warn",
  info: undefined,
};

interface ValidationPreviewProps {
  validations: ValidationMessage[];
  previewRows: PreviewRow[];
  analysisCards?: AnalysisContextCard[];
}

/**
 * Escape a single field per RFC 4180. Wraps the field in double quotes and
 * doubles any embedded quote when the field contains a comma, quote, CR or
 * LF; otherwise returns the field unchanged.
 */
function escapeCsvField(value: string): string {
  if (value === "") {
    return "";
  }
  if (/[",\r\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function buildTsv(validations: ValidationMessage[]): string {
  const header = ["Severity", "Area", "Title", "Detail"].join("\t");
  const rows = validations.map((message) =>
    [message.severity, message.area, message.title, message.detail]
      .map((field) => String(field ?? "").replace(/[\t\r\n]+/g, " "))
      .join("\t"),
  );
  return [header, ...rows].join("\n");
}

function buildCsv(validations: ValidationMessage[]): string {
  const header = ["Severity", "Area", "Title", "Detail"].map(escapeCsvField).join(",");
  const rows = validations.map((message) =>
    [message.severity, message.area, message.title, message.detail]
      .map((field) => escapeCsvField(String(field ?? "")))
      .join(","),
  );
  return [header, ...rows].join("\r\n");
}

function downloadBlob(filename: string, body: string, mimeType: string) {
  if (typeof document === "undefined") {
    return;
  }
  const blob = new Blob([body], { type: `${mimeType};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export function ValidationPreview({
  validations,
  previewRows,
  analysisCards = [],
}: ValidationPreviewProps) {
  const { copy } = useCopyToClipboard();
  const pushNotification = useNotificationStore((state) => state.push);
  const setContextOpen = useShellStore((state) => state.setContextOpen);

  const issues = validations.filter((message) => message.severity !== "info");
  const issueCount = issues.length;
  const hasIssues = issueCount > 0;
  const errorCount = issues.filter((message) => message.severity === "error").length;
  const warningCount = issues.filter((message) => message.severity === "warning").length;

  const handleCopyIssues = async () => {
    if (!hasIssues) {
      return;
    }
    const tsv = buildTsv(issues);
    const ok = await copy(tsv);
    pushNotification({
      tone: ok ? "success" : "error",
      title: ok ? "Issues copied" : "Copy failed",
      detail: ok
        ? `${issueCount} issue${issueCount === 1 ? "" : "s"} copied as TSV — paste into Excel or a bug report.`
        : "Clipboard write failed.",
    });
  };

  const handleExportCsv = () => {
    if (!hasIssues) {
      return;
    }
    const csv = buildCsv(issues);
    const filename = `validation_issues_${Date.now()}.csv`;
    downloadBlob(filename, csv, "text/csv");
    pushNotification({
      tone: "success",
      title: "CSV exported",
      detail: `${issueCount} issue${issueCount === 1 ? "" : "s"} written to ${filename}.`,
    });
  };

  return (
    <div className="validation-layout">
      {analysisCards.length > 0 ? (
        <div className="analysis-card-list">
          {analysisCards.map((card) => (
            <article key={card.id} className="analysis-card">
              <p className="eyebrow">{card.eyebrow}</p>
              <strong>{card.title}</strong>
              <p>{card.detail}</p>
              <div className="analysis-card__metrics">
                {/* v2 N8: metrics are category data → mono text, not blue
                    chips. True warnings keep a dot + warning-colored note. */}
                {card.metrics.length > 0 ? (
                  <span className="analysis-card__metric-text">{card.metrics.join(" · ")}</span>
                ) : null}
                {card.warning ? (
                  <span className="analysis-card__warning">
                    <i className="dot" data-tone="warn" aria-hidden="true" />
                    {card.warning}
                  </span>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      ) : null}

      {hasIssues ? (
        <div className="validation-preview__toolbar" role="group" aria-label="Validation export actions">
          <span className="validation-preview__toolbar-count">
            <span className="num">{issueCount}</span> issue{issueCount === 1 ? "" : "s"}
          </span>
          {errorCount > 0 ? (
            <span className="badge-state badge-state--bad" title={`${errorCount} error${errorCount === 1 ? "" : "s"}`}>
              {errorCount}
            </span>
          ) : null}
          {warningCount > 0 ? (
            <span className="badge-state badge-state--warn" title={`${warningCount} warning${warningCount === 1 ? "" : "s"}`}>
              {warningCount}
            </span>
          ) : null}
          <button
            type="button"
            className="validation-preview__export-button"
            onClick={() => {
              void handleCopyIssues();
            }}
          >
            Copy issues
          </button>
          <button
            type="button"
            className="validation-preview__export-button"
            onClick={handleExportCsv}
          >
            Export CSV
          </button>
        </div>
      ) : null}

      <div className="validation-list">
        {validations.map((message) => (
          <article key={message.id} className="validation-card" data-severity={message.severity}>
            <i className="dot" data-tone={SEVERITY_TONE[message.severity]} aria-hidden="true" />
            <div className="validation-card__body">
              <strong>{message.title}</strong>
              <p>{message.detail}</p>
            </div>
            <span className="validation-card__area">{message.area}</span>
          </article>
        ))}
      </div>

      {previewRows.length > 0 ? (
        <>
          {/* Two columns only — four text columns hard-clipped mid-word in
              the ~430px side panel. The full row (local / next-higher
              effect) lives in the Review drawer, one click away. */}
          <div className="table-shell">
            <table className="preview-table preview-table--compact">
              <thead>
                <tr>
                  <th>RefDes</th>
                  <th>Failure mode</th>
                </tr>
              </thead>
              <tbody>
                {previewRows.map((row) => (
                  <tr key={row.id}>
                    <td>{row.refdes}</td>
                    <td title={`${row.failureMode} — ${row.localEffect}`}>{row.failureMode}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button
            type="button"
            className="validation-layout__full-preview"
            onClick={() => setContextOpen(true)}
          >
            Open full preview
          </button>
        </>
      ) : (
        <EmptyState
          compact
          icon={Table}
          headline="No preview rows yet"
          body="Load inputs and run validation to see output rows here."
        />
      )}
    </div>
  );
}
