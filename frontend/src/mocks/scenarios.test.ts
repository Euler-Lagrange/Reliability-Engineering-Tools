import { describe, expect, it } from "vitest";

import type { DemoScenario } from "../app/types";
import {
  bomCompareDemoScenarios,
  demoScenarios,
  failureRateDemoScenarios,
  refdesDemoScenarios,
} from "./scenarios";

// Tier-3 #28 / Wiring Invariant #4: every workflow needs a DemoScenario whose
// inputs cover that workflow's roles. A missing scenario or an empty inputs
// array rendered Custom Compare with zero file slots. This is the registry-wide
// guard that was missing.
const scenarioGroups: Array<[string, DemoScenario[]]> = [
  ["FMEA", demoScenarios],
  ["BOM Compare", bomCompareDemoScenarios],
  ["Failure Rate", failureRateDemoScenarios],
  ["RefDes Extractor", refdesDemoScenarios],
];

describe("demo scenario completeness", () => {
  it("every scenario across every tool exposes at least one fully-specified file slot", () => {
    for (const [tool, scenarios] of scenarioGroups) {
      expect(scenarios.length, `${tool} has no demo scenarios`).toBeGreaterThan(0);
      for (const scenario of scenarios) {
        // Zero inputs renders a tool with no upload rows — the exact regression
        // that shipped Custom Compare with no file slots.
        expect(
          scenario.inputs.length,
          `${tool} scenario '${scenario.workflowId}' has zero file slots`,
        ).toBeGreaterThan(0);
        for (const input of scenario.inputs) {
          // A slot needs a role + label to render; the path may be empty for an
          // optional/pristine slot (e.g. RefDes' optional pinlist), which is a
          // valid unfilled slot, not a zero-slots defect.
          expect(input.role, `${tool}/${scenario.workflowId} input missing role`).toBeTruthy();
          expect(input.label, `${tool}/${scenario.workflowId} input missing label`).toBeTruthy();
          expect(
            typeof input.path,
            `${tool}/${scenario.workflowId} input path not a string`,
          ).toBe("string");
        }
      }
    }
  });

  it("BOM Compare custom workflow keeps its two file slots", () => {
    // The specific regression: Custom Compare needs bomA + bomB, not a single
    // grouping/bom pair. A missing second slot left the user unable to run it.
    const custom = bomCompareDemoScenarios.find(
      (scenario) => scenario.workflowId === "bom_compare_custom",
    );
    expect(custom).toBeDefined();
    expect(custom?.inputs.length).toBe(2);
  });
});
