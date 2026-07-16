# Claude Code prompt — implement Design Pass v2

Copy everything below the line into Claude Code, run from the repo root. Put the
`design_handoff_v2/` folder at the repo root first (next to `frontend/`).

---

Implement the "Design Pass v2" visual refinement of Reliability Tools Desktop
(React 19 + TS + Vite + Tauri, CSS custom properties + CSS modules, no component
library). The design bundle is in `design_handoff_v2/`:

- `Handoff Notes v2.html` — THE PLAN. Work packages N1–N10, each mapped to exact
  component files, with rollout order. Read it first (it's plain HTML; read the
  markup directly).
- `tokens-v2.css` — drop-in token values for the `:root` and
  `:root[data-theme="dark_precision"]` blocks of `frontend/src/theme/styles.css`.
- `Critique v2.html` — why each change exists (R1–R12), if context is needed.
- `FMEA v2.html` + `fmea-v2.css` + `fmea-v2.js` — target mockup. Reference for
  measurements and patterns ONLY; do not copy these files into the app.
- `Data Surface v2.html` — MappingTable spec (row anatomy, numeric rules).
- `Tokens v2.html` — token rationale + v1→v2 diff table.

## Ground rules (non-negotiable)

1. Do not rename existing tokens, add a CSS framework, or fork a second
   chip/badge system mid-migration — alias, migrate call sites, then delete.
2. Keep every existing a11y behavior: reduced-motion overrides, escape-layer
   stack, aria-live run meta, focus management on tool switch, keep-alive shell.
3. Keep DOM semantics tests rely on: roles, accessible names, `data-selected`,
   `aria-pressed`. Update test assertions only where the visible text moved
   (e.g. topbar chips → log strip). Run the suite after each package:
   `npm run test`, `npm run typecheck`.
4. The app is fully offline — self-hosted Inter + JetBrains Mono only. Never add
   a CDN font. (The mockup HTML uses Google Fonts for preview; that's mockup-only.)
5. Color discipline: gray builds structure; color appears only as a 6px dot, a
   text token, or an 18px count badge, and only for state — never for categories
   or decoration. One accent. Borders-only depth (shadows only on popover/toast
   + focus ring). No gradients.
6. All numbers, IDs, RefDes, paths, sheet names, Excel headers, timestamps,
   durations: `var(--font-mono)` + `tabular-nums` (the `.num` utility in
   tokens-v2.css).

## Order of work

Ship each package as its own commit; stop and show diffs between packages.

- **N1** Token swap: replace the `:root` + `dark_precision` blocks in
  `frontend/src/theme/styles.css` with `design_handoff_v2/tokens-v2.css`
  (names preserved). Delete the two decorative gradients:
  `.topbar::before` (AppShell.module.css) and `.run-log-panel::before`
  (styles.css). Re-check the 9 personality themes keep a monotonic 4-tier
  text ramp (text > secondary > muted > faint in contrast).
- **N4** Add `.num` utility; apply at every numeric call site (sweep list in
  Handoff N4): hero/header metrics (FmeaTool), `.run-result__metric`, run ID,
  progress %, ETA (RunStatePanel), validation counts, preview cells, log count.
- **N10** Badge/dot sweep: `.status-chip` pills → 18px/4px-radius mono badges
  (counts + true alerts only); row/timeline states → 6px dot + word; normalize
  all dots to 6px; sentence-case tag strings in `mocks/scenarios.ts`.
- **N2** Shell: 48px topbar (14px/600 title, inline mode, subtitle deleted,
  status chips removed), 224px rail on `--bg` with 30px nav rows + mono
  shortcut digits, active = accent-soft tint (no border/glow), theme picker out
  of the rail footer. Files: `app/AppShell.module.css`, `app/App.tsx`.
- **N3** Log strip: 30px collapsed bar with mono count + severity badges;
  backend status (dot + "Ready · Desktop bridge") moves here from the topbar;
  log grid `56px 42px 64px 1fr`; INFO renders `--text-faint` — color only for
  WARN/ERROR. Files: `components/GlobalLogPanel.tsx`, `theme/styles.css`.
- **N6** InputGrid → 44px file rows (indicator ring/dot/check · label+* ·
  mono path RTL-truncated + hover copy · quiet sheet select · 24px Browse).
  Delete the `opacity: 0.62` pending state. Helper copy → `title` attrs.
- **N7** MappingTable per `Data Surface v2.html`: 32px rows, sentence-case
  11px headers, CustomSelect `quiet` variant (mono value, border on hover),
  dot+word status map, note column 11px faint + row-hover "Apply match",
  toolbar counts, coverage meter in the section header. Keep help panel,
  Do-Not-Map sentinel, escape layer.
- **N8** ValidationPreview: dot severity rows + mono area tags + count badges;
  all-mono preview table; analysis-card metric chips → mono text.
- **N9** WorkflowSelector → compact 4-up cards (selected = 1px accent border +
  4% tint + corner check; LEAN/BALANCED badges deleted); ToggleChip →
  neutral segmented control (soft track, 24px raised segment).
- **N5** FMEA layout: numbered section strips (01 Workflow · 02 Inputs ·
  03 Output · 04 Column mapping; SectionCard `variant="bare"` + compact
  header, description props deleted), persistent 320px Run rail replacing the
  Preview/Run tabs: readiness checklist → 32px CTA (always visible, `⌘↵`) →
  blocked reason → 3px progress + phase list (mono elapsed) → result card
  (path well, Open folder/Copy, 2×2 mono metrics grid). RunStatePanel keeps
  its props contract and gains `readiness`. ContextTabs retires here.
  Match every state to the mockup's state jumper: Pristine / Loaded /
  Blocked / Ready / Running / Success.
- Then clone N5's pattern to bom-compare, failure-rate, refdes-extractor.

## Verify

After each package: `npm run typecheck && npm run test`, then launch and
compare against `design_handoff_v2/FMEA v2.html` in a browser (open it and use
the State buttons + the moon toggle for Dark Precision). At the end, walk all
six mockup states against the real app at 1440×900 and in both Precision
themes, and confirm no console errors and keyboard focus is visible everywhere.

Note: this bundle already applied three repo edits you may have received via
sync — `frontend/vite.config.ts` → `vite.config.mts` (refs updated in
package.json/tsconfig.node.json), `ErrorBoundary.tsx` reads `__APP_VERSION__`
instead of `import.meta.env.VITE_APP_VERSION`, and the v1 mockup's `App.jsx` →
`FmeaRedesignApp.jsx`. If your checkout predates them, apply them first.
