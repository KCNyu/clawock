# Dashboard design system

The standard a new component on `site/` is built from. Everything here exists as
a token or a rule in `site/assets/css/dashboard.css` (the one stylesheet for the
dashboard and the reading pages); this page says which one to pick and when not
to. Gates that enforce a rule are named beside it, so "is this still true?" has
a command to run.

If a design needs a value that is not on these scales, the scale is what gets
discussed and changed — not the component.

## 0. The one rule

**Colour on this dashboard is data.** Gain and loss, on-limit and over-limit,
healthy and broken are read off colour before the number is read. So the
palette is two layers that never trade places:

- **Semantic** colours say *what something is* (a gain, a breach). Their
  assignment is fixed. Their values may be tuned only as a set, in `:root`, and
  never so that a meaning changes hands.
- **Everything else** — surfaces, text steps, borders, the accent, chart
  series — is furniture. It may be restyled, as long as it never looks like the
  semantic layer.

A change that makes the page calmer and swaps which colour means "loss" has
made a screen that misreports money look nicer.

## 1. Colour

### 1.1 Semantic — state and direction

| Token | Means | Use it for | Never for |
|---|---|---|---|
| `--positive` | gain, up, passed, healthy | signed P&L, up moves, a win, a met condition | a category, a brand accent, "selected" |
| `--negative` | loss, down, breached, failed | signed P&L, down moves, a loss, a hard-gate breach | "this is mine", "important", an author |
| `--warning` | needs a look; not yet wrong | stale data, soft limits, mid-band scores | a second accent, a chart series, an asset class |
| `--neutral` | no verdict | pending, unknown, a category chip | dimming text (use a text step) |
| `--positive-display` / `--negative-display` | the same two meanings at headline size | the one hero figure | anything under `--fs-xxl` |
| `--positive-ink` / `--negative-ink` / `--warning-ink` / `--accent-ink` | text on a tint of its own hue | the label inside a status badge | text on a bare surface |

Rules:

- **Up is `--positive`, down is `--negative`, in both themes.** There is no
  locale switch and no component-level override.
- **Colour is never the only carrier.** A signed number keeps its sign; a status
  keeps its word or its glyph (the refresh button's two outcomes differ by
  shape, not only by tint).
- **A category is not a state.** "Who said it", "which signal family", "which
  market" are categories: they take `--neutral` or `--accent`, and the label
  carries the distinction. Author badges and driver chips used to borrow green,
  red and amber; a red author beside a red "bearish" badge said two different
  things in one colour.
- **A number never sits on a fill of a status or accent hue** strong enough to
  move its contrast. A badge is the exception and uses the `-ink` step.

How this stays true: component rules may only name these tokens (§6), so what a
class means is readable in its one line, and `tests/test_dashboard_contrast.py`
resolves every tinted badge on every surface in both themes.

### 1.2 Surfaces

Six rungs, each visibly a step (`test_every_surface_step_is_a_step_a_reader_can_see`):
`--bg` → `--surface-0` → `--surface-1` → `--surface-2` → `--surface-3` → `--overlay`.

Components do not pick a rung. They name a **role**:

| Role token | Is | Use |
|---|---|---|
| `--fill-card` | a card | `.card` |
| `--fill-inset` | a block inside a card | `.inset-block`, table headers, wells |
| `--fill-inset-2` | a block inside a block | rare; if you need a fourth level, flatten the layout |

Never fill a rounded block with the colour of what it sits on
(`test_nothing_rounded_is_painted_the_colour_of_the_card_it_sits_on`).

Glass (`--glass-deck` / `--glass-card` / `--glass-thin` with the matching
`--blur-*`) is for the first screen's three surfaces, the top bar, the menu and
drawers. A new card is not glass. Any frosted rule must be neutralised in the
`prefers-reduced-transparency` block
(`test_every_frosted_surface_turns_solid_under_reduced_transparency`).

### 1.3 Text

| Token | Use | Contrast on `--surface-1` (dark / light) |
|---|---|---|
| `--text-primary` | figures, titles, body | 15.5 / 17.9 |
| `--text-secondary` | labels, captions, category-chip text | 7.8 / 6.4 |
| `--text-tertiary` | metadata, timestamps, axis labels | 5.1 / 5.7 |

