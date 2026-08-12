"""Behavioral tests for the pure daily-brief portfolio risk guardrail.

The production module is loaded only when this test module executes a fixture.
That keeps a missing optional/local dependency from breaking collection of the
rest of the suite, and none of these tests call its file, subprocess, or network
functions.  ``BRIEF_PREFLIGHT_UNDER_TEST`` is intentionally supported so the
same assertions can mutation-test a scratch copy without editing product code.
"""

import importlib
import importlib.util
import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_MODULE = (
    ROOT / "instances" / "kcnyu" / "src" / "clawock_kcnyu" / "harness" /
    "brief_preflight.py"
)


@pytest.fixture(scope="module")
def preflight():
    """Lazily load only the module containing the pure functions under test."""
    module_path = Path(os.environ.get("BRIEF_PREFLIGHT_UNDER_TEST", PRODUCTION_MODULE))
    data_path = str(ROOT / "scripts" / "data")
    sys.path.insert(0, data_path)
    try:
        if module_path.resolve() == PRODUCTION_MODULE.resolve():
            return importlib.import_module("clawock_kcnyu.harness.brief_preflight")
        spec = importlib.util.spec_from_file_location(
            "clawock_kcnyu.harness._brief_preflight_guardrail_under_test",
            module_path,
        )
        if spec is None or spec.loader is None:
            pytest.skip(f"cannot load brief_preflight from {module_path}")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except ImportError as exc:
            pytest.skip(f"brief_preflight local dependency unavailable: {exc}")
        return module
    finally:
        sys.path.remove(data_path)


def _holding(ticker, value, *, leveraged=False, pnl_pct=0.0, shares=1):
    cost_value = value / (1 + pnl_pct / 100)
    return {
        "ticker": ticker,
        "name": ticker,
        "shares": shares,
        "cost_basis": cost_value / shares if shares else 0,
        "current_value": value,
        "is_leveraged_etf": leveraged,
    }


def _evaluate(preflight, *, hk=(), us=(), hk_conc=None, us_conc=None,
              risk=None, lev_regime=None):
    hk = list(hk)
    us = list(us)
    if hk_conc is None:
        hk_conc = preflight.compute_concentration(hk)
    if us_conc is None:
        us_conc = preflight.compute_concentration(us)
    return preflight.compute_risk_guardrail(
        hk, us, hk_conc, us_conc, risk or {}, lev_regime
    )


def _only_breach(result, expected_type):
    assert result["hard_stop_watch"] == []
    assert result["breach_count"] == 1
    assert len(result["breaches"]) == 1
    breach = result["breaches"][0]
    assert breach["type"] == expected_type
    assert breach["action"].strip()
    return breach


def test_guardrail_cap_definitions_are_locked(preflight):
    assert preflight.GUARDRAIL_CAPS == {
        "single_name_review_pct": 35,
        "single_name_mandatory_pct": 60,
        "leveraged_single_name_pct": 35,
        "correlated_cluster_pct": 70,
        "correlation_min_coverage_pct": 80,
        "lev_etf_leg_pct": 50,
        "us_beta_max": 3.0,
        "lev_etf_stop_pct": -18,
    }


def test_technical_setup_usage_counts_only_broker_followed_tranches(preflight, monkeypatch):
    rows = []
    for status in ("followed", "unknown", "not_followed"):
        rows.append({
            "ticker": "00100", "action": "add_only_on_trigger",
            "driven_by": "technical", "technical_setup_id": "trend_pullback",
            "technical_campaign_id": "trend_pullback:2026-08-12",
            "execution": {"status": status},
        })
    monkeypatch.setattr(preflight.decision_v2, "load_decisions", lambda: rows)

    assert preflight._technical_setup_usage() == {
        "00100": {"trend_pullback:2026-08-12": 1}
    }


def test_nonleveraged_single_name_45_percent_is_review_not_forced_trim(preflight):
    result = _evaluate(preflight, hk=[
        _holding("BIG", 45),
        _holding("MID", 30),
        _holding("SMALL", 25),
    ])

    assert result["breaches"] == []
    assert result["breach_count"] == 0
    assert result["concentration_reviews"][0]["ticker"] == "BIG"


