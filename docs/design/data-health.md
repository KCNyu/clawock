# Data Health redesign brief (2026-09-24)

## Question and visual direction

The first glance must answer **what is wrong, where, and whether action is due**. The prior card repeated rounded buttons and a second, long list of rounded task cards. It gave every healthy row the same visual weight as a problem.

Use one strong verdict at the top, a compact service summary for the three data lanes, then a quiet task ledger. The alert carries color and space; healthy rows carry labels and a restrained status mark. The task slot history is a small directly labeled strip attached to its job, not a second chart after the list.

## Patterns borrowed

| Reference | Concrete pattern | Use here |
| --- | --- | --- |
| [Atlassian Statuspage](https://www.githubstatus.com/) | One overall state above component rows and 90-day uptime history | A prominent overall verdict above the three lanes. Use slot history only for today's known slots; do not imply 90-day uptime from a one-day payload. |
| [Better Stack status pages](https://betterstack.com/status-page.md) | Incident text and affected services are visible, while detailed charts are secondary | Keep the issue reason visible; put completed healthy details behind disclosure. |
| [Grafana Status history](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/status-history.md) | One entity per horizontal row, with discrete colored boxes for observed states | Give every scheduled job its own compact strip of slot results and a directly labeled current state. |
| UI/UX Pro Max, Apple Design, Emil Design Engineering, Dataviz skills | Semantic badges, 44px touch reach, typography hierarchy, restrained state color, direct labels, no hover-only answers | The status pill is static text; the full row is the disclosure target. Use existing tokens, focus ring and press language. State changes need no decorative motion. |

## Component contract

- Overall: large number or check mark, plain-language verdict, page trust, and an issue list immediately below.
- Three lanes: one shared inset surface separated by hairlines; each lane shows its own icon + text state, count, visual summary, and reason. The disclosure control reads like a row, not a filled button.
- Jobs: issues first. Each row has name, static status pill, last-success time/age, and a compact observed-slot strip. The reason is visible on affected rows. Expanding reveals every slot and its note by tap, mouse or keyboard.
- Healthy and not-yet-due have different text, icon and mark shape. Missing data says unknown; never paint it healthy.
- At 390px and 1280px, card edges have breathing room; long names and reasons wrap without clipping. Mobile pager behavior remains unchanged.

## Acceptance

Compare before/after viewport screenshots at iPhone 13 and desktop widths. The new hierarchy must be obvious before reading small text: verdict, one grouped service surface, then the problem-first task ledger. If it still looks like a stack of generic blue buttons, revise it.
