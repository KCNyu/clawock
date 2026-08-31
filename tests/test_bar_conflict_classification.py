"""A refused provider disagreement has to be countable, not just printed (#1146).

`market_data.bars` already detected a stored-vs-fetched disagreement and already
refused to overwrite — that refusal is the invariant that keeps a settled ledger
reproducible. What it could not do was say *what kind* of disagreement it
refused, or how often: every refusal was one line in one cron log, so a source
that re-prices a bar by a split ratio once a quarter and a source that drifts by
a tick every week produced the same output.

So: classify at the point of refusal, append to an immutable log, and summarise
the log into the health report. Reporting only — nothing here may block a
publish, because the bars were not written and nothing downstream is wrong.
"""

import json
from pathlib import Path


def _bars_module(tmp_path, monkeypatch):
    from clawock.market_data import bars

    monkeypatch.setattr(bars, 'BARS_DIR', tmp_path)
    monkeypatch.setitem(
        bars.MANIFEST, 'TEST',
        {'leg': 'hk', 'tencent': 'hkTEST', 'em': None, 'retired': False})
    monkeypatch.setattr(bars, '_last_closed_session', lambda leg: '2026-01-31')
    return bars


def test_the_four_shapes_of_a_disagreement_are_told_apart():
    from clawock.market_data import bars

    stored = {'open': 10.0, 'high': 11.0, 'low': 9.0, 'close': 10.5}

    # Every leg scaled by one ratio — the signature of an adjusted series
    # reaching a store that is contractually raw.
    assert bars.classify_conflict(
        stored, {'open': 5.0, 'high': 5.5, 'low': 4.5, 'close': 5.25}
    ) == 'uniform_rescale'

    # Only the settlement price moved: an exchange revising the close.
    assert bars.classify_conflict(
        stored, {'open': 10.0, 'high': 11.0, 'low': 9.0, 'close': 10.7}
    ) == 'close_only'

    # Under 5bp on every leg is precision, not information.
    assert bars.classify_conflict(
        stored, {'open': 10.001, 'high': 11.0, 'low': 9.0, 'close': 10.5}
    ) == 'rounding'

    # Anything else is a real disagreement about what happened that session.
    assert bars.classify_conflict(
        stored, {'open': 10.0, 'high': 12.4, 'low': 9.0, 'close': 10.5}
    ) == 'bar_revision'

    # And the vocabulary is closed: every kind the classifier can emit is
    # declared, or a consumer counting kinds silently drops one.
    for fetched in ({'open': 5.0, 'high': 5.5, 'low': 4.5, 'close': 5.25},
                    {'open': 10.0, 'high': 11.0, 'low': 9.0, 'close': 10.7},
                    {'open': 10.001, 'high': 11.0, 'low': 9.0, 'close': 10.5},
                    {'open': 10.0, 'high': 12.4, 'low': 9.0, 'close': 10.5}):
        assert bars.classify_conflict(stored, fetched) in bars.CONFLICT_KINDS


def test_a_refusal_carries_its_kind_and_still_refuses(tmp_path, monkeypatch):
    mod = _bars_module(tmp_path, monkeypatch)
    first = [{'date': '2026-01-05', 'open': 10, 'high': 11, 'low': 9, 'close': 10.5}]
    assert mod.merge('TEST', first, repair=False)[0] == 1

    revised = [{'date': '2026-01-05', 'open': 5, 'high': 5.5, 'low': 4.5, 'close': 5.25}]
    added, _revised, conflicts = mod.merge('TEST', revised, repair=False)

    assert added == 0
    assert len(conflicts) == 1
    assert conflicts[0]['kind'] == 'uniform_rescale'
    assert conflicts[0]['stored']['close'] == 10.5
    assert conflicts[0]['fetched']['close'] == 5.25
    # The invariant this whole file is built on: nothing was overwritten.
    assert mod.load_bars('TEST')['bars']['2026-01-05']['close'] == 10.5


