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
| `--text-on-accent` | Foreground for elements filled with `--accent` | `#ffffff` |

Every theme overrides the same set of tokens. No theme adds new color names.

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
| `--text-md`  | 16 px | Section card titles |
| `--text-lg`  | 18 px | Subsection headlines |
| `--text-xl`  | 20 px | Tool banner title |
| `--text-2xl` | 24 px | Legacy headline size; retained for unchanged consumers |
| `--text-xxl` | 28 px | Topbar `<h1>` (bumped in 0.4.5) |
| `--text-3xl` | 32 px | Hero metric utility (opt-in, see below) |

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
| `--tracking-uppercase` | 0.08em |

`--tracking-uppercase` was standardized at `0.08em` in Phase G. Every
uppercase metadata label — eyebrows, status chips, scenario pill meta,
header metrics, Mission Control typography overrides — references this
token so spacing stays consistent across the shell.

## Spacing Tokens

All spacing follows a 4 px grid. Phase G introduced an 8-step scale; every
component CSS file references these tokens for `padding`, `margin`, `gap`,
and `min-height`.

| Token | Value | Intended use |
|-------|-------|--------------|
| `--space-1` | 4 px | Micro: icon gaps, fine adjustments |
| `--space-2` | 8 px | Tight: within components |
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
| `--gap-section` | `var(--space-7)` (32 px) | Between SectionCards or other major regions |
| `--gap-page` | `var(--space-8)` (48 px) | Major page-level regions |

Adoption is opportunistic — no call-site migration shipped in 0.4.5.

## Border Radius Tokens

Expanded from 3 radii to 6 in Phase G.

| Token | Value | Intended use |
|-------|-------|--------------|
| `--radius-xs` | 4 px | Tiny: dropdown items, chips |
| `--radius-sm` | 6 px | Small: buttons, inputs |
| `--radius-md` | 8 px | Default: cards, sections |
| `--radius-lg` | 10 px | Large: prominent containers (analysis cards) |
| `--radius-xl` | 12 px | Extra: rail tool buttons, brand glyph |
| `--radius-pill` | 999 px | Pill: badges, progress bars |

## Shadow Tokens

**Depth strategy is borders-only by default.** Shadows are reserved for
floating, focused, or instrument-style elements and exist as named tokens
so per-theme overrides can tune their intensity.

| Token | Default value | Intended use |
|-------|---------------|--------------|
| `--shadow-popover` | `0 10px 28px rgba(15, 23, 42, 0.12)` | Dropdowns, menus, custom-select popovers |
| `--shadow-focus-ring` | `0 0 0 3px rgba(35, 94, 231, 0.08)` | `:focus-visible` state on all interactive elements |
| `--shadow-rail-active` | `0 0 0 1px rgba(35, 94, 231, 0.04), 0 6px 18px rgba(35, 94, 231, 0.08)` | Selected tool button in the rail |
| `--shadow-toast` | `0 8px 24px rgba(15, 23, 42, 0.08)` | Notification toasts |

Per-theme overrides exist for `dark_precision`, `midnight_blue`,
`high_contrast`, `synthwave`, and `mission_control` — dark themes need
stronger rgba values because light-theme shadows are invisible against
dark surfaces.

**Don't add decorative box-shadows to the global stylesheet.** If a theme
needs a glow or halo effect, scope it inside that theme's override block
(see **Mission Control Theme Exception** below).

## Motion

| Token | Value |
|-------|-------|
| `--ease` | `cubic-bezier(0.25, 1, 0.5, 1)` |

## Icon Size Conventions

Phosphor icons are used throughout the shell. The size is set on the
component, not via CSS, so each call site picks the right scale. Use
`weight="bold"` for accent/active states.

| Size | Context |
|------|---------|
| 12 px | Inline meta (timestamps, counts next to text) |
| 14 px | Button glyphs (primary/ghost button icons) |
| 16 px | Chip glyphs (status chips, toggle chips) |
| 20 px | Rail navigation (tool buttons, theme chip) |
| 24 px | Hero / empty state illustrations |

## Asymmetric Padding (AppShell)

Not every shell surface uses symmetric padding. `AppShell.module.css`
intentionally uses asymmetric values, each with an inline comment
explaining the deviation:

| Surface | Padding (top / right / bottom / left) | Reason |
|---------|---------------------------------------|--------|
| `.rail` | `20 / 16` | Extra vertical breathing room above/below tool icons; narrower sides to keep the rail compact |
| `.topbar` | `20 / 24 / 0` | Bottom padding is `0` so the accent gradient (see below) sits flush with the content boundary |
| `.content` | `16 / 24 / 24` | Asymmetric top padding compensates for the topbar's zero-bottom so total gap stays 20 px |

