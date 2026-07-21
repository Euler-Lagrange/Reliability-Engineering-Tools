import type { MappingOrigin, WorkflowId } from "../../app/types";

/**
 * Phase 5: canonical FMEA mapping column metadata.
 *
 * Single source of truth for the 15 FMEA mapping rows rendered in the
 * Column Mapping SectionCard. Each entry carries:
 *
 *   - `canonical`      — the default display label (rows 6 and 7 override
 *                        this via `getLabel` so the header text tracks the
 *                        currently selected FMD standard)
 *   - `help`           — rich "About this column" body text. Verbatim from
 *                        the approved plan section A4. These strings are
 *                        user-facing, reviewed content — do not edit
 *                        without a plan update.
 *   - `origin`         — drives the mapping-state badge. `"derived"` rows render
 *                        with the read-only "Derived" state even when the
 *                        user has not picked a mapping. `"merge_only"`
 *                        rows are hidden in non-merge modes.
 *   - `required`       — critical columns. Selecting "— Do Not Map —" for
 *                        a required row should surface a backend error
 *                        rather than silently derive a value.
 *   - `isVisibleInMode` — per-mode visibility filter. Keeps BOM-Only and
 *                        non-merge modes clean by hiding rows that don't
 *                        apply.
 *
 * Tradeoff for row 2 ("Failure Mode Causes"): the plan marks it required
 * only in merge modes. `required` is a static boolean, so we keep it
 * `false` here and rely on the merge-mode backend validator to raise if
 * it is left unmapped. The frontend still shows the help text and allows
 * the user to pick a column in any mode.
 */
export interface FmeaColumnMetadata {
  /** Default canonical header. Rows with a dynamic label override via `getLabel`. */
  canonical: string;
  /**
   * Dynamic label resolver. Only set for rows whose header text depends
   * on the active FMD standard (rows 6 and 7). When present, the runtime
   * calls this with the current `failureModesStandard` and uses the
   * return value as the row's canonical label.
   */
  getLabel?: (fmdStandard: "FMD-91" | "FMD-2016") => string;
  /** Rich "About this column" body text. Verbatim from plan section A4. */
  help: string;
  /** Drives mapping-state badge behavior downstream. */
  origin: MappingOrigin;
  /** Hard-required columns. See tradeoff note in file header. */
  required: boolean;
  /** Per-mode visibility filter. */
  isVisibleInMode: (workflowId: WorkflowId) => boolean;
}

const isMergeMode = (workflowId: WorkflowId): boolean =>
  workflowId === "functional_to_piecepart" || workflowId === "fill_gaps";

