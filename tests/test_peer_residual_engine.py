import json
from datetime import date, timedelta
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
from clawock.market_data import peer_residuals as peer


def _bars(rate, count=80, volume=1000):
    start = date(2026, 1, 1)
    return [
        {
            "date": (start + timedelta(days=index)).isoformat(),
            "close": 100 * ((1 + rate) ** index),
            "volume": volume,
        }
        for index in range(count)
    ]


def test_capped_liquidity_weights_are_normalized_and_respect_cap():
    weights = peer.capped_weights({"A": 100, "B": 10, "C": 1}, cap=0.4)

    assert sum(weights.values()) == pytest.approx(1.0)
    assert max(weights.values()) <= 0.4
    assert weights == pytest.approx({"A": 0.4, "B": 0.4, "C": 0.2})


def test_taxonomy_folds_leveraged_products_and_never_auto_discovers_hk():
    factor_config = {
        "symbols": [
            {"ticker": "ONE", "region": "us", "sector": "sector"},
            {"ticker": "P1", "region": "us", "sector": "sector"},
        ],
        "leveraged_proxies": [
            {"ticker": "TWO", "region": "us", "underlying": "ONE", "leverage": 2}
        ],
    }
    peer_map = {
        "holdings": {
            "TWO": {
                "listed_peers": [
                    {"ticker": "ONE", "region": "us", "name": "One"},
                    {"ticker": "P1", "region": "us", "name": "Peer"},
                ]
            },
            "00100": {
                "listed_peers": [
                    {"ticker": "00020", "region": "hk", "name": "Peer HK"}
                ]
            },
        }
    }

    taxonomy, fetch_config = peer.build_taxonomy(factor_config, peer_map)

    assert taxonomy["TWO"]["signal_ticker"] == "ONE"
    assert [row["ticker"] for row in taxonomy["TWO"]["peers"]] == ["P1"]
    assert taxonomy["00100"]["automatic_discovery"] is False
    assert {row["ticker"] for row in fetch_config["symbols"]} >= {
        "ONE", "P1", "00100", "00020"
    }


def test_metrics_publish_equal_and_liquidity_residuals_and_leadership():
    taxonomy = {
        "target": "T",
        "signal_ticker": "T",
        "peer_source": "curated_listed_peers",
        "automatic_discovery": False,
        "peers": [
            {"ticker": "P1", "region": "us"},
            {"ticker": "P2", "region": "us"},
            {"ticker": "P3", "region": "us"},
        ],
    }
    fetched = {
        "T": {"bars": _bars(0.02, volume=1000)},
        "P1": {"bars": _bars(0.01, volume=3000)},
        "P2": {"bars": _bars(0.005, volume=2000)},
        "P3": {"bars": _bars(0.001, volume=1000)},
    }
    as_of = fetched["T"]["bars"][-1]["date"]

    result = peer.metrics_at(taxonomy, fetched, as_of, weight_cap=0.4)

    assert result["residual_equal_5d"] > 0
    assert result["residual_liquidity_5d"] > 0
    assert result["peer_breadth_20d"] == 1.0
    assert result["leadership_persistence"] == 3
    assert result["sector_regime"] == "broad_up"
    assert result["available_peer_count"] == 3


def test_rule_triggers_are_separate_and_require_curated_peer_depth():
    base = {
        "available_peer_count": 3,
        "residual_blend_1d": 0.01,
        "residual_blend_5d": 0.02,
        "residual_blend_20d": 0.04,
        "peer_dispersion_1d": 0.01,
        "peer_liquidity_return_20d": 0.03,
        "peer_breadth_20d": 0.7,
        "peer_breadth_1d": 0.7,
        "leadership_persistence": 3,
        "laggard_persistence": 0,
    }

    assert peer.triggered_rules(base) == ["leader_continuation"]

    laggard = {
        **base,
        "residual_blend_5d": -0.02,
        "residual_blend_20d": -0.04,
        "leadership_persistence": 0,
        "laggard_persistence": 2,
    }
    assert peer.triggered_rules(laggard) == ["laggard_avoidance"]

    shock = {
        **base,
        "residual_blend_1d": -0.02,
        "residual_blend_5d": 0.0,
        "residual_blend_20d": 0.0,
        "leadership_persistence": 0,
    }
    assert peer.triggered_rules(shock) == ["mean_reversion"]
    assert peer.triggered_rules({**base, "available_peer_count": 2}) == []


def test_activation_needs_prospective_clustered_support_for_each_rule():
    config = peer.load_rule_config()
    empty = {
        rule: {
            "n_events": 0,
            "n_dates": 0,
            "n_tickers": 0,
            "signed_residual_ci95": None,
            "hit_rate_ci95": None,
        }
        for rule in config["rules"]
    }

    activation = peer.activate_rules(config, empty)

    assert all(not state["active"] for state in activation.values())
    assert all("dates" in state["blockers"] for state in activation.values())
    assert all("signed_residual_ci" in state["blockers"]
               for state in activation.values())


def test_calibration_deduplicates_leveraged_and_underlying_exposures():
    taxonomy = {
        "ONE": {"signal_ticker": "ONE"},
        "TWO": {"signal_ticker": "ONE"},
        "THREE": {"signal_ticker": "THREE"},
    }

    selected = peer._canonical_taxonomy_items(taxonomy)

    assert [target for target, _ in selected] == ["ONE", "THREE"]


def test_registered_rule_contract_keeps_hk_automatic_discovery_disabled():
    payload = json.loads(
        (ROOT / "config" / "peer-residual-rules.json").read_text()
    )

    assert payload["registered_at"] == "2026-07-26"
    assert payload["automatic_hk_peer_discovery"] is False
    assert payload["peer_source"].endswith("listed_peers only")


def test_checked_in_peer_artifact_has_no_unearned_live_rule():
    artifact = json.loads(
        (ROOT / "assets" / "data" / "peer_residual.json").read_text()
    )

    assert artifact["taxonomy"]["automatic_hk_peer_discovery"] is False
    assert all(
        state["usable_for_decisions"] is False
        for state in artifact["rule_activation"].values()
    )
    assert all(
        row["usable_for_decisions"] is False
        for row in artifact["live"].values()
    )