When adjusting these, preserve the inline comment and the reasoning — the
asymmetry is load-bearing for the accent-gradient alignment.

## Signature Topbar Accent Gradient

Phase G13 introduced a 1 px accent gradient at the top edge of the App
shell topbar:

```css
.topbar::before {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(
    to right,
    transparent 28%,
    var(--accent) 50%,
    transparent 72%
  );
  opacity: 0.35;
}
```

This mirrors the existing `.run-log-panel::before` gradient at the top
edge of the global log panel, creating a visual rhyme where the active
tool area is framed between two "instrument chrome" lines.

**Invariant.** The gradient stop positions (`28%` / `72%`) must stay in
sync between `.topbar::before` and `.run-log-panel::before`. If you adjust
one, adjust the other in the same change.

## Global Run Log Panel Styling

The `GlobalLogPanel` (Phase B) is docked at the bottom of the app shell.
Its styling choices:

- **Font.** Log lines use `var(--font-mono)` (JetBrains Mono). Timestamps
  additionally apply `font-variant-numeric: tabular-nums` so columns stay
  aligned when the seconds digits change.
- **Level colors.** Each log level maps to a token:
  - `info` → `var(--accent)`
  - `warning` → `var(--warning)`
  - `error` → `var(--danger)`
  - `debug` → `var(--text-faint)`
- **Layout.** Log rows use a 4-column CSS grid: `64px 56px 160px 1fr`
  (time / level / tool / message).
- **Body height.** `max-height: 280px` when expanded; scrolls internally.
- **Collapse.** A chevron button in the header toggles the body.
- **Top edge.** The 1 px accent gradient described in **Signature Topbar
  Accent Gradient** — same stop positions, same opacity.
- **Status dot (added 0.4.5).** A 10 px circle next to the "Run Log"
  title reflects the current `runStore.activeRun.phase`:
  idle = `var(--text-faint)`, active = `var(--accent)` with a 1.6 s
  pulse, good = `var(--success)`, warn = `var(--warning)`,
  bad = `var(--danger)`. Decorative only (`aria-hidden`); meaning is
  carried by the log body text itself.
- **Collapsed count legibility (0.4.5).** The truncation/entry-count
  text bumped from `var(--text-2xs)` / `var(--text-faint)` to
  `var(--text-sm)` / `var(--text-secondary)` so the summary reads as
  data, not decoration.
- **Resize handle (0.4.5).** Hit area widened 6 px → 10 px; the hover
  band still activates on the same rule, just over a larger grab zone.

## Mission Control Theme Exception

Mission Control is **the only theme allowed to use decorative
box-shadows**. Every other theme uses borders-only depth. The two
exceptions Mission Control carries are the cyan glow on
`.status-chip--success` and the cyan-tinted halo on `.input-card:hover`
(documented in the next section).

**Rule.** Do not add new `box-shadow` declarations to the global
stylesheet for decorative purposes. If you need a glow effect for a
specific theme, scope it inside that theme's
`:root[data-theme="..."]` block.

## Hover/Focus State Audit

Every interactive element in the shell now has a consistent
`:focus-visible` style using `var(--shadow-focus-ring)`. The audit covers:
`.toggle-chip`, `.panel-toggle__button`, `.primary-button`, `.ghost-button`,
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
| Kraft Paper | `kraft_paper` | Workshop notebook aesthetic | Warm paper and graphite (light). Icon: NotePencil |
| Forest Depth | `forest_depth` | Biophilic dark theme for long runs | Deep pine and moss (dark). Icon: TreeEvergreen |
| Graphite Dawn | `graphite_dawn` | Newsprint precision | Soft charcoal on warm ivory (light). Icon: Compass |

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
| `SectionCard` | `SectionCard.tsx` | Bordered card with eyebrow, title, description, and an actions slot. `variant="outlined" \| "divided" \| "bare"` (default `"outlined"`) added in 0.4.5 |
| `ContextDrawer` | `ContextDrawer.tsx` | Right-anchored overlay "Review" drawer toggled by ⌘R / Ctrl+R (new in 0.4.5). Renders run summary + `output_preview` table; informational, not modal |
| `InputGrid` | `InputGrid.tsx` | Grid of input file cards with status chips and sheet pickers. Each card carries `data-state="pending\|active\|loaded"` driving the stepper CSS added in 0.4.5 |
| `MappingTable` | `MappingTable.tsx` | Column-mapping table for canonical → mapped pairs |
| `RunStatePanel` | `RunStatePanel.tsx` | Sticky run-state panel: button, progress, timeline, result |
| `WorkflowSelector` | `WorkflowSelector.tsx` | Workflow choice cards (emits both `data-active` and `data-selected`) |
| `StrategySelector` | `StrategySelector.tsx` | Output strategy cards (emits both `data-active` and `data-selected`) |
| `CustomSelect` | `CustomSelect.tsx` | Accessible dropdown with keyboard navigation |
| `ValidationPreview` | `ValidationPreview.tsx` | Pre-run validation message list |

