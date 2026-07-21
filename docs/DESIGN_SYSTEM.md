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
| `--bg` | Page background | `#f6f7f9` |
| `--surface` | Card and panel background | `#ffffff` |
| `--surface-muted` | Subtle alternate surface | `#f6f7f9` |
| `--surface-soft` | Recessed inset surface | `#f0f2f5` |
| `--line` | Default border | `#e4e7ec` |
| `--line-strong` | Emphasized border (buttons, inputs) | `#c9d0da` |
| `--text` | Primary text | `#14181f` |
| `--text-secondary` | Secondary text | `#3e4756` |
| `--text-muted` | Tertiary / helper text | `#5d6675` |
| `--text-faint` | Eyebrows, labels, faint metadata | `#737c8a` |
| `--accent` | Primary action / focus | `#2f5bd8` |
| `--accent-hover` | Primary-action hover | `color-mix(in srgb, var(--accent) 88%, var(--text))` |
| `--accent-active` | Primary-action press | `color-mix(in srgb, var(--accent) 76%, var(--text))` |
| `--accent-soft` | Accent fill (selected controls) | `#edf1fc` |
| `--accent-border` | Selected-control outline | `color-mix(in srgb, var(--accent) 32%, transparent)` |
| `--success` | Success text and icons | `#1a7f53` |
| `--success-soft` | Success fill | `#e9f5ef` |
| `--warning` | Warning text and icons | `#8f5f04` |
| `--warning-soft` | Warning fill | `#faf3e1` |
| `--danger` | Error text and icons | `#b2412f` |
| `--danger-soft` | Error fill | `#fbefec` |
| `--text-on-accent` | Foreground for elements filled with `--accent` | `#ffffff` |

Theme blocks reuse this semantic vocabulary; components do not introduce
theme-specific color names. Hover/active tones derive from the current
`--accent` and `--text`, so a theme that changes its accent cannot fall back
to Light Precision cobalt during interaction. A theme may still override a
derived interaction token when contrast requires a specialized value.

`--text-on-accent` defaults to `#ffffff` and is overridden per-theme only
where the accent color demands it — the High Contrast theme sets
`--text-on-accent: #000000` because its accent is yellow. Components like
`.primary-button` now reference `var(--text-on-accent)` instead of hardcoding
`color: #ffffff`.

### Section surface tokens (added 0.4.5)

A namespaced set of tokens that drives `SectionCard` variants without
colliding with the existing theme-aware `--surface-muted` palette color
above. Prefer these when you need the "surface of a section container"
rather than the "theme's muted background".

| Token | Default value | Intended use |
|-------|---------------|--------------|
| `--section-surface-primary` | `var(--surface)` | Default outlined card (SectionCard `variant="outlined"`) |
| `--section-surface-muted` | `transparent` | Supporting section (SectionCard `variant="divided"`) |
| `--section-surface-decoration` | `var(--surface-soft)` | Preview / diagnostic inset (e.g., Review drawer preview table) |

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
| `--text-md`  | 16 px | Panel metrics |
| `--text-lg`  | 18 px | Result values |
| `--text-xl`  | 20 px | The single hero metric per tool |
| `--text-2xl` | 24 px | Modal and full-screen headers |
| `--text-xxl` | 24 px | Legacy alias; the 48 px topbar does not use it |
| `--text-3xl` | 24 px | Legacy alias; hero metrics cap at `--text-xl` |

The compact topbar title is an intentional off-grid 14 px at weight 600.
It is chrome, not a page headline, so do not reconnect it to the legacy
`--text-xxl` token.

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
| `--tracking-wide` | 0.02em |
| `--tracking-uppercase` | 0.06em |

`--tracking-uppercase` is `0.06em`. Design Pass v2 limits uppercase chrome
to navigation-group labels and log-level tokens; ordinary section labels,
state words, and topbar text stay sentence case.

## Spacing Tokens

All spacing follows a 4 px grid. Phase G introduced an 8-step scale; every
component CSS file references these tokens for `padding`, `margin`, `gap`,
and `min-height`.

