"""The brief records the FX owner's degraded branches, not an invented key."""
import json
import os
import time

import pytest

from clawock.harness import brief_preflight as bp
from clawock.portfolio import fx


@pytest.mark.parametrize('branch', ['primary', 'secondary', 'stale', 'peg'])
def test_fx_owner_degradation_reaches_brief_issues(monkeypatch, tmp_path, branch):
    cache = tmp_path / 'fx.json'
    monkeypatch.setattr(fx, 'CACHE_PATH', str(cache))
    monkeypatch.setattr(fx, '_save_cache', lambda data: None)
    monkeypatch.setattr(fx, '_record_rate', lambda data: None)
    monkeypatch.setattr(fx, '_get_frankfurter', lambda: 7.84 if branch == 'primary' else None)
    monkeypatch.setattr(fx, '_get_exchangerate_host', lambda: 7.83 if branch == 'secondary' else None)
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


def test_subprocess_failure_still_records_an_issue(monkeypatch):
    monkeypatch.setattr(bp, 'fetch_fx_rate', lambda: {
        'rate': 7.8, 'source': 'fallback', 'error': 'provider down'})
    _, issues = bp.fx_rate()
    assert issues == ['FX fallback used: provider down']
