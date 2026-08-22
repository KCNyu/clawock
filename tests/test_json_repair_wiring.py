"""Where json_repair is plugged in, and how each outcome stays visible.

A correct repairer that nothing calls fixes nothing, and a repair nobody can see
is worse than the crash it replaced: the 2026-07-28 sidecar defect was noticed
only *because* it turned the daily health check red. These tests pin the path
that keeps it observable without keeping it fatal:

    build_dashboard  →  `repair:` on stderr, distinct from `warn:`
    _harness_common  →  repair_count in dashboard_build_status.json
    cron_health_check→  state 'repaired', its own line, exit code unchanged

and two boundaries that must not move:

  * an unrepairable or ambiguous file still degrades the build, and
  * it must NOT look like an absent file, because absence republishes the
    previous day's card — showing yesterday's critique as today's.
"""
import json
from types import SimpleNamespace
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from clawock.publish import dashboard  # noqa: E402
import cron_health_check  # noqa: E402
from clawock.harness import _harness_common  # noqa: E402


BROKEN = ('{\n  "behavioral_review": [{"tag": "bias", "text": "chased"}],\n'
          '  "data_caveats": [\n    "US quotes are yesterday\n  ]\n}\n')
VALID = '{"behavioral_review": [{"tag": "bias", "text": "chased"}]}'
AMBIGUOUS_TEXT = '[\n "a\n,",\n "\n]'
UNREPAIRABLE_TEXT = 'this was never JSON'


def _sidecar(tmp_path, monkeypatch, body, name='insights-2026-07-28.json'):
    tmp = tmp_path / 'memory' / '.tmp'
    tmp.mkdir(parents=True)
    (tmp / name).write_text(body, encoding='utf-8')
    monkeypatch.setattr(dashboard, 'WS_ROOT', tmp_path)


# ── build_dashboard: the card survives, the defect is announced ──────────────

def test_broken_sidecar_still_yields_its_content(tmp_path, monkeypatch, capsys):
    _sidecar(tmp_path, monkeypatch, BROKEN)

    data = dashboard.load_tmp_sidecar('insights')

    assert data['behavioral_review'] == [{'tag': 'bias', 'text': 'chased'}]
    assert data['data_caveats'] == ['US quotes are yesterday']
    assert data['_source'] == 'insights-2026-07-28.json'
    err = capsys.readouterr().err
    assert 'repair:' in err
    assert 'unterminated_string' in err


def test_a_repair_is_not_reported_as_a_warning(tmp_path, monkeypatch, capsys):
    """`warn:` is what makes the build degraded and the health check red. A
    repaired sidecar rendered every card, so it must not use that prefix — the
    whole point is that a recoverable typo stops costing a red run."""
    _sidecar(tmp_path, monkeypatch, BROKEN)

    dashboard.load_tmp_sidecar('insights')

    assert 'warn:' not in capsys.readouterr().err


def test_valid_sidecar_stays_silent(tmp_path, monkeypatch, capsys):
    _sidecar(tmp_path, monkeypatch, VALID)

    data = dashboard.load_tmp_sidecar('insights')

    assert data['behavioral_review'][0]['text'] == 'chased'
    assert capsys.readouterr().err == ''


# ── The boundary: unreadable is neither repaired nor absent ──────────────────

@pytest.mark.parametrize('body,marker', [
    (UNREPAIRABLE_TEXT, 'unrepairable'),
    (AMBIGUOUS_TEXT, 'ambiguous'),
    ('[1, 2, 3]', 'top level is list'),
])
def test_an_unusable_sidecar_warns_and_is_marked_invalid(tmp_path, monkeypatch,
                                                         capsys, body, marker):
    _sidecar(tmp_path, monkeypatch, body)

    data = dashboard.load_tmp_sidecar('insights')

    err = capsys.readouterr().err
    assert 'warn:' in err
    assert marker in err
    assert data['_invalid'] is True


