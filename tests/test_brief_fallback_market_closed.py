"""The off-host brief fallback must not manufacture a brief for a closed day.

`prepare_context` reports a `market_closed` sentinel as "incomplete", and
incomplete means fail-closed artifacts — a zero-action pre-open.md + plan.json.
Written on a day neither market opens, those read downstream as "the brief ran
and had nothing to say". brief_watchdog gates that day and should never dispatch
this workflow, but a manual `gh workflow run brief-fallback.yml` bypasses it,
which is the whole reason this second layer exists.
"""
import json
from datetime import date

import pytest

from clawock.automation import brief_fallback


TODAY = '2026-12-25'
SENTINEL = {'status': 'market_closed', 'date': TODAY,
            'reason': '港股节假日休市+美股节假日休市', 'skip': True}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    (tmp_path / 'memory' / '.tmp').mkdir(parents=True)
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(tmp_path))
    monkeypatch.setenv('TODAY', TODAY)
    return tmp_path


def test_a_market_closed_sentinel_writes_no_artifacts(workspace, monkeypatch):
    (workspace / 'memory' / '.tmp' / f'brief-context-{TODAY}.json').write_text(
        json.dumps(SENTINEL, ensure_ascii=False))
    monkeypatch.setattr(brief_fallback, 'chat',
                        lambda *a, **kw: pytest.fail('vendor call on a closed day'))

    brief_fallback.main([])

    assert not (workspace / 'memory' / f'{TODAY}-pre-open.md').exists()
    assert not (workspace / 'memory' / f'{TODAY}-plan.json').exists()


def test_manual_fallback_defaults_to_the_hk_desk_date(tmp_path, monkeypatch):
    (tmp_path / 'memory' / '.tmp').mkdir(parents=True)
    (tmp_path / 'memory' / '.tmp' / f'brief-context-{TODAY}.json').write_text(
        json.dumps(SENTINEL, ensure_ascii=False))
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(tmp_path))
    monkeypatch.delenv('TODAY', raising=False)
    monkeypatch.setattr(brief_fallback.sessions, 'hkt_today',
                        lambda: date.fromisoformat(TODAY))

    brief_fallback.main([])

    assert not (tmp_path / 'memory' / f'{TODAY}-plan.json').exists()


def test_an_ordinary_incomplete_context_still_fails_closed(workspace, monkeypatch):
    """The gate is about `market_closed` only — a real broken context still fails closed."""
    (workspace / 'memory' / '.tmp' / f'brief-context-{TODAY}.json').write_text(
        json.dumps({'date': TODAY}))
    monkeypatch.setattr(brief_fallback, 'chat',
                        lambda *a, **kw: pytest.fail('vendor call on a broken context'))

    brief_fallback.main([])

    assert (workspace / 'memory' / f'{TODAY}-pre-open.md').exists()
    assert (workspace / 'memory' / f'{TODAY}-plan.json').exists()


@pytest.mark.parametrize('failure', ['price_refresh_failed', 'preflight_timeout'])
def test_failed_price_refresh_never_calls_model_or_overwrites_brief(workspace, monkeypatch, failure):
    (workspace / 'memory' / '.tmp' / f'brief-context-{TODAY}.json').write_text(
        json.dumps({'status': failure, 'date': TODAY,
                    'issues': ['US refresh failed']}))
    old = {}
    for suffix in ('pre-open.md', 'plan.json'):
        path = workspace / 'memory' / f'{TODAY}-{suffix}'
        path.write_text('earlier successful artifact')
        old[path] = (path.read_bytes(), path.stat().st_mtime_ns)
    monkeypatch.setattr(brief_fallback, 'chat',
                        lambda *a, **kw: pytest.fail('model call after price refresh failure'))

    with pytest.raises(SystemExit) as exit:
        brief_fallback.main([])
    assert exit.value.code == 1
    for path, before in old.items():
        assert (path.read_bytes(), path.stat().st_mtime_ns) == before