| Token | Value | Intended use |
|-------|-------|--------------|
| `--space-1` | 4 px | Micro: icon gaps, fine adjustments |
| `--space-2` | 8 px | Tight: within components |
| `--space-2-5` | 8 px | Deprecated compatibility alias; prefer `--space-2` or `--space-3` |
| `--space-3` | 12 px | Standard: between related elements |
| `--space-4` | 16 px | Comfortable: section padding |
| `--space-5` | 20 px | Relaxed: rail padding, chrome |
| `--space-6` | 24 px | Generous: between sections |
| `--space-7` | 32 px | Major: section separation |
| `--space-8` | 48 px | Hero: major page sections |

**Rule.** Never use raw pixel values for padding, margin, gap, or
min-height in component CSS — always reach for one of the tokens above.
Off-grid values are allowed only with an inline comment explaining the
deviation (e.g., negative-margin hit-area expansion on an icon button).

### Semantic gap aliases (added 0.4.5)

Named aliases over `--space-*` that say what the gap *means*, not just how
big it is. Existing `var(--space-N)` usage still works; reach for these
when the intent is clearer than the pixel value.

| Token | Maps to | Intended use |
|-------|---------|--------------|
| `--gap-inline` | `var(--space-2)` (8 px) | Within a single control (icon + label, chip + count) |
| `--gap-group` | `var(--space-4)` (16 px) | Between related controls inside a form row |
| `--gap-section` | `var(--space-6)` (24 px) | Between SectionCards or other major regions |
| `--gap-page` | `var(--space-7)` (32 px) | Major page-level regions |

Adoption is opportunistic — no call-site migration shipped in 0.4.5.

## Border Radius Tokens

Expanded from 3 radii to 6 in Phase G.

| Token | Value | Intended use |
|-------|-------|--------------|
| `--radius-xs` | 4 px | Tiny: dropdown items, chips |
| `--radius-sm` | 6 px | Small: buttons, inputs |
| `--radius-md` | 8 px | Default: cards, sections |
| `--radius-lg` | 8 px | Alias of `--radius-md`; there is no third card radius |
| `--radius-xl` | 8 px | Legacy alias; rail buttons use the shared system radius |
| `--radius-pill` | 999 px | Progress and coverage-meter tracks only |

## Shadow Tokens

**Depth strategy is borders-only for docked surfaces.** Shadows are reserved
for layers that actually float and for keyboard focus.

| Token | Default value | Intended use |
|-------|---------------|--------------|
| `--shadow-popover` | `0 4px 16px rgba(15, 20, 30, 0.10), 0 1px 3px rgba(15, 20, 30, 0.08)` | Dropdowns, menus, custom-select popovers |
| `--shadow-focus-ring` | 2 px accent color-mix ring | `:focus-visible` state on interactive elements |
| `--shadow-toast` | `0 6px 20px rgba(15, 20, 30, 0.12)` | Notification toasts |

Theme overrides may tune floating-layer shadows for contrast. Selected rail
rows are tint + accent text, not a shadow or glow. Do not add decorative
box-shadows to docked shell or tool surfaces.

## Motion

One easing curve, three durations. Never write a raw `ms` literal in a
transition/animation shorthand — reach for a duration token.

| Token | Value | Use |
|-------|-------|-----|
| `--ease` | `cubic-bezier(0.25, 1, 0.5, 1)` | Every transition/animation |
| `--duration-fast` | `150ms` | Micro-interactions: dense-row hovers, filters |
| `--duration-base` | `200ms` | Standard control transitions |
| `--duration-slow` | `250ms` | Larger reveals: drawers, panels, progress |

## Icon Size Conventions

Phosphor icons are used throughout the shell. The size is set on the
component, not via CSS, so each call site picks the right scale. Use
`weight="bold"` for accent/active states.

| Size | Context |
|------|---------|
| 12 px | Inline meta (timestamps, counts next to text) |
| 14 px | Button glyphs (primary/ghost button icons) |
| 16 px | Toolbar, badge, and toggle glyphs |
| 20 px | Rail navigation and compact theme toggle |
| 24 px | Hero / empty state illustrations |

