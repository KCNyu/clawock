"""The risk card's two time axes: how long a breach has been tripped, and
whether the gate is tightening or easing (#1252).

`brief_preflight._append_guardrail_history` has written one row per brief to
`assets/data/guardrail_history.jsonl` since 2026-07-15, and README leans on it
for the 风控纪律 claim — but nothing read it. Not the dashboard, not the plugin:
a grep for `guardrail_history` across `site/` and `examples/` returned nothing.
So the card could answer "what is tripped right now" and neither "how long" nor
"is this getting better", while the data for both was already published.

These tests pin the two things that are easy to get wrong here:
  * a row is a TRADING day, not a calendar day — the file has no weekend rows,
    so an age must count rows and never subtract dates;
  * an age that runs off the start of the record is a lower bound, and saying
    "33" when the truth is ">= 33" is the card asserting a number it has not got.
"""
import json

import pytest

from clawock.publish import dashboard


def _write(ws, rows):
    data = ws / 'assets' / 'data'
    data.mkdir(parents=True, exist_ok=True)
    (data / dashboard.GUARDRAIL_HISTORY_NAME).write_text(
        ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows),
        encoding='utf-8')
    return ws


def _row(date, breaches=(), stops=()):
    return {
        'date': date,
        'breach_count': len(breaches) + len(stops),
        'breaches': [dict(b) for b in breaches],
        'hard_stop_watch': [dict(s) for s in stops],
    }


LEV_HK = {'type': 'leveraged_exposure', 'leg': 'HK', 'ticker': None}
NAME_US = {'type': 'single_name', 'leg': 'US', 'ticker': 'SPCH'}
STOP_HK = {'ticker': '07226', 'leg': 'HK'}


def test_history_is_read_oldest_first_and_survives_a_torn_line(tmp_path):
    ws = _write(tmp_path, [_row('2026-08-03'), _row('2026-08-01')])
    (ws / 'assets' / 'data' / dashboard.GUARDRAIL_HISTORY_NAME).open('a').write(
        '{"date": "2026-08-04"\n')       # an append killed mid-write
    rows = dashboard.load_guardrail_history(ws)
    assert [r['date'] for r in rows] == ['2026-08-01', '2026-08-03']


def test_a_missing_history_is_not_an_error(tmp_path):
    """A fresh clone has none, and the card still has to render."""
    assert dashboard.load_guardrail_history(tmp_path) == []


def test_age_counts_recorded_rows_not_calendar_days(tmp_path):
    """Fri -> Mon is two rows and must read 2, not 4.

    The file has no weekend rows because there is no brief on a weekend, so any
    implementation that subtracted the two dates would inflate every age by the
    weekends it spans.
    """
    ws = _write(tmp_path, [
        _row('2026-08-28', [LEV_HK]),    # Friday
        _row('2026-08-31', [LEV_HK]),    # Monday
    ])
    guardrail = {'breaches': [dict(LEV_HK, severity='high', detail='x')]}
    dashboard.annotate_guardrail_history(
        guardrail, dashboard.load_guardrail_history(ws))
    assert guardrail['breaches'][0]['age_days'] == 2


def test_a_streak_only_counts_back_to_the_first_gap(tmp_path):
    ws = _write(tmp_path, [
        _row('2026-08-25', [LEV_HK]),
        _row('2026-08-26', []),          # cleared for a day
        _row('2026-08-27', [LEV_HK]),
        _row('2026-08-28', [LEV_HK]),
    ])
    guardrail = {'breaches': [dict(LEV_HK, severity='high', detail='x')]}
    dashboard.annotate_guardrail_history(
        guardrail, dashboard.load_guardrail_history(ws))
    assert guardrail['breaches'][0]['age_days'] == 2, 'the gap must end the streak'
    assert 'age_capped' not in guardrail['breaches'][0]


def test_an_age_that_runs_off_the_record_is_marked_as_a_lower_bound(tmp_path):
    ws = _write(tmp_path, [_row('2026-08-27', [LEV_HK]), _row('2026-08-28', [LEV_HK])])
    guardrail = {'breaches': [dict(LEV_HK, severity='high', detail='x')]}
    dashboard.annotate_guardrail_history(
        guardrail, dashboard.load_guardrail_history(ws))
    breach = guardrail['breaches'][0]
    assert (breach['age_days'], breach['age_capped']) == (2, True), (
        'the streak reaches the oldest row on record, so 2 is a floor and the '
        'card must render it as "2 天+"')