def test_an_unusable_sidecar_must_not_look_absent(tmp_path, monkeypatch, capsys):
    """`insights_present = bool(load_tmp_sidecar(...))` decides whether
    `_preserve_absent` republishes the previous day's card. Returning `{}` for a
    file that exists but is unreadable would show yesterday's critique as today's
    — this is the assertion that keeps the two cases apart."""
    _sidecar(tmp_path, monkeypatch, UNREPAIRABLE_TEXT)

    present = bool(dashboard.load_tmp_sidecar('insights'))

    assert present is True
    capsys.readouterr()


def test_an_unreadable_file_is_invalid_not_absent(tmp_path, monkeypatch, capsys):
    """The exception path, not the parser path: a sidecar that exists but cannot
    even be decoded used to fall through to `{}` and republish yesterday's card.
    Bad encoding is exactly as untrustworthy as bad syntax."""
    tmp = tmp_path / 'memory' / '.tmp'
    tmp.mkdir(parents=True)
    (tmp / 'insights-2026-07-28.json').write_bytes(b'{"a": "\xff\xfe not utf-8"}')
    monkeypatch.setattr(dashboard, 'WS_ROOT', tmp_path)

    data = dashboard.load_tmp_sidecar('insights')

    assert data['_invalid'] is True
    assert 'warn:' in capsys.readouterr().err


def test_an_unstattable_file_is_invalid_not_absent(tmp_path, monkeypatch, capsys):
    """The failure happens while *selecting* the newest file, before any parse.

    `glob` found a sidecar, so one exists; if `getmtime` then raises we know
    nothing about its content — and must not answer "absent", which republishes
    yesterday's card.
    """
    tmp = tmp_path / 'memory' / '.tmp'
    tmp.mkdir(parents=True)
    (tmp / 'insights-2026-07-28.json').write_text(VALID, encoding='utf-8')
    monkeypatch.setattr(dashboard, 'WS_ROOT', tmp_path)
    monkeypatch.setattr(dashboard.os.path, 'getmtime',
                        lambda p: (_ for _ in ()).throw(OSError('stat failed')))

    data = dashboard.load_tmp_sidecar('insights')

    assert data['_invalid'] is True
    assert 'warn:' in capsys.readouterr().err


def test_an_unlistable_directory_is_invalid_not_absent(tmp_path, monkeypatch, capsys):
    """Cannot even enumerate: we do not know whether a sidecar exists, so
    claiming absence — and republishing the old card — is not available."""
    monkeypatch.setattr(dashboard, 'WS_ROOT', tmp_path)
    monkeypatch.setattr(dashboard.glob, 'glob',
                        lambda p: (_ for _ in ()).throw(OSError('listing failed')))

    data = dashboard.load_tmp_sidecar('insights')

    assert data['_invalid'] is True
    assert 'warn:' in capsys.readouterr().err


def test_a_genuinely_absent_sidecar_is_still_falsy(tmp_path, monkeypatch):
    """The GHA case: memory/.tmp is gitignored, so a fresh checkout has no file
    at all. That one may republish the previous card."""
    (tmp_path / 'memory' / '.tmp').mkdir(parents=True)
    monkeypatch.setattr(dashboard, 'WS_ROOT', tmp_path)

    assert dashboard.load_tmp_sidecar('insights') == {}


# ── _harness_common: repairs counted apart from degradations ────────────────

def test_repairs_and_warnings_are_counted_separately(tmp_path):
    output = (
        '  repair: insights-2026-07-28.json — repaired JSON (unterminated_string)\n'
        '  warn: something genuinely degraded\n'
        '  repair: intraday-insights-2026-07-28.json — repaired JSON (trailing_comma)\n'
    )

    _harness_common._record_dashboard_build(True, True, output, ws=tmp_path)

    status = json.loads((tmp_path / _harness_common.DASHBOARD_BUILD_STATUS).read_text())
    assert status['repair_count'] == 2
    assert status['warn_count'] == 1


def test_a_clean_build_records_zero_repairs(tmp_path):
    _harness_common._record_dashboard_build(
        True, True, '  wrote dashboard.json\n', ws=tmp_path
    )

    status = json.loads((tmp_path / _harness_common.DASHBOARD_BUILD_STATUS).read_text())
    assert status['repair_count'] == 0
    assert status['warn_count'] == 0