Quiet text is a text step, **never `opacity`**
(`test_no_markup_dims_text_with_inline_opacity`).

### 1.4 Borders, shade and gloss

- `--border-subtle` divides; `--border-strong` outlines a control or marks a
  quoted block.
- `--shade-1…4` are the strengths of darkness laid on a surface (well, scroll
  edge / scrim, contact shadow, far shadow); `--gloss-1/2` the highlights on a
  small filled mark. They carry their own ink per theme, so a rule writes the
  rung and gets black on the dark page and the navy shadow ink on the light one.
- Elevation is `--shadow-card`, `--shadow-card-hover`, `--shadow-topbar`. There
  is no fourth shadow.

### 1.5 Accent

`--accent` is the brand blue: links, the active tab, selection, "this row is
about your holdings", progress. `--accent-strong` is its pressed/emphasis step,
`--accent-soft` its opaque wash, `--focus` the ring. One accent. A second
decorative hue is how the page got busy.

### 1.6 Tints

A status or accent hue behind text comes in four strengths only:

| Token | Strength | Use |
|---|---|---|
| `--tint-wash` | 7% | touching a whole row |
| `--tint-soft` | 15% | the fill of a badge |
| `--tint-strong` | 35% | a bar segment, a solid badge with no text on it |
| `--tint-edge` | 40% | a same-hue outline |

Written as `color-mix(in srgb, var(--negative) var(--tint-soft), transparent)`
(`test_status_tints_come_off_the_tint_scale`).

### 1.7 Chart series

A chart needs to tell series apart, and a series is a category. It therefore has
its own palette, used **only** inside charts:

`--viz-1` … `--viz-6` (the cool blue–indigo–slate run, separated by lightness)
and `--viz-warm` (the single warm contrast line).

- Series that *are* a state (a win/loss bar, an up/down candle) use the semantic
  tokens. Series that are merely different use `--viz-*`.
- `--viz-warm` has the same value as `--warning` today. That is a coincidence of
  two palettes, not an alias: neither may be defined as the other.
- Canvas code reads the palette through `getCSS("--token")` (the names it may
  ask for are `THEME_CSS_KEYS` in `dashboard.core.js`); it never carries a hex
  of its own (`test_chart_colours_come_from_the_palette_too`).

## 2. Motion

### 2.1 What moves and what does not

Ask in this order; stop at the first "no".

1. **How often is it seen?** Something triggered from the keyboard or dozens of
   times a session (switching tabs, sorting, hovering rows) gets no movement — a
   colour change at most. Occasional things (opening a fold, a drawer, an error)
   get the standard treatment. Only a rare completion gets anything more.
2. **Which of these is it for?** *Feedback* (the page heard you), *state* (this
   changed), *origin* (this came from there), *no jump* (this would otherwise
   teleport). "It looks alive" is not on the list.
3. **Is it data the reader is reading?** Then it does not move. In particular:
   **a figure is never tweened or rolled.** Every value on screen at every
   instant is a real one; an interpolated P&L is a number that was never true.
   A figure that changed is *marked*, not animated (§2.4).
4. **Can it run on `transform` and `opacity` alone?** Layout is not animated.
   Colour may transition (it repaints, it does not reflow).

### 2.2 Durations

| Token | Value | For |
|---|---|---|
| `--duration-instant` | 100ms | the press under the finger |
| `--duration-fast` | 150ms | small things changing state: colour, icon, caret, hover; release of a press |
| `--duration-standard` | 240ms | a block arriving or moving: fold content, banner tone, bars reaching their length, a drawer |
| `--duration-slow` | 400ms | reserved; an interaction never uses it |
| `--duration-enter` / `--duration-exit` | standard / fast | role aliases — leaving is one step quicker than arriving |
| `--duration-mark` | 1600ms | how long a change mark stays; a notice, not a transition |

Loops (`infinite`) state their own period and are the only place a literal time
may appear.

### 2.3 Curves

