import json
import sys
from datetime import date as real_date
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "data"))

import quant_signal_review as review  # noqa: E402


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


def test_hit_rate_uses_hits_as_the_numerator(monkeypatch):
    result = _run_review(
        monkeypatch,
        _factor_days("trend_on_follow", [True, False, True, True]),
    )

    factor = result["factors"]["trend_on_follow"]
    assert factor["n"] == 4
    assert factor["hit_rate"] == 0.75
    assert factor["ci95"] == [0.301, 0.954]


def test_empty_history_has_no_rates_or_unlocked_factors(monkeypatch):
    result = _run_review(monkeypatch, [])

    assert result["days_logged"] == 0
    assert result["min_n"] == 20
    assert result["summary"] == "全部因子样本 <20，累积中（0 天留痕）——结论未解锁"
    assert all(
        factor
        == {
            "n": 0,
            "hit_rate": None,
            "ci95": None,
            "edge_significant": False,
            "usable": False,
            "note": "样本不足，brief 不得引用方向结论",
        }
        for factor in result["factors"].values()
    )


def test_nineteen_samples_are_withheld_from_the_unlocked_summary(monkeypatch):
    result = _run_review(
        monkeypatch,
        _factor_days("trend_on_follow", [True] * 19),
    )

    factor = result["factors"]["trend_on_follow"]
    assert factor["n"] == 19
    assert factor["hit_rate"] == 1.0
    assert factor["usable"] is False
    assert factor["note"] == "样本不足，brief 不得引用方向结论"
    assert "trend_on_follow" not in result["summary"]
    assert result["summary"].endswith("——结论未解锁")


def test_twenty_all_wins_unlock_at_the_exact_sample_threshold(monkeypatch):
    result = _run_review(
        monkeypatch,
        _factor_days("trend_on_follow", [True] * 20),
    )

    factor = result["factors"]["trend_on_follow"]
    assert factor == {
        "n": 20,
        "hit_rate": 1.0,
        "ci95": [0.839, 1.0],
        "edge_significant": True,
        "usable": True,
        "note": "",
    }
    assert result["summary"] == "trend_on_follow 100%[84–100](n=20)"


def test_twenty_all_losses_unlock_as_a_zero_hit_rate(monkeypatch):
    result = _run_review(
        monkeypatch,
        _factor_days("trend_on_follow", [False] * 20),
    )

    factor = result["factors"]["trend_on_follow"]
    assert factor == {
        "n": 20,
        "hit_rate": 0.0,
        "ci95": [0.0, 0.161],
        "edge_significant": False,
        "usable": True,
        "note": "",
    }
    assert result["summary"] == "trend_on_follow 0%[0–16](n=20)"


def test_summary_preserves_declared_factor_order(monkeypatch):
    days = [{"as_of": f"day-{i:03d}", "rows": {}} for i in range(6)]
    for index in range(20):
        trend_symbol = f"T{index:03d}"
        rsi_symbol = f"R{index:03d}"
        days[0]["rows"][trend_symbol] = {"close": 100.0, "trend_on": True}
        days[1]["rows"][trend_symbol] = {"close": 110.0}
        days[0]["rows"][rsi_symbol] = {"close": 100.0, "rsi14": 30}
        days[5]["rows"][rsi_symbol] = {"close": 110.0}

    result = _run_review(monkeypatch, days)

    assert result["summary"] == (
        "trend_on_follow 100%[84–100](n=20)、"
        "rsi_oversold_bounce 100%[84–100](n=20)"
    )


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


@pytest.mark.parametrize(
    ("hits", "n", "expected"),
    [
        (15, 20, [0.531, 0.888]),
        (14, 20, [0.481, 0.855]),
        (20, 20, [0.839, 1.0]),
        (0, 20, [0.0, 0.161]),
    ],
)
def test_wilson_ci_matches_known_95_percent_intervals(hits, n, expected):
    assert review.wilson_ci(hits, n) == expected


def test_wilson_ci_returns_none_for_zero_observations():
    assert review.wilson_ci(0, 0) is None


def test_edge_significance_requires_the_wilson_lower_bound_above_half(monkeypatch):
    significant = _run_review(
        monkeypatch,
        _factor_days("trend_on_follow", [True] * 15 + [False] * 5),
    )
    indistinguishable = _run_review(
        monkeypatch,
        _factor_days("trend_on_follow", [True] * 14 + [False] * 6),
    )

    significant_factor = significant["factors"]["trend_on_follow"]
    indistinguishable_factor = indistinguishable["factors"]["trend_on_follow"]
    assert significant_factor["hit_rate"] == 0.75
    assert significant_factor["ci95"] == [0.531, 0.888]
    assert significant_factor["edge_significant"] is True
    assert indistinguishable_factor["hit_rate"] == 0.7
    assert indistinguishable_factor["ci95"] == [0.481, 0.855]
    assert indistinguishable_factor["edge_significant"] is False