## Shell Geometry (Design Pass v2)

The desktop shell uses four stable geometry anchors:

| Surface | Size | Current role |
|---------|------|--------------|
| Navigation rail | 224 px wide | Grouped 30 px navigation rows on the canvas background |
| Topbar | 48 px high | 14 px tool title, divider, per-tool `Mode · …` label, quiet actions |
| Global log strip | 30 px collapsed height | Cross-tool log controls and backend-health telemetry |
| Per-tool side rail | 320 px wide | Persistent **Run** and **Validation** cards in all four analysis tools |

The topbar, rail, and log strip are separated by hairline borders. The old
topbar/log accent gradients, oversized eyebrow/subtitle title stack, and
decorative active-rail glow are retired. Main tool content uses numbered
`SectionCard variant="bare"` sections; the 320 px side rail remains visible
instead of switching between Preview and Run tabs.

## Global Run Log Panel Styling

The `GlobalLogPanel` (Phase B) is docked at the bottom of the app shell.
Its styling choices:

- **Font.** Log lines use `var(--font-mono)` (JetBrains Mono). Timestamps
  additionally apply `font-variant-numeric: tabular-nums` so columns stay
  aligned when the seconds digits change.
- **Level colors.** Each log level maps to a token:
  - `info` → `var(--text-faint)`
  - `warning` → `var(--warning)`
  - `error` → `var(--danger)`
  - `debug` → `var(--text-faint)`
- **Layout.** Log rows use a 4-column CSS grid:
  `56px 42px 64px minmax(0, 1fr)` (time / level / tool / message).
- **Body height.** User-resizable from 120–640 px, defaulting to 240 px and
  clamped to leave usable tool chrome visible; scrolls internally and persists
  the chosen height in local storage.
- **Collapse.** A chevron button in the header toggles the body.
- **Status dots.** A canonical 6 px circle next to the "Run Log"
  title reflects the current `runStore.activeRun.phase`:
  idle = `var(--text-faint)`, active = `var(--accent)` with a 1.6 s
  pulse, good = `var(--success)`, warn = `var(--warning)`,
  bad = `var(--danger)`. Decorative only (`aria-hidden`); meaning is
  carried by the log body text itself.
- **Backend health.** `GlobalLogPanel` owns the right-aligned backend dot,
  status word, and bridge-mode label (for example, `Ready · Desktop bridge`).
  Full diagnostics remain in Settings; backend telemetry does not live in
  the topbar.
- **Collapsed count.** The entry count uses
  `var(--text-2xs)` / `var(--text-faint)`; a truncation warning uses the
  warning foreground/background pair.
- **Resize handle (0.4.5).** Hit area widened 6 px → 10 px; the hover
  band still activates on the same rule, just over a larger grab zone.

## Mission Control Theme Rules

Mission Control uses the mono family throughout and applies restrained
uppercase treatment to eyebrow text. Design Pass v2 removed the former
success-chip and input-card hover glows; there is no live component-level
glow exception. Like every other theme, its docked surfaces use borders and
state tint rather than decorative depth.

## Hover/Focus State Audit

Every interactive element in the shell now has a consistent
`:focus-visible` style using `var(--shadow-focus-ring)`. The audit covers:
`.toggle-chip`, `.primary-button`, `.ghost-button`,
`.scenario-pill`, `.choice-card`, `.run-log-panel__action`,
`.run-log-panel__filter-option`, `.toolButton`, `.themeButton`,
`.themeOption`, and `.healthButton`.

When adding a new interactive element, mirror the existing pattern:

```css
.my-control:focus-visible {
  outline: none;
  box-shadow: var(--shadow-focus-ring);
}
```

## Column Mapping Dropdown Spacing

The mapping table's `CustomSelect` no longer passes the `compact` prop.
The menu is sized by two rules in the global stylesheet:

