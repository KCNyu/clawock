import json
import sys
from datetime import date as real_date
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "data"))

from clawock.decision import signal_review as review  # noqa: E402


class _HistoryStub:
    """In-memory stand-in that keeps aggregation tests free of file I/O."""

    def __init__(self, days):
        self._text = "\n".join(json.dumps(day) for day in days)

    def exists(self):
        return True

    def read_text(self):
        return self._text


class _FixedDate:
    @classmethod
    def today(cls):
        return real_date(2026, 7, 17)


def _run_review(monkeypatch, days):
    captured = {}

    def capture_write(_path, data, indent=2):
        captured["data"] = data
        captured["indent"] = indent

    monkeypatch.setattr(review, "HIST", _HistoryStub(days))
    monkeypatch.setattr(review, "safe_write_json", capture_write)
    monkeypatch.setattr(review, "date", _FixedDate)
    review.main()
    return captured["data"]


def _factor_days(factor_name, outcomes):
    predicate, direction, horizon = review.FACTOR_TESTS[factor_name]
    del predicate
    trigger_fields = {
        "trend_on_follow": {"trend_on": True},
        "trend_off_avoid": {"trend_on": False},
        "rsi_oversold_bounce": {"rsi14": 30},
        "rsi_overbought_fade": {"rsi14": 70},
        "zscore_extreme_revert": {"zscore20": -2},
        "stop_breach_continue": {"stop_distance_pct": -0.01},
    }[factor_name]
    days = [{"as_of": f"day-{i:03d}", "rows": {}} for i in range(horizon + 1)]
    for index, won in enumerate(outcomes):
        symbol = f"S{index:03d}"
        days[0]["rows"][symbol] = {"close": 100.0, **trigger_fields}
        move = direction if won else -direction
        days[horizon]["rows"][symbol] = {"close": 100.0 + 10.0 * move}
    return days


def _clustered_factor_days(factor_name, outcomes_by_date):
    """Build separated signal/mark windows with repeat tickers across dates."""
    _predicate, direction, horizon = review.FACTOR_TESTS[factor_name]
    trigger_fields = {
        "trend_on_follow": {"trend_on": True},
        "trend_off_avoid": {"trend_on": False},
        "rsi_oversold_bounce": {"rsi14": 30},
        "rsi_overbought_fade": {"rsi14": 70},
        "zscore_extreme_revert": {"zscore20": -2},
        "stop_breach_continue": {"stop_distance_pct": -0.01},
    }[factor_name]
    step = horizon + 1
    total_days = (len(outcomes_by_date) - 1) * step + horizon + 1
    days = [{"as_of": f"day-{i:03d}", "rows": {}} for i in range(total_days)]
    for date_index, outcomes in enumerate(outcomes_by_date):
        base = date_index * step
        for ticker_index, won in enumerate(outcomes):
            symbol = f"S{ticker_index:03d}"
            days[base]["rows"][symbol] = {"close": 100.0, **trigger_fields}
            move = direction if won else -direction
            days[base + horizon]["rows"][symbol] = {
                "close": 100.0 + 10.0 * move}
    return days


def test_hit_rate_uses_hits_as_the_numerator(monkeypatch):
    result = _run_review(
        monkeypatch,
        _factor_days("trend_on_follow", [True, False, True, True]),
    )

    factor = result["factors"]["trend_on_follow"]
    assert factor["n_events"] == 4
    assert factor["n_dates"] == 1
    assert factor["n_tickers"] == 4
    assert factor["hit_rate"] == 0.75
    assert factor["ci95"] is None
    assert factor["usable"] is False


def test_empty_history_has_no_rates_or_unlocked_factors(monkeypatch):
    result = _run_review(monkeypatch, [])

    assert result["days_logged"] == 0
    assert result["unlock_rule"] == "cluster_ci_entirely_above_or_below_50pct"
    assert result["summary"] == "没有因子通过聚类 CI 50% 闸（0 天留痕）——结论未解锁"
    assert all(
        factor
        == {
            "n_events": 0,
            "n_dates": 0,
            "n_tickers": 0,
            "hit_rate": None,
            "ci95": None,
            "ci_method": "date_ticker_two_way_cluster_bootstrap",
            "edge_significant": False,
            "reverse_edge_significant": False,
            "decision_direction": None,
            "usable": False,
            "note": "date/ticker 聚类不足，方向结论不入决策",
        }
        for factor in result["factors"].values()
    )


