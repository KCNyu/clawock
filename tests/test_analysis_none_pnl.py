"""`analyze-us` / `analyze-hk` render a row whose pnl fields are explicitly null.

`.get('pnl_percent', 0)` defaults only a *missing* key. A holding whose quote
was never refreshed can carry `None` while its shares are active, and the whole
report used to abort with a TypeError instead of degrading that row (#3498).
"""

from clawock.market_data import hk_analysis, us_analysis


def _holding(ticker, currency='USD'):
    return {
        'ticker': ticker, 'shares': 1, 'current_price': 10.0,
        'cost_basis': 5.0, 'current_value': 10.0, 'prev_close': 9.9,
        'today_change': 0.1, 'today_change_pct': 1.0,
        'pnl_percent': None, 'pnl_abs': None,
    }


def _book(leg, currency, holding):
    return {'portfolios': {leg: {
        'currency': currency, 'holdings': [holding],
        'total_cost': 5.0, 'total_current_value': 10.0, 'total_pnl': 5.0,
        'total_pnl_percent': 100.0, 'today_total_change': 0.1,
        'realized_pnl': 0.0,
    }}}


def test_us_reports_treat_none_pnl_as_unmeasured(capsys):
    holding = _holding('CRCL')
    data = _book('us_stocks', 'USD', holding)
    analysis = {'holding': holding, 'tech': {}, 'signal': 'HOLD',
                'reasons': [], 'news': []}

    us_analysis.print_report(data, [analysis])
    us_analysis.print_wechat_report(data, [analysis])

    out = capsys.readouterr().out
    assert 'CRCL' in out


def test_hk_reports_treat_none_pnl_as_unmeasured(monkeypatch, capsys):
    monkeypatch.setattr(hk_analysis, 'fetch_indices', lambda: {})
    holding = _holding('02208', 'HKD')
    data = _book('hk_stocks', 'HKD', holding)

    assert hk_analysis.signal(holding)  # must not compare None with a number
    hk_analysis.print_report(data, {})
    hk_analysis.print_wechat_report(data, {})

    out = capsys.readouterr().out
    assert '02208' in out
