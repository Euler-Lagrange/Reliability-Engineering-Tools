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
          {/* v2 N9: compact card — title + one summary line. The LEAN/
              BALANCED badge is deleted (its meaning folds into the
              summary); selection reads as border + tint + corner check. */}
          <span className="choice-card__check" aria-hidden="true">
            ✓
          </span>
          <h3>{workflow.title}</h3>
          <p>{workflow.summary}</p>
        </button>
      ))}
    </div>
  );
}
