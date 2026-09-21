"""Tab semantics and keyboard focus on the dashboard shell.

Two findings from the same root: the markup carries `role="tab"` without the
attributes that make a tab a tab, and the stylesheet grew `:hover` affordances
without the `:focus-visible` twin, one component at a time (#1446, #1453).

* A `role="tab"` with no `aria-controls`, on a panel with no `role="tabpanel"`,
  reads to a screen reader as a plain button: switching panels announces
  nothing, so a keyboard user has no way to tell the content changed.
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
LAYOUT = (ROOT / "site/_layouts/default.html").read_text()
CSS = (ROOT / "site/assets/css/dashboard.css").read_text()
JS = "\n".join(p.read_text() for p in sorted((ROOT / "site/assets/js").glob("*.js")))

TAB_BUTTONS = re.findall(r'<button class="tab-btn[^"]*"[^>]*role="tab"[^>]*>', HTML)
PANELS = re.findall(r'<section class="panel[^"]*"[^>]*>', HTML)

#: Classes that carry a `:hover` rule and deliberately have no `:focus-visible`
#: twin, because nothing focusable ever wears them. `test_non_focusable_hover_
#: classes_are_really_not_focusable` re-checks that claim against the markup.
NON_FOCUSABLE_HOVER = {
    "card": "面板里的容器 div，没有 tabindex；里面的按钮各自有焦点环",
    "dm-signal": "决策地图的 <tr>；可聚焦的是单元格 .dm-cell（tabindex=0，已有 :focus-visible）",
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


def test_tab_buttons_and_panels_point_at_each_other():
    # The count is not asserted against a literal any more. Adding a tab is a
    # real change that touches the animation contract too, and a bare `== 6` here
    # only meant the number was written down in two test files; the pairing below
    # is the part that can actually be wrong.
    assert TAB_BUTTONS, "the dashboard declares no tabs at all"
    assert len(TAB_BUTTONS) == len(PANELS), (
        f"{len(TAB_BUTTONS)} tab buttons and {len(PANELS)} panels — every tab "
        "needs a panel and every panel needs a tab")

    panels = {_attr(p, "data-panel"): p for p in PANELS}
    assert None not in panels, "a .panel has no data-panel — the pager keys on it"

    for btn in TAB_BUTTONS:
        name = _attr(btn, "data-tab")
        assert _attr(btn, "id") == f"tab-{name}", f"tab {name}: id"
        assert _attr(btn, "aria-controls") == f"panel-{name}", f"tab {name}: aria-controls"
        assert _attr(btn, "aria-selected") in {"true", "false"}, (
            f"tab {name}: no aria-selected in the static markup — a reader that "
            f"arrives before dashboard.ui.js runs sees a tablist with no state"
        )
        panel = panels[name]
        assert _attr(panel, "id") == f"panel-{name}", f"panel {name}: id"
        assert _attr(panel, "role") == "tabpanel", f"panel {name}: role"
        assert _attr(panel, "aria-labelledby") == f"tab-{name}", (
            f"panel {name}: aria-labelledby"
        )


def test_exactly_one_tab_starts_selected():
    selected = [b for b in TAB_BUTTONS if _attr(b, "aria-selected") == "true"]
    assert len(selected) == 1, f"{len(selected)} tabs start selected"
    assert _attr(selected[0], "data-tab") == "hero", "the landing tab is Overview"


def test_the_site_menu_replaces_the_link_row_without_losing_a_destination():
    """The four destinations are a `<details>` disclosure in the top-right now.

    #1702's requirement did not change — dashboard and Jekyll pages advertise
    the same four places — but the control did: a row of links spent a quarter
    of the bar on the rarest intent there is. Assert the menu carries all four
    and marks where you are, because a disclosure that silently drops an item
    looks exactly like one that works.
    """
    menu = re.search(r'<details class="site-menu".*?</details>', HTML, re.S)
    assert menu, "the site menu is missing from site/index.html"
    block = menu.group(0)
    assert 'aria-label="Switch site section"' in block, (
        "the trigger has no accessible name beyond its label text")
    items = re.findall(r'<a class="site-menu-item[^"]*"', block)
    assert len(items) == 4, (
        f"{len(items)} destinations in the site menu — Dashboard / Briefs / FAQ / "
        "GitHub is the set both headers promise")
    assert any("is-current" in i for i in items), (
        "no destination is marked as the current one — the menu cannot answer "
        "'where am I'")
    assert 'aria-current="page"' in block, (
        "the current destination needs aria-current, not just a class")
    # <details> supplies open/close and the keyboard natively; the script is
    # only allowed to add the two behaviours it does not have.
    assert 'getElementById("site-menu")' in JS, (
        "nothing closes the site menu on an outside click or Escape")


def test_both_headers_are_drawn_by_one_stylesheet():
    """#1702's actual cause, checked instead of patrolled.

    The dashboard is styled by `assets/css/dashboard.css`; the Jekyll layout
    used to carry a hand-copied excerpt of it inline. Nothing connected the two,
    so redesigning the dashboard's navigation (#1700) left the other half of the
    site on the previous one and the inconsistency was found days later by a
    patrol. A copy cannot be kept in sync by care; it can only be removed.
    """
    assert "assets/css/dashboard.css" in LAYOUT, (
        "the shared layout no longer links the stylesheet the dashboard uses — "
        "whatever replaced it is a second copy of one design")
    # The shell's vocabulary has exactly one definition site. A `--token: value`
    # here is a second one, which is how the two halves drift apart again.
    shell_tokens = ("--bg:", "--card:", "--border:", "--text:", "--accent:",
                    "--radius:", "--mono:", "--surface-1:", "--focus:")
    redefined = [t for t in shell_tokens if t in LAYOUT]
    assert redefined == [], (
        f"the shared layout re-declares shell tokens {redefined} instead of "
        "inheriting them from the stylesheet it links")
    # Same for the chrome: the header, the menu and the footer are drawn once.
    for selector in (".site-menu-btn {", ".site-menu-panel {", ".topbar {",
                     "header.topbar {", ".brand-mark {"):
        assert selector not in LAYOUT, (
            f"the shared layout styles `{selector.strip(' {')}` itself; that rule "
            "belongs in the stylesheet both documents load")


def test_the_shared_layout_carries_the_same_site_menu_as_the_dashboard():
    """Both headers promise the same four places, in the same control.

    `test_the_site_menu_replaces_the_link_row_without_losing_a_destination`
    checks the dashboard's copy of this markup. It passed all through #1702,
    because it never looked at the other document.
    """
    menu = re.search(r'<details class="site-menu".*?</details>', LAYOUT, re.S)
    assert menu, "the site menu is missing from site/_layouts/default.html"
    block = menu.group(0)
    assert 'aria-label="Switch site section"' in block, (
        "the trigger has no accessible name beyond its label text")
    items = re.findall(r'<a class="site-menu-item[^"]*"', block)
    assert len(items) == 4, (
        f"{len(items)} destinations in the shared layout's site menu — "
        "Dashboard / Briefs / FAQ / GitHub is the set both headers promise")
    assert 'aria-current="page"' in block, (
        "the current destination needs aria-current, not just a class")
    # These pages load no bundle, so the outside-click/Escape behaviour the
    # dashboard's JS adds has to come from the layout's own script.
    assert 'getElementById("site-menu")' in LAYOUT, (
        "nothing closes the site menu on an outside click or Escape")


def test_the_js_keeps_aria_selected_in_sync():
    """The static markup is only the starting state; setActiveButton owns the rest."""
    assert 'setAttribute("aria-selected"' in JS, (
        "nothing updates aria-selected when the pager moves"
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


def test_refresh_focus_ring_stays_close_to_the_round_button():
    """The refresh ring remains visible without reading as a second halo."""
    m = re.search(r'\.refresh-btn:focus-visible\s*\{([^}]*)\}', CSS)
    assert m, "refresh button lost its component-specific focus treatment"
    rule = m.group(1)
    assert "outline: var(--focus-ring)" in rule
    assert "outline-offset: 1px" in rule


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
