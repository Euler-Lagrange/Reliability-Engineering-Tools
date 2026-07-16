import type { OutputStrategy, OutputStrategyId } from "../app/types";

interface StrategySelectorProps {
  strategies: OutputStrategy[];
  selectedStrategyId: OutputStrategyId;
  onSelect: (strategyId: OutputStrategyId) => void;
  disabled?: boolean;
}

export function StrategySelector({
  strategies,
  selectedStrategyId,
  onSelect,
  disabled = false,
}: StrategySelectorProps) {
  // v2 N9: output strategy is a value picker, not a decision that earns
  // card real estate — it renders as a neutral segmented control. The
  // summary copy rides each segment's tooltip; selection color stays
  // reserved for the workflow choice.
  return (
    <div className="toggle-chip-group" role="group" aria-label="Output strategy">
      {strategies.map((strategy) => (
        <button
          key={strategy.id}
          className="toggle-chip"
          data-selected={strategy.id === selectedStrategyId}
          aria-pressed={strategy.id === selectedStrategyId}
          aria-disabled={disabled}
          disabled={disabled}
          title={
            disabled
              ? "Output strategy cannot be changed while this tool has an active run."
              : strategy.summary
          }
          onClick={() => onSelect(strategy.id)}
          type="button"
        >
          {strategy.title}
        </button>
      ))}
    </div>
  );
}
