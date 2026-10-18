# Stats at the bottom, stacked by provider, in brand hues (2026-10-18)

Two reviews settled this surface. First the stats card moved from beside “recently ended” to the
bottom of the task chip. Then the daily chart became **stacked provider bars, no total line, no
second axis**, and the provider colours became **brand-led** (Claude orange, dsh blue, Codex
green-teal, OpenCode violet). This note records the final version, the brand-vs-state collision and
the removed caption.

![The stats layer: stacked brand-coloured provider bars for seven days, then the token and completion sections.](task-chip-patrol-stats.png)

## Placement

The stats card is the closing summary of the whole task chip: after the patrol entry, before the
ops footer. The footer is provenance metadata (`ops <sha> · runner api N`) and stays last. The card
is not duplicated at the top. It is a lazy read through `taskStats` on the panel's first open, never
on the queue's 15s poll.

The cost is scrolling to the end of a long panel. That is acceptable for a retrospective read after
the queue; if usage shows it is missed, the next step is a quiet header link, not a duplicate card.

## The chart

Seven local days, one **stacked** bar per day, one provider per segment, one left axis.

- **The measure is tokens.** Title, axis and legend all say token; the API estimate stays in the
  page's table and its own footnote, never in the bars.
- **Stacking makes the total the bar's height by construction.** No total line, no right axis, no
  second aggregation. The seven stacked heights add to the card's token total (the fixture verifies
  786,747,978).
- **No line.** kcn rejected the line as ugly; a line variant would just be a second scale again. The
  stack answers “how much in all?”.
- **Empty days are 0, explicitly.** All seven dates are labelled; a day with no task has no bar, and
  a visible note says “N days had no task, drawn as 0” — only when such a day exists.
- **Zero-task providers are not rows** in the table or the legend; a provider with a real zero-token
  terminal day is a 0-high segment, not a missing one.
- **Seven days, not thirty.** The popover is the last seven days; 30d/all remain the
  `/dispatch-stats` table.

Data path: `task_queue_ops.py summary` fills `daily[date][agent]` in the same read-only pass that
builds the cards (`tasks` for all, `tokens` or `unknown` for terminal only; live adds no tokens;
patrol excluded unless `--all`); `readStats` validates the optional `daily`; an older ops entry
without it still returns the card and the two existing tables, just no chart; `statsView` fills all
seven dates and computes the one axis maximum; `client.ts` draws pure SVG, no chart library, no
second RPC.

## Colour: brand hues, muted into the category band

The previous all-blue scale did not tell providers apart; the four low-chroma pastels did, but kcn
asked for the actual brand identities. The brand hues are used **at the category band**, not at
full saturation:

| Provider | Token | Brand / reason | L | C | Hue |
|---|---|---|---|---|---|
| Claude Code | `--tq-brand-claude` | Anthropic's coral/terracotta | 0.62 | 0.10 | 50 |
| dsh / DeepSeek | `--tq-brand-dsh` | DeepSeek's brand blue | 0.60 | 0.10 | 260 |
| Codex / OpenAI | `--tq-brand-codex` | OpenAI's green-teal | 0.62 | 0.08 | 165 |
| OpenCode | `--tq-brand-opencode` | no strong brand: a violet category, not a state | 0.62 | 0.08 | 310 |
| MiniMax | `--tq-brand-minimax` | a blue-slate overflow slot | 0.62 | 0.06 | 230 |
| other DeepSeek | `--tq-brand-deepseek` | same brand as dsh | 0.60 | 0.10 | 260 |

The fills are `--tq-series-N: color-mix(in oklab, var(--tq-brand-N) 90%, transparent)`; the legend
swatch uses the same tint. The stack area is small (one 18px bar per day), the chroma is 0.06–0.10,
and the lightness is one band (0.60–0.62), so the colours are recognisable brands without the v2
“4,032 px² of full-saturation tiles” problem. The area and saturation are still restrained; only
the hue changed.

### The dsh blue and the whale

The DeepSeek mark is the whale in `renderWhale()`, drawn in `currentColor` (the glyph ink). That ink
is **neutral text**, not a blue: using it as the dsh series would make dsh a grey category and
contradict “dsh 是蓝色”. So:

- the **mark** stays the whale in glyph ink everywhere it is a brand mark (provider rows, agent
  columns);
- the **series** uses the DeepSeek brand blue's hue (260) at the category band, as a separate
  `--tq-brand-dsh`;
- the semantic `--tq-run` (running) is **not** reused or moved; it keeps its assignment. If you
  prefer the glyph ink exactly, `--tq-brand-dsh` is a one-token swap, but the bar would read neutral,
  not blue.

### The collision with state colours — explicit handling

Three brand hues sit near a state hue: Claude orange near partial amber, dsh blue near running/done
blue, Codex green near the healthy check. The rules:

