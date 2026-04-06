import type { DemoScenario } from "../app/types";

interface ScenarioRailProps {
  scenarios: DemoScenario[];
  selectedScenarioId: string;
  onSelect: (scenarioId: string) => void;
  activeDescription: string;
}

export function ScenarioRail({
  scenarios,
  selectedScenarioId,
  onSelect,
  activeDescription,
}: ScenarioRailProps) {
  return (
    <section className="scenario-rail">
      <div className="scenario-rail__header">
        <div>
          <p className="eyebrow">Scenario</p>
          <h2>Fixture states</h2>
        </div>
        <p>{activeDescription}</p>
      </div>

      <div className="scenario-rail__list" role="tablist" aria-label="Demo scenarios">
        {scenarios.map((scenario, index) => (
          <button
            key={scenario.id}
            className="scenario-pill"
            data-active={scenario.id === selectedScenarioId}
            onClick={() => onSelect(scenario.id)}
            role="tab"
            aria-selected={scenario.id === selectedScenarioId}
          >
            <span className="scenario-pill__label">{scenario.label}</span>
            <span className="scenario-pill__meta">S{String(index + 1).padStart(2, "0")}</span>
          </button>
        ))}
      </div>
    </section>
  );
}
