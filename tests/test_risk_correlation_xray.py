"""Concentration has to measure bets, not tickers.

`brief_preflight.compute_concentration` grades the book on dollar weights alone
and then uses `top2_factor_pct` as a stand-in for "these are one factor". The
comment above `GUARDRAIL_CAPS` records that the 2026-06 drawdown was a
construction problem — "HK 85% one factor" — which is exactly the quantity the
proxy was standing in for and nothing was measuring.

Run: python3 -m pytest tests/test_risk_correlation_xray.py -q
"""
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

ROOT = Path(__file__).resolve().parents[1]
from clawock import portfolio_risk_metrics as risk

START = datetime(2026, 4, 1, tzinfo=timezone.utc)


def _series(returns, start_price=100.0, offset_days=0):
    """Build a (ts, close) series whose close-to-close returns are `returns`."""
    out, price = [], start_price
    for index, ret in enumerate([0.0, *returns]):
        price *= (1 + ret)
        day = START + timedelta(days=index + offset_days)
        out.append((int(day.timestamp()), price))
    return out


def _holding(ticker, value):
    return {"ticker": ticker, "current_value": float(value)}


def _walk(seed, n=40, scale=0.02):
    rng = np.random.default_rng(seed)
    return list(rng.normal(0, scale, n))


def _xray(us=(), hk=(), series=None, fx=0.128):
    series = series or {}
    return risk.correlation_xray(
        {"us": list(us), "hk": list(hk)},
        {"us": {t: s for t, s in series.items() if t in {h["ticker"] for h in us}},
         "hk": {t: s for t, s in series.items() if t in {h["ticker"] for h in hk}}},
        fx,
    )


# ── the headline claim ──────────────────────────────────────────────────────

def test_duplicate_exposure_reports_far_fewer_bets_than_names():
    """A 2x ETF held alongside its 1x underlying is two tickers and one bet.
    Weight-only concentration cannot see the difference."""
    base = _walk(1)
    out = _xray(
        us=[_holding("PLTR", 1000), _holding("PLTU", 1000)],
        series={"PLTR": _series(base), "PLTU": _series([2 * r for r in base])},
    )

    assert out["effective_names"] == pytest.approx(2.0, abs=0.01)
    assert out["effective_bets"] == pytest.approx(1.0, abs=0.05), (
        "perfectly co-moving holdings must collapse to ~1 effective bet")


def test_an_uncorrelated_book_keeps_its_bets():
    out = _xray(
        us=[_holding("AAA", 1000), _holding("BBB", 1000), _holding("CCC", 1000)],
        series={"AAA": _series(_walk(11)), "BBB": _series(_walk(22)),
                "CCC": _series(_walk(33))},
    )

    assert out["effective_names"] == pytest.approx(3.0, abs=0.01)
    assert out["effective_bets"] > 2.0, out["effective_bets"]


def test_the_diversification_ratio_is_near_one_when_everything_moves_together():
    base = _walk(4)
    out = _xray(
        us=[_holding("AAA", 1000), _holding("BBB", 1000)],
        series={"AAA": _series(base), "BBB": _series(base)},
    )

    assert out["diversification_ratio"] == pytest.approx(1.0, abs=0.01)


# ── clusters, and what the Top2 proxy misses ────────────────────────────────

def test_clusters_group_names_that_move_together():
    base = _walk(5)
    out = _xray(
        hk=[_holding("07226", 4000), _holding("03033", 3000),
            _holding("02208", 3000)],
        series={"07226": _series([2 * r for r in base]),
                "03033": _series(base), "02208": _series(_walk(6))},
    )

    biggest = out["clusters"][0]
    assert set(biggest["tickers"]) == {"07226", "03033"}
    assert biggest["weight_pct"] == pytest.approx(70.0, abs=0.01)


def test_the_cluster_alert_fires_where_a_top2_weight_check_would_not():
    """Three correlated names at 30/30/25 make a 85% single-factor cluster while
    any two of them are only 60% — under the 70% Top2 cap that stands in for
    factor exposure today."""
    base = _walk(7)
    holdings = [_holding("A", 3000), _holding("B", 3000), _holding("C", 2500),
                _holding("D", 1500)]
    series = {name: _series([base[i] * (1 + 0.01 * k) for i in range(len(base))])
              for k, name in enumerate(("A", "B", "C"))}
    series["D"] = _series(_walk(8))

    out = _xray(hk=holdings, series=series)
    alerts = risk._correlation_alerts(out)

    biggest = out["clusters"][0]
    assert set(biggest["tickers"]) == {"A", "B", "C"}
    top2 = sorted((h["current_value"] for h in holdings), reverse=True)[:2]
    assert sum(top2) / sum(h["current_value"] for h in holdings) * 100 < 70, (
        "fixture no longer demonstrates the gap: Top2 alone would have fired")
    assert biggest["weight_pct"] > 70
    assert [a["type"] for a in alerts if a["type"] == "correlated_cluster"]