```css
.custom-select__menu {
  min-width: max(220px, 100%);
  max-width: 480px;
}

.mapping-table__select-cell {
  min-width: 240px;
}
```

This is the "boxes super close together horizontally" fix — without these
constraints the select cells collapsed to fit their current text and the
dropdown menus clipped long column names.

## The 10 Themes

Themes are toggled by setting `data-theme` on the `<html>` element from
`ThemeController.tsx`. The attribute is **always** set: Light Precision
corresponds to `data-theme="light_precision"`, not the absence of the
attribute. The single source of truth for the theme list — id, label,
icon, native colorScheme, and rail visibility — is
`frontend/src/shared/theme/themeRegistry.ts`. The Settings tool, the rail's
compact light/dark toggle, and `ThemeController` all read from that registry.

| Theme id | data-theme | Use case | Personality |
|----------|------------|----------|-------------|
| Light Precision | `light_precision` | Daily use on bright displays | Calm blues on near-white surfaces; the workhorse |
| Dark Precision | `dark_precision` | Long sessions, dim rooms | Slate surfaces with the same blue accent |
| Signal Slate | `signal_slate` | Reduced-saturation light alternative | Cooler greys with a teal accent |
| Midnight Blue | `midnight_blue` | Aerospace / defense engineering reviews | Deep navy surfaces with ice-blue accents, tuned for fatigue resistance |
| High Contrast | `high_contrast` | Accessibility, projectors, older monitors | Pure black/white with a yellow accent — targets WCAG AAA |
| Synthwave | `synthwave` | Off-hours dev-tool vibe | Hot magenta on deep purple, 80s retro-futurism |
| Mission Control | `mission_control` | Technical-precision instrument-panel aesthetic | Near-black with cyan accents, monospaced typography throughout |
| Kraft Paper | `kraft_paper` | Workshop notebook aesthetic | Warm paper and graphite (light). Icon: NotePencil |
| Forest Depth | `forest_depth` | Biophilic dark theme for long runs | Deep pine and moss (dark). Icon: TreeEvergreen |
| Graphite Dawn | `graphite_dawn` | Newsprint precision | Soft charcoal on warm ivory (light). Icon: Compass |

## Mission Control Special Rules

Mission Control overrides the typography tokens and keeps its live
component-level rule limited to eyebrow treatment:

```css
:root[data-theme="mission_control"] {
  /* Typography override — mono everywhere */
  --font-sans: var(--font-mono);
  --font-display: var(--font-mono);
  font-family: var(--font-mono);
  font-feature-settings: "tnum" 1, "zero" 1, "cv11" 1;
}

/* Eyebrows: uppercase + medium weight */
:root[data-theme="mission_control"] .eyebrow,
:root[data-theme="mission_control"] .section-card__eyebrow {
  text-transform: uppercase;
  letter-spacing: var(--tracking-uppercase);
  font-weight: var(--weight-medium);
}
```

`tnum` and `zero` are font-feature-settings that map to CSS
`font-variant-numeric: tabular-nums slashed-zero`. They make every digit
identical width and disambiguate `0` from `O` — appropriate for instrument
readouts. Mission Control does not restore the deleted status-chip family or
add a special input-card hover glow.

## Shared Components

Components live in `frontend/src/components/` and are wired into every
tool's `*Tool.tsx`.

| Component | File | Purpose |
|-----------|------|---------|
| `SectionCard` | `SectionCard.tsx` | Bordered card with eyebrow, title, description, and an actions slot. `variant="outlined" \| "divided" \| "bare"` (default `"outlined"`) added in 0.4.5 |
| `ContextDrawer` | `ContextDrawer.tsx` | Right-anchored overlay "Review" drawer toggled by ⌘R / Ctrl+R (new in 0.4.5). Renders run summary + `output_preview` table; informational, not modal |
| `InputGrid` | `InputGrid.tsx` | One bordered set of 44 px file rows with step/status indicators, required asterisks, paths, sheet pickers, and Browse actions. Each row carries `data-state="pending\|active\|loaded"` |
| `MappingTable` | `MappingTable.tsx` | Column-mapping table for canonical → mapped pairs |
| `RunStatePanel` | `RunStatePanel.tsx` | Persistent Run-rail content: readiness checklist, Start/Cancel action, progress, timeline, and result. A supplied `readiness` prop also arms the guarded Ctrl/Cmd+Enter shortcut |
| `WorkflowSelector` | `WorkflowSelector.tsx` | Workflow choice cards using `data-selected` and `aria-pressed` |
| `StrategySelector` | `StrategySelector.tsx` | Output strategy cards using `data-selected` and `aria-pressed` |
| `CustomSelect` | `CustomSelect.tsx` | Accessible dropdown with keyboard navigation |
| `ValidationPreview` | `ValidationPreview.tsx` | Pre-run validation message list |

