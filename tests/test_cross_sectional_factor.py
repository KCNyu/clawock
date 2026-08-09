import copy
import json
from datetime import date, timedelta
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
from clawock import cross_sectional_factor as factor


def _bars(rate, count=180, volume=1000):
    start = date(2025, 1, 1)
    return [
        {
            "date": (start + timedelta(days=index)).isoformat(),
            "close": 100 * ((1 + rate) ** index),
            "volume": volume,
        }
        for index in range(count)
    ]


def _small_config():
    config = factor.load_config()
    config["symbols"] = [
        {"ticker": "A1", "region": "us", "sector": "alpha"},
        {"ticker": "A2", "region": "us", "sector": "alpha"},
        {"ticker": "A3", "region": "us", "sector": "alpha"},
        {"ticker": "B1", "region": "us", "sector": "beta"},
        {"ticker": "B2", "region": "us", "sector": "beta"},
        {"ticker": "B3", "region": "us", "sector": "beta"},
    ]
    config["leveraged_proxies"] = []
    return config


def _fact(value, filed, end="2025-12-31", form="10-K"):
    return {
        "val": value,
        "filed": filed,
        "end": end,
        "form": form,
        "fp": "FY",
    }


def test_quality_snapshot_uses_filing_date_and_never_future_information():
    facts = {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": [
                        _fact(100, "2026-01-15"),
                        _fact(200, "2026-03-15", end="2026-02-28", form="10-Q"),
                    ]}
                },
                "Revenues": {
                    "units": {"USD": [
                        _fact(120, "2026-01-20")
                    ]}
                },
                "GrossProfit": {"units": {"USD": [_fact(50, "2026-01-15")]}},
                "OperatingIncomeLoss": {
                    "units": {"USD": [_fact(20, "2026-01-15")]}
                },
                "NetIncomeLoss": {"units": {"USD": [_fact(10, "2026-01-15")]}},
                "Assets": {"units": {"USD": [_fact(200, "2026-01-15")]}},
            }
        }
    }

    snapshot = factor.quality_snapshot(facts, "2026-02-01")

    assert snapshot["available"] is True
    assert snapshot["known_as_of"] == "2026-01-20"
    assert snapshot["period_end"] == "2025-12-31"
    # The newer alternate revenue tag wins while the future filing stays out.
    assert snapshot["metrics"] == {
        "gross_margin": 0.416667,
        "operating_margin": 0.166667,
        "return_on_assets": 0.05,
    }
    assert snapshot["available"] is True
    assert snapshot["raw_score"] == pytest.approx(0.211111)


def test_rank_snapshot_is_centered_within_sector_not_across_sector_beta():
    config = _small_config()
    fetched = {
        "A1": {"bars": _bars(0.010, volume=3000)},
        "A2": {"bars": _bars(0.005, volume=2000)},
        "A3": {"bars": _bars(0.001, volume=1000)},
        "B1": {"bars": _bars(0.020, volume=3000)},
        "B2": {"bars": _bars(0.015, volume=2000)},
        "B3": {"bars": _bars(0.011, volume=1000)},
    }
    as_of = fetched["A1"]["bars"][-1]["date"]

    rows = factor.rank_snapshot(config, fetched, as_of)

    assert rows["A1"]["composite_score"] > rows["A2"]["composite_score"]
    assert rows["A2"]["composite_score"] > rows["A3"]["composite_score"]
    assert rows["B1"]["composite_score"] > rows["B2"]["composite_score"]
    assert rows["B2"]["composite_score"] > rows["B3"]["composite_score"]
    for sector in ("alpha", "beta"):
        sector_rows = [row for row in rows.values() if row["sector"] == sector]
        for name in factor.RAW_FACTORS:
            ranks = [
                row["sector_neutral_ranks"][name]
                for row in sector_rows if name in row["sector_neutral_ranks"]
            ]
            assert sum(ranks) == pytest.approx(0.0)


def test_two_way_cluster_ci_requires_both_date_and_ticker_clusters():
    one_date = [
        {"date": "d1", "ticker": "A", "value": 0.1},
        {"date": "d1", "ticker": "B", "value": 0.2},
    ]
    clustered = [
        {"date": date_, "ticker": ticker, "value": 0.1}
        for date_ in ("d1", "d2", "d3")
        for ticker in ("A", "B", "C")
    ]

    assert factor.clustered_mean_ci(one_date) is None
    assert factor.clustered_mean_ci(clustered) == [0.1, 0.1]


def test_activation_remains_blocked_by_survivorship_and_prospective_evidence():
    config = factor.load_config()
    prospective = {
        "n_dates": 0,
        "n_tickers": 0,
        "n_sectors": 0,
        "signed_return_ci95": None,
    }

    result = factor.activation_status(
        config, prospective, price_coverage=1.0, quality_coverage=1.0
    )

    assert result["active"] is False
    assert result["usable_for_decisions"] is False
    assert "membership_history" in result["blockers"]
    assert "prospective_dates" in result["blockers"]
    assert "clustered_edge" in result["blockers"]


def test_activation_requires_cluster_ci_lower_bound_above_zero():
    config = factor.load_config()
    config = copy.deepcopy(config)
    config["membership_history_complete"] = True
    prospective = {
        "n_dates": 30,
        "n_tickers": 15,
        "n_sectors": 4,
        "signed_return_ci95": [-0.001, 0.02],
    }

    result = factor.activation_status(
        config, prospective, price_coverage=1.0, quality_coverage=1.0
    )

    assert result["active"] is False
    assert result["blockers"] == ["clustered_edge"]


def test_leveraged_proxy_reports_tracking_and_decay_gap_without_live_permission():
    config = _small_config()
    config["leveraged_proxies"] = [
        {"ticker": "LEV", "region": "us", "underlying": "A1", "leverage": 2}
    ]
    dates = [(date(2025, 1, 1) + timedelta(days=index)).isoformat()
             for index in range(130)]
    underlying = [
        {"date": day, "close": 100 * (1.001 ** index), "volume": 1000}
        for index, day in enumerate(dates)
    ]
    leveraged = [
        {"date": day, "close": 100 * (1.0015 ** index), "volume": 1000}
        for index, day in enumerate(dates)
    ]

    result = factor.leveraged_decay(
        config,
        {"A1": {"bars": underlying}, "LEV": {"bars": leveraged}},
        {"A1": {"composite_score": -0.1}},
    )["LEV"]

    assert result["horizons"]["1m"]["tracking_and_decay_gap"] < 0
    assert result["research_only_preference"] == "prefer_1x_or_no_add"
    assert result["usable_for_decisions"] is False


def test_pre_registered_config_is_valid_json_and_weights_sum_to_one():
    payload = json.loads(
        (ROOT / "config" / "factor-universe.json").read_text()
    )

    assert payload["registered_at"] == "2026-07-26"
    assert payload["membership_history_complete"] is False
    assert sum(payload["factor_weights"].values()) == pytest.approx(1.0)


def test_checked_in_research_artifact_cannot_silently_become_a_live_signal():
    artifact = json.loads(
        (ROOT / "assets" / "data" / "cross_sectional_factor.json").read_text()
    )

    assert artifact["activation"]["active"] is False
    assert artifact["activation"]["usable_for_decisions"] is False
    assert "membership_history" in artifact["activation"]["blockers"]
    assert all(
        row["usable_for_decisions"] is False
        for row in artifact["live_rankings"].values()
    )
