# Data Health monitoring board (2026-09-24)

## Decision in one glance

The page answers three questions in order: **is anything wrong, which lane or scheduled job, and what happened?** The earlier layouts repeated rounded metric cards, lane cards, and task cards at nearly equal weight. The current layout has one textual verdict, a single column aligned board, and a detail area that appears only after selection.

## Research and design choices

| Source | Observed pattern | Decision here |
| --- | --- | --- |
| [GitHub Status / Atlassian Statuspage](https://www.githubstatus.com/) | A single overall state precedes component status and uptime history. | Put the verdict above the board; give each component and job an explicit state label. |
| [Better Stack status pages](https://betterstack.com/status-page.md) | Active incidents are announced before the quiet component list. | Keep actionable issues under the overview, and sort problem jobs before routine jobs. |
| [Grafana Status history](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/status-history.md) | One entity per row, discrete observations on a common horizontal scale. | Position each known cron slot on the same 00–24 HKT axis; do not imply a longer history than the payload contains. |
| Apple Design, Emil Design Engineering, UI/UX Pro Max, Dataviz | Strong type hierarchy, restrained color, semantic text alongside marks, predictable touch and focus behavior. | Use neutral surfaces, hairline dividers, existing semantic tokens, tabular numbers, native button/summary controls, and instant disclosure. |

## Information architecture

1. **Overview:** one verdict; actual file coverage (in period / total), oldest recorded file age, and the count requiring action. The compact strip represents file states only. Missing file data shows an em dash instead of fabricated coverage or cycle time. Build time and known WeChat drops remain in the metadata line.
2. **Monitoring board:** three domains and every cron job share name, state, latest result, observation strip, and due/reason columns. The domain observation strips summarize actual file, integrity, or delivery data. Cron marks use today's known slots on one 24 hour HKT axis. Issues precede routine jobs; healthy rows are intentionally quiet. Semantic state uses text and glyphs as well as color; pending is never described or painted as healthy.
3. **Drill down:** selecting a domain moves its existing detailed ledger to the dedicated bottom area. Selecting a job reveals slot times, results, reasons, the raw `last_success_at` and `schedule.date` fields, and a link to the source dashboard payload there. Native buttons and summaries provide keyboard and touch access; hidden domain ledgers are inert.

The board uses a 4/8px spacing rhythm, a small type scale, one accent plus semantic status colors, and no gradients or decorative shadows. At phone widths the same rows reflow into aligned name/state and result/history/due lines without horizontal scrolling. The dashboard pager remains outside this section and retains its existing navigation behavior.

## Verification

Compare the before and after 390px and 1280px viewport captures. The visible difference should be the removal of the number tile and nested cards, and the appearance of a single ruled monitoring board. Runtime contracts cover per-job status, the shared columns, actual summary readings, next due, bottom keyboard disclosure, phone edge spacing and overflow, and the mobile pager.
