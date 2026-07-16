# Design Pass v2 — Reliability Tools Desktop

Elevates the suite from "structurally sound" (v1) to the fintech/dev-tool craft bar:
Linear density, Stripe/Mercury trust, calibrated-instrument feel. v1's ten principles
are treated as settled; v2 is about color discipline, contrast order, numeric
treatment, and chrome density.

## Files

| File | Deliverable |
|---|---|
| `Critique v2.html` | **1 — Ranked critique** (R1–R12, severity + file evidence) plus a v1 A–J scorecard and a "don't touch" list. |
| `Tokens v2.html` + `tokens-v2.css` | **2 — Refined token system.** The `.css` is the literal drop-in for the `:root` + `dark_precision` blocks in `frontend/src/theme/styles.css` (all v1 names preserved). |
| `FMEA v2.html` (+ `fmea-v2.css`, `fmea-v2.js`) | **3a/3b — Full-fidelity redesign**: app shell (rail, 48px topbar, log strip) + FMEA run screen end-to-end. Interactive: state jumper (Pristine → Loaded → Blocked → Ready → Running → Success), live run animation, light/dark toggle, expandable log. Fixed 1440×900 layout, scaled-to-fit in smaller windows. |
| `Data Surface v2.html` | **3c — Dense data surface**: annotated MappingTable spec + the mono/tabular-nums numeric rule. |
| `Handoff Notes v2.html` | **4 — Implementation map**: N1–N10 work packages, every recommendation tied to its component file, with rollout order and test-safety notes. |

## The five v2 commitments

1. One accent (desaturated cobalt) — color otherwise appears only as 6px dots,
   text tokens, or 18px count badges, and only for state. Both decorative
   gradients are deleted.
2. Borders-only depth. Shadows survive on two floating layers (popover, toast)
   plus a *visible* focus ring (the v1 ring was 8% alpha).
3. Monotonic four-tier text ramp (v1's `--text-faint` had become darker than
   `--text-muted` — inverted). All tiers AA.
4. Strict 4px spacing; `--space-2-5` (10px) deprecated to 8px. Controls 28px,
   CTA 32px, table rows 32px, topbar 48px.
5. Radius capped at 8px; pills retired to the progress bar; badges are 4px
   rectangles.

Mockups are design references, not production code — port the patterns into the
existing React components per the handoff notes. Mockup pages load Inter/JetBrains
Mono from Google Fonts for preview convenience only; the app stays on its
self-hosted fonts.
