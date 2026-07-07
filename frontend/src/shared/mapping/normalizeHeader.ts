/**
 * Canonical header normalizer shared by the mapping layers: lowercase,
 * trim, and collapse every non-alphanumeric run to a single space so
 * "Reference-Designator" and "Reference   Designator" compare equal.
 *
 * Lives in shared/ (not features/fmea) because both the FMEA canonical
 * builder and the shared fixture-row derivation depend on it — shared code
 * must never import from a feature directory (layering follow-up #3 from
 * the holistic review).
 */
export function normalizeHeader(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, " ");
}