| Token | For |
|---|---|
| `--ease-out` | entering, leaving, answering a press — the default |
| `--ease-in-out` | something already on screen travelling from A to B |
| `--ease-standard` | colour or opacity only, nothing moves |
| `--ease-drawer` | a sheet sliding in from an edge |
| `--ease-spring` | one use: the "new data landed" tick. 1.5% overshoot. Not for ordinary controls |
| `--ease-linear` | constant motion: the spinner, the loading line |

There is no ease-in: it spends the first frames — the ones being watched —
barely moving (`test_the_motion_scale_is_complete_and_nothing_eases_in`).
A transition or animation names a duration token and a curve token; nothing
else (`test_no_transition_or_entrance_invents_its_own_timing`).

### 2.4 The motion that exists, and its reduced form

`prefers-reduced-motion: reduce` collapses every transition and animation to an
instant change (the global block in `dashboard.css`); JS-driven motion reads the
same query. Where the motion carried information, a static form replaces it.

| What | Why | Normal | Reduced motion |
|---|---|---|---|
| Press on any control | feedback | scale to `--press-scale`, in `instant`, out `fast` | instant scale |
| Hover lift on a card (fine pointers only) | feedback | `--hover-lift`, `fast` | instant |
| Tab indicator, carets, fold arrows | state | `fast`, `--ease-out` | instant |
| Fold opened by the reader | no jump | content fades in, `enter`; layout is immediate; closing is instant | no fade |
| Panel loading | state | 2px line travelling the top edge; content at 55% | the line spans the edge, still |
| Panel loaded | no jump | content returns to full opacity, `standard` | instant |
| Panel load error | no jump | box fades in and rises `--enter-shift` | appears |
| First figures on the first screen | no jump | three blocks fade in 40ms apart, once per page load | appear |
| A figure changed in a refresh | state | accent underline under the changed figure, held then faded over `--duration-mark` | the underline holds, then is removed, no fade |
| Verdict banner changes tone | state | fill and border cross to the new colour, `standard` | instant |
| Refresh in flight / landed | feedback | spinner; then ✓ pops with `--ease-spring` | spinner still; ✓ appears |
| Deck of verdict cards | origin | spring that follows the finger (JS) | cross-fade |
| Decision-map drawer | origin | slides from its edge, `--ease-drawer` | appears |
| Chart intro | — | ECharts default | duration 0 |

Deliberately still: switching tabs, sorting a table, table rows on hover, the
hero figure itself, anything on a timer that is not loading.

The change mark is an underline and not a fill for a measured reason: a 35%
accent fill takes a loss figure on the dark card from 5.1:1 to 2.7:1.

## 3. Space, corners, elevation, type

**Spacing** — `--space-1…6` = 4 / 8 / 12 / 16 / 24 / 32px. Between blocks in a
card: `--space-3`. Between cards: `--space-3` (phone) / `--space-4` (desktop).
Above a section divider: `--space-5`. Space between blocks is the *following*
block's top margin; a card has no bottom margin.

**Corners** — `--radius-sm` 6 (chips, inset blocks, controls) · `--radius` 10 ·
`--radius-float` 12 (menus, tooltips) · `--radius-lg` 16 (cards). Pills are
`999px`, dots `50%` (`test_container_corners_come_off_the_corner_scale`).

**Type** — eight sizes, `--fs-display` / `xxl` / `xl` / `lg` / `md` / `sm` /
`xs` / `micro`, and no bare `px`
(`test_every_font_size_is_a_step_of_the_type_scale`). `--mono` is for figures
and code; `--font` for every word. Tracking tightens with size
(`--tr-display…lg`); body text has none.

**Touch** — a control is at least 44px of finger on a coarse pointer, whatever
it paints.

## 4. Component recipes

### 4.1 Card

`<section class="card">` with an `<h3>`. Surface `--fill-card`, corner
`--radius-lg`, `--shadow-card`, padding `--space-4`. No colour of its own; if a
card must announce a state, the state goes in a badge in its header.

### 4.2 Block inside a card

`class="inset-block"` (`--fill-inset`, `--border-subtle`, `--radius-sm`) plus
your padding. Never a tinted box: a block that is green because it is "the
domestic one" has borrowed a state it does not have.

### 4.3 Key–value row

