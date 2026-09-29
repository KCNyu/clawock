"""#2176: the report leg names the holdings whose price it did not refresh.

The analyzer keeps the previous price for a holding no provider answered, and
its one "Failed:" line is swallowed in --wechat mode, so the block the report
delivers read as today's numbers. Drives the real `report_preflight.main()`
with the analyzer and network seams stubbed.
"""
import json
from datetime import datetime

from clawock import sessions as trading_calendar
from clawock.harness import report_preflight as preflight

BLOCK = '🇭🇰 港股盯盘 | 09/29 10:00 HKT\n\n📊 市值 HK$9,000'


def _holding(ticker, stamp):
    return {'ticker': ticker, 'shares': 100, 'current_price': 10.0,
            'data_source': f'Tencent {stamp} HKT'}


def test_a_carried_price_is_named_in_the_block_and_the_context(tmp_path, monkeypatch):
    portfolio = tmp_path / 'portfolio.json'

    def analyze(market):
        # A fetch stamps the rows it refreshed; 02208 keeps an old stamp.
        now = datetime.now(trading_calendar.HKT).strftime('%b %d %H:%M')
        portfolio.write_text(json.dumps({'portfolios': {'hk_stocks': {'holdings': [
            _holding('00100', now), _holding('02208', 'Sep 01 16:10')]}}}))
        return 0, BLOCK, ''

    monkeypatch.setattr(preflight, 'WS', tmp_path)
    monkeypatch.setattr(preflight, 'TMP', tmp_path)
    monkeypatch.setattr(preflight, 'run_analyze', analyze)
    monkeypatch.setattr(preflight, '_market_closed_reason', lambda *a: None)
    monkeypatch.setattr(preflight.workflow_outcomes, 'record_stage', lambda *a, **k: None)
    monkeypatch.setattr(preflight, 'collect_peers', lambda market: {})
    monkeypatch.setattr(preflight, 'live_information', lambda market: {})
    monkeypatch.setattr(preflight.research_surface, 'movers_thesis_context', lambda *a: {})
    monkeypatch.setattr(preflight.mover_news, 'probe', lambda *a, **k: {})
    monkeypatch.setattr(preflight.plan_surface, 'open_decisions_context', lambda **k: {})
    monkeypatch.setattr(preflight, 'parse_anomalies', lambda stdout: [
        {'ticker': '02208', 'move_pct': -3.5}, {'ticker': '00100', 'move_pct': 4.0}])

    assert preflight.main(['--market', 'hk', '--phase', 'open']) == 0
    ctx = json.loads(next(tmp_path.glob('report-context-hk-open-*.json')).read_text())

    assert ctx['quote_coverage'] == {'refreshed': 1, 'active': 2, 'unrefreshed': ['02208']}
    lines = ctx['raw_wechat_block'].splitlines()
    assert lines[0] == BLOCK.splitlines()[0]  # the watchdog's anchor
    assert lines[1].startswith('⛔') and '02208' in lines[1] and '00100' not in lines[1]
    assert [a.get('quote_fresh', True) for a in ctx['anomalies']] == [False, True]


def test_a_fully_refreshed_block_is_delivered_as_is():
    coverage = {'refreshed': 2, 'active': 2, 'unrefreshed': []}
    assert preflight.disclose_stale_quotes(BLOCK, coverage) == BLOCK
