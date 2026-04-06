import type { OutputStrategy, OutputStrategyId } from "../app/types";

interface StrategySelectorProps {
  strategies: OutputStrategy[];
  selectedStrategyId: OutputStrategyId;
  onSelect: (strategyId: OutputStrategyId) => void;
}

export function StrategySelector({
  strategies,
  selectedStrategyId,
  onSelect,
}: StrategySelectorProps) {
  return (
    <div className="card-grid">
      {strategies.map((strategy) => (
        <button
          key={strategy.id}
          className="choice-card choice-card--strategy"
          data-active={strategy.id === selectedStrategyId}
          onClick={() => onSelect(strategy.id)}
          type="button"
        >
          <div className="choice-card__header">
            <span className="choice-card__eyebrow">Output strategy</span>
            <span className="choice-card__badge">{strategy.badge}</span>
          </div>
          <h3>{strategy.title}</h3>
          <p>{strategy.summary}</p>
        </button>
      ))}
    </div>
  );
}
