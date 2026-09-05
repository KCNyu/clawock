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