def test_rebuild_fails_closed_when_the_publication_push_fails(
    tmp_path, monkeypatch
):
    """Regression for the 2026-08-08 freeze: build green + push red is red."""
    monkeypatch.setattr(_harness_common, 'refresh_today_snapshot', lambda ws: (True, 'ok'))
    monkeypatch.setattr(_harness_common, 'sync_gha_data_files', lambda ws: (True, 'ok'))
    results = iter([
        SimpleNamespace(returncode=0, stdout='', stderr=''),
        SimpleNamespace(returncode=0, stdout='wrote dashboard.json\n', stderr=''),
        SimpleNamespace(
            returncode=1,
            stdout='money integrity gate rejected data-plane push\n',
            stderr='error: failed to push some refs\n',
        ),
    ])
    monkeypatch.setattr(_harness_common.subprocess, 'run', lambda *a, **k: next(results))
    # rebuild_dashboard takes a workspace, but the workflow ledger it calls
    # resolves its own paths from CLAWOCK_WORKSPACE (falling back to cwd), so
    # without this the ledger wrote assets/data/workflow-outcomes.json into the
    # real checkout — an untracked file that then persisted and armed a dormant
    # assertion in test_dashboard_payload_size (#816).
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(tmp_path))

    ok, detail = _harness_common.rebuild_dashboard(tmp_path)
    status = json.loads(
        (tmp_path / _harness_common.DASHBOARD_BUILD_STATUS).read_text()
    )

    assert ok is False
    assert status['ok'] is False
    assert status['build_ok'] is True
    assert status['publish_ok'] is False
    assert 'money integrity gate rejected' in status['tail']
    assert 'data-plane publish failed' in detail


# ── cron_health_check: reported, never escalated ────────────────────────────

def _status_file(tmp_path, monkeypatch, **fields):
    logs = tmp_path / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    payload = {'checked_at': '2999-01-01T00:00:00Z', 'ok': True,
               'warn_count': 0, 'repair_count': 0, 'tail': ''}
    payload.update(fields)
    (logs / 'dashboard_build_status.json').write_text(json.dumps(payload))
    monkeypatch.setattr(cron_health_check, 'WS', tmp_path)


def test_repairs_get_their_own_state_not_a_degradation(tmp_path, monkeypatch):
    _status_file(tmp_path, monkeypatch, repair_count=2)

    result = cron_health_check.check_dashboard_build()

    assert result['state'] == 'repaired'
    assert result['warn_count'] == 0          # would ride exit 2
    assert result['repair_count'] == 2
    assert '2 sidecar' in result['detail']


def test_a_real_degradation_still_outranks_a_repair(tmp_path, monkeypatch):
    _status_file(tmp_path, monkeypatch, warn_count=1, repair_count=3)

    result = cron_health_check.check_dashboard_build()

    assert result['state'] == 'degraded'
    assert result['repair_count'] == 3        # carried, not dropped


@pytest.mark.parametrize('fields,state', [
    ({}, 'ok'),
    ({'repair_count': 1}, 'repaired'),
    ({'warn_count': 2}, 'degraded'),
    ({'ok': False}, 'failed'),
])
def test_every_state_carries_the_repair_count_key(tmp_path, monkeypatch, fields, state):
    _status_file(tmp_path, monkeypatch, **fields)

    result = cron_health_check.check_dashboard_build()

    assert result['state'] == state
    assert 'repair_count' in result


@pytest.mark.parametrize('fields', [{}, {'repair_count': 1}, {'warn_count': 2},
                                     {'ok': False}, {'absent': True}])
def test_every_reachable_state_has_an_icon(tmp_path, monkeypatch, fields):
    """`cron_health_check` indexes `DASHBOARD_STATE_ICONS` directly, so a state
    without an entry is a KeyError that takes down the whole daily check. The
    real map is indexed here — restating it in the test would pass even after
    the mapping was deleted."""
    if fields.pop('absent', None):
        monkeypatch.setattr(cron_health_check, 'WS', tmp_path)
    else:
        _status_file(tmp_path, monkeypatch, **fields)

    state = cron_health_check.check_dashboard_build()['state']

    assert cron_health_check.DASHBOARD_STATE_ICONS[state]
