# Data Health card (2026-09-25 rewrite)

The card answers three questions, in this order: **is anything wrong, where, and
what exactly happened?** The 2026-09-24 iterations (#1834, #1836, #1838) stacked a
verdict, a metric tile row, an overview strip, a to-do list, a lane board, a
per-job board, a grey summary band and a bottom detail panel at nearly equal
weight. The owner rejected them: the layout was chaotic and the text/card edges
were wrong. This version was rebuilt from an empty section, reusing only the
payload and the dashboard's own tokens and components.

## Structure

1. **Overview.** The kicker, then one verdict: `N 项需处理 · M 项观察` or
   `一切正常`, with a status dot. Under it sits one meta line. Its first part answers only
   "can I trust the numbers on this page?" (`页面数字可用` / `页面数字存疑：…`). A
   failed task never turns this red (#1270). The rest of the line gives build time
   and the known, won't-fix WeChat drop count (#771).
2. **Four readings.** Data files (in period / total), integrity (ERROR / WARN),
   finished products in the outcomes window (delivered / total), and today's
   cron slots (landed / due, plus who runs next). Each reading has its own state
   word. The layout follows the search-visibility card (`sv-grid`): hairline
   cells with no fills, four columns on desktop and 2 × 2 on a phone. The first three
   readings are buttons. Each opens its ledger directly under the row, one at a
   time, like a tab. The fourth reading's detail is the board below.
3. **需处理.** The one place that says "act on this". It shows stale or missing
   files, integrity ERRORs, failed products, and today's `needs_action` cron slots.
   Each item carries its next step and is visible without any click. Watch-level
   items never enter this list.
4. **Scheduled-jobs board.** One row per job, with columns for name, state, last
   success (time and age), today's slots, and next run. Rows with issues sort
   first (`需处理` → `观察` → `状态未知` → `账本看不到`). Quiet rows (`运行中`,
   `待跑`, `正常`) keep schedule order and use a lighter text step. The slot strip
   has one mark per slot (uptime-bar style). The header counts double as the
   legend, and the counts always add up to the total. Pressing a row expands its
   slot history, the raw `last_success_at` and `schedule.date` fields, and a
   link to the source payload, in place.
5. **Caption.** Defines the disposition words (需处理 / 观察 / 已知不修) on
   the same screen.

## Visual rules

- No card-in-card, fills, gradients or decorative icons. Hierarchy comes from
  the type scale (`--fs-xl` verdict and values, `--fs-sm`/`--fs-xs` body),
  weight, and `--border-subtle` hairlines. Spacing uses the `--space-*` 4px scale.
- Every text edge sits on the card's content edge. Interactive rows do not
  bleed into the card padding. The focus ring is the global 2px outside ring.
- Colour follows meaning, and every state has a word. Brand blue means
  healthy (#920: data state is not a P&L colour). `--warning` means watch,
  `--negative` means act. A hollow ring marks not yet due, so healthy never
  looks like "not yet" (#1816). Neutral means the ledger cannot see the job.
- Phone: readings go 2 × 2. Board rows become two lines
  (`name … state` / `slots … 成功 N 前 · 下次 HH:MM`) with 44px targets. The
  column header is hidden because each value carries its own label. Nothing
  scrolls sideways, so the #1802 pager keeps sole ownership of horizontal
  gestures.

## Contracts

`tests/dashboard_tab_runtime.spec.js`:

- `testDataHealthAnswersIsAnythingWrongAtEveryWidth` checks at 390 and 1280px:
  the verdict and trust line, the four readings and their states, the
  to-do list, row order and states, slot counts, and ok-vs-pending
  distinctness. It also asserts that nothing leaves the content box, overflows
  or clips.
- `testDataHealthDrillsDownWhereYouTapAndSurvivesARefresh` covers keyboard
  disclosure of a job row, one ledger at a time, and state kept across
  `renderDataHealth()` refreshes.
- `testAnOldScheduleIsOneWatchItemNotOnePerJob` checks that an old schedule is
  marked `过期` and counts as one watch item.

`renderDataHealth` and its helpers are duplicated in `dashboard.hero.js` and
`dashboard.render.js`, and must stay byte-identical
(`tests/test_dashboard_bundle_parity.py`).
