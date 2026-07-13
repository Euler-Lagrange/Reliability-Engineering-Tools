import { lazy, type LazyExoticComponent, type ComponentType } from "react";
import type { Icon } from "@phosphor-icons/react";
import {
  Cpu,
  Faders,
  GitDiff,
  Pulse,
  TreeStructure,
} from "@phosphor-icons/react";
import {
  bomCompareWorkflowOptions,
  failureRateDemoScenarios,
  refdesDemoScenarios,
  workflowOptions,
} from "../mocks/scenarios";
import type { ToolId } from "../stores/shellStore";
import type { WorkflowId } from "./types";

const FmeaTool = lazy(() =>
  import("../features/fmea/FmeaTool").then((module) => ({ default: module.FmeaTool })),
);
const BomCompareTool = lazy(() =>
  import("../features/bom-compare/BomCompareTool").then((module) => ({
    default: module.BomCompareTool,
  })),
);
const FailureRateTool = lazy(() =>
  import("../features/failure-rate/FailureRateTool").then((module) => ({
    default: module.FailureRateTool,
  })),
);
const RefDesTool = lazy(() =>
  import("../features/refdes-extractor/RefDesExtractorTool").then((module) => ({
    default: module.RefDesExtractorTool,
  })),
);
const SettingsTool = lazy(() =>
  import("../features/settings/SettingsTool").then((module) => ({
    default: module.SettingsTool,
  })),
);

export interface ToolDefinition {
  id: ToolId;
  label: string;
  eyebrow: string;
  description: string;
  icon: Icon;
  status: "active" | "placeholder";
  workflowIds: readonly WorkflowId[];
  component: LazyExoticComponent<ComponentType>;
}

export const toolDefinitions: ToolDefinition[] = [
  {
    id: "dark_star_fmea",
    label: "FMEA Generator",
    eyebrow: "Active tool",
    description: "Generate piece-part FMEA workbooks from grouping, BOM, and failure mode sources.",
    icon: TreeStructure,
    status: "active",
    workflowIds: workflowOptions.map((workflow) => workflow.id),
    component: FmeaTool,
  },
  {
    id: "bom_compare",
    label: "BOM Comparison Tool",
    eyebrow: "Active tool",
    description: "Compare grouping files or two BOMs to find missing, extra, and mismatched RefDes.",
    icon: GitDiff,
    status: "active",
    workflowIds: bomCompareWorkflowOptions.map((workflow) => workflow.id),
    component: BomCompareTool,
  },
  {
    id: "failure_rate",
    label: "Failure Rate Integration",
    eyebrow: "Active tool",
    description: "Link prediction failure rates to FMEA failure modes with configurable unit conversion.",
    icon: Pulse,
    status: "active",
    workflowIds: failureRateDemoScenarios.map((scenario) => scenario.workflowId),
    component: FailureRateTool,
  },
  {
    id: "refdes_extractor",
    label: "RefDes Extractor",
    eyebrow: "Active tool",
    description: "Extract and verify RefDes from annotated schematic PDFs with adaptive geometry analysis.",
    icon: Cpu,
    status: "active",
    workflowIds: refdesDemoScenarios.map((scenario) => scenario.workflowId),
    component: RefDesTool,
  },
  {
    id: "settings",
    label: "Settings",
    eyebrow: "Platform",
    description: "Theme selection, backend diagnostics, and application info.",
    icon: Faders,
    status: "active",
    workflowIds: [],
    component: SettingsTool,
  },
];

export function resolveToolIdForWorkflow(workflowId: string): ToolId | null {
  return (
    toolDefinitions.find((tool) =>
      tool.workflowIds.some((candidate) => candidate === workflowId),
    )?.id ?? null
  );
}
