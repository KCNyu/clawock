"""The rate that combines two currencies has to survive the day it was fetched.

Prices already do — every snapshot carries `current_price` per holding. The
USD/HKD rate did not: its only durable record was the commit history of
`assets/data/dashboard.json`, and #314 moved that file off `master`. A rebuild
of any past day would stamp it with *today's* rate and produce a combined figure
that looks entirely normal (#323).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_HARNESS = ROOT / "instances" / "kcnyu" / "src" / "clawock_kcnyu" / "harness"
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
