from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHARTS = (ROOT / "site/assets/js/dashboard.charts.js").read_text()
UI = (ROOT / "site/assets/js/dashboard.ui.js").read_text()


def test_equity_chart_is_native_and_outside_echarts_gate():
    # Equity Curve 已随卡片挪到 Reflect（首屏曲线减负），但它仍是全站唯一的
    # native canvas 图：注册在 NATIVE_CHART_FNS，绝不进 ECharts 懒加载闸 ——
    # 否则展示它就得先拖 ~620KB 的包。
    native_block = CHARTS.split("const NATIVE_CHART_FNS", 1)[1].split("const CHART_FNS", 1)[0]
    echarts_block = CHARTS.split("const CHART_FNS", 1)[1].split("const _chartTabsShown", 1)[0]

    assert "reflect:" in native_block
    assert "renderEquityChart()" in native_block
    assert "hero:" not in native_block
    # ECharts 系注册表只管自己的三张图，不得染指 equity
    assert "renderEquityChart" not in echarts_block
    assert "createNativeEquityChart" in CHARTS


def test_market_switch_renders_in_place_without_forcing_echarts_fetch():
    # 切换器与两张图同住 Reflect：能点到按钮 = 面板可见。切换必须就地重画
    # 两张图（native 直画；ECharts 未就绪时由其内部 early-return 兜住，
    # 懒加载完成后经 ensureTabCharts 重画），而不是自己去 whenEcharts 拉包。
    market_block = CHARTS.split("function setMarketView", 1)[1].split(
        "function renderShadowPortfolioChart", 1
    )[0]

    assert 'if (currentTab() === "reflect")' in market_block
    assert "renderEquityChart()" in market_block
    assert "renderDailyPnlChart()" in market_block
    assert "whenEcharts" not in market_block


def test_native_equity_preserves_interaction_contract():
    native = CHARTS.split("function createNativeEquityChart", 1)[1].split(
        "function renderEquityChart", 1
    )[0]

    for contract in (
        'type="range"',
        'aria-label="净值图起始日期"',
        'pointermove',
        'pointerleave',
        '总利润较昨日',
        '回撤',
    ):
        assert contract in native


def test_boot_documents_detail_only_echarts_loading():
    assert "ECharts bundle is fetched only" in UI
