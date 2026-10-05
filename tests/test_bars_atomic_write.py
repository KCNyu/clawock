"""A failed daily-bar update must retain the last complete settlement input."""
import errno
import io
import json

import pytest

from clawock.market_data import bars


def test_interrupted_bar_write_retains_previous_store(tmp_path, monkeypatch):
    monkeypatch.setattr(bars, "BARS_DIR", tmp_path)
    old = {"ticker": "TEST", "bars": {"2026-09-10": {"close": 10}}}
    bars.write_bars("TEST", old)
    before = bars.bars_path("TEST").read_bytes()
    real_open = io.open

    class InterruptedWriter:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def write(self, text):
            self.handle.write(text[:len(text) // 2])
            self.handle.flush()
            raise OSError(errno.ENOSPC, "injected disk full after partial write")

    def interrupted_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        return InterruptedWriter(handle) if "w" in mode else handle

    # io.open is shared by Path.write_text and os.fdopen: inject the same real
    # partial-write failure regardless of whether the writer stages its bytes.
    monkeypatch.setattr(io, "open", interrupted_open)
    with pytest.raises(OSError, match="injected disk full"):
        bars.write_bars("TEST", {"ticker": "TEST", "bars": {
            **old["bars"], "2026-09-11": {"close": 11}}})
    assert bars.bars_path("TEST").read_bytes() == before
    assert bars.load_bars("TEST") == old
    assert list(tmp_path.iterdir()) == [bars.bars_path("TEST")]


def test_successful_bar_write_preserves_sorted_storage_format(tmp_path, monkeypatch):
    monkeypatch.setattr(bars, "BARS_DIR", tmp_path)
    doc = {"ticker": "TEST", "bars": {
        "2026-09-11": {"close": 11}, "2026-09-10": {"close": 10}}}
    bars.write_bars("TEST", doc)
    assert list(bars.load_bars("TEST")["bars"]) == ["2026-09-10", "2026-09-11"]
    assert bars.bars_path("TEST").read_text() == json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def test_merge_flags_a_jump_against_the_prior_stored_close(tmp_path, monkeypatch):
    # #2274: the >50% detector needs the prior close; merge() never passed it.
    monkeypatch.setattr(bars, "BARS_DIR", tmp_path)
    monkeypatch.setattr(bars, "CONFLICT_LOG", tmp_path / "bar-conflicts.jsonl")
    monkeypatch.setitem(bars.MANIFEST, "TEST", {"tencent": "usTEST", "leg": "us"})
    monkeypatch.setattr(bars, "_last_closed_session", lambda leg: "2026-09-11")
    monkeypatch.setattr(bars, "_sync_manifest_flags", lambda ticker: None, raising=False)

    def bar(day, close):
        return {"date": day, "open": close, "high": close * 1.01,
                "low": close * 0.99, "close": close}

    added, _, conflicts = bars.merge(
        "TEST", [bar("2026-09-09", 10.0), bar("2026-09-10", 10.5), bar("2026-09-11", 16.6)], False)
    stored = bars.load_bars("TEST")["bars"]

    assert added == 3 and conflicts == []
    assert "implausible_move" not in stored["2026-09-10"]
    assert stored["2026-09-11"]["implausible_move"].startswith("58.")
    logged = [json.loads(line) for line in
              (tmp_path / "bar-conflicts.jsonl").read_text().splitlines()]
    assert [(r["ticker"], r["date"], r["kind"]) for r in logged] == [
        ("TEST", "2026-09-11", "implausible_move")]


def test_grade_stored_is_idempotent_and_never_rewrites_prices(tmp_path, monkeypatch):
    monkeypatch.setattr(bars, 'BARS_DIR', tmp_path)
    monkeypatch.setattr(bars, 'CONFLICT_LOG', tmp_path / 'conflicts.jsonl')
    doc = {'ticker': 'TEST', 'bars': {
        '2026-09-10': {'open': 10, 'high': 11, 'low': 9, 'close': 10},
        '2026-09-11': {'open': 16, 'high': 18, 'low': 15, 'close': 17}}}
    bars.write_bars('TEST', doc)
    assert bars.grade_stored('TEST') == 1
    assert bars.grade_stored('TEST') == 0
    stored = bars.load_bars('TEST')['bars']
    for day, old in doc['bars'].items():
        assert {key: stored[day][key] for key in old} == old
    assert stored['2026-09-11']['implausible_move'] == '70.0%'
    assert len((tmp_path / 'conflicts.jsonl').read_text().splitlines()) == 1


def test_ledger_grades_legacy_unflagged_bars_without_mutating_the_store(tmp_path, monkeypatch):
    from clawock.decision import ledger
    monkeypatch.setattr(ledger, 'BARS_DIR', tmp_path)
    monkeypatch.setattr(ledger, '_BAR_CACHE', {})
    path = tmp_path / 'PLTU.json'
    path.write_text(json.dumps({'bars': {
        '2026-08-03': {'open': 28, 'high': 29, 'low': 27, 'close': 28.39},
        '2026-08-04': {'open': 36.98, 'high': 45, 'low': 36, 'close': 44.82}}}))
    before = path.read_bytes()
    assert ledger.bar('PLTU', '2026-08-04')['implausible_move'] == '57.9%'
    assert path.read_bytes() == before


def test_ledger_grades_a_leveraged_fund_with_its_underlying_from_the_same_store(tmp_path, monkeypatch):
    """With PLTR's two closes beside it, PLTU's +57.9% is its multiple, not a suspect bar (#2595)."""
    from clawock.decision import ledger
    monkeypatch.setattr(ledger, 'BARS_DIR', tmp_path)
    monkeypatch.setattr(ledger, '_BAR_CACHE', {})
    (tmp_path / 'PLTU.json').write_text(json.dumps({'bars': {
        '2026-08-03': {'open': 28, 'high': 29, 'low': 27, 'close': 28.39},
        '2026-08-04': {'open': 36.98, 'high': 45, 'low': 36, 'close': 44.82,
                       'implausible_move': '57.9%'}}}))
    (tmp_path / 'PLTR.json').write_text(json.dumps({'bars': {
        '2026-08-03': {'open': 125, 'high': 127, 'low': 124, 'close': 125.65},
        '2026-08-04': {'open': 150, 'high': 165, 'low': 149, 'close': 162.66}}}))
    assert 'implausible_move' not in ledger.bar('PLTU', '2026-08-04')
    assert 'implausible_move' not in ledger.bar('PLTR', '2026-08-04')
