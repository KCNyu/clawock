"""Static guardrails for the desktop-only layout fixes.

Rendered Chromium smoke tests remain the visual proof. These checks make the
intentional ownership classes and desktop scope hard to lose in a later CSS
refactor.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "site/index.html").read_text()
CSS = (ROOT / "site" / "assets" / "css" / "dashboard.css").read_text()
VISUAL_REGRESSION = ROOT / "docs" / "visual-regression" / "issue-206"
VISUAL_REGRESSION_DOC = (
    ROOT / "docs" / "visual-regression" / "issue-206" / "README.md"
)


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
    # 决策矩阵与持仓表已合并成一张可展开主表（#875）；契约不变：宽表独占桌面宽度
    assert 'class="card desktop-wide" id="book-card"' in HTML
    assert 'class="card desktop-wide" id="tape-card"' in HTML
    assert 'profit-extremes-card" id="recovery-card"' in HTML
    assert ".panel.active > .card.desktop-wide," in CSS


def test_holdings_dividers_do_not_partition_the_masonry_flow():
    selector = '.panel.active[data-panel="drill"] > .sect-divider'
    start = CSS.index(selector)
    rule = CSS[start:CSS.index("}", start)]
    assert "column-span: none" in rule
    assert "break-after: avoid" in rule
    assert ".holdings-section-heading" in CSS
    assert ".price-section-heading," in CSS
    # movers / anomalies 合并成一张「今日异动」卡（#877）。原来每张卡各挂一个
    # desktop-section-kicker 来标同一段落，合并后一段只需要一个标题，所以这里
    # 断的是「分节标题没有重复」而不是原来的固定条数。
    assert 'id="today-action-card"' in HTML
    assert HTML.count('class="desktop-section-kicker"') <= 2


def test_webkit_reflect_uses_desktop_only_ordinary_flow_fallback():
    ui = (ROOT / "site" / "assets" / "js" / "dashboard.ui.js").read_text()
    assert "/AppleWebKit/i.test" in ui
    assert 'classList.toggle("is-webkit", WEBKIT)' in ui

    selector = 'html.is-webkit .panel.active[data-panel="reflect"] {'
    start = CSS.index(selector)
    block = enclosing_desktop_block(start)
    rule = CSS[start:CSS.index("}", start)]
    assert selector in block
    assert "column-count: auto" in rule
    assert 'html.is-webkit .panel.active[data-panel="reflect"] > * {' in block
    assert "break-inside: auto" in block
    assert "column-span: none" in block


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


def test_gold_dca_uses_the_full_desktop_row_and_an_internal_grid():
    gold = CSS.index(
        ".overview-command > .hero-gold-card {", CSS.index("min-height: 760px")
    )
    block = enclosing_desktop_block(gold)
    assert "grid-column: 1 / -1" in block
    assert "min-height: 0" in block
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in block
    assert '"title domestic"' in block
    assert '"hero domestic"' in block
    assert '"stats domestic"' in block
    assert '"spark london"' in block
    assert '"proj london"' in block
    assert '"asof asof"' in block
    for area, selector in (
        ("title", ".hero-gold-card > h3"),
        ("hero", "#gold-hero"),
        ("stats", "#gold-stats"),
        ("domestic", "#gold-domestic"),
        ("london", "#gold-london"),
        ("spark", "#gold-spark"),
        ("proj", "#gold-proj"),
        ("asof", "#gold-asof"),
    ):
        assert f"{selector} {{ grid-area: {area};" in block


def test_gold_dca_mobile_floor_and_single_column_rules_remain():
    mobile = CSS.split("@media (max-width: 767px)", 1)[1]
    assert ".overview-command { display: flex; flex-direction: column" in mobile
    assert ".overview-command > .hero-gold-card { min-height: 760px; }" in mobile


def test_issue_206_visual_regression_evidence_is_shipped():
    readme = VISUAL_REGRESSION_DOC.read_text(encoding="utf-8")
    for name in (
        "before-1440.jpg", "after-1440.jpg",
        "before-1920.jpg", "after-1920.jpg", "after-390.jpg",
    ):
        image = VISUAL_REGRESSION / name
        assert image.stat().st_size > 20_000, f"missing/empty screenshot: {name}"
        assert name in readme
    assert "scrollWidth == clientWidth" in readme


def test_overview_keeps_one_owner_per_first_screen_fact():
    """首屏同一个数只能有一个 owner（第七次迭代，kcn：「内容会和下面重复」）。

    v6 之前判定牌组四张里有两张是别处的子集：黄金回本牌是下方
    ``#gold-dca-card`` 的逐字子集，执行纪律牌的「执行率 / 笔可核」是正上方
    hero-rail 第四格「遵守率 30D · 主动 call n=」的同一对数字；牌组的异动
    零轴柱与 strip 的「今日异动」格同吃 ``today_movers``。删掉的是重复的那
    一份，留下的是更全的那份 —— 这条闸钉的就是「不许把它们加回来」，而不是
    某个具体的牌数。
    """
    # 黄金 / 纪律：牌上的挂载点没了，完整卡还在
    assert 'id="deck-gold"' not in HTML
    assert 'id="deck-discipline"' not in HTML
    assert 'id="gold-dca-card"' in HTML
    # 异动：strip 的摘要格没了，判定牌的 top3 零轴柱还在（hl-mv 由 JS 生成，
    # 这里钉的是它的样式契约仍在，且 strip 不再有第二个 owner）
    assert 'id="overview-mover-summary"' not in HTML
    assert ".deck-card .hl-mv-bar" in CSS
    assert HTML.count('class="overview-strip-cell') == 2
    # 异常：只留 strip 那一格（牌上的 chip 由 renderTodayHighlights 生成，
    # 两份 bundle 里都不许再出现那枚 chip 的构造）
    assert 'id="overview-anomaly-count"' in HTML
    for bundle in ("dashboard.hero.js", "dashboard.render.js"):
        js = (ROOT / "site" / "assets" / "js" / bundle).read_text()
        assert "异常×${highN}" not in js
