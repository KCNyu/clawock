"""Static guardrails for the desktop-only layout fixes.

Rendered Chromium smoke tests remain the visual proof. These checks make the
intentional ownership classes and desktop scope hard to lose in a later CSS
refactor.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text()
CSS = (ROOT / "assets" / "css" / "dashboard.css").read_text()


def enclosing_desktop_block(rule_start):
    """Return the nearest 1024px media block containing a rule."""
    block_start = CSS.rindex("@media (min-width: 1024px)", 0, rule_start)
    brace_start = CSS.index("{", block_start)
    depth = 0
    for index in range(brace_start, len(CSS)):
        if CSS[index] == "{":
            depth += 1
        elif CSS[index] == "}":
            depth -= 1
            if depth == 0:
                assert block_start < rule_start < index
                return CSS[block_start:index + 1]
    raise AssertionError("desktop media block is not closed")


def test_wide_table_and_profit_cards_own_desktop_width():
    assert 'class="card desktop-wide" id="decision-matrix-card"' in HTML
    assert 'class="card desktop-wide" id="holdings-card"' in HTML
    assert 'class="card lead profit-extremes-card"' in HTML
    assert ".panel.active > .card.desktop-wide," in CSS


def test_holdings_dividers_do_not_partition_the_masonry_flow():
    selector = '.panel.active[data-panel="drill"] > .sect-divider'
    start = CSS.index(selector)
    rule = CSS[start:CSS.index("}", start)]
    assert "column-span: none" in rule
    assert "break-after: avoid" in rule
    assert ".holdings-section-heading" in CSS
    assert ".price-section-heading," in CSS
    assert 'id="movers-card"' in HTML
    assert 'id="anomalies-card"' in HTML
    assert HTML.count('class="desktop-section-kicker"') == 5
    assert HTML.count(
        'class="desktop-section-kicker" role="heading" aria-level="2"'
    ) == 2


def test_desktop_numeric_and_overview_height_rules_are_scoped_to_desktop():
    honesty = CSS.index(
        ".overview-command > .hero-honesty-card { align-self: start; }"
    )
    nowrap = CSS.index(".profit-extremes-card .ext-row .v {", honesty)
    block = enclosing_desktop_block(honesty)
    assert ".overview-command > .hero-honesty-card { align-self: start; }" in block
    assert ".profit-extremes-card .ext-row .v {" in block
    rule = CSS[nowrap:CSS.index("}", nowrap)]
    assert "white-space: nowrap" in rule
    assert "overflow-wrap: normal" in rule
    assert "text-overflow: ellipsis" in rule
    assert ".desktop-wide .holdings-table th," in block
    assert "height: 36px" in block