### Primitives (`components/primitives/`)

Reusable building-block components extracted from tool surfaces.

| Component | File | Purpose |
|-----------|------|---------|
| `CommandPalette` | `CommandPalette.tsx` | Ctrl+K action search and navigation overlay |
| `ToggleChip` | `ToggleChip.tsx` | Boolean toggle styled as a chip |
| `OptionsField` | `OptionsField.tsx` | Labeled field wrapper for option controls |
| `CheckboxField` | `CheckboxField.tsx` | Labeled checkbox with description |
| `OptionsSection` | `OptionsSection.tsx` | Grouped options container with heading |
| `HoldButton` | `HoldButton.tsx` | Press-and-hold confirmation button |
| `EmptyState` | `EmptyState.tsx` | Placeholder for empty content areas |

## CSS Module Conventions

The codebase uses two styling strategies:

| Strategy | When |
|----------|------|
| Global classes in `styles.css` | Default. Every shared component uses global class names like `.section-card`, `.input-card`, `.badge-state`, and `.state-word`. Themes target these classes directly. |
| CSS modules (`*.module.css`) | Used only for layout that is unique to a feature surface. Current modules: `frontend/src/app/AppShell.module.css` (shell layout), `frontend/src/features/settings/SettingsTool.module.css` (settings page layout), `frontend/src/shared/notifications/NotificationCenter.module.css` (notification stack). |

CSS modules are scoped to a single component import. Use them when the
class names would otherwise pollute the global namespace and there is no
intent to theme the surface differently from the rest of the app.

## Usage Rules

- **Always reference tokens.** Never hardcode `#2f5bd8`, `13px`, or `8px`
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
  test it under Mission Control. Numeric data and identifiers should use
  the shared `.num`/mono treatment instead of a theme-specific selector.
- **Choose state vocabulary by meaning.** Use a dot + state word for row or
  timeline state, and reserve `.badge-state` for counts and true alerts.

## Badge, Dot, Tag, and Shortcut Vocabulary

The old `.status-chip` family and alias were deleted in Design Pass v2.
Do not reintroduce it: state, classification, workbook identifiers, and
keyboard hints each have a separate treatment.

| Class | Treatment | Role | Examples |
|-------|-----------|------|----------|
| `.badge-state` (+ `--good` / `--warn` / `--bad` / `--idle`) | 18 px, 4 px-radius semantic rectangle | Counts and true alerts | error count, warning count, capped |
| `.dot` + `.state-word` | 6 px dot plus sentence-case text | Row, mapping, readiness, and timeline state | `Mapped`, `Not mapped`, `Ready` |
| `.tag-category` | Outlined neutral | Classification without urgency | `FUNCTIONAL`, `PIECE-PART`, `LEAN`, `BALANCED` |
| `.column-tag` | Mono text on a sunken well | Workbook identifiers | column and sheet names |
| `.kbd-shortcut` | Text-only monospace, no box | Keyboard hint | `⌘K`, `⌘R`, `CTRL+[` |

Mixing treatments is a smell — a card full of filled pills trains the eye
to ignore color. Pick the one that matches the role.

## Selection State (0.4.5)

A single global rule handles every "you picked this one" UI affordance so
choice cards, theme tiles, radio chips, and workflow cards look the same
when selected:

