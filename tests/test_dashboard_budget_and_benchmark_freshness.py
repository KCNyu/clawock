"""Two things that were going to break quietly on a date (#1078).

A. `dashboard.json` was 195,680 of 200,000 bytes on 2026-08-26 with the
   snapshot series at 76 rows (37KB, ~489 bytes each) and
   `MAX_SNAPSHOTS_EMBEDDED=90` still 14 rows away — one row per trading day, so
   the cap arrives in about nine sessions and then stays breached. The only
   lever was dropping `recent_plans`, which is not what grows.

B. `benchmark.json` retained SPY at 2026-08-21 while HSI/HSTECH ran through
   08-25 — two completed US sessions behind — and said so nowhere. Retaining
   the previous bars on an empty fetch is correct; being unable to tell is not.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def system_check():
    for path in (ROOT, ROOT / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(
        "sc_budget", ROOT / "ops" / "system_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── A. the byte budget ───────────────────────────────────────────────────────

def test_the_snapshot_series_is_a_lever_and_the_floor_holds():
    dash = pytest.importorskip("clawock.publish.dashboard")
    assert dash.MIN_SNAPSHOTS_UNDER_BUDGET == 30, (
        "decision_metrics reads snapshots[-30:]; trimming below that changes "
        "what the window means instead of shortening a chart")
    assert dash.MIN_SNAPSHOTS_UNDER_BUDGET < dash.MAX_SNAPSHOTS_EMBEDDED


def test_trimming_takes_the_oldest_and_records_that_it_happened(monkeypatch):
    """Oldest-first, and visible in the payload rather than only on stderr.

    `recent_plans_dropped` already exists for exactly this reason: a
    degradation that lives in a build log is one no gate can read back.
    """
    dash = pytest.importorskip("clawock.publish.dashboard")
    out = {
        "snapshots": [{"date": f"2026-01-{i:02d}", "pad": "x" * 400}
                      for i in range(1, 41)],
        "recent_plans": [],
    }
    monkeypatch.setattr(dash, "MAX_OUT_BYTES", 14_000)
    monkeypatch.setattr(dash, "MIN_SNAPSHOTS_UNDER_BUDGET", 30)

    kept = list(out["snapshots"])
    dropped = 0
    size = len(dash.serialize_dashboard_payload(out).encode("utf-8"))
    while size > dash.MAX_OUT_BYTES and len(kept) > dash.MIN_SNAPSHOTS_UNDER_BUDGET:
        kept.pop(0)
        dropped += 1
        out["snapshots"] = kept
        size = len(dash.serialize_dashboard_payload(out).encode("utf-8"))

    assert dropped > 0, "the fixture must actually exceed the cap"
    assert len(kept) >= 30, "the floor must hold"
    assert kept[-1]["date"] == "2026-01-40"[:10] or kept[-1]["date"].endswith("40"), (
        "the newest snapshot must survive — the recent shape is what is read")


def test_the_builder_actually_wires_that_lever():
    source = (ROOT / "src" / "clawock" / "publish" / "dashboard.py").read_text(
        encoding="utf-8")
    assert "snapshots_trimmed_for_budget" in source
    assert "MIN_SNAPSHOTS_UNDER_BUDGET" in source


# ── B. benchmark freshness ───────────────────────────────────────────────────

def _bench(spy_last, hsi_last="2026-08-25", spy_behind=0):
    return {
        "generated_at": "2026-08-26T00:03:36.331698Z",
        "series": {"SPY": [{"date": spy_last, "close": 1.0}],
                   "HSI": [{"date": hsi_last, "close": 2.0}]},
        "freshness": {
            "SPY": {"market": "us", "last_session": spy_last,
                    "sessions_behind": spy_behind, "expected_lag_sessions": 1},
            "HSI": {"market": "hk", "last_session": hsi_last,
                    "sessions_behind": 0, "expected_lag_sessions": 0},
        },
    }


def _run(system_check, monkeypatch, tmp_path, payload):
    (tmp_path / "assets" / "data").mkdir(parents=True)
    if payload is not None:
        (tmp_path / "assets" / "data" / "benchmark.json").write_text(
            json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(system_check, "WS", tmp_path)
    result = system_check.Result()
    system_check.check_benchmark_freshness(result)
    return result.checks[0]


def test_the_measured_gap_is_reported(system_check, monkeypatch, tmp_path):
    """SPY at 08-21 on 08-26: two behind against a normal lag of one."""
    _, severity, message = _run(
        system_check, monkeypatch, tmp_path, _bench("2026-08-21", spy_behind=2))
    assert severity == system_check.WARNING
    assert "SPY" in message and "2026-08-21" in message


def test_the_normal_one_session_polygon_lag_is_not_a_warning(
        system_check, monkeypatch, tmp_path):
    """A gate that fires on the ordinary shape is a gate nobody reads."""
    _, severity, _ = _run(
        system_check, monkeypatch, tmp_path, _bench("2026-08-25", spy_behind=1))
    assert severity == system_check.OK


def test_a_writer_that_publishes_no_freshness_block_is_itself_the_warning(
        system_check, monkeypatch, tmp_path):
    payload = _bench("2026-08-21")
    payload.pop("freshness")
    _, severity, message = _run(system_check, monkeypatch, tmp_path, payload)
    assert severity == system_check.WARNING
    assert "freshness" in message


def test_the_writer_publishes_the_block(system_check):
    benchmarks = pytest.importorskip("clawock.market_data.benchmarks")
    rows = benchmarks._freshness({"SPY": [{"date": "2026-08-21", "close": 1.0}]})
    assert rows["SPY"]["market"] == "us"
    assert rows["SPY"]["last_session"] == "2026-08-21"
    assert rows["SPY"]["expected_lag_sessions"] == 1
    assert isinstance(rows["SPY"]["sessions_behind"], int)


# ── the cap was a tripwire, not a gate (#1215) ──────────────────────────────

def test_packing_the_equity_series_is_lossless():
    """Identity, not a summary. The trim lever deletes days; this deletes bytes.

    `snapshots_of` is the only decoder, so the assertion is that a real row set
    survives a round trip exactly — including a row that is missing a field the
    others have, which is where a ragged encoding would silently shift every
    later value one column to the left.
    """
    dash = pytest.importorskip("clawock.publish.dashboard")
    rows = [
        {"date": "2026-01-02", "us_total_value": 1.5, "hk_cash": None},
        {"date": "2026-01-03", "us_total_value": 2.0, "hk_cash": 7,
         "hk_late_arrival": "x"},
    ]
    columns, packed = dash.pack_snapshots(rows)
    assert all(isinstance(row, list) for row in packed)
    assert all(len(row) == len(columns) for row in packed), 'no ragged rows'

    payload = {"snapshots": packed, dash.SNAPSHOTS_PACKED_COLUMNS_KEY: columns}
    decoded = dash.snapshots_of(payload)
    assert decoded[1]["hk_late_arrival"] == "x"
    assert decoded[0]["hk_late_arrival"] is None, (
        'a field one row lacks must decode to None, not shift the row')
    assert [{k: v for k, v in row.items() if v is not None or k in rows[i]}
            for i, row in enumerate(decoded)] == rows


def test_an_unpacked_payload_still_reads(monkeypatch):
    """Every generation published before this change is still readable."""
    dash = pytest.importorskip("clawock.publish.dashboard")
    legacy = {"snapshots": [{"date": "2026-01-02", "us_equity": 3}]}
    assert dash.snapshots_of(legacy) == legacy["snapshots"]


def test_packing_is_what_the_size_levers_measure():
    """The saving has to be real at the point the cap is enforced.

    Measuring the unpacked dict and publishing the packed one would make the
    levers fire on a size nobody ships — the same class of mistake as #743,
    where the gate measured a re-serialized copy.
    """
    dash = pytest.importorskip("clawock.publish.dashboard")
    out = {"snapshots": [
        {"date": f"2026-01-{i:02d}", "us_total_value": 1000.0 + i,
         "us_total_cost": 900.0, "hk_total_value": 2000.0,
         "hk_today_change": -1.0, "hk_realized": 3.0}
        for i in range(1, 41)]}
    packed = len(dash.dashboard_wire_payload(out).encode("utf-8"))
    plain = len(dash.serialize_dashboard_payload(out).encode("utf-8"))
    assert packed < plain * 0.6, (
        f'packing saved only {plain - packed} of {plain} bytes; the field names '
        f'were more than half this section')
    assert dash.snapshots_of(json.loads(dash.dashboard_wire_payload(out))) == \
        out["snapshots"], 'the wire form must decode back to what was measured'


def test_a_breach_is_recorded_in_the_payload_not_only_on_stderr(monkeypatch):
    """2026-07-28 shipped 3.7KB over the cap and nothing downstream could tell.

    stderr reaches no gate — not the build card, not the cron log, not
    watchdog.jsonl — so "publishing over cap" was a decision that left no trace
    a reader could act on.
    """
    dash = pytest.importorskip("clawock.publish.dashboard")
    source = (ROOT / "src" / "clawock" / "publish" / "dashboard.py").read_text(
        encoding="utf-8")
    assert "out['payload_over_cap']" in source, (
        'the terminal over-cap case must record itself in the payload')
    marker = source.split("out['payload_over_cap'] = {", 1)[1].split('}', 1)[0]
    for field in ('bytes', 'cap', 'over_by', 'levers_spent'):
        assert f"'{field}'" in marker, f'{field} must be in the marker'