def test_raw_event_count_never_unlocks_without_date_clusters(monkeypatch):
    result = _run_review(
        monkeypatch,
        _factor_days("trend_on_follow", [True] * 100),
    )

    factor = result["factors"]["trend_on_follow"]
    assert factor["n_events"] == 100
    assert factor["n_dates"] == 1
    assert factor["hit_rate"] == 1.0
    assert factor["usable"] is False
    assert factor["note"] == "date/ticker 聚类不足，方向结论不入决策"
    assert "trend_on_follow" not in result["summary"]


def test_cluster_ci_above_half_unlocks_original_direction(monkeypatch):
    result = _run_review(
        monkeypatch,
        _clustered_factor_days("trend_on_follow", [[True] * 5] * 4),
    )

    factor = result["factors"]["trend_on_follow"]
    assert factor["n_events"] == 20
    assert factor["n_dates"] == 4
    assert factor["n_tickers"] == 5
    assert factor["ci95"] == [1.0, 1.0]
    assert factor["edge_significant"] is True
    assert factor["decision_direction"] == "original"
    assert factor["usable"] is True
    assert "events=20, dates=4, tickers=5" in result["summary"]


def test_low_hit_rate_reverses_only_when_cluster_ci_is_below_half(monkeypatch):
    result = _run_review(
        monkeypatch,
        _clustered_factor_days("trend_on_follow", [[False] * 5] * 4),
    )

    factor = result["factors"]["trend_on_follow"]
    assert factor["ci95"] == [0.0, 0.0]
    assert factor["edge_significant"] is False
    assert factor["reverse_edge_significant"] is True
    assert factor["decision_direction"] == "reverse"
    assert factor["usable"] is True
    assert "反向" in result["summary"]


def test_cluster_ci_crossing_half_stays_out_of_decisions(monkeypatch):
    result = _run_review(
        monkeypatch,
        _clustered_factor_days(
            "trend_on_follow",
            [[True] * 5, [False] * 5, [True] * 5, [False] * 5],
        ),
    )

    factor = result["factors"]["trend_on_follow"]
    assert factor["hit_rate"] == 0.5
    assert factor["ci95"][0] <= 0.5 <= factor["ci95"][1]
    assert factor["usable"] is False
    assert factor["decision_direction"] is None
    assert factor["note"] == "聚类 CI 跨 50%，方向结论不入决策"


@pytest.mark.parametrize(
    ("factor_name", "at_threshold", "outside_threshold", "direction", "horizon"),
    [
        ("trend_on_follow", {"trend_on": True}, {"trend_on": 1}, 1, 1),
        ("trend_off_avoid", {"trend_on": False}, {"trend_on": 0}, -1, 5),
        ("rsi_oversold_bounce", {"rsi14": 30}, {"rsi14": 30.001}, 1, 5),
        ("rsi_overbought_fade", {"rsi14": 70}, {"rsi14": 69.999}, -1, 5),
        ("zscore_extreme_revert", {"zscore20": -2}, {"zscore20": -1.999}, 1, 5),
        (
            "stop_breach_continue",
            {"stop_distance_pct": -0.001},
            {"stop_distance_pct": 0},
            -1,
            5,
        ),
    ],
)
def test_factor_thresholds_directions_and_horizons(
    factor_name, at_threshold, outside_threshold, direction, horizon
):
    predicate, actual_direction, actual_horizon = review.FACTOR_TESTS[factor_name]

    assert predicate(at_threshold) is True
    assert predicate(outside_threshold) is False
    assert actual_direction == direction
    assert actual_horizon == horizon


def test_rsi_zero_is_still_extreme_oversold():
    # Regression: RSI 0 is maximally oversold, not missing data. The predicate
    # now distinguishes None (→neutral 50) from a real 0 reading.
    predicate, _direction, _horizon = review.FACTOR_TESTS["rsi_oversold_bounce"]

    assert predicate({"rsi14": 0}) is True


def test_rsi_missing_defaults_to_neutral_not_oversold():
    predicate, _direction, _horizon = review.FACTOR_TESTS["rsi_oversold_bounce"]
    assert predicate({}) is False
    assert predicate({"rsi14": None}) is False


def test_cluster_ci_requires_both_date_and_ticker_clusters():
    one_date = [
        {"date": "d1", "ticker": "A", "hit": True},
        {"date": "d1", "ticker": "B", "hit": True},
    ]
    one_ticker = [
        {"date": "d1", "ticker": "A", "hit": True},
        {"date": "d2", "ticker": "A", "hit": True},
    ]
    assert review.clustered_ci(one_date) is None
    assert review.clustered_ci(one_ticker) is None