def test_nonleveraged_single_name_above_60_percent_is_mandatory_trim(preflight):
    result = _evaluate(preflight, hk=[
        _holding("BIG", 61), _holding("MID", 20), _holding("SMALL", 19),
    ])

    breach = _only_breach(result, "single_name")
    assert "trim BIG" in breach["action"]
    assert "≤60%" in breach["action"]
    assert breach["required_reduction"] == {
        "kind": "market_value",
        # (61 - 2.5) / (100 - 2.5) == 60%; a simple 1-unit subtraction
        # would leave 60/99 > 60% and fail its own instruction.
        "minimum_value": 2.5,
        "currency": "HKD",
        "target_pct": 60,
        "target_tickers": ["BIG"],
    }


def test_single_name_exactly_35_percent_is_compliant(preflight):
    result = _evaluate(preflight, hk=[
        _holding("A", 35),
        _holding("B", 35),
        _holding("C", 30),
    ])

    assert result["breaches"] == []
    assert result["breach_count"] == 0


def test_measured_multi_name_cluster_above_70_percent_is_factor_breach(preflight):
    holdings = [_holding("A", 40), _holding("B", 31), _holding("C", 29)]
    risk = {"correlation": {
        "covered_weight_pct": 100, "cluster_rho": 0.8,
        "clusters": [{"tickers": ["A", "B"], "weight_pct": 71}],
    }, "meta": {"fx_hkd_to_usd_used": 0.125}}
    result = _evaluate(preflight, us=holdings, risk=risk)

    breach = _only_breach(result, "factor_concentration")
    assert breach["leg"] == "BOOK"
    assert breach["ticker"] is None
    assert breach["severity"] == "high"
    assert "A, B" in breach["action"]
    assert "≤70%" in breach["action"]


def test_single_name_cluster_never_becomes_factor_breach(preflight):
    risk = {"correlation": {
        "covered_weight_pct": 100, "cluster_rho": 0.8,
        "clusters": [{"tickers": ["A"], "weight_pct": 80}],
    }}
    result = _evaluate(preflight, us=[
        _holding("A", 60), _holding("B", 25), _holding("C", 15),
    ], risk=risk)

    assert result["breaches"] == []
    assert result["breach_count"] == 0


def test_correlation_cluster_is_advisory_when_coverage_is_thin(preflight):
    risk = {"correlation": {
        "covered_weight_pct": 79.9, "cluster_rho": 0.8,
        "clusters": [{"tickers": ["A", "B"], "weight_pct": 80}],
    }}
    result = _evaluate(preflight, us=[
        _holding("A", 45), _holding("B", 35), _holding("C", 20),
    ], risk=risk)

    assert not any(
        breach["type"] == "factor_concentration"
        for breach in result["breaches"]
    )


def test_leveraged_sleeve_above_50_percent_emits_one_high_us_swap(preflight):
    result = _evaluate(preflight, us=[
        _holding("PLTU", 26, leveraged=True),
        _holding("MSFU", 25, leveraged=True),
        _holding("PLTR", 25),
        _holding("MSFT", 24),
    ])

    breach = _only_breach(result, "leveraged_exposure")
    assert breach["leg"] == "US"
    assert breach["ticker"] is None
    assert breach["severity"] == "high"
    assert "1.0 USD" in breach["action"]
    assert "PLTU→PLTR" in breach["action"]
    assert "MSFU→MSFT" in breach["action"]


def test_leveraged_sleeve_exactly_50_percent_is_compliant_because_operator_is_strict_gt(preflight):
    result = _evaluate(preflight, us=[
        _holding("PLTU", 25, leveraged=True),
        _holding("MSFU", 25, leveraged=True),
        _holding("PLTR", 25),
        _holding("MSFT", 25),
    ])

    assert result["breaches"] == []
    assert result["hard_stop_watch"] == []
    assert result["breach_count"] == 0


def test_us_beta_above_3_emits_one_high_beta_breach(preflight):
    result = _evaluate(preflight, risk={"us": {"beta_spx": 3.01}})

    breach = _only_breach(result, "beta")
    assert breach["leg"] == "US"
    assert breach["ticker"] is None
    assert breach["severity"] == "high"
    assert "降 US β" in breach["action"]


