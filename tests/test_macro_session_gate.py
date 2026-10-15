"""A macro snapshot is today's when its index closes are the latest completed
session, not when it is under 36 hours old (#2988).

The 2026-10-15 08:03 HKT brief printed 10-13's VIX/HSI/HSTECH/SPX/Nasdaq as
the day's 大盘速读: the file it read was 23.4 hours old, inside the wall-clock
cutoff, and one full session behind in both markets.
"""
import json
from datetime import date, datetime, timedelta, timezone

from clawock.harness import brief_preflight, brief_render
from clawock.plugin_host import live
from clawock.strategies.plugins import morning_scans
from clawock.strategies.plugins.morning_scans import Scans

#: 2026-10-15 08:03 HKT, when the brief read the snapshot.
BRIEF_AT = datetime(2026, 10, 15, 0, 3, tzinfo=timezone.utc)


def _snapshot(generated_at, hk_session, us_epoch_vix, us_epoch_spx, us_session):
    """The shape `clawock macro` writes: Tencent rows carry a date, Yahoo an epoch."""
    return {
        'generated_at': generated_at.isoformat(),
        'vix': {'price': 15.27, 'change_pct': 2.9, 'source': 'yahoo', 'as_of': us_epoch_vix},
        'dxy': {'price': 102.17, 'change_pct': -0.01, 'source': 'yahoo', 'as_of': us_epoch_spx},
        'treasury_10y': {'yield_pct': 5.217, 'as_of': us_epoch_spx},
        'fear_greed': {'score': 44.7, 'rating': 'fear'},
        'hsi': {'price': 24345.22, 'change_pct': 0.3, 'source': 'tencent', 'as_of': hk_session},
        'hstech': {'price': 4136.63, 'change_pct': -0.79, 'source': 'tencent', 'as_of': hk_session},
        'spx': {'price': 7805.45, 'change_pct': -0.08, 'source': 'yahoo', 'as_of': us_epoch_spx},
        'nasdaq': {'price': 27204.38, 'change_pct': -0.15, 'source': 'tencent', 'as_of': us_session},
    }


# What the brief read: written 2026-10-14T00:39:51Z, the 10-13 session in both markets.
YESTERDAY = _snapshot(datetime(2026, 10, 14, 0, 39, 51, tzinfo=timezone.utc),
                      '2026-10-13', 1791922501, 1791923582, '2026-10-13')
# What the 07:20 HKT host-dispatched scan had committed: the 10-14 session.
TODAY = _snapshot(datetime(2026, 10, 14, 23, 20, 22, tzinfo=timezone.utc),
                  '2026-10-14', 1792008901, 1792010168, '2026-10-14')


def _workspace(tmp_path, payload):
    data = tmp_path / 'assets' / 'data'
    data.mkdir(parents=True, exist_ok=True)
    (data / 'macro.json').write_text(json.dumps(payload))
    return tmp_path


def test_a_snapshot_one_session_behind_is_stale_inside_the_wall_clock_cutoff(tmp_path):
    gate = Scans(36)
    answer = gate.macro(_workspace(tmp_path, YESTERDAY), at=BRIEF_AT)
    assert round(answer['age_hours'], 1) == 23.4 and not gate.is_stale(answer['age_hours'])
    assert answer['status'] == 'stale' and answer['reading'] == {}
    assert answer['detail']['sessions_behind'] == {
        'hk': {'session': '2026-10-13', 'expected': '2026-10-14'},
        'us': {'session': '2026-10-13', 'expected': '2026-10-14'},
    }


def test_the_latest_completed_session_is_served_with_each_index_row_naming_it(tmp_path):
    answer = Scans(36).macro(_workspace(tmp_path, TODAY), at=BRIEF_AT)
    assert answer['status'] == 'ok'
    reading = answer['reading']
    for key in ('vix', 'hsi', 'hstech', 'spx', 'nasdaq'):
        assert reading[key]['session'] == '2026-10-14', key
    # DXY trades around the clock; its stamp names no session.
    assert 'session' not in reading['dxy']


def test_a_fresh_stamp_on_old_closes_is_stale(tmp_path):
    rewritten = dict(YESTERDAY, generated_at=(BRIEF_AT - timedelta(minutes=5)).isoformat())
    answer = Scans(36).macro(_workspace(tmp_path, rewritten), at=BRIEF_AT)
    assert answer['status'] == 'stale' and set(answer['detail']['sessions_behind']) == {'hk', 'us'}


def test_monday_morning_reads_fridays_closes_as_current(tmp_path):
    monday_brief = datetime(2026, 10, 19, 0, 3, tzinfo=timezone.utc)
    friday = _snapshot(datetime(2026, 10, 18, 23, 20, tzinfo=timezone.utc), '2026-10-16',
                       int(datetime(2026, 10, 16, 20, 15, tzinfo=timezone.utc).timestamp()),
                       int(datetime(2026, 10, 16, 20, 30, tzinfo=timezone.utc).timestamp()),
                       '2026-10-16')
    assert Scans(36).macro(_workspace(tmp_path, friday), at=monday_brief)['status'] == 'ok'


def test_undated_index_rows_leave_the_wall_clock_to_judge(tmp_path):
    undated = {'generated_at': (BRIEF_AT - timedelta(hours=1)).isoformat(), 'vix': {'price': 20}}
    assert Scans(36).macro(_workspace(tmp_path, undated), at=BRIEF_AT)['status'] == 'ok'


def _hours_ago(hours):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def test_the_brief_omits_a_snapshot_behind_the_calendar_without_an_issue(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(morning_scans, 'latest_completed_session',
                        lambda market, at=None: date(2026, 10, 14))
    _workspace(tmp_path, dict(YESTERDAY, generated_at=_hours_ago(1)))
    monkeypatch.setattr(brief_preflight, 'WS', tmp_path)
    issues = []
    macro, _ = brief_preflight.load_macro_and_sentiment(None, issues)
    assert macro == {} and not [issue for issue in issues if 'macro' in issue]
    out = capsys.readouterr().out
    assert 'macro behind the latest completed session (hk 2026-10-13 < 2026-10-14, ' \
           'us 2026-10-13 < 2026-10-14' in out
    assert live.service('scans').macro(tmp_path)['status'] == 'stale'


def test_an_omitted_snapshot_prints_no_readings_line():
    assert brief_render.macro_section({'macro': {}}, {}) == ''
    said = brief_render.macro_section({}, {'narrative': {'macro_read': '⚠️ 宏观快照过期，本段不印读数'}})
    assert said == '### 大盘速读\n\n⚠️ 宏观快照过期，本段不印读数'
    assert 'as_of' not in said and 'VIX' not in said
