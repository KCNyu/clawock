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
    "ret-cell": "只存在于 CSS，全仓没有任何生产者渲染它",
}


def _attr(tag, name):
    m = re.search(rf'{name}="([^"]*)"', tag)
    return m.group(1) if m else None


def test_tab_buttons_and_panels_point_at_each_other():
    assert len(TAB_BUTTONS) == 6, f"expected 6 tab buttons, found {len(TAB_BUTTONS)}"
    assert len(PANELS) == 6, f"expected 6 panels, found {len(PANELS)}"

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