def test_us_beta_exactly_3_is_compliant_because_operator_is_strict_gt(preflight):
    result = _evaluate(preflight, risk={"us": {"beta_spx": 3.0}})

    assert result["breaches"] == []
    assert result["breach_count"] == 0


def test_us_beta_action_is_withheld_when_risk_window_is_ineligible(preflight):
    result = _evaluate(
        preflight,
        risk={"us": {
            "beta_spx": 4.2,
            "n_returns": 9,
            "threshold_eligible": False,
        }},
    )

    assert result["breaches"] == []
    assert result["breach_count"] == 0


def test_us_beta_action_is_withheld_when_benchmark_overlap_is_ineligible(preflight):
    result = _evaluate(
        preflight,
        risk={"us": {
            "beta_spx": 4.2,
            "n_returns": 30,
            "threshold_eligible": True,
            "benchmark_n_returns": 7,
            "beta_threshold_eligible": False,
        }},
    )

    assert result["breaches"] == []
    assert result["breach_count"] == 0


def test_leveraged_etf_loss_exactly_minus_18_triggers_inclusive_stop(preflight):
    result = _evaluate(preflight, us=[
        _holding("PLTU", 25, leveraged=True, pnl_pct=-18),
        _holding("A", 25),
        _holding("B", 25),
        _holding("C", 25),
    ])

    assert result["breaches"] == []
    assert result["breach_count"] == 1
    assert len(result["hard_stop_watch"]) == 1
    stop = result["hard_stop_watch"][0]
    assert stop["ticker"] == "PLTU"
    assert stop["leg"] == "US"
    assert stop["pnl_pct"] == -18.0
    assert "≤ 硬止损线 -18%" in stop["detail"]
    assert "1x 同因子 PLTR" in stop["action"]


def test_leveraged_etf_loss_above_minus_18_is_compliant(preflight):
    result = _evaluate(preflight, us=[
        _holding("PLTU", 25, leveraged=True, pnl_pct=-17.9),
        _holding("A", 25),
        _holding("B", 25),
        _holding("C", 25),
    ])

    assert result["hard_stop_watch"] == []
    assert result["breach_count"] == 0


@pytest.mark.xfail(
    strict=False,
    reason=(
        "OPEN tolerance question for kcn (not a confirmed bug): _holding_pnl_pct "
        "rounds to 1dp before the <= -18 stop compare, so -17.96% triggers. This "
        "may be intended tolerance ('stop when the loss rounds to -18%'). An exact "
        "compare was tried and reverted — it makes the boundary float-fragile (a "
        "constructed exactly-18% loss becomes -17.9999.. and STOPS triggering). "
        "Whether to keep 1dp tolerance or pick a robust exact threshold is a call "
        "for a human; left unchanged."
    ),
)
def test_leverage_stop_compares_unrounded_loss_to_minus_18(preflight):
    result = _evaluate(preflight, us=[
        _holding("PLTU", 25, leveraged=True, pnl_pct=-17.96),
        _holding("A", 25),
        _holding("B", 25),
        _holding("C", 25),
    ])

    assert result["hard_stop_watch"] == []


def test_regime_cut_for_a_held_us_leveraged_etf_emits_forced_delever(preflight):
    result = _evaluate(
        preflight,
        us=[
            _holding("PLTU", 25, leveraged=True),
            _holding("A", 25),
            _holding("B", 25),
            _holding("C", 25),
        ],
        lev_regime={"us": {"names": [{
            "state": "cut",
            "etf": "PLTU",
            "underlying": "PLTR",
            "dist_ma_pct": -12.5,
            "vol_annualized": 0.81,
            "vol_hot_cap": 0.70,
        }]}},
    )

    breach = _only_breach(result, "regime_delever")
    assert breach["leg"] == "US"
    assert breach["ticker"] == "PLTU"
    assert breach["severity"] == "high"
    assert "PLTU 2x→PLTR" in breach["action"]
    assert "driven_by=risk_rule" in breach["action"]


