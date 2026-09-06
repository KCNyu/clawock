"""Motion and keyboard reach every control on the dashboard, not most of them.

Both halves here are gates on a *set*, not on the two lines that were wrong:

* Reduced motion. `dashboard.css` has one global
  `@media (prefers-reduced-motion: reduce)` block, and both decks and the smooth
  scroll read the query in JS — so the preference looked handled while the
  ECharts intro animated anyway, because ECharts paints on a canvas the CSS
  block cannot reach and reads the query nowhere itself (#1315). Any *new*
  JS-driven duration has the same blind spot, so the assertion is over every
  duration in the bundle.
* Keyboard. The holdings rows are `tabindex="0" role="button"` with an
  Enter/Space handler; the sort headers of the same table were `th.onclick` and
  nothing else, so the column order was mouse-only and its state was invisible
  to a screen reader (#1316). The assertion is over every sortable column in
  the markup, not over the eight that exist today.

Static by construction: this host cannot render (see the loop's instrument
rule — ~200 MB available, headless rAF at ~9 fps), so browser-level proof of
the same properties belongs in tests/dashboard_tab_runtime.spec.js.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_DIR = ROOT / "site" / "assets" / "js"
INDEX = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "site" / "assets" / "css" / "dashboard.css").read_text(encoding="utf-8")

# Vendored bundles are not ours to edit; the application layer is what must
# consult the preference on their behalf.
OURS = sorted(p for p in JS_DIR.glob("dashboard.*.js") if not p.name.endswith(".min.js"))

REDUCED_MOTION_READ = re.compile(r"prefers-reduced-motion|_RM\b|\bRM\.matches|REDUCED_MOTION")


def test_every_js_animation_duration_is_gated_on_reduced_motion():
    """A literal duration in JS is a motion the CSS media block cannot switch off."""
    offenders = []
    for path in OURS:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = re.search(r"animation\w*Duration\w*\s*:\s*(.+?),?\s*$", line)
            if not match:
                continue
            value = match.group(1).rstrip(",")
            if value.strip() == "0" or REDUCED_MOTION_READ.search(value):
                continue
            offenders.append(f"{path.name}:{number} → {value.strip()}")
    assert not offenders, (
        "these animation durations run whatever the OS motion preference says; "
        "gate them on the reduced-motion query the way baseChartOpts() does, or "
        f"set them to 0: {offenders}")


def test_the_chart_layer_reads_the_preference_live():
    """Latching `.matches` at load would miss every tab-lazy chart built later."""
    charts = (JS_DIR / "dashboard.charts.js").read_text(encoding="utf-8")
    assert 'matchMedia("(prefers-reduced-motion: reduce)")' in charts, (
        "dashboard.charts.js no longer asks for the preference at all")
    assert re.search(r"animationDuration:\s*\w+\.matches\s*\?", charts), (
        "the duration must read `.matches` at option-build time, not a boolean "
        "captured when the bundle loaded")


def _sortable_headers() -> list[str]:
    return re.findall(r"<th\b[^>]*\bdata-sort=[^>]*>.*?</th>", INDEX, re.DOTALL)


def test_every_sortable_column_is_operable_from_the_keyboard():
    headers = _sortable_headers()
    assert headers, "no sortable headers found; this gate is looking at the wrong markup"
    for header in headers:
        column = re.search(r'data-sort="([^"]+)"', header).group(1)
        assert "<button" in header, (
            f"the `{column}` header sorts on click but has no button; a bare "
            "<th onclick> cannot be focused or triggered from the keyboard (#1316)")
        assert "aria-sort" in header, (
            f"the `{column}` header does not expose its sort state via aria-sort")


def test_no_dashboard_script_hangs_a_click_handler_on_a_bare_table_header():
    offenders = [
        f"{path.name}:{number}"
        for path in OURS
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\bth\.onclick\s*=", line)
    ]
    assert not offenders, (
        "a <th> got a click handler again; the control belongs in a button "
        f"inside the header so the keyboard can reach it: {offenders}")


def test_the_sort_button_has_a_visible_focus_ring():
    """Focusable and invisible is not keyboard support."""
    assert re.search(r"\.sort-btn:focus-visible\s*\{[^}]*outline:", CSS), (
        "the sort button has no :focus-visible outline; the holdings rows next "
        "to it have had one since they became focusable")


# Every attribute the tab machinery sets on a `.panel` is a claim about what
# that panel is doing. A claim with no rule behind it is invisible to the person
# looking at the screen.
PANEL_STATE_ATTR = re.compile(r'panel\.setAttribute\("([a-zA-Z-]+)"')


def test_every_panel_state_the_code_sets_has_a_picture():
    """`aria-busy` was set and removed with nothing styled on it.

    A detail tab loads `dashboard.json` (191 KB, from the data branch) plus
    `dashboard.render.js` (266 KB) before it can paint. While that is in flight
    the panel showed its card chrome and an empty table; if it failed, the only
    trace was `console.error` and the same empty table — which reads as "you
    hold nothing", not "this did not load". Two of the three states had no
    picture, so this asserts over the set of state attributes rather than over
    the one that was missing.
    """
    ui = (JS_DIR / "dashboard.ui.js").read_text(encoding="utf-8")
    states = set(PANEL_STATE_ATTR.findall(ui))

    assert states, "the tab machinery no longer marks panel state at all"
    for attr in sorted(states):
        assert f"[{attr}" in CSS, (
            f'the code sets `{attr}` on a panel and dashboard.css never selects '
            f"on it, so the state it announces is invisible to anyone looking "
            f"at the page")


def test_a_panel_whose_load_failed_offers_a_way_back():
    """Report the failure, and make the retry reachable the way #1316 required.

    The failure path must write to the DOM rather than to the console, and the
    control it offers must be a real `<button>` — the sort headers of this same
    dashboard were mouse-only for exactly the reason a `<div onclick>` is.
    """
    ui = (JS_DIR / "dashboard.ui.js").read_text(encoding="utf-8")
    # The tab activation's own failure path, not the renderer loader's.
    activation = ui[ui.index("function activateTabData"):]
    activation = activation[:activation.index("\n  function ")]
    failure = activation[activation.index(".catch(error => {"):]

    assert "_showPanelLoadError" in failure, (
        "a tab whose data never arrived still only reaches the console")
    helper = ui[ui.index("function _showPanelLoadError"):]
    helper = helper[:helper.index("\n  function ")]
    assert 'createElement("button")' in helper, "the retry must be focusable"
    assert "panel.prepend" in helper, "the message has to reach the panel itself"
    assert ".panel-load-error" in CSS and ".panel-load-retry" in CSS


#: Properties whose read forces the browser to flush pending style writes.
LAYOUT_READS = re.compile(
    r"clientWidth|clientHeight|offsetWidth|offsetHeight|scrollWidth|scrollHeight"
    r"|getBoundingClientRect")


def _function_body(source: str, name: str) -> str:
    """The braces-balanced body of `function <name>(`."""
    start = source.index(f"function {name}(")
    depth = 0
    for i in range(source.index("{", start), len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
    raise AssertionError(f"unbalanced body for {name}")


def test_the_deck_measures_once_per_paint_not_once_per_card():
    """A layout read inside a per-card writer is a read after a write.

    `pose` sets `visibility`, `opacity` and `transform` on one card, and `paint`
    runs it once per card from inside the spring's `requestAnimationFrame` loop.
    Reading `stage.clientWidth` inside `pose` therefore flushed layout again for
    every card after the first, on every frame of every deck transition — the
    read-write-read-write alternation the worklist defines as thrash, as opposed
    to the one-read-then-write that computing a position legitimately needs.

    The width belongs to the stage, not to the card, so `paint` measures once and
    hands it down. Both bundles carry this deck by hand (see
    `test_dashboard_bundle_parity`), so both are asserted.
    """
    for path in (JS_DIR / "dashboard.hero.js", JS_DIR / "dashboard.render.js"):
        source = path.read_text(encoding="utf-8")
        pose = _function_body(source, "pose")
        assert not LAYOUT_READS.search(pose), (
            f"{path.name}: `pose` reads layout while writing card styles; "
            "measure in `paint` and pass the value in")
        paint = _function_body(source, "paint")
        assert "W()" in paint and "pose(i, w)" in paint, (
            f"{path.name}: `paint` must take the one measurement the cards share")

