# Workbench host conformance (2026-11-08)

kcn's review: "你让参考dsh原生那个automation tasks那个plugin来实现吧
我觉得css完全可以重新做啥的？"

This page records the **measured** host reference, the new Workbench
baseline, what matches, and what is still intentionally different. The
reference is dsh's Automation tasks plugin
(`dsh-client-ui-schedule/lib/client.js`); its CSS is inline in the bundle
(`TaskManagerPage.module.css`), and the values below were also read back
from the live DOM with `getComputedStyle` at 390x844.

## Measured host (Automation tasks)

![Automation tasks, the reference](workbench-host-reference-390.png)

| Host element | Measured value |
|---|---|
| Page content | `padding: 0 20px 48px` at <=767px; width 960px max |
| Page heading | `padding-top: 28px; margin-bottom: 24px`; h1 **20px / 28px / 500**; left **20px** |
| Header action "New" | 32px high, padding 0 12px, radius 16px, 13px/20px, primary black |
| Filter tabs (Enabled/Paused/Ended/All) | 28px high, padding 0 10px, radius 14px, 14px/22px; selected background `--dsw-alias-interactive-bg-hover`; gap 12px |
| Search field | 36px high, radius 12px, 0.5px border, 14px input |
| List row | padding **8px**, gap 12px, radius **12px**, no divider; list gap **2px**; row title **14px/23px/500**; summary **13px/21px**, tertiary |
| Empty | centered, padding 48px 20px, 14px/22px tertiary; action 44px high |
| Detail pane | border-left .5px, gutter 24px, 14px/1.6 body |

## New Workbench baseline

The Workbench CSS now uses the same page rhythm (a single superseding
"Automation tasks baseline" block at the end of `styles.module.css`):

| Workbench element | New value | Host value | Status |
|---|---|---|---|
| Page inset `--wb-pad` | **20px** | 20px | matched |
| Title | **20px/28px/500**, left 20 | 20/28/500, left 20 | matched |
| Subtitle | 14px/22px, tertiary, left 20 | (host has no subtitle) | host rhythm |
| Tabs (Tasks/Providers/Overview) | **28px high, 0 10px, radius 14, 14/22**, selected hover fill, gap 12 | filter tabs 28/14/10/14 | matched visual; view tabs, not status filters |
| Count in tab | inline `4` at 14px, no chip | host tabs have no count | intentional difference |
| Status/Source grouping | 28px filter pill, radius 14, selected fill | host filter tabs | matched visual |
| Group header | 36px, 14/22/500, no border, chevron right | (host list has no group) | host rhythm |
| Task row | padding **8**, gap 12, radius **12**, no divider, 2px gap; title **14/23/500**; meta **13/21** | identical | matched |
| Row left text | 28px (20 + 8px padding) | 28px | matched |
| Primary/secondary buttons | **32px high, radius 16, 13/20** | 32/16/13/20 | matched |
| Detail pills | 28px, radius 14, 13/21 | 28px filter height | matched |
| Empty | centered 48px 20px, 14/22 tertiary, action 44px | identical | matched |
| Provider alert | 6px red dot | host alert dot | matched shape |
| History rows | 8px padding, radius 12, no divider, 2px gap | identical list rhythm | matched |
| Search field | none | 36px field | **difference** (Workbench has no search surface) |
| Detail body | 13/21, gutter 20px | 14/1.6, gutter 24px | close, not identical |
| Providers data table | name/meta + 3px bar | no host analogue | custom data surface |

Colours use the host aliases (`--dsw-alias-label-primary`,
`--dsw-alias-label-tertiary`, `--dsw-alias-interactive-bg-hover`,
`--dsw-alias-border-l4`), so light/dark follow dsh. The only host controls
not reused are the React components themselves: dsh does not export the
Automation tasks React components to plugin slots. The CSS above is a
measured clone, not a wrapper around a host component.

## Left edges (measured)

`--wb-pad` is 20px at 390/375/320 (the host's mobile content inset). Page
chrome starts at 20; row text starts at 28 because the host row itself has
8px padding. The `header` gauge asserts:

```text
390: title 20 · subtitle 20 · tabs 20 · group 20 · row 28
375: title 20 · subtitle 20 · tabs 20 · group 20 · row 28
320: title 20 · subtitle 20 · tabs 20 · group 20 · row 28
```

Earlier the page had 44/16/12 baselines; that is gone.

## Screenshots

| Width | Home | History | Detail |
|---|---|---|---|
| 390 | ![](workbench-conformance-390.png) | ![](workbench-conformance-history-390.png) | ![](workbench-conformance-detail-390.png) |
| 375 | ![](workbench-conformance-375.png) | (same layout, row text 28) | (same layout) |
| 320 | ![](workbench-conformance-320.png) | (same) | (same) |

## What is still different

1. No search field (the Workbench has no search data flow; adding one
   would be a new feature, not CSS).
2. The tab count is inline text; Automation's tabs carry no count.
3. Detail body is 13/21 with a 20px gutter vs the host detail's 14/1.6
   with 24px; the Workbench detail is a full-page focus layer, and the
   tighter reading line is retained for the long closing reports.
4. Provider rows are a data table (name, balance, bar) with no direct
   host analogue; they follow the same row radius/padding/type.

The functional contracts from the 2026-11-08 fixes remain: UTF-8
fetch+TextDecoder+blob previews, single-column brief, History ¥/$ and
"latest 5", Dismiss ack, rendered Markdown, the G1 generic-scan negative
control, the G2 Log note, and the G3 doc correction.

## Related

- [`workbench-geometry.md`](workbench-geometry.md)
- [`workbench-type.md`](workbench-type.md)