def test_new_listing_cut_reports_unavailable_volatility_and_short_ma_basis(preflight):
    result = _evaluate(
        preflight,
        us=[
            _holding("PLTU", 25, leveraged=True),
            _holding("A", 25),
            _holding("B", 25),
            _holding("C", 25),
        ],
        lev_regime={"us": {"names": [{
            "state": "cut",
            "etf": "PLTU",
            "underlying": "PLTR",
            "dist_ma_pct": -3.5,
            "ma_window": 5,
            "vol_annualized": None,
            "regime_basis": "short_ma_5",
        }]}},
    )

    breach = _only_breach(result, "regime_delever")
    assert "完整波动率不可用" in breach["detail"]
    assert "short_ma_5" in breach["detail"]
    assert "波动 0%" not in breach["detail"]
    assert "波动>70%" not in breach["action"]


@pytest.mark.parametrize("state", ["watch", "ok"])
def test_regime_non_cut_state_is_compliant(preflight, state):
    result = _evaluate(
        preflight,
        us=[
            _holding("PLTU", 25, leveraged=True),
            _holding("A", 25),
            _holding("B", 25),
            _holding("C", 25),
        ],
        lev_regime={"us": {"names": [{
            "state": state,
            "etf": "PLTU",
            "underlying": "PLTR",
        }]}},
    )

    assert result["breaches"] == []
    assert result["breach_count"] == 0


def test_every_triggered_directive_is_tagged_as_risk_rule(preflight):
    result = _evaluate(
        preflight,
        risk={"us": {"beta_spx": 3.01}},
        us=[
            _holding("PLTU", 25, leveraged=True),
            _holding("A", 25),
            _holding("B", 25),
            _holding("C", 25),
        ],
        lev_regime={"us": {"names": [{
            "state": "cut",
            "etf": "PLTU",
            "underlying": "PLTR",
            "dist_ma_pct": -5,
            "vol_annualized": 0.8,
            "vol_hot_cap": 0.7,
        }]}},
    )

    assert result["breach_count"] == 2
    assert "driven_by=risk_rule" in result["directive"]
    regime = next(b for b in result["breaches"] if b["type"] == "regime_delever")
    assert "driven_by=risk_rule" in regime["action"]
    assert "driven_by=technical" not in result["directive"]
    assert "driven_by=technical" not in regime["action"]


@pytest.mark.parametrize(
    ("leveraged", "underlying"),
    [
        ("07226", "03033"),
        ("PLTU", "PLTR"),
        ("ROBN", "HOOD"),
        ("MSFU", "MSFT"),
        ("TQQQ", "QQQ"),
        ("SOXL", "SOXX"),
        ("RKLX", "RKLB"),
        ("SPCH", "SPCX"),
    ],
)
def test_documented_leveraged_etf_maps_to_its_1x_underlying(
    preflight, leveraged, underlying
):
    holding = _holding(leveraged, 10, leveraged=True)

    assert preflight.LEV_1X_SWAP[leveraged] == underlying
    assert preflight._swap_suggestions([holding]) == f"{leveraged}→{underlying}"


def test_unmapped_leveraged_etf_uses_sane_fallback_without_crashing(preflight):
    holdings = [
        _holding("UNKNOWN2X", 25, leveraged=True, pnl_pct=-18),
        _holding("A", 25),
        _holding("B", 25),
        _holding("C", 25),
    ]

    assert preflight._swap_suggestions(holdings) == ""
    result = _evaluate(preflight, us=holdings)
    assert result["breach_count"] == 1
    assert "同因子 1x/标的现货" in result["hard_stop_watch"][0]["action"]


def test_no_breach_path_emits_the_normal_decision_directive(preflight):
    result = _evaluate(preflight, hk=[
        _holding("A", 25),
        _holding("B", 25),
        _holding("C", 25),
        _holding("D", 25),
    ])

    assert result["breaches"] == []
    assert result["hard_stop_watch"] == []
    assert result["breach_count"] == 0
    assert result["directive"] == "✅ 无仓位/杠杆硬闸触发，按常规决策。"


