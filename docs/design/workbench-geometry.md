# Workbench geometry on a phone

The live dsh host draws `sidebar.panellist` rows as 36px buttons (measured
2026-11-08 at 390x844 and 402x874) with a 16px glyph slot, a 14px/22px
label and a 6px glyph-to-label gap. The rail is the same list at 56px with
36px hit boxes and a 12px gap. The Workbench page uses a 20px content inset (Automation tasks baseline).
The Workbench entry is a 16px glyph with no
numeric badge in either state: the count is words in the host's label
(`Workbench · 1 alert`), and a row with no alert has no suffix. The rail,
where the host hides the label, keeps only the non-numeric alert mark.

## Contracts pinned by `tests/workbench_overlap.spec.js`

- **Sidebar rows** (390x844 and 375x667, host-like fixture): four adjacent
  rows stay 36px and do not intersect; the label, glyph and rail alert
  each stay inside their row. The row has no `[data-wb-badge]`
  node; the label carries the alert count and no suffix at zero, and the
  36px row height is the same whether the label is `Workbench` or
  `Workbench · N alerts`. The rail keeps the non-numeric alert mark.
- **Closing report** (390x844, 375x667, 320x568, desktop): the Full log row
  clears the report card by at least 8px; the card clips neither its last
  line nor its width.
- **Patrol coverage** (390x844 and 375x667): the two tables stack in one
  column and neither overflows horizontally. The old three-column layout
  must not come back on a phone.
- **Providers** (390x844, 375x667, 320x568, dark): a name, its primary and
  secondary values, and the meta row's two ends never intersect; no row
  overflows horizontally.

## Evidence

The screenshots are WebKit at 390x844 with the real bundle and the
host-like 36px sidebar; the after column is the fixed bundle. The sidebar
pair is a 2x crop of the same viewport; the task pair is the full viewport.

![Sidebar before/after](workbench-overlap-sidebar.png)

![Closing report before/after](workbench-overlap-detail.png)