Label in `--text-secondary` at `--fs-xs`/`--fs-sm`; value in `--mono`,
`--text-primary`, `font-variant-numeric: tabular-nums`. A signed value adds
`.pos` / `.neg` and keeps its sign. Rows are divided by `--border-subtle`.

### 4.4 Status badge

```css
.my-badge.is-bad {
  background: color-mix(in srgb, var(--negative) var(--tint-soft), transparent);
  color: var(--negative-ink);
}
```

Fill = hue at `--tint-soft`; text = that hue's `-ink`. A category badge is the
same shape with `--neutral` and `--text-secondary`. The contrast gate finds any
rule of this form by itself; nothing needs registering.

### 4.5 Empty, loading, error

- **Empty** — `.empty-state`: one quiet sentence saying what would be here.
  Never a blank card; a blank holdings table reads as "you hold nothing".
- **Loading** — set `aria-busy="true"` on the panel; the stylesheet draws the
  line and dims the content. Skeletons are still bars (`.dm-skel`), never
  shimmering.
- **Error** — `.panel-load-error` with a real `<button class="panel-load-retry">`.
  It says what is being shown instead ("the last loaded content").

### 4.6 Any control

Use a `<button>`, `<summary>` or `role="button"`. Focus ring, press and touch
target then come from the baselines. If the rule writes its own `transition`,
it must name `transform` too
(`test_a_control_that_writes_its_own_transition_still_names_transform`). Hover
styles live inside `@media (hover: hover) and (pointer: fine)`.

## 5. Accessibility

- **Contrast** — text ≥ 4.5:1 on the surface it actually sits on, tint included;
  chart marks and the focus ring ≥ 3:1. Measured, not eyeballed:
  `tests/test_dashboard_contrast.py`.
- **Focus** — one ring, `var(--focus-ring)`, offset 2px outside or −2px inside a
  clipping box (`test_one_focus_ring`). `outline: none` only where the rule
  draws its own replacement.
- **Keyboard** — everything clickable is reachable and operable with Tab and
  Enter/Space; state is exposed (`aria-sort`, `aria-expanded`, `aria-busy`).
- **Reduced motion** — §2.4, per item. **Reduced transparency** — glass turns
  solid. A new animation ships with its reduced form in the same change.
- **Announcements** — a refresh result goes to the `role="status"` region, not
  only to a colour.

## 6. Not allowed

| Don't | Do | Gate |
|---|---|---|
| A colour literal (`#hex`, `rgb()`, `rgba()`) in a component rule or in chart code | a token; add one to `:root` in **both** themes if a role is missing | `test_a_colour_is_written_once_in_the_palette_and_named_everywhere_else`, `test_chart_colours_come_from_the_palette_too` |
| A status hue for a category, an author, a market, or emphasis | `--neutral` / `--accent` + a label | review; §1.1 |
| A legacy alias (`--green`, `--red`, `--amber`, `--card-2`, …) | the semantic or role name | `test_status_colours_have_one_name_each` |
| A tint percentage of your own | `--tint-*` | `test_status_tints_come_off_the_tint_scale` |
| A literal duration, a bare `ease`, a `cubic-bezier()` in a rule | `--duration-*` + `--ease-*` | `test_no_transition_or_entrance_invents_its_own_timing` |
| `ease-in`; `transition: all` | `--ease-out`; name the properties | `test_the_motion_scale_is_complete_and_nothing_eases_in` |
| Animating a figure's value, or `width`/`height`/`top`/`left` | mark the change (§2.4); `transform`/`opacity` | review |
| An entrance from `scale(0)` | opacity, plus `--enter-shift` for small blocks | review |
| `opacity` to quieten text | a text step | `test_no_markup_dims_text_with_inline_opacity` |
| A bare `px` font size or a corner off the scale | `--fs-*`, `--radius-*` | type-scale and corner gates |
| `:hover` outside the fine-pointer media query | wrap it | `test_hover_is_never_left_stuck_on_a_touch_screen` |
| A new inline `style="background:…"` / `style="color:#…"` in a renderer | a class | review |

The gates live in `tests/test_dashboard_component_language.py`,
`tests/test_dashboard_css_tokens.py` and `tests/test_dashboard_contrast.py`.