@pytest.mark.parametrize(
    ("hk", "us"),
    [
        ([], []),
        ([_holding("HK-CASH", 0, shares=0)], [_holding("US-CASH", 0, shares=0)]),
    ],
    ids=["empty", "all-cash"],
)
def test_empty_or_all_cash_portfolio_has_no_breaches_and_no_crash(
    preflight, hk, us
):
    result = _evaluate(preflight, hk=hk, us=us)

    assert result["breaches"] == []
    assert result["hard_stop_watch"] == []
    assert result["breach_count"] == 0
    assert result["eff_lev_caps"] == {}
    assert result["directive"] == "✅ 无仓位/杠杆硬闸触发，按常规决策。"


# ── freshness must come from generated_at, not tracked-file mtime (2026-07 audit) ──

def test_payload_age_uses_generated_at_not_file_mtime(preflight):
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    age = preflight._payload_age_hours(
        {'generated_at': (now - timedelta(hours=50)).isoformat()})
    assert 49 < age < 51


def test_payload_age_is_none_for_missing_or_bad_stamp(preflight):
    # None => callers treat as STALE; an unprovable age is not a fresh one.
    assert preflight._payload_age_hours({}) is None
    assert preflight._payload_age_hours({'generated_at': 'not-a-date'}) is None
    assert preflight._payload_age_hours({'generated_at': ''}) is None


def test_payload_age_accepts_zulu_and_naive_timestamps(preflight):
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    zulu = preflight._payload_age_hours(
        {'generated_at': (now - timedelta(hours=3)).isoformat().replace('+00:00', 'Z')})
    assert 2.5 < zulu < 3.5
    # a naive stamp is assumed UTC, not crashed
    naive = preflight._payload_age_hours(
        {'generated_at': (now - timedelta(hours=3)).replace(tzinfo=None).isoformat()})
    assert 2.5 < naive < 3.5


def test_stale_committed_sidecar_is_omitted_not_fed_and_never_hard_fails(
        preflight, tmp_path, monkeypatch):
    """The integration bug: a sidecar committed days ago but freshly checked out
    (current mtime) must be judged by generated_at, not the file clock. Stale /
    no-generated_at data is OMITTED (not fed as fresh) and, critically, appends
    NOTHING to `issues` — main() returns exit 1 on any issue and the fallback
    workflow runs under pipefail, so a fatal stale-issue would hard-fail the whole
    brief (2026-07 review, blocking #1)."""
    import json
    from datetime import datetime, timezone, timedelta
    data = tmp_path / 'assets' / 'data'
    data.mkdir(parents=True)
    old = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
    # macro: old generated_at, file written now (fresh mtime) → must read as stale
    (data / 'macro.json').write_text(json.dumps({'generated_at': old, 'vix': {'price': 20}}))
    # sentiment: NO generated_at at all → unknown age → stale
    (data / 'sentiment.json').write_text(
        json.dumps({'tickers': [{'ticker': 'X', 'reddit_mentions_7d': 5}], 'sources': ['reddit']}))
    monkeypatch.setattr(preflight, 'WS', tmp_path)

    issues = []
    macro_trim, sentiment_trim = preflight.load_macro_and_sentiment('2026-07-24', issues)

    assert macro_trim == {} and sentiment_trim == {}      # omitted, not fed as fresh
    assert issues == []                                   # non-fatal → brief still runs


def test_fresh_sidecar_is_fed_with_real_age(preflight, tmp_path, monkeypatch):
    import json
    from datetime import datetime, timezone, timedelta
    data = tmp_path / 'assets' / 'data'
    data.mkdir(parents=True)
    fresh = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    (data / 'macro.json').write_text(json.dumps({'generated_at': fresh, 'vix': {'price': 20}}))
    (data / 'sentiment.json').write_text(json.dumps({'generated_at': fresh, 'tickers': [], 'sources': []}))
    monkeypatch.setattr(preflight, 'WS', tmp_path)

    macro_trim, sentiment_trim = preflight.load_macro_and_sentiment('2026-07-24', [])
    assert macro_trim.get('vix') == {'price': 20, 'change_pct': None, 'source': None}
    assert 1.5 < macro_trim['age_hours'] < 2.5


def test_future_timestamp_beyond_skew_is_stale(preflight):
    from datetime import datetime, timezone, timedelta
    future = (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat()
    age = preflight._payload_age_hours({'generated_at': future})
    assert age < 0 and preflight._is_stale(age, 36)  # negative age must not read as fresh
