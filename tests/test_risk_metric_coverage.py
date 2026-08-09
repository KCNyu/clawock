"""Public risk numbers must disclose — and obey — their data denominator."""

import numpy as np

from clawock import portfolio_risk_metrics as risk


def _series(start=1780000000, closes=(100, 101, 102, 103, 104, 105, 106)):
    return [(start + i * 86400, close) for i, close in enumerate(closes)]


def test_partial_bucket_is_caveated_and_missing_leg_is_not_called_combined(monkeypatch):
    holdings = [
        {"ticker": "FETCHED", "yahoo_symbol": "FETCHED", "current_value": 900.0},
        {"ticker": "MISSING", "yahoo_symbol": "MISSING", "current_value": 100.0},
    ]
    monkeypatch.setattr(
        risk,
        "fetch_history",
        lambda symbol, **_kwargs: _series() if symbol == "FETCHED" else None,
    )

    us, us_meta = risk.compute_bucket(holdings, None, "us", sleep_between=0)

    assert us["history_coverage"] == {
        "holdings_fetched": 1,
        "holdings_total": 2,
        "current_value_pct": 90.0,
        "excluded_tickers": ["MISSING"],
    }
    alerts = risk.build_alerts(us, None, None, {})
    assert any(
        a["type"] == "risk_data_coverage"
        and "90.0%" in a["detail"]
        and "MISSING" in a["detail"]
        for a in alerts
    )

    hk_meta = {
        "aligned_dates": [f"2026-07-{d:02d}" for d in range(1, 8)],
        "port_rets": np.array([0.01, -0.01, 0.02, 0.0, -0.005, 0.01]),
    }
    # An active US leg with no current stream must not silently disappear from
    # a metric still published under the label "combined".
    assert risk.compute_combined(
        {"fetched": [], "failed": ["FETCHED", "MISSING"]},
        hk_meta,
        {"us": holdings, "hk": [{"ticker": "HK", "current_value": 1000.0}]},
        fx_hkd_to_usd=0.128,
    ) is None
