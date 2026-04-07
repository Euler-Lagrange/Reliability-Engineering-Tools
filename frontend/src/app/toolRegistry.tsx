import { lazy, type LazyExoticComponent, type ComponentType } from "react";
import type { Icon } from "@phosphor-icons/react";
import {
  ArrowsLeftRight,
  Gauge,
  GearSix,
  MagnifyingGlass,
  ShieldChevron,
} from "@phosphor-icons/react";
import type { ToolId } from "../stores/shellStore";

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
  component: LazyExoticComponent<ComponentType>;
}

export const toolDefinitions: ToolDefinition[] = [
  {
    id: "dark_star_fmea",
    label: "FMEA",
    eyebrow: "Active tool",
    description: "Generate piece-part FMEA workbooks from grouping, BOM, and failure mode sources.",
    icon: ShieldChevron,
    status: "active",
    component: FmeaTool,
  },
  {
    id: "bom_compare",
    label: "Compare",
    eyebrow: "Active tool",
    description: "Compare grouping files or two BOMs to find missing, extra, and mismatched RefDes.",
    icon: ArrowsLeftRight,
    status: "active",
    component: BomCompareTool,
  },
  {
    id: "failure_rate",
    label: "Rates",
    eyebrow: "Active tool",
    description: "Link prediction failure rates to FMEA failure modes with configurable unit conversion.",
    icon: Gauge,
    status: "active",
    component: FailureRateTool,
  },
  {
    id: "refdes_extractor",
    label: "RefDes",
    eyebrow: "Active tool",
    description: "Extract and verify RefDes from annotated schematic PDFs with adaptive geometry analysis.",
    icon: MagnifyingGlass,
    status: "active",
    component: RefDesTool,
  },
  {
    id: "settings",
    label: "Settings",
    eyebrow: "Platform",
    description: "Theme selection, backend diagnostics, and application info.",
    icon: GearSix,
    status: "active",
    component: SettingsTool,
  },
];
