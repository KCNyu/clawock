# Workbench host conformance (2026-11-08)

kcn's review: "这个也是没对齐一样 而且ui也不符合dsh的". This page records
what was measured against the host, what is reused, and what is still a
plugin-owned surface rather than a host component. It is deliberately a
gap table, not a claim that the page is pixel-identical to dsh.

Measured on the live host (dsh 0.2.2-rc.1, 390x844 and 375x667) from the
DOM, 2026-11-08 13:4x CST. The dsh components live inside
`dsh-client-ui-*` bundles and are not exported to plugin slots; a plugin
receives slots and the host CSS custom properties, not the host's React
components. That is the constraint behind the "not reused" rows.

## Left baseline (fixed)

`--wb-pad` is the one inset: 16px at 375/390, 12px below 360.

| Element | left at 390 | left at 375 | left at 320 |
|---|---|---|---|
| Title "Workbench" | 16 | 16 | 12 |
| Subtitle | 16 | 16 | 12 |
| Tab frame | 16 | 16 | 12 |
| Group title | 16 | 16 | 12 |
| Row title | 16 | 16 | 12 |

The `header` geometry gauge asserts max-min <= 0.6px at all three widths.
The host's own **Open sidebar** control above the page is left where dsh
draws it (it has the panel-left icon and `aria-label="Open sidebar"`); it
is not a plugin leftover.

## Control-by-control

| Page control | Host reference | Host measurement | This page | Status |
|---|---|---|---|---|
| Page title/subtitle | dsh panel header / section label | 14px/22px, 12-16px inset | same inset and `--fs-*`/`--lh-*` tokens | matched |
| Segmented Tasks/Providers/Overview | dsh sidebar panel rows (only exported analogue) | 36px high, 12px radius, 14px | 44px high, 10px radius, 14px | **not matched** — a host `segmented` component is not exported; the page keeps its own three-segment control |
| Count badge ("1") | dsh neutral count pill | 18px, `--dsw-*` fill | 18px neutral pill | matched shape/token |
| Status / Source | dsh Automation tasks filter | host menu/select bound to host state | two-value grouping toggle | **not matched** — this is "group by", not a filter; a select would have to own the grouping state |
| Group header (Active/Needs review) | dsh section label | 14px medium, 36-40px row | 44px row, 14px medium | close; row height remains 4-8px taller |
| Task row | dsh task list (no plugin-accessible row component) | two-line 72px in the live page | two-line 72px, 8px inner padding | structurally matched, not a host component |
| Red provider alert | dsh alert dot | non-numeric red dot | red `!` circle (not a number) | shape differs; semantics (non-numeric alert) matches |
| Detail primary/secondary buttons | dsh "New session" button | 38px high, 12px radius, 14px | 44px high, 8px radius, 14px | **not matched** — queued for a follow-up |
| Detail pills (Brief/Log/Timeline) | dsh tag/chip | 28-32px, 12px radius | 28px, 8px radius | close; radius differs |

## What is genuinely reused

- Host CSS custom properties for type (`--fs-*`, `--lh-*`, `--fw-*`), radii
  (`--dsw-radius-*`), focus rings, and state fills.
- The host `sidebar.panellist` row, the host `Open sidebar`/back surfaces,
  and the host's slot lifecycle (no second navigation chrome is drawn).
- Host colors for body ink, hairline borders and the hover/press fills; the
  plugin does not define a second palette.

## Remaining work (honest)

A true B-level conformance needs one of:

1. dsh exports its segmented control, filter menu, section-label and button
   primitives to plugin slots (then reuse them directly), or
2. kcn accepts a token/measurement clone of those primitives, implemented
   in the plugin (larger than a pixel pass; owns hover/focus/disabled states).

Until then the page keeps the host's type/color/radius tokens and the one
left baseline, but the segmented control, filter toggle, row height and
primary/secondary button height differ from the host's. The screenshots in
the task report show the current state at 390/375; the before images are
kcn's inbound screenshots.

## Related

- [`workbench-geometry.md`](workbench-geometry.md) — the phone overlap and
  left-baseline contracts.
- [`workbench-type.md`](workbench-type.md) — the type roles and tokens.
