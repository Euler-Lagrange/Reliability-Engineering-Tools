# Live UX Look-In — 2026-07-07 (browser preview, v0.4.8)

A screenshot-driven pass through all five tools in **browser-preview mode**
(`npm run dev` → localhost:5173, Claude-in-Chrome on Edge). Purpose:
document UX findings for a future session to fix — none of these were
changed today. Desktop-only surfaces (real run lifecycle, toasts from a
real backend, the RefDes prefix editor, theme variants, keyboard-only
navigation) were NOT covered and remain untested live.

## Findings (fix candidates, priority order)

### 1. MEDIUM — Selected-card affordance is nearly invisible
Across the workflow cards (FMEA modes, BOM Compare workflows), output
strategy cards, and Settings theme cards, the ONLY visual cue for the
selected card is the small eyebrow label turning accent-blue (verified by
zooming the FMEA mode row with "Piece-Part from BOM Only" selected — card
border/fill are identical to unselected cards). A sighted user cannot tell
at a glance which mode is active; they must find the small "MODE" readout.
- **Caution:** the minimal `data-selected` styling was a deliberate
  2026-07-02 design-overhaul decision ("data-selected only") — confirm
  with the user before strengthening. Suggested: accent border +
  low-alpha accent fill on `[data-selected="true"]` cards.
- Files: `frontend/src/theme/styles.css` (workflow/strategy/theme card
  selected rules), `components/WorkflowSelector.tsx`,
  `components/StrategySelector.tsx`, `features/settings/SettingsTool.tsx`.
- Note: `aria-pressed` (added v0.4.8) already covers screen readers; this
  is the sighted-user half.

### 2. MEDIUM — FMEA hero metric renders literal "TBD"
The FMEA header shows `AUTO-MAPPED: TBD` before any inspection — reads as
unfinished placeholder UI in an otherwise polished header. Show `—`, hide
the metric until a file is inspected, or show `0/13 columns`.
- File: `frontend/src/features/fmea/FmeaTool.tsx` (auto-mapped hero metric,
  near the `autoMappedMetric`/hero computation ~line 660 region).

### 3. LOW-MEDIUM — Optional mapping rows counted as "unmapped" warnings
Failure Rate: the optional "FMEA: function column" renders an amber
`ATTENTION` chip and drives the amber "1 unmapped" toolbar badge even
though its own recommendation text says "Optional." Optional-and-empty is
not a warning state; it sends users chasing a non-issue. Same class
applies anywhere `MappingTable.unmappedCount` counts non-required rows
(`components/MappingTable.tsx:~123-127`).
- Fix direction: exclude rows without `required` (or with an explicit
  `optional` flag) from `unmappedCount`, and give optional-unmapped rows a
  neutral chip (e.g. "Optional") instead of `attention`. FMEA rows already
  carry `required`; the BOM Compare / Failure Rate fixture rows in
  `mocks/scenarios.ts` + `shared/mapping/deriveMappingRows.ts` would need
  the flag added.

### 4. LOW — Single-word workflow badges are unexplained
FMEA cards carry `BALANCED` / `LEAN` badges (BOM Compare's `COVERAGE` /
`DELTA` / `DRIFT` are guessable; `FUNCTIONAL`/`PIECE-PART` are fine).
"BALANCED" and "LEAN" mean nothing to a first-time user and have no
tooltip. Add a `title` tooltip, or fold the meaning into the card body
text, or drop those two badges.
- Files: badge strings come from the workflow metadata in
  `frontend/src/mocks/scenarios.ts` (workflowOptions `badge` fields),
  rendered by `components/WorkflowSelector.tsx`.

### 5. LOW (browser-mock only) — Inconsistent demo staging in FMEA
In browser preview, FMEA stages its demo files as LOADED but every mapping
row as "Not mapped" (amber "10 unmapped" + section text "Select files
above to enable column mapping" while files ARE staged). BOM Compare and
Failure Rate demos stage MAPPED rows, so FMEA's preview looks broken by
comparison. Desktop mode is unaffected (real inspection drives the rows).
- Fix direction: either stage the FMEA demo mappings as mapped (like the
  other tools) or drop the "Select files above…" copy when files are
  staged. `frontend/src/mocks/scenarios.ts` (FMEA scenario mappings) +
  `features/fmea/FmeaTool.tsx` mapping-card description.

## Verified good (no action)
- Workflow-card switching updates everything it should: mode readout, CCA
  identifier field (with its excellent "'PSU' produces 'PSU-C200-A'"
  caption), input roles, mapping-row visibility.
- Required-column markers (`*`) and required-input chips render as
  designed; info tips present on every FMEA mapping row and RefDes option.
- Empty states are clear ("Compare two BOMs", "Link failure rates",
  "Extract reference designators") with honest browser-mock messaging
  ("Example data staged", "Browser preview active. Real file inspection
  requires the Tauri shell.").
- Settings: theme gallery, log-path copy/open affordances, backend
  diagnostics all coherent.
- No console errors observed during the pass.

## Known intentional placeholders (do not "fix" without user)
- "Load example" buttons show coming-soon toasts (documented placeholder).
- Minimal `data-selected` styling (see finding 1 caution).
