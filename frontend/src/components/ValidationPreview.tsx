import type { AnalysisContextCard, PreviewRow, ValidationMessage } from "../app/types";

interface ValidationPreviewProps {
  validations: ValidationMessage[];
  previewRows: PreviewRow[];
  analysisCards?: AnalysisContextCard[];
}

export function ValidationPreview({
  validations,
  previewRows,
  analysisCards = [],
}: ValidationPreviewProps) {
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
              </div>
            </article>
          ))}
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

      <div className="table-shell">
        <table className="preview-table">
          <thead>
            <tr>
              <th>RefDes</th>
              <th>Failure mode</th>
              <th>Local effect</th>
              <th>Next higher effect</th>
            </tr>
          </thead>
          <tbody>
            {previewRows.map((row) => (
              <tr key={row.id}>
                <td>{row.refdes}</td>
                <td>{row.failureMode}</td>
                <td>{row.localEffect}</td>
                <td>{row.nextHigherEffect}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