1. **State tokens are not moved.** `--tq-run` = running, `--tq-wait` = warn/partial, `--tq-bad` =
   error, `--tq-text-ok` = healthy. The brand values are new category tokens; the chart's
   `--tq-series-*` are their 90% tints. No state token is the provider value.
2. **Different lightness and chroma.** The category band is L 0.60–0.62, C 0.08–0.10. The state
   marks are brighter/more chromatic (running/done blue, partial amber, error red), and the brand
   orange is a deeper terracotta than the amber warning. The dsh category blue is a quieter
   periwinkle-blue, not the completion bar's saturated blue.
3. **Different marks, positions and words.** The provider colours only appear in the **stacked chart
   + legend** at the top of the stats page. The semantic colours only appear in the **completion
   bars** below, each with its word (`完成 / 部分 / 未完成 / 进行中`) and the per-agent caption. A
   provider colour never fills a state chip; a state colour never fills a provider segment.
4. **The legend names the provider.** The stacked chart's legend is `Claude Code 536.2M`,
   `Codex 116.7M`, `dsh 419.5M`; the completion section has its own legend and headings. No colour
   is asked to carry the distinction alone.
5. **The green exception is spatial.** The stats page has no green state mark; the healthy green
   check lives on the patrol page (a different layer). Codex's green-teal and the check never share
   a screen.

If a future theme makes the category and state colours too close, the fallback is to desaturate the
brand token one step further, not to move the semantic token. The current render is shown above.

## The removed caption and the “+”

The latest screenshot carried a literal caption:

> `8 个任务未记录 token；柱和线是下界 4 个进行中任务未计入 token`

It was stale (“柱和线” — there is no line) and it was narrating two facts that the interface can
carry without a paragraph. This pass:

- **removes the visible unknown/live notes**; the unknown fact stays in each affected segment's
  `<title>` (`8 个未记录`) and the chart's accessible name (`…；8 个任务未记录 token；柱是下界`),
  and the live count stays in the stats card's `进行中 4` and the completion rows;
- **keeps the zero-day note**, but only when a quiet day exists: `N 天没有任务，按 0 计（不是缺数据）`;
- **fixes the stale “柱和线”** everywhere it survived: the `stats.chart.unknown` screen-reader text
  now says `柱是下界`, and the UI has no line/axis copy. Code comments and the design note may still
  say “no line” because that is the decision, not a label.
- **removes the `+?`** in the old chart legend: the legend prints the provider and its number, no
  suffix; the unknown state is the segment title and the aria note.
- **removes the non-verb `汇总 +{n}`** on patrol rows (`汇总 {n}`, `digest {n}`); the action buttons
  `重试 +1` / `截止 +2h` / `续跑 +1` stay: there the plus is the verb “one more”.

The old caption was the one kcn saw; it no longer exists in visible UI.

## Motion

The chart is static: no draw-on, no count-up, no hover easing. The page swaps immediately like a
task detail. The only nearby motion is the patrol strip on its own page, documented in
`task-chip-patrol.md`. Reduced motion is irrelevant here because there is no animation to reduce.

## Alternatives

- **Grouped bars + right total line.** Rejected by kcn: “折线好丑”; it needed a second scale too.
- **Stacked bars + a total line on the same axis.** Still a line; rejected.
- **One hue with light/dark steps.** kcn asked for richer provider differentiation; brand hues do
  it with the area/chroma restraints.
- **Full-saturation brand colours.** Rejected: the v2 “太艳” lesson; the brand is the hue, not the
  saturation.
- **The host's `--viz-*`.** The dsh theme does not expose it (the tokens resolve empty), so this is a
  local category scale; if it appears, swap the six brand declarations.
- **Use the glyph ink for dsh.** It is neutral text; the user asked for blue. The hue is the DeepSeek
  brand blue; the mark stays ink.
- **Move `--tq-run` to the dsh series.** Rejected: the semantic assignment is fixed; the category
  token is separate.
- **A separate stats route.** The existing detail layer already has back/focus; not needed.
- **30 days in the popover.** Too dense; the table covers wider windows.

## Captures

- **`task-chip-patrol-stats.png`** is a real WebKit render of this branch's `lib/client.js` on the
  live dsh. The daily numbers were frozen from the live task directories through the new
  `task_queue_ops.py summary` at 2026-10-18 18:30 HKT. The installed dsh host half is still #3060 and
  does not serve `daily`; this is a preview of the new host half, with **no install or restart**.
- **`task-chip-patrol-summary.png` / `task-chip-patrol-panel.png`** show the stats card at the bottom
  of the panel. The stats card is the later lazy read, as it is live.
- The daily numbers are real, not a schematic. The only schematics in this PR are the patrol entry
  and page's open-count variants, labelled in the patrol note.
- The v4 chart (four low-chroma pastels, before the brand pass) is kept at
  `task-chip-patrol-v4-stats.png` for the PR's history.
