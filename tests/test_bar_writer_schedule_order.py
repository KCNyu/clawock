"""Writer-time freshness and underlying-first merges; archives remain immutable."""
import json
from datetime import datetime

import pytest

from clawock.market_data import bars
from clawock.portfolio import integrity
from clawock.scheduling import latest_brief_bar_refresh, load_contract


def test_bar_clock_matches_brief_weekdays():
    job = next(j for j in load_contract()['jobs'] if j['name'] == '盘前深度简报')
    assert job['schedule']['expr'] == '3 8 * * 1-5'


@pytest.mark.parametrize('at', ['2026-10-21T08:30+08:00', '2026-10-21T17:30+08:00',
                                '2026-10-22T08:02+08:00', '2026-10-22T08:22+08:00'])
def test_store_stays_fresh_until_next_writer_deadline(tmp_path, at):
    for market in ['hk', 'us']:
        (tmp_path / f'{market}.json').write_text(json.dumps({
            'leg': market, 'bars': {'2026-10-20': {'close': 10}}}))
    assert integrity.summarize_bar_staleness(tmp_path, now=datetime.fromisoformat(at)) == []


def test_two_missed_writer_days_are_visible(tmp_path):
    (tmp_path / 'A.json').write_text(json.dumps({'leg': 'hk', 'bars': {'2026-10-16': {'close': 10}}}))
    rows = integrity.summarize_bar_staleness(tmp_path, now=datetime.fromisoformat('2026-10-22T08:23+08:00'))
    assert rows[0]['missing_sessions'] == ['2026-10-20', '2026-10-21']


def test_weekend_and_both_closed_days_do_not_create_writer_slots():
    for at in ['2026-10-24T18:00+08:00', '2026-10-26T08:02+08:00']:
        assert latest_brief_bar_refresh(datetime.fromisoformat(at)).isoformat().startswith('2026-10-23T08:03')
    assert latest_brief_bar_refresh(datetime.fromisoformat('2026-12-25T18:00+08:00')).date().isoformat() == '2026-12-24'


def test_registry_dependencies_precede_funds_and_single_ticker_stays_single():
    order = bars.dependency_order(list(bars.MANIFEST))
    for fund, underlying in [('SOXL', 'SOXX'), ('SPCH', 'SPCX'), ('07709', 'SKHY')]:
        assert order.index(underlying) < order.index(fund)
    assert bars.dependency_order(['SOXL']) == ['SOXL']


def _bar(close):
    return {'open': close, 'high': close * 1.01, 'low': close * .99, 'close': close}


def test_writer_merges_explanation_before_grading_and_preserves_history(tmp_path, monkeypatch):
    monkeypatch.setattr(bars, 'BARS_DIR', tmp_path / 'bars')
    monkeypatch.setattr(bars, 'CONFLICT_LOG', tmp_path / 'bar-conflicts.jsonl')
    monkeypatch.setattr(bars, 'MANIFEST', {t: bars.MANIFEST[t] for t in ['SOXL', 'SOXX']})
    monkeypatch.setattr(bars, '_last_closed_session', lambda _: '2026-10-21')
    for t in ['SOXL', 'SOXX']:
        bars.write_bars(t, {'bars': {'2026-10-20': _bar(100)}})
    calls = []
    def fetch(symbol, *_):
        calls.append(symbol)
        return [{'date': '2026-10-21', **_bar(155 if 'SOXL' in symbol else 118.333333)}]
    monkeypatch.setattr(bars, 'fetch_tencent', fetch)
    assert bars.main([]) == 0
    assert 'SOXX' in calls[0]
    fund = bars.load_bars('SOXL')['bars']
    assert fund['2026-10-20'] == _bar(100)
    assert not fund['2026-10-21'].get('implausible_move')
    assert not bars.CONFLICT_LOG.exists()


def test_conflict_summary_regrades_without_rewriting_log_or_bars(tmp_path):
    store = tmp_path / 'bars'
    store.mkdir()
    for t, close in [('SOXL', 155), ('SOXX', 118.333333)]:
        (store / f'{t}.json').write_text(json.dumps({'bars': {
            '2026-10-20': _bar(100), '2026-10-21': {**_bar(close), 'implausible_move': '55%'} if t == 'SOXL' else _bar(close)}}))
    log = tmp_path / 'bar-conflicts.jsonl'
    log.write_text(json.dumps({'ticker': 'SOXL', 'date': '2026-10-21', 'seen_at': '2026-10-21', 'kind': 'implausible_move'})+'\n')
    before = {p: p.read_bytes() for p in [log, *store.glob('*.json')]}
    assert integrity.summarize_bar_conflicts(log, now=datetime.fromisoformat('2026-10-21T18:00+08:00'))['total'] == 0
    assert all(p.read_bytes() == raw for p, raw in before.items())
    (store / 'SOXX.json').unlink()
    assert integrity.summarize_bar_conflicts(log, now=datetime.fromisoformat('2026-10-21T18:00+08:00'))['total'] == 1


def test_dashboard_normal_writer_schedule_is_healthy(tmp_path, monkeypatch):
    from clawock.publish import dashboard
    at = datetime.fromisoformat('2026-10-21T17:30+08:00')
    for market in ['hk', 'us']:
        (tmp_path / f'{market}.json').write_text(json.dumps({
            'leg': market, 'bars': {'2026-10-20': {'close': 10}}}))
    stale = integrity.summarize_bar_staleness(tmp_path, now=at)
    monkeypatch.setattr(integrity, 'check', lambda **k: {
        'ok': True, 'error_count': 0, 'warn_count': len(stale), 'findings': [], 'bar_staleness': stale})
    monkeypatch.setattr(dashboard, '_market_leg_freshness', lambda *a, **k: {'fresh': True})
    status = dashboard.compute_build_status({}, tmp_path, at=at,
        generated_files={'portfolio.json', *dashboard._FRESHNESS_POLICY})
    assert status['healthy'] is True
