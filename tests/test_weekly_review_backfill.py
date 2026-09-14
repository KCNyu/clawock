"""Backfilling a weekly review whose scheduled Sunday run produced nothing."""
from datetime import date

import pytest

from clawock.automation import weekly_review as weekly
from clawock.publish import artifacts


def test_scheduled_run_has_no_backfill_note():
    assert weekly.backfill_note(None, '2026-W38', today=date(2026, 9, 20)) == ''
    assert weekly.backfill_note(date(2026, 9, 20), '2026-W38', today=date(2026, 9, 20)) == ''


def test_backfill_tells_the_reader_the_risk_numbers_are_from_the_run_day():
    note = weekly.backfill_note(date(2026, 9, 13), '2026-W37', today=date(2026, 9, 15))
    assert note.startswith('> 补跑于 2026-09-15')
    assert '2026-W37' in note and '2026-09-13' in note and 'risk.json' in note
    assert note.endswith('\n\n')


def test_as_of_reaches_aggregate_week(monkeypatch):
    seen = []

    class Stop(Exception):
        pass

    def fake_aggregate(as_of):
        seen.append(as_of)
        raise Stop

    monkeypatch.setattr(weekly, 'aggregate_week', fake_aggregate)
    with pytest.raises(Stop):
        weekly.main(['--as-of', '2026-09-13'])
    with pytest.raises(Stop):
        weekly.main([])
    assert seen == [date(2026, 9, 13), None]


def test_sidecar_check_reads_the_backfilled_week():
    assert artifacts.weekly_review_week_id({'WEEKLY_REVIEW_WEEK': '2026-W37'}) == '2026-W37'
    assert artifacts.weekly_review_week_id({}, today=date(2026, 9, 15)) == '2026-W38'
    with pytest.raises(AssertionError):
        artifacts.weekly_review_week_id({'WEEKLY_REVIEW_WEEK': '37'})