### Primitives (`components/primitives/`)

Reusable building-block components extracted from tool surfaces.

| Component | File | Purpose |
|-----------|------|---------|
| `CommandPalette` | `CommandPalette.tsx` | Ctrl+K action search and navigation overlay |
| `ToggleChip` | `ToggleChip.tsx` | Boolean toggle styled as a chip |
| `OptionsField` | `OptionsField.tsx` | Labeled field wrapper for option controls |
| `ContextTabs` | `ContextTabs.tsx` | Tabbed context switcher |
| `CheckboxField` | `CheckboxField.tsx` | Labeled checkbox with description |
| `OptionsSection` | `OptionsSection.tsx` | Grouped options container with heading |
| `HoldButton` | `HoldButton.tsx` | Press-and-hold confirmation button |
| `EmptyState` | `EmptyState.tsx` | Placeholder for empty content areas |

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

## Pill, Chip, Badge Vocabulary (0.4.5)

`.status-chip` was previously used for three different jobs — runtime
state, classification, and keyboard hints — all rendered as filled pills.
The 0.4.5 design pass split the vocabulary so each job has one
treatment. `.status-chip` is retained as a legacy alias of `.badge-state`
so existing call sites keep working; call-site migration is
opportunistic.

| Class | Treatment | Role | Examples |
|-------|-----------|------|----------|
| `.badge-state` (+ `--good` / `--warn` / `--bad` / `--idle`) | Filled, semantic color | Runtime state a user needs to notice | `LOADED`, `VALIDATED`, `ERROR`, `MAPPED` |
| `.tag-category` | Outlined neutral | Classification without urgency | `FUNCTIONAL`, `PIECE-PART`, `LEAN`, `BALANCED` |
| `.kbd-shortcut` | Text-only monospace, no box | Keyboard hint | `⌘K`, `⌘R`, `CTRL+[` |

Mixing treatments is a smell — a card full of filled pills trains the eye
to ignore color. Pick the one that matches the role.

## Selection State (0.4.5)

A single global rule handles every "you picked this one" UI affordance so
choice cards, theme tiles, radio chips, and workflow cards look the same
when selected:

```css
[data-selected="true"] {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--text);
}

[data-selected="true"] .eyebrow,
[data-selected="true"] .section-card__eyebrow,
[data-selected="true"] .choice-card__eyebrow {
  color: var(--accent);
}
```

`StrategySelector`, `WorkflowSelector`, `ToggleChip`, and the Settings
theme tiles emit both `data-selected={isSelected}` and the pre-existing
`data-active={isSelected}`. The two attributes coexist during the
migration — component CSS still keys off `data-active` where it already
does; new surfaces should prefer `data-selected`.

## Hero Metric Utility (0.4.5)

A standalone class for the one prominent numeric KPI per tool
(designator count, diff count, FR rollup total). Available for opt-in;
no call site adopts it in 0.4.5.

```css
.hero-metric {
  font-size: var(--text-3xl);
  font-weight: var(--weight-semibold);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
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
| `"divided"` | `border-top` only, `var(--section-surface-muted)` (transparent) background, `padding-inline: 0` | Supporting sections like the Review Panel — quieter than primary |
| `"bare"` | No border, no background, no inline padding | Free-flow content that just needs the title block |

The FMEA, BOM Compare, Failure Rate, and RefDes Extractor tools all use
`variant="divided"` on their Review Panel SectionCards. Every other
call site relies on the `"outlined"` default.

## InputGrid Progressive Disclosure (0.4.5)

Each `.input-card` now carries a `data-state` attribute computed from
the input's loaded/pending/active status and a step-indicator span
showing the step number or `✓`:

| `data-state` | Condition | Visual treatment |
|--------------|-----------|-------------------|
| `"pending"` | No path picked yet AND a different card is already `"active"` | Dimmed (`opacity: 0.62`), decoration-tinted background; hover/focus restores full opacity |
| `"active"` | First card missing a path, OR a card that's resolving sheets | Outlined in `var(--accent)`; full legibility |
| `"loaded"` | Path set, status `"ready"`, sheets resolved | Decoration-tinted background; indicator flips to ✓ with success tint |

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
| ⌥L / Alt+L | Switch to Light Precision theme |
| ⌥D / Alt+D | Switch to Dark Precision theme |

Bindings respect `isEditableKeyboardTarget` so typing inside an input
never hijacks a shortcut.
