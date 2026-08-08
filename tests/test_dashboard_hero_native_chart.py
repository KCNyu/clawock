from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHARTS = (ROOT / "site/assets/js/dashboard.charts.js").read_text()
UI = (ROOT / "site/assets/js/dashboard.ui.js").read_text()


def test_hero_renderer_is_native_and_outside_echarts_gate():
    native_block = CHARTS.split("const NATIVE_CHART_FNS", 1)[1].split("const CHART_FNS", 1)[0]
    echarts_block = CHARTS.split("const CHART_FNS", 1)[1].split("const _chartTabsShown", 1)[0]

    assert "hero:" in native_block
    assert "renderEquityChart()" in native_block
    assert "hero:" not in echarts_block
    assert "createNativeEquityChart" in CHARTS


def test_market_switch_does_not_load_echarts_from_hero():
    market_block = CHARTS.split("function setMarketView", 1)[1].split(
        "function renderShadowPortfolioChart", 1
    )[0]

    assert "if (window.echarts) renderDailyPnlChart()" in market_block
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