def test_a_breach_that_appeared_after_the_brief_reads_zero_not_missing(tmp_path):
    """0 is a real answer — "new since this morning" — and must survive."""
    ws = _write(tmp_path, [_row('2026-08-28', [LEV_HK])])
    guardrail = {'breaches': [dict(NAME_US, severity='high', detail='x')]}
    dashboard.annotate_guardrail_history(
        guardrail, dashboard.load_guardrail_history(ws))
    assert guardrail['breaches'][0]['age_days'] == 0


def test_identity_separates_two_breaches_of_the_same_type(tmp_path):
    """HK and US leveraged exposure are two gates, not one that moved legs."""
    lev_us = {'type': 'leveraged_exposure', 'leg': 'US', 'ticker': None}
    ws = _write(tmp_path, [
        _row('2026-08-27', [LEV_HK]),
        _row('2026-08-28', [LEV_HK, lev_us]),
    ])
    guardrail = {'breaches': [dict(LEV_HK, severity='high', detail='x'),
                              dict(lev_us, severity='high', detail='y')]}
    dashboard.annotate_guardrail_history(
        guardrail, dashboard.load_guardrail_history(ws))
    assert [b['age_days'] for b in guardrail['breaches']] == [2, 1]


def test_hard_stops_are_aged_against_their_own_list(tmp_path):
    """A stop and a breach can share a ticker; they are not the same gate."""
    ws = _write(tmp_path, [
        _row('2026-08-27', [], [STOP_HK]),
        _row('2026-08-28', [], [STOP_HK]),
    ])
    guardrail = {
        'breaches': [dict(LEV_HK, severity='high', detail='x')],
        'hard_stop_watch': [dict(STOP_HK, severity='critical', detail='y')],
    }
    dashboard.annotate_guardrail_history(
        guardrail, dashboard.load_guardrail_history(ws))
    assert guardrail['breaches'][0]['age_days'] == 0
    assert guardrail['hard_stop_watch'][0]['age_days'] == 2


def test_the_published_series_is_capped_but_the_age_is_not(tmp_path):
    """The chart window and the measurement window are deliberately different.

    Ages read from the whole record; only the tail is worth payload. Capping
    both would make every age read "30 天+" the moment the chart window filled.
    """
    days = dashboard.GUARDRAIL_HISTORY_DAYS
    rows = [_row(f'2026-{7 + (i // 28):02d}-{1 + (i % 28):02d}', [LEV_HK])
            for i in range(days + 12)]
    ws = _write(tmp_path, rows)
    guardrail = {'breaches': [dict(LEV_HK, severity='high', detail='x')]}
    history = dashboard.load_guardrail_history(ws)
    assert len(history) == days + 12, 'the loader must not cap by default'
    dashboard.annotate_guardrail_history(guardrail, history)
    assert len(guardrail['breach_history']) == days
    assert guardrail['breaches'][0]['age_days'] == days + 12


def test_a_failed_compute_is_left_alone(tmp_path):
    """The card distinguishes "no breaches" from "could not compute" (#…);
    decorating the failure case would put a trend on an all-clear it never made."""
    guardrail = {'computed': False, 'error': 'boom'}
    dashboard.annotate_guardrail_history(
        guardrail, dashboard.load_guardrail_history(tmp_path))
    assert 'breach_history' not in guardrail


def test_the_history_is_fingerprinted(tmp_path):
    """It is read by the build, so --skip-if-unchanged must be able to see it.

    `brief_preflight` appends a row and then rebuilds the dashboard in the same
    run, so a fingerprint blind to this file would publish yesterday's trend
    (#1247 is the same class of bug from the other direction).
    """
    assert f'assets/data/{dashboard.GUARDRAIL_HISTORY_NAME}' in \
        dashboard.FINGERPRINT_FILES

    ws = _write(tmp_path, [_row('2026-08-28', [LEV_HK])])
    (ws / 'memory').mkdir(exist_ok=True)
    before = dashboard.dashboard_input_fingerprint(ws)
    _write(ws, [_row('2026-08-28', [LEV_HK]), _row('2026-08-31', [LEV_HK])])
    assert dashboard.dashboard_input_fingerprint(ws) != before


@pytest.mark.parametrize('bad', ['not json', '[]', '{"no": "date"}'])
def test_unusable_lines_are_skipped_rather_than_raising(tmp_path, bad):
    data = tmp_path / 'assets' / 'data'
    data.mkdir(parents=True)
    (data / dashboard.GUARDRAIL_HISTORY_NAME).write_text(
        bad + '\n' + json.dumps(_row('2026-08-28')) + '\n', encoding='utf-8')
    assert [r['date'] for r in dashboard.load_guardrail_history(tmp_path)] \
        == ['2026-08-28']