```css
[data-selected="true"] {
  border-color: var(--accent-border);
  background: color-mix(in srgb, var(--accent) 4%, var(--surface));
  color: var(--text);
}

[data-selected="true"] .eyebrow,
[data-selected="true"] .section-card__eyebrow {
  color: var(--accent);
}
```

The migration is complete: `data-selected` is the only selection
attribute. `StrategySelector`, `WorkflowSelector`, `ToggleChip`, the
Settings theme tiles, the rail tool/theme buttons, the panel toggles,
the run-log filter, and the topbar Review toggle all emit it, and every
selection selector in CSS keys off it. Do not reintroduce
`data-active` — the command palette's transient keyboard highlight uses
the `.is-active` class and `aria-selected`, which is a different job
(highlight, not selection).

## Hero Metric Utility (0.4.5)

A standalone class for the one prominent numeric KPI per tool
(designator count, diff count, FR rollup total). `RunStatePanel` and the
Review drawer use it for result/progress metrics.

```css
.hero-metric {
  font-family: var(--font-mono);
  font-size: var(--text-xl);
  font-weight: var(--weight-medium);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
  color: var(--text);
  line-height: 1.1;
}
```

## SectionCard Variants (0.4.5)

```ts
type SectionCardVariant = "outlined" | "divided" | "bare";
```

| Variant | Treatment | When to use |
|---------|-----------|-------------|
| `"outlined"` (default) | 1 px border, `var(--section-surface-primary)` background | Primary cards (choice, inputs, mapping, run panel) |
| `"divided"` | `border-top` only, `var(--section-surface-muted)` (transparent) background, `padding-inline: 0` | Supporting content that needs separation without a card |
| `"bare"` | No border, no background, no inline padding | Numbered main workflow sections |

FMEA, BOM Compare, Failure Rate, and RefDes Extractor use numbered
`variant="bare"` sections for their main workflow spine. The persistent
320 px side rail uses dedicated `.rail-card` containers for **Run** and
**Validation**; it is not a SectionCard-based Review/Run tab surface.

## InputGrid Row States

Each `.input-card` now carries a `data-state` attribute computed from
the input's loaded/pending/active status. A 14 px leading indicator shows a
hollow ring, active dot, or `✓`; required roles use a danger-colored `*`
with a tooltip. Row text never dims.

| `data-state` | Condition | Visual treatment |
|--------------|-----------|-------------------|
| `"pending"` | No path picked yet and a different row is active | Hollow neutral ring; full text legibility |
| `"active"` | First missing path, or a row resolving sheets | Accent ring with an inner dot |
| `"loaded"` | Path set, status `"ready"`, sheets resolved | Success-colored `✓` |

Every control stays in the DOM regardless of state so existing tests
still query cards by role/label.

## Keyboard Shortcuts

The shell-level hook `useAppShortcuts` (`frontend/src/shared/hooks/`)
binds every global shortcut. Design-system consumers should prefer
adding bindings there rather than installing ad-hoc listeners.

| Shortcut | Action |
|----------|--------|
| ⌘K / Ctrl+K | Toggle Command Palette |
| ⌘1 … ⌘5 / Ctrl+1 … Ctrl+5 | Jump to tool by index |
| ⌘[ / Ctrl+[ | Previous tool |
| ⌘] / Ctrl+] | Next tool |
| ⌘R / Ctrl+R | Toggle Review drawer (0.4.5) |
| ⌘Enter / Ctrl+Enter | Start the visible tool when its persistent Run rail is ready |
| ⌥L / Alt+L | Switch to Light Precision theme |
| ⌥D / Alt+D | Switch to Dark Precision theme |

Bindings respect `isEditableKeyboardTarget` so typing inside an input
never hijacks a shortcut. The Run shortcut is owned by `RunStatePanel`
rather than `useAppShortcuts`: it is armed only when the panel receives a
`readiness` prop, ignores busy/disabled state, and rejects any panel under a
`[hidden]` keep-alive ancestor. Multiple mounted tools therefore cannot
start together.
