"""#2680: freeze the pre-extraction writer at its normalized provider seams.

Inputs combine incident quotes already captured in test_us_quote_staleness with
synthetic boundary cases. Expected documents and diagnostics were captured from
master db5f1d644 BEFORE extraction; tests never regenerate the oracle. No live
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
    monkeypatch.setattr(quotes, 'fetch_us_quotes', lambda *args: {'PLTU': copy.deepcopy(case['quote'])})
    monkeypatch.setattr(quotes, 'fetch_us_indices', lambda: {})
    monkeypatch.setattr(quotes, 'get_prev_closes_polygon_grouped',
                        lambda *args: (copy.deepcopy(case['grouped']), case['rate_limited'], case['snapshot_valid']))
    calls = []

    def per_ticker(ticker, key):
        calls.append(ticker)
        return case['per_ticker']

    monkeypatch.setattr(quotes, 'get_prev_close_polygon', per_ticker)
    path.write_text(json.dumps(case['portfolio']))
    result = quotes.update_us_portfolio(str(path))
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
