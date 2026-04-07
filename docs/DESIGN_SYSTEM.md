# Design System

## Single Source of Truth

All design tokens, themes, and global element styles live in
`frontend/src/theme/styles.css`. Component files reference tokens through
CSS custom properties (`var(--accent)`, `var(--text-base)`, etc.). Adding
a new color or font size means adding a token in `styles.css` first; never
hardcode values in component CSS or inline styles.

## Color Tokens

| Token | Role | Light Precision (default) |
|-------|------|---------------------------|
| `--bg` | Page background | `#f6f8fb` |
| `--surface` | Card and panel background | `#ffffff` |
| `--surface-muted` | Subtle alternate surface | `#f8fafc` |
| `--surface-soft` | Recessed inset surface | `#f2f5f9` |
| `--line` | Default border | `#dfe5ec` |
| `--line-strong` | Emphasized border (buttons, inputs) | `#c8d1dc` |
| `--text` | Primary text | `#172433` |
| `--text-secondary` | Secondary text | `#415268` |
| `--text-muted` | Tertiary / helper text | `#617289` |
| `--text-faint` | Eyebrows, labels, faint metadata | `#8794a8` |
| `--accent` | Primary action / focus | `#235ee7` |
| `--accent-soft` | Accent fill (active chips, tinted cards) | `#edf3ff` |
| `--success` | Success text and icons | `#1b8758` |
| `--success-soft` | Success fill | `#eaf7f0` |
| `--warning` | Warning text and icons | `#946100` |
| `--warning-soft` | Warning fill | `#fff6df` |
| `--danger` | Error text and icons | `#b14433` |
| `--danger-soft` | Error fill | `#fff0ed` |

Every theme overrides the same set of tokens. No theme adds new color names.

## Typography Tokens

### Font families

| Token | Stack |
|-------|-------|
| `--font-sans` | `"Inter", "Segoe UI Variable Display", "Segoe UI", system-ui, sans-serif` |
| `--font-display` | `"Inter", "Segoe UI Variable Display", system-ui, sans-serif` |
| `--font-mono` | `"JetBrains Mono", "Cascadia Code", "Consolas", ui-monospace, monospace` |

### Font loading

The shell self-hosts both variable fonts so the desktop build renders the
same on every machine. Files live in `frontend/public/fonts/` and are
declared at the top of `styles.css`:

```css
@font-face {
  font-family: "Inter";
  src: url("/fonts/Inter-Variable.woff2") format("woff2-variations"),
       url("/fonts/Inter-Variable.woff2") format("woff2");
  font-weight: 100 900;
  font-display: swap;
}

@font-face {
  font-family: "JetBrains Mono";
  src: url("/fonts/JetBrainsMono-Variable.ttf") format("truetype-variations"),
       url("/fonts/JetBrainsMono-Variable.ttf") format("truetype");
  font-weight: 100 800;
  font-display: swap;
}
```

Both fonts are OFL-licensed; the license text travels in
`frontend/public/fonts/`.

### Type scale

| Token | Size | Typical use |
|-------|------|-------------|
| `--text-2xs` | 10 px | Status pin, fine print |
| `--text-xs`  | 11 px | Eyebrows, microcopy, table headers |
| `--text-sm`  | 12 px | Helper text, monospace paths |
| `--text-base`| 13 px | Body, button labels |
| `--text-md`  | 16 px | Section card titles |
| `--text-lg`  | 18 px | Subsection headlines |
| `--text-xl`  | 20 px | Tool banner title |
| `--text-2xl` | 24 px | Topbar `<h1>` |

### Weights

| Token | Value |
|-------|-------|
| `--weight-normal` | 400 |
| `--weight-medium` | 500 |
| `--weight-semibold` | 600 |
| `--weight-bold` | 700 |

### Line heights

| Token | Value |
|-------|-------|
| `--leading-tight` | 1.2 |
| `--leading-snug` | 1.35 |
| `--leading-normal` | 1.5 |
| `--leading-relaxed` | 1.65 |

### Letter spacing

| Token | Value |
|-------|-------|
| `--tracking-tight` | -0.01em |
| `--tracking-normal` | 0 |
| `--tracking-wide` | 0.02em |
| `--tracking-uppercase` | 0.06em |

## Shape Tokens

| Token | Value |
|-------|-------|
| `--radius-sm` | 6 px |
| `--radius-md` | 8 px |
| `--radius-lg` | 10 px |
| `--ease` | `cubic-bezier(0.25, 1, 0.5, 1)` |

## The 7 Themes

Themes are toggled by setting `data-theme` on the `<html>` element from
`ThemeController.tsx`. The attribute is **always** set: Light Precision
corresponds to `data-theme="light_precision"`, not the absence of the
attribute. The single source of truth for the theme list — id, label,
icon, native colorScheme, and rail visibility — is
`frontend/src/shared/theme/themeRegistry.ts`. The shell rail, the
Settings tool, the topbar chip, and the ThemeController all read from
that one registry.