def test_refusals_are_appended_to_an_immutable_log(tmp_path, monkeypatch):
    mod = _bars_module(tmp_path, monkeypatch)
    log = tmp_path / 'bar-conflicts.jsonl'

    written = mod.record_conflicts('TEST', [
        {'date': '2026-01-05', 'kind': 'close_only', 'detail': 'x'},
    ], path=log)
    assert written == 1
    mod.record_conflicts('TEST', [
        {'date': '2026-01-06', 'kind': 'bar_revision', 'detail': 'y'},
    ], path=log)

    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert [row['date'] for row in rows] == ['2026-01-05', '2026-01-06']
    assert all(row['ticker'] == 'TEST' and row['seen_at'] for row in rows)
    # Nothing to record must not create a file — an empty log and a silent
    # failure to write one should not look the same.
    assert mod.record_conflicts('TEST', [], path=tmp_path / 'absent.jsonl') == 0
    assert not (tmp_path / 'absent.jsonl').exists()


def test_the_health_report_counts_them_by_kind_without_blocking(tmp_path):
    from datetime import datetime, timedelta, timezone

    from clawock.portfolio import integrity

    now = datetime(2026, 1, 31, tzinfo=timezone.utc)
    recent = (now - timedelta(days=2)).isoformat(timespec='seconds')
    stale = (now - timedelta(days=90)).isoformat(timespec='seconds')
    log = tmp_path / 'bar-conflicts.jsonl'
    log.write_text('\n'.join(json.dumps(row) for row in [
        {'ticker': '00100', 'date': '2026-01-28', 'kind': 'close_only', 'seen_at': recent},
        {'ticker': '00100', 'date': '2026-01-29', 'kind': 'close_only', 'seen_at': recent},
        {'ticker': 'SPCH', 'date': '2026-01-29', 'kind': 'bar_revision', 'seen_at': recent},
        {'ticker': 'SPCH', 'date': '2025-10-01', 'kind': 'bar_revision', 'seen_at': stale},
    ]) + '\n')

    summary = integrity.summarize_bar_conflicts(log, now=now)

    assert summary['total'] == 3, "the 90-day-old row is outside the window"
    assert summary['by_kind'] == {'close_only': 2, 'bar_revision': 1}
    assert summary['by_ticker'] == {'00100': 2, 'SPCH': 1}
    assert summary['last_seen_at'] == recent


def test_a_missing_or_corrupt_log_is_zero_not_an_exception(tmp_path):
    from clawock.portfolio import integrity

    absent = integrity.summarize_bar_conflicts(tmp_path / 'nope.jsonl')
    assert absent['total'] == 0 and absent['by_kind'] == {}

    broken = tmp_path / 'broken.jsonl'
    broken.write_text('{not json\n\n')
    assert integrity.summarize_bar_conflicts(broken)['total'] == 0


def test_the_report_names_them_and_still_publishes(tmp_path, monkeypatch):
    """WARN, never ERROR: the bars were refused, so nothing downstream is wrong.

    Blocking a publish over a provider's revision would trade a disagreement
    that is visible for one that is not — the same trade this repo refuses
    everywhere else.
    """
    from clawock.portfolio import integrity

    book = tmp_path / 'portfolio.json'
    book.write_text(json.dumps({'portfolios': {}}))

    clean = integrity.check(book)
    assert clean['bar_conflicts']['total'] == 0
    assert not [f for f in clean['findings'] if f['code'] == 'BAR_CONFLICT']

    monkeypatch.setattr(integrity, 'summarize_bar_conflicts', lambda *a, **k: {
        'window_days': 30, 'total': 3, 'by_kind': {'bar_revision': 2, 'rounding': 1},
        'by_ticker': {'00100': 3}, 'last_seen_at': '2026-01-29T08:00:00+08:00',
        'log': 'bar-conflicts.jsonl',
    })
    noisy = integrity.check(book)

    finding = [f for f in noisy['findings'] if f['code'] == 'BAR_CONFLICT']
    assert len(finding) == 1
    assert finding[0]['level'] == 'WARN'
    # Ordered worst-first so the six findings the dashboard shows lead with the
    # kind that actually disagrees about the session.
    assert 'bar_revision 2' in finding[0]['msg']
    assert noisy['warn_count'] == clean['warn_count'] + 1
    assert noisy['ok'] is True, 'a refused bar must never block a publish'
    assert noisy['bar_conflicts']['by_ticker'] == {'00100': 3}
