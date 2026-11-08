# Workbench geometry on a phone

The live dsh host draws `sidebar.panellist` rows as 36px buttons (measured
2026-11-08 at 390x844 and 402x874) with a 16px glyph slot, a 14px/22px
label and a 6px glyph-to-label gap. The rail is the same list at 56px with
36px hit boxes and a 12px gap. The Workbench entry is a 16px glyph; its
marks belong to the glyph's own box, not to the host wrapper (which is 16px
in the drawer and 36px in the rail), so the wide row has no glyph badge:
the alert or pending count is written into the host's label instead. The
rail, where the label is hidden, keeps the count chip and the alert mark.

## Contracts pinned by `tests/workbench_overlap.spec.js`

- **Sidebar rows** (390x844 and 375x667, host-like fixture): four adjacent
  rows stay 36px and do not intersect; the label, glyph, count badge and
  rail alert each stay inside their row. The wide row carries no glyph
  badge and keeps a visible label; the rail keeps the chip, the chip covers
  at most 40% of the glyph, and the chip and the alert never intersect.
- **Closing report** (390x844, 375x667, 320x568, desktop): the Full log row
  clears the report card by at least 8px; the card clips neither its last
  line nor its width.
- **Patrol coverage** (390x844 and 375x667): the two tables stack in one
  column and neither overflows horizontally. The old three-column layout
  must not come back on a phone.
- **Providers** (390x844, 375x667, 320x568, dark): a name, its primary and
  secondary values, and the meta row's two ends never intersect; no row
  overflows horizontally.

The `sidebar-legacy` state replays the pre-fix badge CSS as a negative
control, so the detector cannot quietly stop seeing the defect.

## Evidence

The screenshots are WebKit at 390x844 with the real bundle and the
host-like 36px sidebar; the after column is the fixed bundle. The sidebar
pair is a 2x crop of the same viewport; the task pair is the full viewport.

![Sidebar badge before/after](workbench-overlap-sidebar.png)

![Closing report before/after](workbench-overlap-detail.png)
