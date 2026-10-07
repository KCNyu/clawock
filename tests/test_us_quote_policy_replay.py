"""#2680: freeze the pre-extraction writer at its normalized provider seams.

Inputs combine incident quotes already captured in test_us_quote_staleness with
synthetic boundary cases. Expected documents and diagnostics were captured from
master db5f1d644 BEFORE extraction; additional branch cases were captured from
fb31168ab before the #2754 fix. Tests never regenerate the oracle. No live
portfolio, credentials or network are involved.
"""
import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

from clawock.market_data import us_quotes as quotes

FIXTURES = Path(__file__).parent / 'fixtures' / 'us_quote_policies'
CASES = json.loads((FIXTURES / 'replay.json').read_text())


def run_case(case, monkeypatch, path, capsys):
    instant = datetime.fromisoformat(case['now'])

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(quotes, 'datetime', Clock)
    monkeypatch.setattr(quotes, 'load_api_keys', lambda: case['keys'])
    quote_calls = []

    def fetch(tickers, keys):
        quote_calls.append(list(tickers))
        return {ticker: copy.deepcopy(case['quote']) for ticker in tickers}

    monkeypatch.setattr(quotes, 'fetch_us_quotes', fetch)
    if 'index_providers' in case:
        providers = case['index_providers']
        for function, provider in [('get_tencent_us_index', 'tencent'),
                                   ('get_yfinance_quote', 'yfinance'),
                                   ('get_nasdaq_quote', 'nasdaq')]:
            monkeypatch.setattr(quotes, function,
                                lambda symbol, provider=provider: copy.deepcopy(
                                    providers.get(provider, {}).get(symbol)))
    else:
        monkeypatch.setattr(quotes, 'fetch_us_indices', lambda: {})
    monkeypatch.setattr(quotes, 'get_prev_closes_polygon_grouped',
                        lambda *args: (copy.deepcopy(case['grouped']), case['rate_limited'], case['snapshot_valid']))
    calls = []

    def per_ticker(ticker, key):
        calls.append(ticker)
        return case['per_ticker']

    monkeypatch.setattr(quotes, 'get_prev_close_polygon', per_ticker)
    path.write_text(json.dumps(case['portfolio']))
    before = path.read_bytes(), path.stat().st_mtime_ns
    if case.get('dry_run'):
        from clawock import safe_io
        from clawock.portfolio import realized
        monkeypatch.setattr(safe_io, 'mutate_json',
                            lambda *args, **kwargs: pytest.fail('dry-run attempted a write'))
        monkeypatch.setattr(realized, 'recompute',
                            lambda *args, **kwargs: pytest.fail('dry-run recomputed realized'))
    result = quotes.update_us_portfolio(
        str(path), dry_run=case.get('dry_run', False),
        tickers_override=case.get('tickers_override'))
    if case.get('dry_run'):
        assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    if 'tickers_override' in case:
        assert quote_calls == [case['tickers_override'] or ['PLTU', 'RKLB']]
    out, err = capsys.readouterr()
    return {'returned': result, 'written': json.loads(path.read_text()),
            'stdout': out.replace(str(path), '<portfolio>'), 'stderr': err,
            'per_ticker_calls': calls}


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['name'])
def test_writer_replays_pre_extraction_documents(case, monkeypatch, tmp_path, capsys):
    assert run_case(case, monkeypatch, tmp_path / 'portfolio.json', capsys) == case['expected']


@pytest.mark.parametrize('provider_pc,expected_price,repaired', [(27.35, 28.82, True), (20, 27.35, False)])
def test_stale_repair_requires_the_same_provider_baseline(provider_pc, expected_price, repaired, capsys):
    q = {'c': 27.35, 'pc': provider_pc, 'nc': 1.47, 'dp': 5.37, 'source': 'Nasdaq API (etf)'}
    price, repair = quotes._stale_last_price_guard(
        q, 27.35, 27.35, '2026-08-04', ticker='PLTU', today_et_date='2026-08-05',
        now_et=datetime.fromisoformat('2026-08-05T12:01:00-04:00'))
    assert price == expected_price
    assert bool(repair) is repaired
    assert ('NOT rebuilding' in capsys.readouterr().err) is not repaired


def test_prior_close_ladder_prefers_provider_move_to_stored_close():
    q = {'c': 30, 'pc': 30, 'dp': 20}
    holding = {'prev_close': 24, 'prev_close_date': '2026-08-04'}
    assert quotes._resolve_prev_close(
        q, holding, {}, ticker='PLTU', today_et_date='2026-08-05',
        expected_prev_session='2026-08-04') == (30, 25, '2026-08-04')


@pytest.mark.parametrize('ticker,provider_has_quote', [
    ('INVALID_TICKER', False), ('MSFT', True), ('CLOSED', True),
])
def test_override_rejects_non_active_holdings_before_fetch(
    ticker, provider_has_quote, monkeypatch, tmp_path
):
    path = tmp_path / 'portfolio.json'
    path.write_text(json.dumps(CASES[0]['portfolio']))
    before = path.read_bytes(), path.stat().st_mtime_ns
    calls = []
    monkeypatch.setattr(quotes, 'load_api_keys', lambda: {})

    def fetch(tickers, keys):
        calls.append(tickers)
        return {t: copy.deepcopy(CASES[0]['quote']) for t in tickers} if provider_has_quote else {}

    monkeypatch.setattr(quotes, 'fetch_us_quotes', fetch)
    monkeypatch.setattr(quotes, 'fetch_us_indices', lambda: {})
    with pytest.raises(ValueError, match='tickers_override contains non-active holdings'):
        quotes.update_us_portfolio(str(path), tickers_override=['PLTU', ticker])
    assert calls == []
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
