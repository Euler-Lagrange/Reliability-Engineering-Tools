import { Table } from "@phosphor-icons/react";
import { EmptyState } from "./primitives/EmptyState";
import { useCopyToClipboard } from "../shared/hooks/useCopyToClipboard";
import { useNotificationStore } from "../stores/notificationStore";
import { useShellStore } from "../stores/shellStore";
import type { AnalysisContextCard, PreviewRow, ValidationMessage } from "../app/types";

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

  const issueCount = validations.length;
  const hasIssues = issueCount > 0;

  const handleCopyIssues = async () => {
    if (!hasIssues) {
      return;
    }
    const tsv = buildTsv(validations);
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
    const csv = buildCsv(validations);
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
                {card.metrics.map((metric) => (
                  <span key={metric} className="status-chip status-chip--info">
                    {metric}
                  </span>
                ))}
                {card.warning ? (
                  <span className="status-chip status-chip--warning">
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
            {issueCount} issue{issueCount === 1 ? "" : "s"}
          </span>
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
            <div className="validation-card__header">
              <span className={`status-chip status-chip--${message.severity}`}>{message.severity}</span>
              <span className="validation-card__area">{message.area}</span>
            </div>
            <div className="validation-card__body">
              <strong>{message.title}</strong>
              <p>{message.detail}</p>
            </div>
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
            className="ghost-button validation-layout__full-preview"
            onClick={() => setContextOpen(true)}
          >
            Full preview
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
