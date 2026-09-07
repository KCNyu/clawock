"""A closed-market sentinel must not be mistaken for today's brief context.

Sibling of the 2026-09-07 intraday_watchdog holiday bug. `brief_preflight`
writes a blockless `market_closed` sentinel under the same
`brief-context-{date}.json` name it uses for a real context, so on a day both
markets are closed the newest file by mtime is a five-key stub. That stub still
passes the caller's `bool(brief_ctx)` presence test, which is what tells the
merge-not-overwrite guard NOT to restore the last good card — so the risk and
add-side cards would publish empty, as if the brief had run and found nothing.
"""
import json
import os
import time

from clawock.publish import dashboard


REAL = {
    'date': '2026-12-24',
    'concentration': {'hk': {'weights': [{'ticker': '0700.HK', 'weight_pct': 30}]}},
    'opportunity': {'candidates': []},
}
SENTINEL = {
    'status': 'market_closed',
    'date': '2026-12-25',
    'reason': '港股节假日休市+美股节假日休市',
    'skip': True,
}


def _write(tmp_path, name, payload, mtime):
    path = tmp_path / 'memory' / '.tmp' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False))
    os.utime(path, (mtime, mtime))
    return path


def test_the_newest_context_is_skipped_when_it_is_a_holiday_sentinel(
        tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, 'WS_ROOT', tmp_path)
    now = time.time()
    real = _write(tmp_path, 'brief-context-2026-12-24.json', REAL, now - 86400)
    _write(tmp_path, 'brief-context-2026-12-25.json', SENTINEL, now)

    path, context = dashboard._latest_brief_context()

    assert path == str(real)
    assert context['concentration']          # the card keeps yesterday's real data


def test_only_sentinels_reads_as_no_context_so_the_restore_path_runs(
        tmp_path, monkeypatch):
    """(None, None) is the state the merge-not-overwrite guard is built for."""
    monkeypatch.setattr(dashboard, 'WS_ROOT', tmp_path)
    _write(tmp_path, 'brief-context-2026-12-25.json', SENTINEL, time.time())

    assert dashboard._latest_brief_context() == (None, None)


def test_a_normal_day_still_picks_the_newest_context(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, 'WS_ROOT', tmp_path)
    now = time.time()
    _write(tmp_path, 'brief-context-2026-12-23.json', {'date': '2026-12-23'}, now - 86400)
    newest = _write(tmp_path, 'brief-context-2026-12-24.json', REAL, now)

    path, context = dashboard._latest_brief_context()

    assert path == str(newest)
    assert context['date'] == '2026-12-24'