def test_a_single_name_cluster_never_raises_a_cluster_alert():
    """One heavy name is a concentration finding the existing caps already own;
    duplicating it here would just add noise."""
    out = {"clusters": [{"tickers": ["AAA"], "weight_pct": 95.0}],
           "effective_names": 1.0, "effective_bets": 1.0}

    assert not [a for a in risk._correlation_alerts(out)
                if a["type"] == "correlated_cluster"]


# ── currency, coverage and the honest failure paths ─────────────────────────

def test_both_legs_are_converted_to_usd_before_weighting():
    """HKD and USD are never added. At 0.125, HK$8000 is US$1000 — equal weight
    with the US leg, so effective_names must be 2.0, not lopsided."""
    out = _xray(
        us=[_holding("AAA", 1000)], hk=[_holding("00100", 8000)],
        series={"AAA": _series(_walk(9)), "00100": _series(_walk(10))},
        fx=0.125,
    )

    assert out["effective_names"] == pytest.approx(2.0, abs=0.01)


def test_a_new_listing_is_excluded_instead_of_truncating_everyone_else():
    """The real book has a 16-session holding. Requiring every name to share
    every session capped the sample at 15 and produced nothing at all."""
    out = _xray(
        us=[_holding("OLD1", 1000), _holding("OLD2", 1000), _holding("NEW", 100)],
        series={"OLD1": _series(_walk(12)), "OLD2": _series(_walk(13)),
                "NEW": _series(_walk(14, n=5))},
    )

    assert out["excluded_short_history"] == ["NEW"]
    assert "reason" not in out, "the x-ray computed, so it must not report a refusal"
    assert out["effective_bets"] is not None
    assert out["n_common_sessions"] >= risk.MIN_CORR_SESSIONS
    # And the reader can see how much of the book the answer covers.
    assert out["covered_weight_pct"] == pytest.approx(95.24, abs=0.05)


def test_a_book_of_only_new_listings_says_so_instead_of_guessing():
    out = _xray(
        us=[_holding("AAA", 1000), _holding("BBB", 1000)],
        series={"AAA": _series(_walk(15, n=8)), "BBB": _series(_walk(16, n=8))},
    )

    assert out["effective_bets"] is None
    assert out["excluded_short_history"] == ["AAA", "BBB"]
    assert "enough history" in out["reason"]
    assert [a["type"] for a in risk._correlation_alerts(out)] == [
        "insufficient_observations"]


def test_too_few_shared_sessions_states_the_reason_and_publishes_no_number():
    """Each name has plenty of its own history; they barely overlap. Correlation
    needs contemporaneous returns, so this is a real refusal, not a shortcut."""
    out = _xray(
        us=[_holding("AAA", 1000), _holding("BBB", 1000)],
        series={"AAA": _series(_walk(15, n=30)),
                "BBB": _series(_walk(16, n=30), offset_days=25)},
    )

    assert out["effective_bets"] is None
    assert "required" in out["reason"]
    # Unavailable must still be *visible*, not silently absent.
    assert [a["type"] for a in risk._correlation_alerts(out)] == [
        "insufficient_observations"]


def test_a_zero_variance_holding_is_named_rather_than_becoming_nan():
    out = _xray(
        us=[_holding("AAA", 1000), _holding("FLAT", 1000)],
        series={"AAA": _series(_walk(17)), "FLAT": _series([0.0] * 40)},
    )

    assert out["effective_bets"] is None
    assert "FLAT" in out["reason"]


def test_a_holding_with_no_price_history_is_listed_not_dropped_in_silence():
    out = _xray(
        us=[_holding("AAA", 1000), _holding("BBB", 1000), _holding("GONE", 500)],
        series={"AAA": _series(_walk(18)), "BBB": _series(_walk(19))},
    )

    assert out["excluded_no_history"] == ["GONE"]
    assert out["effective_bets"] is not None


def test_every_published_number_survives_a_strict_json_writer():
    out = _xray(
        us=[_holding("AAA", 1000), _holding("BBB", 1000)],
        series={"AAA": _series(_walk(20)), "BBB": _series(_walk(21))},
    )

    json.dumps(out, allow_nan=False)
    for key in ("effective_names", "effective_bets", "diversification_ratio",
                "var_95", "expected_shortfall_95"):
        assert out[key] is None or math.isfinite(out[key]), key


def test_expected_shortfall_is_at_least_as_bad_as_var():
    out = _xray(
        us=[_holding("AAA", 1000), _holding("BBB", 1000)],
        series={"AAA": _series(_walk(23)), "BBB": _series(_walk(24))},
    )

    assert out["expected_shortfall_95"] <= out["var_95"]
