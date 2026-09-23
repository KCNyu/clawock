"""The rate that combines two currencies has to survive the day it was fetched.

Prices already do — every snapshot carries `current_price` per holding. The
USD/HKD rate did not: its only durable record was the commit history of
`assets/data/dashboard.json`, and #314 moved that file off `master`. A rebuild
of any past day would stamp it with *today's* rate and produce a combined figure
that looks entirely normal (#323).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_HARNESS = ROOT / 'src' / 'clawock' / 'harness'
from clawock.portfolio import fx as fetch_fx


def _entry(rate, day="2026-08-05", source="Frankfurter"):
    return {"rate": rate, "pair": "USDHKD", "source": source,
            "fetched_at": f"{day}T00:01:13.000000+00:00", "fallback_used": False}


def test_a_rerun_that_agrees_records_nothing_new(tmp_path):
    """The fetcher runs up to 6x/day on a 4-hour TTL. A re-fetch that agrees
    carries no new information, and a line per run would bury the day's rate in
    repetition."""
    ledger = tmp_path / "fx-rates.jsonl"

    fetch_fx._record_rate(_entry(7.8433), str(ledger))
    fetch_fx._record_rate(_entry(7.8433), str(ledger))

    assert len(ledger.read_text().splitlines()) == 1


def test_a_rate_that_moved_within_the_day_is_kept(tmp_path):
    """The opposite case, and the reason this is not keyed on the day alone: an
    intraday move is a real observation. The reader takes the last."""
    ledger = tmp_path / "fx-rates.jsonl"

    fetch_fx._record_rate(_entry(7.8433), str(ledger))
    fetch_fx._record_rate(_entry(7.8500), str(ledger))

    assert len(ledger.read_text().splitlines()) == 2
    assert fetch_fx.read_rate_ledger(str(ledger))["2026-08-05"]["rate"] == 7.8500


def test_one_bad_line_does_not_cost_every_other_day(tmp_path):
    """Appended to over months. A record that becomes unreadable in its entirety
    because of one truncated write is not a record."""
    ledger = tmp_path / "fx-rates.jsonl"
    fetch_fx._record_rate(_entry(7.8426, day="2026-08-04"), str(ledger))
    with ledger.open("a") as handle:
        handle.write('{"day": "2026-08-05", "rate": 7.84\n')     # truncated
    fetch_fx._record_rate(_entry(7.8440, day="2026-08-06"), str(ledger))

    days = fetch_fx.read_rate_ledger(str(ledger))

    assert set(days) == {"2026-08-04", "2026-08-06"}
    assert days["2026-08-06"]["rate"] == 7.8440


def test_recording_cannot_break_a_price_fetch(tmp_path):
    """This is provenance riding along on the money path. An unwritable ledger
    must degrade to "no record", never to "no rate" — the FX rate is what values
    the HK leg, and refusing to fetch it would be a far worse failure than
    losing a line."""
    unwritable = tmp_path / "not-a-dir" / "fx-rates.jsonl"
    (tmp_path / "not-a-dir").write_text("I am a file", encoding="utf-8")

    fetch_fx._record_rate(_entry(7.8433), str(unwritable))  # must not raise

    assert fetch_fx.read_rate_ledger(str(unwritable)) == {}


def test_the_committed_ledger_is_readable_and_complete_per_entry():
    """The record only counts if it is in the repository and every line means
    something. Deliberately asserts SHAPE, not counts — a test that pinned the
    number of days would go red every morning for the wrong reason
    (`clawock-no-live-numbers-in-static-copy`).

    Entries backfilled out of `dashboard.json`'s commit history carry
    `backfilled_from`, so a reader can tell a reconstructed rate from one
    recorded at fetch time; both are equally usable, but they are not the same
    kind of evidence.
    """
    ledger = ROOT / "memory" / "fx-rates.jsonl"
    assert ledger.is_file(), "the FX provenance record is missing"

    days = fetch_fx.read_rate_ledger(str(ledger))
    assert days, "the ledger parses to nothing"
    for day, entry in days.items():
        assert len(day) == 10 and day[4] == "-", day
        assert isinstance(entry.get("rate"), (int, float)) and entry["rate"] > 0, day
        assert entry.get("pair") == "USDHKD", day
        assert entry.get("source"), day


def _cache(tmp_path, age_hours, **entry):
    import json
    import os
    import time
    path = tmp_path / "fx_rate.json"
    path.write_text(json.dumps({"rate": 7.8434, "source": "Frankfurter",
                                "fetched_at": "2026-09-23T00:03:31+00:00",
                                "pair": "USDHKD", **entry}))
    stamp = time.time() - age_hours * 3600
    os.utime(path, (stamp, stamp))
    return str(path)


def _no_network(monkeypatch):
    def refuse():
        raise AssertionError("an offline reader must not call a provider")
    for name in ("_get_frankfurter", "_get_exchangerate_host", "_get_yahoo"):
        monkeypatch.setattr(fetch_fx, name, refuse)


def test_the_afternoon_after_the_morning_refresh_is_not_degraded(tmp_path, monkeypatch):
    """The cache is refreshed once each trading morning and Frankfurter/ECB
    publish daily, so being past the fetcher's 4h TTL is the normal afternoon
    state. Calling it degraded would put a warning on the panel every day, and
    a warning that is always there is read as none (#1781)."""
    _no_network(monkeypatch)

    fx = fetch_fx.read_cached_usdhkd(_cache(tmp_path, fetch_fx.CACHE_TTL_HOURS + 6))

    assert fx["rate"] == 7.8434
    assert fx["stale"] is False and fx["warning"] is None
    assert fx["fallback_used"] is False


def test_a_cache_the_daily_refresh_stopped_updating_is_served_but_flagged(
        tmp_path, monkeypatch):
    """The HKD peg keeps an old rate a small error, so the rate is still used —
    but the payload says it is old, instead of looking exactly like a fresh one."""
    _no_network(monkeypatch)

    fx = fetch_fx.read_cached_usdhkd(_cache(tmp_path, fetch_fx.STALE_READ_HOURS + 1))

    assert fx["rate"] == 7.8434
    assert fx["stale"] is True
    assert fx["age_hours"] > fetch_fx.STALE_READ_HOURS
    assert "stale" in fx["warning"]
    assert fx["source"] == "Frankfurter", "provenance is not rewritten"


def test_a_secondary_provider_stays_marked_as_a_fallback(tmp_path, monkeypatch):
    _no_network(monkeypatch)

    fx = fetch_fx.read_cached_usdhkd(
        _cache(tmp_path, 1, source="exchangerate.host", fallback_used=True))

    assert fx["fallback_used"] is True and fx["stale"] is False


def test_a_missing_or_torn_cache_is_null_with_a_warning_not_a_guess(
        tmp_path, monkeypatch):
    """No peg-midpoint here: an offline reader that invented a rate could not be
    told apart from one that read it."""
    _no_network(monkeypatch)
    torn = tmp_path / "torn.json"
    torn.write_text('{"rate": 7.84')

    for path in (tmp_path / "absent.json", torn):
        fx = fetch_fx.read_cached_usdhkd(str(path))
        assert fx["rate"] is None
        assert fx["warning"]
