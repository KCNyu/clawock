"""Where json_repair is actually plugged in, and how a repair stays visible.

A correct repair function that nothing calls fixes nothing, and a repair nobody
can see is worse than the crash it replaced: the 2026-07-28 sidecar defect was
only ever noticed *because* it turned the daily health check red. These tests
pin the three-stage path that keeps it observable without keeping it fatal:

    build_dashboard  →  `repair:` on stderr   (distinct from `warn:`)
    _harness_common  →  repair_count in dashboard_build_status.json
    cron_health_check→  state 'repaired', its own line, exit code unchanged

and the boundary that must NOT move: an unrepairable file still degrades.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'data'))
sys.path.insert(0, str(ROOT / 'scripts' / 'harness'))

import build_dashboard as dashboard  # noqa: E402
import cron_health_check  # noqa: E402
import _harness_common  # noqa: E402


# The 2026-07-28 shape: a well-formed document whose last string value lost its
# closing quote. Everything before the defect must survive the repair.
BROKEN = ('{\n  "behavioral_review": [{"tag": "bias", "text": "chased"}],\n'
          '  "data_caveats": [\n    "US quotes are yesterday\n  ]\n}\n')
VALID = '{"behavioral_review": [{"tag": "bias", "text": "chased"}]}'


def _sidecar(tmp_path, monkeypatch, body, name='insights-2026-07-28.json'):
    tmp = tmp_path / 'memory' / '.tmp'
    tmp.mkdir(parents=True)
    (tmp / name).write_text(body, encoding='utf-8')
    monkeypatch.setattr(dashboard, 'WS_ROOT', tmp_path)


# ── build_dashboard: the card survives, the defect is announced ───────────────

def test_broken_sidecar_still_yields_its_content(tmp_path, monkeypatch, capsys):
    _sidecar(tmp_path, monkeypatch, BROKEN)

    data = dashboard.load_tmp_sidecar('insights')

    assert data['behavioral_review'] == [{'tag': 'bias', 'text': 'chased'}]
    assert data['_source'] == 'insights-2026-07-28.json'
    err = capsys.readouterr().err
    assert 'repair:' in err
    assert 'unterminated_string' in err


def test_a_repair_is_not_reported_as_a_warning(tmp_path, monkeypatch, capsys):
    """`warn:` is what makes the build degraded and the health check red.

    A repaired sidecar rendered every card, so it must not use that prefix — the
    whole point of the fallback is that a recoverable typo stops costing a red
    run. This is the assertion that fails if someone 'simplifies' the two
    prefixes into one.
    """
    _sidecar(tmp_path, monkeypatch, BROKEN)

    dashboard.load_tmp_sidecar('insights')

    assert 'warn:' not in capsys.readouterr().err


def test_valid_sidecar_stays_silent(tmp_path, monkeypatch, capsys):
    _sidecar(tmp_path, monkeypatch, VALID)

    data = dashboard.load_tmp_sidecar('insights')

    assert data['behavioral_review'][0]['text'] == 'chased'
    assert capsys.readouterr().err == ''


def test_unrepairable_sidecar_still_degrades_the_build(tmp_path, monkeypatch, capsys):
    """The boundary: repair widens what survives, it must not hide a real loss."""
    _sidecar(tmp_path, monkeypatch, 'this was never JSON')

    data = dashboard.load_tmp_sidecar('insights')

    assert data == {}
    assert 'warn:' in capsys.readouterr().err


# ── _harness_common: repairs counted apart from degradations ─────────────────

def test_repairs_and_warnings_are_counted_separately(tmp_path):
    output = (
        '  repair: insights-2026-07-28.json — repaired JSON (unterminated_string)\n'
        '  warn: something genuinely degraded\n'
        '  repair: intraday-insights-2026-07-28.json — repaired JSON (trailing_comma)\n'
    )
    _harness_common._record_dashboard_build(True, output, ws=tmp_path)

    status = json.loads(
        (tmp_path / _harness_common.DASHBOARD_BUILD_STATUS).read_text()
    )
    assert status['repair_count'] == 2
    assert status['warn_count'] == 1


def test_a_clean_build_records_zero_repairs(tmp_path):
    _harness_common._record_dashboard_build(True, '  wrote dashboard.json\n', ws=tmp_path)

    status = json.loads(
        (tmp_path / _harness_common.DASHBOARD_BUILD_STATUS).read_text()
    )
    assert status['repair_count'] == 0
    assert status['warn_count'] == 0


# ── cron_health_check: reported, never escalated ─────────────────────────────

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
    assert '2 sidecar' in result['detail']    # visible, with a count


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
    """One schema across all branches: a caller reading `repair_count` must never
    have to guess which branch produced the dict."""
    _status_file(tmp_path, monkeypatch, **fields)

    result = cron_health_check.check_dashboard_build()

    assert result['state'] == state
    assert 'repair_count' in result


def test_the_repaired_state_has_a_console_icon():
    """`cron_health_check` indexes its icon map directly, so a state without an
    entry is a KeyError that takes down the whole daily check."""
    source = (ROOT / 'scripts' / 'data' / 'cron_health_check.py').read_text()
    icon_line = source[source.index("dash_icon = {"):]
    assert "'repaired'" in icon_line[:200]
