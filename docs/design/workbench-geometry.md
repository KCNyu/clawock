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

## Reading width and wrapping

The absence of intersecting boxes is necessary, but a four-line title in a
40px column is still a layout failure. Content is an independent matrix axis:
English partial status, hyphenated names, an unbroken Latin name, unspaced CJK,
mixed prose, URLs and paths. The same assertions run against the base bundle.

| Role / surface | Contract | Width negotiation |
| --- | --- | --- |
| Detail heading | Natural breaks, emergency wrapping only for an overlong segment; `dsh-pr-review` and the representative Latin/CJK names fit at most two lines | `--wb-heading-row`: 16px glyph, flexible title, max-content chip. Title keeps at least 60% of the row in the regression corpus. The status sentence always has its own row, starting at the title edge. |
| Glyph, title, chip | Center glyph on the entire title block (error at most 1px), chip centered in the same row | Explicit grid areas override all legacy row-grid positions. No flex min-content competition. |
| Status/meta sentences, closing report, NEEDS, brief excerpt, empty-state explanations | Wrap fully; never ellipsize the only copy of a message | `--wb-readable-word: normal`, `--wb-readable-wrap: anywhere`; CJK uses native line breaks, Latin prefers words/hyphens, then emergency breaks. No `break-all` for code paths. |
| Field label / value / controls | Label and value share a baseline; controls remain atomic | Below a **30rem content container**, controls move below the value. Value uses two thirds of the remaining width, at least 160px in supported phone fixtures; no button steals that width. This also applies to a narrow desktop pane. |
| Queue/History title and summary | One line with ellipsis; the row opens the full task | Age/state/cost remain atomic. The 62px host row and its typography stay unchanged. |
| File name / excerpt | File name abbreviates; full-file action opens it. Excerpt wraps | Label gets remaining width (`flex: 1; min-width: 0`), delivery tag stays atomic. Border and padding are included in the button width. |
| Provider name / reset meta; overview metrics, group summary | Single-line scanning labels; provider/overview detail contains the complete context | Numeric reading/pin/chevron keep intrinsic width; flexible label yields first. Group labels are bounded vocabulary, not user task titles. |
| Buttons, chip, time, numeric value | No internal wrapping | Action groups wrap whole controls. Sheet close remains 32px; navigation stays a separate 44px band. |
| Logs | Preserve newlines; wrap long segments inside the explicit scroller | A bounded log scroll region is deliberate; full log remains available. |

The viewport matrix includes 320/375/390/420, 768/834 in both orientations,
1280/1440 desktop, both themes, plus reduced-height and keyboard navigation
fixtures. Width, not orientation, decides the layout. The Workbench page inset
remains 20px. Its Back band sits below the **host-owned sidebar toggle and frame
clearance**; the toggle is not a Workbench header glyph. Moving that control into
Back would change the host/slot contract and is outside this typography change.

Sheet/scrim over the background and a toast above the page are intentional
z-axis intersections; collisions *within* the sheet/toast are not exempt.
Sticky tabs may cover already-scrolled content, never initial content. Parent
containment is not a sibling collision. These exceptions remain recorded per
pair in the matrix artifact. A text-clipping exception is restricted to an
explicit scrolling region or an abbreviated scanning label with a full-content
route; it is not permission to shrink a reading column to a few characters.

Browser geometry is regression evidence, not physical Safari verification.
Real device toolbar/keyboard/safe-area transitions still need a device capture.
