# Stats at the bottom, stacked by provider (2026-10-18)

Two reviews changed this surface. First the stats card moved from beside “recently ended” to the
bottom of the task chip; then the daily chart was simplified: **stacked provider bars, no total
line, no second axis**, and a wider provider palette. This note records the final version and the
colour decisions behind it.

![The stats layer: stacked provider bars for seven days, then the token and completion sections.](task-chip-patrol-stats.png)

## Placement

The stats card is the closing summary of the whole task chip: after the patrol entry, before the
ops footer. The footer is provenance metadata (`ops <sha> · runner api N`) and stays last; putting
content below it would squeeze it into the middle. The card is not duplicated at the top: a second
one-line summary would recreate the “stats next to the queue” adjacency and add another surface to
keep in sync. The card is a lazy read through the existing `taskStats` call, on the panel's first
open, never on the queue's 15s poll.

The cost is scrolling to the end of a long panel. That is acceptable for a retrospective read after
the queue. If usage shows it is missed, the next step is a single quiet link in the panel header,
not a duplicate card.

## The chart

Seven local days, one **stacked** bar per day, one provider per segment, one left axis.

- **The measure is tokens.** Title, axis and legend all say token; the API estimate stays in the
  page's table and its own footnote, never mixed into the bars.
- **Stacking makes the total the bar's height by construction.** There is no total line and no
  right axis, so there is no second aggregation to drift: each segment reads the same per-provider
  `day.tokens[provider]` values, and the full bar is their sum. The seven stacked heights add up to
  the card's token total (the fixture verifies 786,747,978).
- **No line.** kcn's review rejected the line as ugly; a line variant would just be the grouped
  chart with a second scale again. The stack itself answers “how much in all?”.
- **Empty days are 0, explicitly.** All seven dates are labelled; a day with no task has no bar and
  the note says “N days had no task, drawn as 0”. Nothing is skipped, so a gap cannot read as “no
  data”.
- **Unknown is not 0 and has no plus.** A provider-day with terminal tasks whose `TOKENS_TOTAL` was
  empty is marked on its segment's `data-unknown`/title and counted in the lower-bound note; the
  legend shows the number only, no `+?`. The bar is the known tokens, never a fabricated 0.
- **Live is separate.** Live tasks are tasks but not tokens; a note says how many are outside the
  token bars.
- **Seven days, not thirty.** The stats surface is the last seven days; 30d/all remain the
  `/dispatch-stats` table. A 30-day stack in a 300px popover would be a comb of hairlines.

Data path, unchanged in spirit:

1. `task_queue_ops.py summary` loops the task directories once, and in that same pass fills
   `daily[date][agent]` with `tasks`, and for terminal tasks only `tokens` or `unknown`. The same
   frozen `result.env` values feed the aggregate and the bucket; no session is reread; live adds no
   tokens; patrol stays out unless `--all`.
2. `readStats` validates the optional `daily` object. An older ops entry without it still returns
   the card and the two existing tables; the chart is omitted. A malformed `daily` makes the stats
   read unavailable rather than drawing a fake chart.
3. `statsView` fills every date in the window (including quiet ones), assigns the provider order
   and computes the one axis maximum. `client.ts` draws pure SVG; no chart library, no second RPC.

## Colour: four hues, one lightness, low chroma

The earlier “too loud” feedback was about **area at full saturation**, not about the number of
hues. This chart needs more hues to tell providers apart, so the two are reconciled by holding the
area, chroma and lightness down:

| Provider slot | Token | Hue | Lightness | Chroma |
|---|---|---|---|---|
| 1 | `--tq-viz-1` | indigo 275 | 0.62 | 0.10 |
| 2 | `--tq-viz-2` | teal 195 | 0.62 | 0.08 |
| 3 | `--tq-viz-3` | violet 325 | 0.62 | 0.09 |
| 4 | `--tq-viz-4` | olive 110 | 0.62 | 0.07 |
| overflow | `--tq-viz-5/6` | slate / violet-grey | 0.62 | 0.05 / 0.04 |

- **Uniform lightness 0.62**, so no provider shouts louder than another; the hue separates them.
- **Low chroma 0.04–0.10**, well below the semantic state colours; the chart is not a row of
  warnings.
- **The bar fill is a 90% tint** of the base over the panel
  (`--tq-series-N: color-mix(in oklab, var(--tq-viz-N) 90%, transparent)`); the legend swatch uses
  the same tint. The stack area is small (one 18px bar per day), not a wall.
- **No semantic token is used as a category.** The hues are a new local viz scale, not
  `--tq-run`/`--tq-wait`/`--tq-bad`; the completion bars below keep their semantic blue/amber/red.
  None of the four values is a hex or a hand-picked pastel: the palette is written once as
  `oklch()` on `.pbc`, and the tint is derived.
- **No `--viz-*` dependency.** The dsh theme does not expose the dashboard's chart palette (the
  tokens resolve empty), so this local scale is the fallback. If dsh later exposes `--viz-*`, the
  six declarations can be replaced with those tokens; nothing else changes.

The chart is static. It is a reading, not a transition: no draw-on, no count-up, no hover easing;
the page swaps in immediately like a task detail. The only motion nearby is the patrol strip in its
own page, documented in `task-chip-patrol.md`.

## The “+” removal

The latest screenshot had a literal **`+?`** in the old chart legend, marking provider-days with
unrecorded tokens. kcn asked why a `+` was there; that was the one he saw. It is gone:

- the legend now prints the provider and its token total with no suffix;
- the unknown state is a lower-bound note and the segment's title, not a plus;
- the patrol round's quantity copy also lost its non-verb plus: `汇总 +{n}` is now `汇总 {n}`
  (`digest +{n}` → `digest {n}`);
- the **action buttons** `重试 +1` / `截止 +2h` / `续跑 +1` are untouched: there the plus is the
  verb (“one more”), not a number pretending to be an increment.

## Alternatives

- **Grouped bars + right total line.** Rejected by kcn: “折线好丑”; and the grouped version needed
  a second scale to keep the total readable.
- **Stacked bars + a total line on the same axis.** Still a line, and it would trace the stack top;
  kcn rejected the line, so it is not a fallback.
- **One hue with light/dark steps.** Rejected for this round: kcn asked for richer provider
  differentiation; four low-chroma hues do that while the uniform L/small area keep it calm.
- **A separate stats route.** The existing detail layer already has the back bar and focus return;
  a route is a larger app change.
- **A summary at the top.** Duplicate stats surface; a header link is the later option if needed.
- **30 days in this popover.** Too dense; the CLI/table covers wider windows.

## Captures

- **`task-chip-patrol-stats.png`** is a real WebKit render of this branch's `lib/client.js` on the
  live dsh. The daily numbers were frozen from the live task directories through the new
  `task_queue_ops.py summary` at 2026-10-18 18:30 HKT. The installed dsh host half is still #3060
  and does not serve `daily`; this is a preview of the new host half, with **no install or restart**.
- **`task-chip-patrol-summary.png` / `task-chip-patrol-panel.png`** show the stats card at the bottom
  of the panel; their queue/patrol is frozen at 17:06. The stats card is the later lazy read, as it
  is live.
- The daily numbers are real, not a schematic. The only schematics in this PR are the patrol entry
  and page's open-count variants, labelled in the patrol note.
