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
    <div className="card-grid" role="group" aria-label="Output strategy">
      {strategies.map((strategy) => (
        <button
          key={strategy.id}
          className="choice-card choice-card--strategy"
          data-selected={strategy.id === selectedStrategyId}
          aria-pressed={strategy.id === selectedStrategyId}
          onClick={() => onSelect(strategy.id)}
          type="button"
        >
          {/* The badge IS the eyebrow — a literal "Output strategy" eyebrow
              on every card tripled the phrase within one viewport (section
              label + two cards). */}
          <div className="choice-card__header">
            <span className="choice-card__eyebrow">{strategy.badge}</span>
          </div>
          <h3>{strategy.title}</h3>
          <p>{strategy.summary}</p>
        </button>
      ))}
    </div>
  );
}
