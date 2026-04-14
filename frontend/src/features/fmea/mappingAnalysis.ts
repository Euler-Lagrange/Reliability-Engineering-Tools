import type { FileRole, InputFileState, OutputStrategyId } from "../../app/types";

export interface AggregatedMappingSource {
  columns: string[];
  optionLabels: Record<string, string>;
  sourceLabels: string[];
  sourceLabelText: string | null;
}

export interface SettledSheetInspection<T> {
  sheetName: string;
  result: PromiseSettledResult<T>;
}

export interface ResolvedSheetInspections<T> {
  selectedInspection: T;
  successfulInspections: T[];
  skippedSheets: string[];
}

export function normalizeHeader(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, " ");
}

export function mergeColumnsByNormalizedName(columns: string[]): string[] {
  const seen = new Set<string>();
  const merged: string[] = [];

  for (const column of columns) {
    const normalized = normalizeHeader(column);
    if (!normalized || seen.has(normalized)) {
      continue;
    }

    seen.add(normalized);
    merged.push(column);
  }

  return merged;
}

export function buildWorkbookColumnUnion(columnSets: string[][]): string[] {
  return mergeColumnsByNormalizedName(columnSets.flat());
}

export function shouldShowTargetWorkbook(outputStrategyId: OutputStrategyId): boolean {
  return outputStrategyId === "existing_workbook_preserve_formatting";
}

export function formatInputSourceLabels(labels: string[]): string | null {
  if (labels.length === 0) {
    return null;
  }

  if (labels.length === 1) {
    return labels[0];
  }

  if (labels.length === 2) {
    return `${labels[0]} and ${labels[1]}`;
  }

  return `${labels.slice(0, -1).join(", ")}, and ${labels.at(-1)}`;
}

export function buildAggregatedMappingSource(
  inputs: InputFileState[],
  columnsByRole: Partial<Record<FileRole, string[]>>,
): AggregatedMappingSource {
  const sourceInputs = inputs.filter((input) => (columnsByRole[input.role]?.length ?? 0) > 0);
  const sourceLabels = sourceInputs.map((input) => input.label);
  const columnSources = new Map<string, { value: string; sourceLabels: string[] }>();

  sourceInputs.forEach((input) => {
    (columnsByRole[input.role] ?? []).forEach((column) => {
      const normalized = normalizeHeader(column);
      if (!normalized) {
        return;
      }

      const existing = columnSources.get(normalized);
      if (!existing) {
        columnSources.set(normalized, {
          value: column,
          sourceLabels: [input.label],
        });
        return;
      }

      if (!existing.sourceLabels.includes(input.label)) {
        existing.sourceLabels.push(input.label);
      }
    });
  });

  return {
    columns: Array.from(columnSources.values()).map((entry) => entry.value),
    optionLabels: Object.fromEntries(
      Array.from(columnSources.values()).map((entry) => [
        entry.value,
        `${entry.value} - ${formatInputSourceLabels(entry.sourceLabels) ?? "Unknown source"}`,
      ]),
    ),
    sourceLabels,
    sourceLabelText: formatInputSourceLabels(sourceLabels),
  };
}

export function resolveSheetInspections<T>(
  selectedSheet: string,
  inspections: SettledSheetInspection<T>[],
): ResolvedSheetInspections<T> {
  const successfulInspections = inspections.flatMap((inspection) =>
    inspection.result.status === "fulfilled" ? [inspection.result.value] : [],
  );
  const skippedSheets = inspections.flatMap((inspection) =>
    inspection.result.status === "rejected" ? [inspection.sheetName] : [],
  );
  const selectedInspection = inspections.find((inspection) => inspection.sheetName === selectedSheet);

  if (!selectedInspection) {
    throw new Error(`Selected sheet '${selectedSheet}' was not inspected.`);
  }

  if (selectedInspection.result.status === "rejected") {
    throw selectedInspection.result.reason;
  }

  return {
    selectedInspection: selectedInspection.result.value,
    successfulInspections,
    skippedSheets,
  };
}