export const FMEA_COLUMN_METADATA: readonly FmeaColumnMetadata[] = [
  {
    canonical: "FMEA-ID",
    help:
      "Maps the column in your grouping file or existing FMEA that holds the function-group FMEA-ID prefix (e.g. `PSU-C200`). The generator combines that prefix with each component's reference designator and a suffix to produce per-row FMEA-IDs like `PSU-C200-A`. Hidden in BOM-Only mode — in that mode, the CCA identifier from the Workflow card replaces this column.",
    origin: "mapped",
    required: true,
    isVisibleInMode: (workflowId) => workflowId !== "bom_only",
  },
  {
    canonical: "Failure Mode Causes",
    help:
      "Root cause text for each failure mode. On circuit-block rows, this column doubles as a comma-separated list of reference designators belonging to the function group (e.g. `R200, C200, L1, T1`). The backend parses that list to determine which components belong to each group during merge. Required in merge modes.",
    origin: "mapped",
    // Tradeoff: plan says required in merge modes only, but `required`
    // is static. Merge-mode enforcement lives in the backend validator.
    required: false,
    isVisibleInMode: () => true,
  },
  {
    canonical: "Part Number",
    help:
      "Part number for each BOM line (e.g. `BAE PN`, `P/N`, `Part Number`). Required: it drives the HDA commodity join — the generator looks up each part's commodity classification by part number, and the run cannot resolve failure modes without it. Leave unmapped to auto-detect common headers, or pick the column explicitly when your BOM uses a nonstandard name.",
    origin: "mapped",
    required: true,
    isVisibleInMode: () => true,
  },
  {
    canonical: "Component Part Description",
    help:
      "Human-readable part description (e.g. `0.1uF CAP X7R 25V 0603`). Pulled from your BOM or HDA workbook. Optional — leave unmapped to derive from the BOM's description column automatically, or to leave blank if neither source carries it.",
    origin: "mapped",
    required: false,
    isVisibleInMode: () => true,
  },
  {
    canonical: "BAE HDA Commodity Level 1",
    help:
      "Top-level commodity classification from the BAE HDA taxonomy (e.g. `Capacitor`, `Resistor`). Maps to your HDA workbook's Level-1 column, or to the equivalent column inline in your BOM. Used to look up failure modes in the Failure Modes File.",
    origin: "mapped",
    required: false,
    isVisibleInMode: () => true,
  },
  {
    canonical: "BAE HDA Commodity Level 2",
    help:
      "Second-level commodity classification (e.g. `Ceramic MLCC`, `Thick Film Chip`). Paired with Level 1 to narrow the failure mode lookup in the Failure Modes File.",
    origin: "mapped",
    required: false,
    isVisibleInMode: () => true,
  },
  {
    canonical: "FMD Commodity Type 1",
    getLabel: (fmdStandard) => `${fmdStandard} Commodity Type 1`,
    help:
      "Standard-specific commodity type used to resolve failure rates from MIL-HDBK-217 / FMD-91 or FMD-2016 tables. Maps to your HDA workbook. Only the column for the active standard is required.",
    origin: "mapped",
    required: false,
    isVisibleInMode: () => true,
  },
  {
    canonical: "FMD Commodity Type 2",
    getLabel: (fmdStandard) => `${fmdStandard} Commodity Type 2`,
    help:
      "Secondary standard-specific classification paired with Type 1 for precise failure rate lookup.",
    origin: "mapped",
    required: false,
    isVisibleInMode: () => true,
  },
  {
    canonical: "Failure Mode",
    help:
      "The mode of failure being analyzed (e.g. `Open`, `Short`, `Drift`). Maps to the Failure Modes File, which provides the canonical list per commodity. Required: the FMEA cannot be generated without this column.",
    origin: "mapped",
    required: true,
    isVisibleInMode: () => true,
  },
  {
    canonical: "Failure Mode Ratio",
    help:
      "Fraction of the component's failure rate attributable to this failure mode (e.g. `0.43`). Maps to the Failure Modes File. Required — paired with Failure Mode to populate each piece-part row.",
    origin: "mapped",
    required: true,
    isVisibleInMode: () => true,
  },
  {
    canonical: "Part Usage",
    help:
      "Number of times this component appears in the assembly. Maps to your BOM's quantity column. If you leave this unmapped, the generator will count refdes occurrences and derive it automatically. If you map it AND the mapped value disagrees with the computed count, we'll highlight the row in yellow and add a diagnostic entry — treat that as a review flag.",
    origin: "mapped",
    required: false,
    isVisibleInMode: () => true,
  },
  {
    canonical: "FMEA Level",
    help:
      "Derived automatically. Circuit-block header rows get the label `Circuit Block` (grey-highlighted); component rows get `Piece Part`. Not mappable — this is how the generator structures hierarchical output.",
    origin: "derived",
    required: false,
    isVisibleInMode: () => true,
  },
  {
    canonical: "Local Effect",
    help:
      "Effect of the failure at the component level (e.g. `No output voltage`). Component rows can inherit a generated circuit-block value. In Preserve Formatting, a generated blank leaves existing text unchanged; a different nonblank value replaces it and is recorded on Merge Changes.",
    origin: "merge_only",
    required: false,
    isVisibleInMode: isMergeMode,
  },
  {
    canonical: "Next Higher Effect",
    help:
      "Effect propagated to the next assembly level (e.g. `Power supply fails to regulate`). It follows the same inheritance and blank-safe, audited replacement rules as Local Effect.",
    origin: "merge_only",
    required: false,
    isVisibleInMode: isMergeMode,
  },
  {
    canonical: "End Effect",
    help:
      "Final system-level consequence (e.g. `Mission abort`). It follows the same inheritance and blank-safe, audited replacement rules as Local Effect.",
    origin: "merge_only",
    required: false,
    isVisibleInMode: isMergeMode,
  },
] as const;

/**
 * Resolve the canonical label for a metadata entry. Respects `getLabel`
 * when present so the FMD Commodity Type rows track the active standard.
 */
export function resolveColumnLabel(
  meta: FmeaColumnMetadata,
  fmdStandard: "FMD-91" | "FMD-2016",
): string {
  return meta.getLabel ? meta.getLabel(fmdStandard) : meta.canonical;
}

/**
 * Fix B-FMD: migrate manual mapping overrides across an FMD-standard
 * change.
 *
 * `mappingOverrides` is keyed by each row's *resolved* canonical label.
 * For the FMD Commodity Type rows that label is dynamic (`getLabel`), so a
 * standard toggle rebuilds those rows under the other standard's key. The
 * override lookup would then miss and the UI would silently revert to the
 * auto-mapped value while `buildRunRequest` dropped the user's mapping.
 *
 * This helper walks every metadata entry that carries a `getLabel` and
 * moves any override stored under the old standard's label to the new
 * standard's label, deleting the stale key. Static (non-dynamic) keys are
 * left untouched. Returns a fresh object — the input is never mutated.
 */
export function migrateFmdOverrides(
  overrides: Record<string, string>,
  fromStandard: "FMD-91" | "FMD-2016",
  toStandard: "FMD-91" | "FMD-2016",
): Record<string, string> {
  if (fromStandard === toStandard) {
    return { ...overrides };
  }

  const next = { ...overrides };
  for (const meta of FMEA_COLUMN_METADATA) {
    if (!meta.getLabel) {
      continue;
    }
    const oldKey = meta.getLabel(fromStandard);
    const newKey = meta.getLabel(toStandard);
    if (Object.prototype.hasOwnProperty.call(next, oldKey)) {
      next[newKey] = next[oldKey];
      delete next[oldKey];
    }
  }
  return next;
}