| Theme id | data-theme | Use case | Personality |
|----------|------------|----------|-------------|
| Light Precision | `light_precision` | Daily use on bright displays | Calm blues on near-white surfaces; the workhorse |
| Dark Precision | `dark_precision` | Long sessions, dim rooms | Slate surfaces with the same blue accent |
| Signal Slate | `signal_slate` | Reduced-saturation light alternative | Cooler greys with a teal accent |
| Midnight Blue | `midnight_blue` | Aerospace / defense engineering reviews | Deep navy surfaces with ice-blue accents, tuned for fatigue resistance |
| High Contrast | `high_contrast` | Accessibility, projectors, older monitors | Pure black/white with a yellow accent — targets WCAG AAA |
| Synthwave | `synthwave` | Off-hours dev-tool vibe | Hot magenta on deep purple, 80s retro-futurism |
| Mission Control | `mission_control` | Technical-precision instrument-panel aesthetic | Near-black with cyan accents, monospaced typography throughout |

## Mission Control Special Rules

Mission Control is the only theme that overrides typography and applies
component-level rules. The override block at the bottom of `styles.css`
keeps these restrained:

```css
:root[data-theme="mission_control"] {
  /* Typography override — mono everywhere */
  --font-sans: var(--font-mono);
  --font-display: var(--font-mono);
  font-family: var(--font-mono);
  font-feature-settings: "tnum" 1, "zero" 1, "cv11" 1;
}

/* Eyebrows, status chips, banner: uppercase + medium weight */
:root[data-theme="mission_control"] .eyebrow,
:root[data-theme="mission_control"] .section-card__eyebrow,
:root[data-theme="mission_control"] .tool-banner__eyebrow,
:root[data-theme="mission_control"] .status-chip {
  text-transform: uppercase;
  letter-spacing: var(--tracking-uppercase);
  font-weight: var(--weight-medium);
}

/* Subtle cyan glow on success status chips */
:root[data-theme="mission_control"] .status-chip--success {
  box-shadow: 0 0 0 1px rgba(0, 217, 255, 0.3),
              0 0 12px rgba(0, 217, 255, 0.08);
}

/* Numeric data — tabular nums + slashed zero */
:root[data-theme="mission_control"] .data-table,
:root[data-theme="mission_control"] .mapping-table__cell,
:root[data-theme="mission_control"] .run-result__metric-value {
  font-variant-numeric: tabular-nums slashed-zero;
}

/* Cyan accent glow on input cards under hover */
:root[data-theme="mission_control"] .input-card:hover {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px rgba(0, 217, 255, 0.15);
}
```

`tnum` and `zero` are font-feature-settings that map to CSS
`font-variant-numeric: tabular-nums slashed-zero`. They make every digit
identical width and disambiguate `0` from `O` — appropriate for instrument
readouts and metric tables.

## Shared Components

Components live in `frontend/src/components/` and are wired into every
tool's `*Tool.tsx`.

| Component | File | Purpose |
|-----------|------|---------|
| `SectionCard` | `SectionCard.tsx` | Bordered card with eyebrow, title, description, and an actions slot |
| `InputGrid` | `InputGrid.tsx` | Grid of input file cards with status chips and sheet pickers |
| `MappingTable` | `MappingTable.tsx` | Column-mapping table for canonical → mapped pairs |
| `RunStatePanel` | `RunStatePanel.tsx` | Sticky run-state panel: button, progress, timeline, result |
| `WorkflowSelector` | `WorkflowSelector.tsx` | Workflow choice cards |
| `StrategySelector` | `StrategySelector.tsx` | Output strategy cards |
| `CustomSelect` | `CustomSelect.tsx` | Accessible dropdown with keyboard navigation |
| `ValidationPreview` | `ValidationPreview.tsx` | Pre-run validation message list |
| `ScenarioRail` | `ScenarioRail.tsx` | Demo scenario picker (browser preview only) |

## CSS Module Conventions

The codebase uses two styling strategies:

| Strategy | When |
|----------|------|
| Global classes in `styles.css` | Default. Every shared component uses global class names like `.section-card`, `.input-card`, `.status-chip`. Themes target these classes directly. |
| CSS modules (`*.module.css`) | Used only for layout that is unique to a feature surface. Current modules: `frontend/src/app/AppShell.module.css` (shell layout), `frontend/src/features/settings/SettingsTool.module.css` (settings page layout), `frontend/src/shared/notifications/NotificationCenter.module.css` (notification stack). |

CSS modules are scoped to a single component import. Use them when the
class names would otherwise pollute the global namespace and there is no
intent to theme the surface differently from the rest of the app.

## Usage Rules

- **Always reference tokens.** Never hardcode `#235ee7`, `13px`, or `8px`
  inside a component. Use `var(--accent)`, `var(--text-base)`,
  `var(--radius-md)` so theme switches and scale tweaks propagate.
- **Prefer global classes.** A new card surface should reuse `.section-card`
  or `.input-card` rather than introducing a parallel `.my-card` class.
  Themes already target the existing class names.
- **Use CSS modules for layout-only feature scopes.** If the only thing the
  module file does is set up a grid for one feature page, that is the
  correct use. Do not put themable color or typography rules inside a
  module — they will not pick up theme overrides without duplication.
- **Mission Control overrides are global.** When adding a new component,
  test it under Mission Control. If the new surface displays numeric data,
  add it to the `font-variant-numeric` selector list rather than reinventing
  the rule per-component.
- **Status chips use the `--{tone}` / `--{tone}-soft` pair.** Pair every
  status chip with the matching foreground/background tone token so high
  contrast and color-blind palettes stay coherent.
