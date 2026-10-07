"""Discovery must broaden research without turning exposure or missing data into authority."""
import json
from pathlib import Path

import pytest

from clawock.market_data import stock_discovery as D

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / 'config/stock-discovery.json').read_text())
STAMP = '2026-10-08T00:00:00+00:00'


def row(ticker, sector='Health Care', **overrides):
    return {'symbol': ticker, 'name': f'{ticker} Common Stock', 'sector': sector,
            'industry': 'Test industry', 'marketCap': '3,000,000,000',
            'lastsale': '$10', 'volume': '5,000,000', 'pctchange': '2%', **overrides}


def screen(rows, portfolio=None, registry=None, **policy):
    return D.screen_snapshot({'data': {'rows': rows, 'asOf': None}},
                             portfolio or {'portfolios': {}}, registry or {},
                             {**POLICY, **policy}, retrieved_at=STAMP)


def test_breadth_is_independent_of_holdings_and_excludes_leveraged_exposure():
    portfolio = {'portfolios': {'us_stocks': {'holdings': [
        {'ticker': 'LEVR', 'shares': 2}, {'ticker': 'AAA', 'shares': 0}]}}}
    registry = {'LEVR': {'underlying': 'BASE', 'signal_symbol': 'BASE', 'one_x_substitute': 'BASE'}}
    result = screen([row('LEVR'), row('BASE'), row('AAA'),
                     row('MED'), row('TECH', 'Technology'), row('ENE', 'Energy')],
                    portfolio, registry)
    symbols = [r['ticker'] for r in result['candidates']]
    assert 'LEVR' not in symbols and 'BASE' not in symbols
    assert 'AAA' in symbols
    assert len({r['sector'] for r in result['candidates']}) == 3
    assert result['rejections']['held_or_underlying'] == 2
    assert all(r['allowed'] is False and r['state'] == 'needs_entry_gate'
               for r in result['candidates'])
    assert all(r['evidence']['observed_at'] is None for r in result['candidates'])
    assert all(r['evidence']['retrieved_at'] == STAMP for r in result['candidates'])


def test_bad_metrics_missing_sectors_and_noncompanies_never_get_ranked():
    rows = [row('GOOD'), row('NAN', marketCap='NaN'), row('INF', lastsale='Infinity'),
            row('BOOL', volume=True), row('NOSEC', sector=''),
            row('HOT', pctchange='6%'), row('FUND', name='Test ETF Fund'),
            row('WARR', name='Test Warrants'), row('GOOD')]
    result = screen(rows)
    assert [r['ticker'] for r in result['candidates']] == ['GOOD']
    assert result['rejections']['missing_metrics'] == 3
    assert sum(result['rejections'].values()) == 8
    assert screen([row('HOT', pctchange='6%')])['status'] == 'no_candidates'


@pytest.mark.parametrize('rows', [[], [row('BAD', volume=None, sector=None)]])
def test_empty_or_incomplete_cannot_masquerade_as_source_success(rows):
    if not rows:
        with pytest.raises(ValueError):
            screen(rows)
    else:
        assert screen(rows)['candidates'] == []
    with pytest.raises(ValueError, match='columns'):
        D.screen_snapshot({'data': {'rows': [{'symbol': 'BAD'}]}},
                          {'portfolios': {}}, {}, POLICY, retrieved_at=STAMP)


def test_corrupt_book_and_missing_exposure_metadata_fail_closed():
    with pytest.raises(ValueError):
        D.excluded_exposure({}, {})
    with pytest.raises(ValueError):
        D.excluded_exposure({'portfolios': {'us': {'holdings': [{'ticker': 'LEV', 'shares': 1}]}}}, {})


def test_policy_cannot_override_output_budget_or_silently_ignore_bad_bounds():
    for changes in ({'max_candidates': 13}, {'min_price_usd': True},
                    {'min_change_pct': 8, 'max_change_pct': 4}):
        with pytest.raises(ValueError):
            screen([row('GOOD')], **changes)


def test_source_failure_is_distinct_and_collect_never_writes(tmp_path):
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/stock-discovery.json').write_text(json.dumps(POLICY))
    (tmp_path / 'portfolio.json').write_text('{"portfolios": {}}')
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}

    def fail():
        raise TimeoutError('secret-looking provider diagnostic')

    result = D.collect(tmp_path, fetcher=fail)
    assert result['status'] == 'unavailable' and result['candidates'] == []
    assert 'Nasdaq' in result['degraded'][0] and 'secret-looking' not in str(result)
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_real_consumer_path_packet_summary_report_card_and_reinjection():
    from clawock.decision import packet
    from clawock.harness import brief_card, brief_render

    discovery = screen([row('MED'), row('ENE', 'Energy')])
    compiled = packet.compile_packet({
        'date': '2026-10-08', 'generated_at': STAMP,
        'portfolio': {'portfolios': {}}, 'stock_discovery': discovery}, generation_id='discovery-test')
    assert compiled['stock_discovery'] == discovery
    assert packet.validate_plan_constraints({'decisions': [
        {'ticker': 'MED', 'action': 'add_only_on_trigger', 'size': {'shares': 1}}]}, compiled)
    assert packet.summary_view(compiled)['stock_discovery'] == discovery
    report = brief_render.stock_discovery_section(compiled)
    assert 'MED' in report and 'ENE' in report and '时间未核验' in report
    first = brief_card._inject_early_candidate_section('intro\n📈 report', compiled)
    assert 'MED' in first and '持仓外新标的' in first
    second = brief_card._inject_early_candidate_section(first, compiled)
    assert second == first
    failure = brief_card._inject_early_candidate_section(first, {'stock_discovery': D.unavailable('timeout')})
    assert '未取到' in failure and 'MED' not in failure


def test_preflight_runs_bounded_command_and_keeps_failure_out_of_book_issues(monkeypatch):
    from types import SimpleNamespace
    from clawock.harness import brief_preflight as P

    def run(argv, **kwargs):
        assert argv[-2:] == ['discover-stocks', '--json']
        assert kwargs['timeout'] == 25
        return SimpleNamespace(returncode=0, stdout=json.dumps(screen([row('MED')])))

    monkeypatch.setattr(P.subprocess, 'run', run)
    result, issues = P.stock_discovery_node()
    assert result['candidates'][0]['ticker'] == 'MED' and issues == []
    monkeypatch.setattr(P.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=1))
    result, issues = P.stock_discovery_node()
    assert result['status'] == 'unavailable' and issues == []
