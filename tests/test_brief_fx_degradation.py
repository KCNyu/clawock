"""The brief records the FX owner's degraded branches, not an invented key."""
import json
import os
import subprocess
import time
from unittest import mock

import pytest

from clawock.decision.book import validate_plan_book
from clawock.harness import brief_preflight as bp
from clawock.portfolio import fx


@pytest.mark.parametrize('branch', ['primary', 'secondary', 'stale', 'peg'])
def test_fx_owner_degradation_reaches_brief_issues(monkeypatch, tmp_path, branch):
    cache = tmp_path / 'fx.json'
    monkeypatch.setattr(fx, 'CACHE_PATH', str(cache))
    monkeypatch.setattr(fx, '_save_cache', lambda data: None)
    monkeypatch.setattr(fx, '_record_rate', lambda data: None)
    monkeypatch.setattr(fx, '_get_frankfurter', lambda: 7.84 if branch == 'primary' else None)
    monkeypatch.setattr(fx, '_get_open_er_api', lambda: 7.83 if branch == 'secondary' else None)
    monkeypatch.setattr(fx, '_get_yahoo', lambda: None)
    if branch == 'stale':
        cache.write_text(json.dumps({'rate': 7.79, 'source': 'Frankfurter',
                                    'fetched_at': '2026-01-01T00:00:00+00:00'}))
        stamp = time.time() - 50 * 3600
        os.utime(cache, (stamp, stamp))
    result = fx.get_usdhkd(force_refresh=True)
    monkeypatch.setattr(bp, 'fetch_fx_rate', lambda: result)
    booked, issues = bp.fx_rate()
    assert booked == result
    assert bool(issues) == (branch != 'primary')
    if issues:
        assert result['source'] in issues[0]


def _failed_fetch(monkeypatch, tmp_path, cache_entry):
    cache = tmp_path / 'fx.json'
    if cache_entry is not None:
        cache.write_text(json.dumps(cache_entry))
    monkeypatch.setattr(fx, 'CACHE_PATH', str(cache))
    monkeypatch.setattr(bp.subprocess, 'run', mock.Mock(side_effect=RuntimeError('provider down')))


def test_failed_fetch_reads_the_cached_rate_not_a_written_in_one(monkeypatch, tmp_path):
    _failed_fetch(monkeypatch, tmp_path, {
        'rate': 7.8472, 'source': 'Frankfurter',
        'fetched_at': '2026-10-24T00:03:33+00:00'})
    booked, issues = bp.fx_rate()
    assert booked['rate'] == 7.8472
    assert booked['fetched_at'] == '2026-10-24T00:03:33+00:00'
    assert booked['source'] == 'Frankfurter (cached; fx fetch failed)'
    assert issues == ['FX fallback used: Frankfurter (cached; fx fetch failed): '
                      'RuntimeError: provider down']


@pytest.mark.parametrize('stdout', [None, 'not json'])
def test_failed_fetch_without_a_cache_has_no_rate(monkeypatch, tmp_path, stdout):
    _failed_fetch(monkeypatch, tmp_path, None)
    if stdout is not None:
        monkeypatch.setattr(bp.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(
            a, 0, stdout=stdout, stderr=''))
    booked, issues = bp.fx_rate()
    assert booked['rate'] is None and booked['source'] == 'UNAVAILABLE'
    assert issues and issues[0].startswith('FX fallback used: UNAVAILABLE: ')
    # The plan cannot carry a book on no rate: postflight copies fx_used into
    # fx_rate_usdhkd, and the book check refuses it.
    assert validate_plan_book({'fx_rate_usdhkd': booked['rate'],
                               'book': {'hk_leg_hkd': -1000.0, 'us_leg_usd': 50.0}})
