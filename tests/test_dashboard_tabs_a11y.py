"""View-switcher semantics and keyboard focus on the dashboard shell.

Two findings from the same root: the markup carries a role without the
attributes that make the role mean anything, and the stylesheet grew `:hover`
affordances without the `:focus-visible` twin, one component at a time
(#1446, #1453).

* Originally the switcher was a `role="tablist"` of six buttons. #1700's
  six-tab strip was replaced by a picker (a button that opens a menu), so the
  tab roles no longer describe the control and the assertions moved with it:
  the contract is now a single-select menu (`menuitemradio` + `aria-checked`)
  over six panels, plus the panel's own heading as its accessible name.
* A control with a `:hover` style and no `:focus-visible` style is invisible to
  the keyboard exactly where it is obvious to the mouse (WCAG 2.4.7). #1316 and
  #1331 each fixed one such control; nothing stopped the next one from landing
  the same way, which is why this file checks the baseline rule rather than a
  list of components.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "site/index.html").read_text()
CSS = (ROOT / "site/assets/css/dashboard.css").read_text()
JS = "\n".join(p.read_text() for p in sorted((ROOT / "site/assets/js").glob("*.js")))

#: The picker's choices. `menuitemradio` — not plain `menuitem` — because the
#: control is single-select and `aria-checked` is only valid there.
PICKER_ITEMS = re.findall(
    r'<button\s[^>]*class="view-picker-item[^"]*"[^>]*role="menuitemradio"[^>]*>', HTML)
PANELS = re.findall(r'<section class="panel[^"]*"[^>]*>', HTML)
#: The trigger. One button, and the only element that opens the menu.
PICKER_BUTTONS = re.findall(
    r'<button\s[^>]*class="view-picker-btn"[^>]*>', HTML)

#: Classes that carry a `:hover` rule and deliberately have no `:focus-visible`
#: twin, because nothing focusable ever wears them. `test_non_focusable_hover_
#: classes_are_really_not_focusable` re-checks that claim against the markup.
NON_FOCUSABLE_HOVER = {
    "card": "面板里的容器 div，没有 tabindex；里面的按钮各自有焦点环",
    "dm-signal": "决策地图的 <tr>；可聚焦的是单元格 .dm-cell（tabindex=0，已有 :focus-visible）",
    "ret-cell": "只存在于 CSS，全仓没有任何生产者渲染它",
}


def _attr(tag, name):
    m = re.search(rf'{name}="([^"]*)"', tag)
    return m.group(1) if m else None


def _tag_with_id(element_id):
    match = re.search(rf'<[^>]+id="{re.escape(element_id)}"[^>]*>', HTML)
    assert match, f"#{element_id} is missing from site/index.html"
    return match.group(0)


def test_dynamic_status_updates_are_announced_without_repainting_a_whole_card():
    for element_id in (
        "data-refresh-status",
        "status-banner",
        "overview-status-banner",
    ):
        tag = _tag_with_id(element_id)
        assert _attr(tag, "role") == "status", element_id
        assert _attr(tag, "aria-live") == "polite", element_id
        assert _attr(tag, "aria-atomic") == "true", element_id

    assert 'id="data-health" aria-live=' not in HTML, (
        "the whole data-health card must not be a live region; announce the "
        "short refresh outcome instead"
    )
    assert 'getElementById("data-refresh-status")' in JS
    assert "status.textContent = message" in JS
    assert ".sr-only" in CSS


def test_every_picker_choice_has_a_panel_and_every_panel_a_choice():
    # The count is not asserted against a literal. Adding a view is a real change
    # that touches the animation contract too, and a bare `== 6` here only meant
    # the number was written down in two test files; the pairing below is the
    # part that can actually be wrong.
    assert PICKER_ITEMS, "the dashboard declares no view choices at all"
    assert len(PICKER_ITEMS) == len(PANELS), (
        f"{len(PICKER_ITEMS)} picker items and {len(PANELS)} panels — every view "
        "needs a panel and every panel needs a view")

    panels = {_attr(p, "data-panel"): p for p in PANELS}
    assert None not in panels, "a .panel has no data-panel — the pager keys on it"

    for item in PICKER_ITEMS:
        name = _attr(item, "data-tab")
        assert _attr(item, "id") == f"tab-{name}", f"view {name}: id"
        assert _attr(item, "aria-checked") in {"true", "false"}, (
            f"view {name}: no aria-checked in the static markup — a reader that "
            f"arrives before dashboard.ui.js runs sees a menu with no state"
        )
        panel = panels[name]
        assert _attr(panel, "id") == f"panel-{name}", f"panel {name}: id"


def test_exactly_one_view_starts_checked():
    checked = [i for i in PICKER_ITEMS if _attr(i, "aria-checked") == "true"]
    assert len(checked) == 1, f"{len(checked)} views start checked"
    assert _attr(checked[0], "data-tab") == "hero", "the landing view is Overview"


def test_the_trigger_announces_that_it_opens_a_menu():
    assert len(PICKER_BUTTONS) == 1, (
        f"{len(PICKER_BUTTONS)} picker triggers — the view switcher is one control")
    btn = PICKER_BUTTONS[0]
    assert _attr(btn, "aria-haspopup") == "menu", "the trigger does not announce a menu"
    assert _attr(btn, "aria-expanded") in {"true", "false"}, (
        "aria-expanded is absent from the static markup — a reader arriving "
        "before dashboard.ui.js runs cannot tell the menu is closed")
    assert _attr(btn, "aria-controls") == "view-picker-menu", (
        "the trigger does not point at the menu it opens")


def test_panels_keep_their_own_heading_as_the_accessible_name():
    """The old pairing was `role="tabpanel"` + `aria-labelledby="tab-*"`.

    Those roles are gone with the tab strip, and a tabpanel labelled by a
    menuitemradio would be an invalid reference. The panel's own <h2> is what
    names it now — so it has to stay a real heading and stay in the a11y tree
    even though CSS hides it visually.
    """
    for panel in PANELS:
        name = _attr(panel, "data-panel")
        assert _attr(panel, "role") != "tabpanel", (
            f"panel {name}: role=tabpanel is orphaned — nothing has role=tab now")
        assert "aria-labelledby" not in panel, (
            f"panel {name}: aria-labelledby points into the menu, which is not a "
            "valid label source for this section")
    headings = re.findall(r'<section class="panel[^"]*"[^>]*>\s*<h2>', HTML)
    assert len(headings) == len(PANELS), (
        f"{len(PANELS)} panels but only {len(headings)} open with an <h2> — the "
        "section would lose its accessible name")
    # The heading is clipped, never display:none: a display:none heading drops
    # out of the a11y tree and takes the section's name with it.
    assert re.search(r'\.panel(?:\.active)? > h2 \{[^}]*clip-path', CSS), (
        "the panel <h2> is no longer clipped-but-present — display:none here "
        "would remove the section's accessible name")


def test_the_js_keeps_aria_checked_in_sync():
    """The static markup is only the starting state; setActiveButton owns the rest."""
    assert 'setAttribute("aria-checked"' in JS, (
        "nothing updates aria-checked when the view changes"
    )


def test_focus_visible_baseline_covers_every_focusable_element():
    """One rule, so a new control is covered by default instead of by memory."""
    m = re.search(r'((?:\s*(?:a|button|summary|input|select|textarea|\[tabindex\])'
                  r':focus-visible,?)+)\s*\{([^}]*)\}', CSS)
    assert m, (
        "no element-level :focus-visible baseline in dashboard.css — every new "
        "interactive component is back to needing its own rule, which is how "
        ".refresh-btn / .dh-toggle / .panel-load-retry / .nav-link ended up with "
        "no focus ring at all"
    )
    selectors = {s.strip() for s in m.group(1).split(",") if s.strip()}
    for required in ("a:focus-visible", "button:focus-visible", "[tabindex]:focus-visible"):
        assert required in selectors, f"baseline does not cover {required}"
    assert "outline" in m.group(2) and "none" not in m.group(2), (
        f"the baseline draws no outline: {m.group(2).strip()}"
    )


def test_every_hover_affordance_has_a_focus_twin_or_a_reason():
    hover = {c for c in re.findall(r'\.([\w-]+):hover', CSS) if not c.isdigit()}
    focus = set(re.findall(r'\.([\w-]+):focus-visible', CSS))
    missing = sorted(hover - focus - set(NON_FOCUSABLE_HOVER))
    assert not missing, (
        "hover styling with no keyboard equivalent: "
        + ", ".join(f".{c}" for c in missing)
        + " — add a :focus-visible rule, or list it in NON_FOCUSABLE_HOVER with "
          "the reason nothing focusable wears it"
    )


def test_non_focusable_hover_classes_are_really_not_focusable():
    """The allowlist is a claim about the markup, so check it against the markup."""
    for cls, reason in NON_FOCUSABLE_HOVER.items():
        assert f".{cls}:hover" in CSS, (
            f".{cls} no longer has a :hover rule — drop it from NON_FOCUSABLE_HOVER "
            f"({reason})"
        )
        for source, label in ((HTML, "site/index.html"), (JS, "site/assets/js")):
            for line in source.splitlines():
                if cls not in line:
                    continue
                assert not re.search(r'tabindex=|role="button"', line), (
                    f'.{cls} is listed as non-focusable but {label} renders it on a '
                    f'focusable element: {line.strip()[:120]}'
                )
