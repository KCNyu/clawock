"""The durable FX ledger is keyed by the HKT day (#3385)."""
from clawock.portfolio import fx


def test_a_hkt_midnight_fetch_is_not_recorded_under_the_utc_previous_day():
    assert fx._ledger_day({'fetched_at': '2026-11-10T18:00:00Z'}) == '2026-11-11'


def test_a_utc_daytime_fetch_keeps_the_same_day():
    assert fx._ledger_day({'fetched_at': '2026-11-11T00:03:00+00:00'}) == '2026-11-11'
