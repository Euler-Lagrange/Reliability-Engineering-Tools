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

      {/*
        These pills toggle between fixture scenarios. They are NOT ARIA
        tabs because no `tabpanel` is rendered — the tablist/tab roles were
        misleading to assistive tech. Using `aria-pressed` on plain buttons
        expresses the pressed/unpressed toggle state correctly.
      */}
      <div className="scenario-rail__list" role="group" aria-label="Demo scenarios">
        {scenarios.map((scenario, index) => (
          <button
            key={scenario.id}
            type="button"
            className="scenario-pill"
            data-active={scenario.id === selectedScenarioId}
            onClick={() => onSelect(scenario.id)}
            aria-pressed={scenario.id === selectedScenarioId}
          >
            <span className="scenario-pill__label">{scenario.label}</span>
            <span className="scenario-pill__meta">S{String(index + 1).padStart(2, "0")}</span>
          </button>
        ))}
      </div>
    </section>
  );
}
