import type { WorkflowId, WorkflowOption } from "../app/types";

interface WorkflowSelectorProps {
  workflows: WorkflowOption[];
  selectedWorkflowId: WorkflowId;
  onSelect: (workflowId: WorkflowId) => void;
  disabled?: boolean;
}

export function WorkflowSelector({
  workflows,
  selectedWorkflowId,
  onSelect,
  disabled = false,
}: WorkflowSelectorProps) {
  return (
    <div className="card-grid" role="group" aria-label="Workflow">
      {workflows.map((workflow) => (
        <button
          key={workflow.id}
          className="choice-card"
          data-selected={workflow.id === selectedWorkflowId}
          data-disabled={disabled || undefined}
          aria-pressed={workflow.id === selectedWorkflowId}
          aria-disabled={disabled}
          disabled={disabled}
          title={
            disabled
              ? "Workflow cannot be changed while this tool has an active run."
              : undefined
          }
          onClick={() => onSelect(workflow.id)}
          type="button"
        >
          <div className="choice-card__header">
            <span className="choice-card__eyebrow">{workflow.eyebrow}</span>
            <span className="choice-card__badge" title={workflow.badgeHint}>
              {workflow.badge}
            </span>
          </div>
          <h3>{workflow.title}</h3>
          <p>{workflow.summary}</p>
        </button>
      ))}
    </div>
  );
}
