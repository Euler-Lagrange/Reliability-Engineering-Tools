import type { WorkflowId, WorkflowOption } from "../app/types";

interface WorkflowSelectorProps {
  workflows: WorkflowOption[];
  selectedWorkflowId: WorkflowId;
  onSelect: (workflowId: WorkflowId) => void;
}

export function WorkflowSelector({
  workflows,
  selectedWorkflowId,
  onSelect,
}: WorkflowSelectorProps) {
  return (
    <div className="card-grid">
      {workflows.map((workflow) => (
        <button
          key={workflow.id}
          className="choice-card"
          data-active={workflow.id === selectedWorkflowId}
          data-selected={workflow.id === selectedWorkflowId}
          onClick={() => onSelect(workflow.id)}
          type="button"
        >
          <div className="choice-card__header">
            <span className="choice-card__eyebrow">{workflow.eyebrow}</span>
            <span className="choice-card__badge">{workflow.badge}</span>
          </div>
          <h3>{workflow.title}</h3>
          <p>{workflow.summary}</p>
        </button>
      ))}
    </div>
  );
}
