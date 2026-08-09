from datetime import date
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

from clawock import compute_quant_signals as quant  # noqa: E402


def detail(label="LIVE", code="usLIVE.OQ"):
    return {
        "label": label,
        "code": code,
        "note": "",
        "region": "US",
        "source_holdings": [label],
    }


def bars(day, count=40):
    return [
        {
            "date": day,
            "open": float(index + 1),
            "close": float(index + 1),
            "high": float(index + 1),
            "low": float(index + 1),
        }
        for index in range(count)
    ]


def test_successful_row_has_own_as_of_status_and_holding_coverage():
    rows = quant.refresh_rows(
        {},
        [detail()],
        run_date=date(2026, 7, 24),
        expected_sessions={"US": date(2026, 7, 24)},
        fetcher=lambda _code: bars("2026-07-24"),
    )

    assert rows["LIVE"]["status"] == "fresh"
    assert rows["LIVE"]["row_as_of"] == "2026-07-24"
    assert rows["LIVE"]["source_holdings"] == ["LIVE"]
    assert rows["LIVE"]["max_age_days"] == 7


def test_fetch_failure_retains_recent_row_as_explicit_stale():
    previous = {
        "LIVE": {
            "close": 10,
            "tag": "old",
            "row_as_of": "2026-07-22",
            "status": "fresh",
        }
    }
    rows = quant.refresh_rows(
        previous,
        [detail()],
        run_date=date(2026, 7, 24),
        expected_sessions={"US": date(2026, 7, 24)},
        fetcher=lambda _code: [],
    )

    assert rows["LIVE"]["close"] == 10
    assert rows["LIVE"]["status"] == "stale"
    assert rows["LIVE"]["row_as_of"] == "2026-07-22"
    assert "fetch failed" in rows["LIVE"]["stale_reason"]


def test_old_failure_becomes_visible_missing_without_old_factors():
    previous = {
        "LIVE": {
            "close": 10,
            "tag": "old",
            "row_as_of": "2026-07-01",
        }
    }
    rows = quant.refresh_rows(
        previous,
        [detail()],
        run_date=date(2026, 7, 24),
        expected_sessions={"US": date(2026, 7, 24)},
        fetcher=lambda _code: [],
    )

    assert rows["LIVE"]["status"] == "missing"
    assert rows["LIVE"]["last_good_as_of"] == "2026-07-01"
    assert "close" not in rows["LIVE"]
    assert "tag" not in rows["LIVE"]


def test_removed_row_is_retained_then_pruned_after_defined_period():
    previous = {"EXIT": {"close": 10, "row_as_of": "2026-07-01"}}
    retained = quant.refresh_rows(
        previous,
        [],
        run_date=date(2026, 7, 24),
        expected_sessions={},
        fetcher=lambda _code: [],
    )
    assert retained["EXIT"]["status"] == "retired"
    assert retained["EXIT"]["retired_since"] == "2026-07-24"

    pruned = quant.refresh_rows(
        retained,
        [],
        run_date=date(2026, 7, 31),
        expected_sessions={},
        fetcher=lambda _code: [],
    )
    assert "EXIT" not in pruned


def test_current_failure_is_not_hidden_by_unrelated_retired_rows():
    rows = quant.refresh_rows(
        {"OLD": {"close": 9, "row_as_of": "2026-07-20"}},
        [detail("NEW", "usNEW.OQ")],
        run_date=date(2026, 7, 24),
        expected_sessions={"US": date(2026, 7, 24)},
        fetcher=lambda _code: [],
    )

    assert rows["NEW"]["status"] == "missing"
    assert rows["NEW"]["last_good_as_of"] is None
    assert rows["OLD"]["status"] == "retired"


def test_missing_marker_does_not_invent_top_level_as_last_good_date():
    rows = quant.refresh_rows(
        {"LIVE": {"status": "missing", "row_as_of": None, "last_good_as_of": None}},
        [detail()],
        run_date=date(2026, 7, 24),
        previous_as_of="2026-07-23",
        expected_sessions={"US": date(2026, 7, 24)},
        fetcher=lambda _code: [],
    )

    assert rows["LIVE"]["status"] == "missing"
    assert rows["LIVE"]["last_good_as_of"] is None
