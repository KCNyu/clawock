import copy
import json
import sys
from pathlib import Path


WS = Path(__file__).resolve().parents[1]

from clawock.publish import dashboard as build_dashboard  # noqa: E402
from clawock.market_data import bars as fetch_daily_bars
from clawock.market_data import us_quotes as fetch_us_stocks  # noqa: E402
from clawock.portfolio import instruments as instrument_registry  # noqa: E402
from clawock.portfolio import risk as portfolio_risk_metrics  # noqa: E402
from clawock.decision import signals as compute_quant_signals  # noqa: E402
from clawock.decision import regime as compute_regime  # noqa: E402
from clawock.decision import setups as compute_t0_setups  # noqa: E402
from clawock.portfolio import integrity as preflight_integrity  # noqa: E402
from clawock.harness import brief_preflight  # noqa: E402
from clawock.market_data import hk_analysis as analyze_hk_stocks  # noqa: E402
from clawock.market_data import us_analysis as analyze_us_stocks  # noqa: E402


def test_registry_implementation_is_product_not_a_repository_script():
    assert instrument_registry.__file__ == str(
        WS / "src" / "clawock" / "portfolio" / "instruments.py"
    )
    assert not (WS / "scripts" / "data" / "instrument_registry.py").exists()


def _portfolio():
    return json.loads((WS / "portfolio.json").read_text())


def test_registry_schema_and_every_active_holding_are_complete():
    doc = json.loads((WS / "config" / "instruments.json").read_text())
    assert instrument_registry.validate_registry(doc) == []
    assert instrument_registry.validate_active_holdings(_portfolio()) == []


def test_active_holding_missing_metadata_fails_closed():
    portfolio = _portfolio()
    portfolio["portfolios"]["us_stocks"]["holdings"].append(
        {"ticker": "UNREGISTERED", "shares": 1, "current_value": 10, "cost_basis": 10}
    )
    assert instrument_registry.validate_active_holdings(portfolio) == [
        "active us_stocks holding 'UNREGISTERED' missing from registry"
    ]


def test_invalid_one_x_substitute_factor_is_rejected():
    doc = {
        "schema_version": 1,
        "instruments": copy.deepcopy(instrument_registry.INSTRUMENTS),
    }
    doc["instruments"]["SPCH"]["one_x_substitute"] = "MSFT"
    errors = instrument_registry.validate_registry(doc)
    assert any(
        "SPCH.one_x_substitute must share look-through factor" in error
        for error in errors
    )


def test_all_consumer_maps_derive_the_missing_audit_symbols_from_registry():
    assert portfolio_risk_metrics.LEVERAGED["SPCH"] == 2
    assert brief_preflight.LEV_1X_SWAP["RKLX"] == "RKLB"
    assert brief_preflight.LEV_1X_SWAP["SPCH"] == "SPCX"
    assert build_dashboard.LEVERAGED_TICKERS >= {"SPCH", "RKLX", "MSFU", "PLTU"}
    assert fetch_daily_bars.MANIFEST["SPCH"]["tencent"] == "usSPCH.AM"
    assert fetch_us_stocks.EASTMONEY_PREFIX["SPCH"] == "107"
    assert fetch_us_stocks.EASTMONEY_PREFIX["PLTR"] == "105"
    assert compute_regime.US_2X_MAP["RKLX"] == ("RKLB", "usRKLB.OQ")
    assert compute_regime.US_2X_MAP["SPCH"] == ("SPCX", "usSPCX.OQ")
    assert compute_t0_setups.LEVERAGED["SPCH"] == ("SPCX", 2)
    assert analyze_hk_stocks.LEVERAGED == {"07226", "07709", "07747"}
    assert analyze_us_stocks._is_leveraged_holding(
        {"ticker": "SPCH", "name": "name without leverage keywords"}
    )
    assert preflight_integrity.HSTECH_SIBLINGS == {"03032", "03033", "07226"}


def test_quant_universe_uses_canonical_underlyings_and_venue_suffixes():
    universe = compute_quant_signals._universe()
    by_label = {label: (code, note) for label, code, note in universe}
    portfolio = _portfolio()
    active = {
        str(holding["ticker"])
        for book in portfolio["portfolios"].values()
        for holding in book.get("holdings", [])
        if holding.get("shares", 0) > 0
    }
    expected_labels = {
        instrument_registry.require(ticker).get("signal_symbol") or ticker
        for ticker in active
    }
    assert set(by_label) == expected_labels
    for label, (code, _note) in by_label.items():
        assert code == instrument_registry.require(label)["tencent_symbol"]
    # Tradable 1x ETFs need their own price scale for an executable setup.
    assert instrument_registry.require("03032")["signal_symbol"] == "03032"
    assert instrument_registry.require("03033")["signal_symbol"] == "03033"
    # The leveraged 07226 still looks through to the index and cannot add.
    assert by_label["HSTECH"][0] == "hkHSTECH"
    assert "SPCH" not in by_label
    assert "RKLX" not in by_label


def test_live_dashboard_exposure_has_no_other_and_matches_risk_leverage():
    portfolio = _portfolio()
    sectors = build_dashboard.compute_sector_exposure(portfolio)
    assert all(row["sector"] != "Other" for leg in sectors.values() for row in leg)
    assert {"SPCX", "SPCH", "SKHY"} <= {
        ticker for row in sectors["us"] for ticker in row["tickers"]
    }

    leveraged = build_dashboard.compute_leveraged_etf_exposure(portfolio, fx_rate=7.84)
    # us_pct is a share of live market value, so pinning today's quote (it was
    # 83.53) goes red at the next close for no reason. Pin the derivation
    # instead: active-only holdings, current_value denominator, registry-driven
    # numerator. `compute_leveraged_etf_exposure` swallows exceptions and
    # returns us_pct=None, so the not-None check is what keeps that fail-open
    # from passing silently.
    us_active = [
        h
        for h in portfolio["portfolios"]["us_stocks"]["holdings"]
        if h.get("shares", 0) > 0
    ]
    us_total = sum(h.get("current_value", 0) or 0 for h in us_active)
    us_lev = sum(
        h.get("current_value", 0) or 0
        for h in us_active
        if h["ticker"] in instrument_registry.leveraged_symbols()
    )
    assert us_total > 0 and us_lev > 0
    assert leveraged["us_pct"] is not None
    assert leveraged["us_pct"] == round(us_lev / us_total * 100, 2)
    assert set(leveraged["tickers"]) == {
        h["ticker"]
        for h in us_active + portfolio["portfolios"]["hk_stocks"]["holdings"]
        if h.get("shares", 0) > 0
        and h["ticker"] in instrument_registry.leveraged_symbols()
    }

    lookthrough = build_dashboard.compute_lookthrough_exposure(portfolio)
    assert lookthrough["us"]["metadata_coverage_pct"] == 100.0
    spacex = next(
        row for row in lookthrough["us"]["factors"] if row["factor"] == "SPACEX"
    )
    assert spacex["tickers"] == ["SPCH", "SPCX"]
    assert spacex["gross_value"] > spacex["capital_value"]
    assert lookthrough["us"]["factor_hhi"] > 0
    assert lookthrough["us"]["sector_hhi"] > 0


def test_leveraged_exposure_ignores_closed_positions_with_stale_values():
    """Live portfolio.json zeroes current_value on exit, so the active-only
    filter in compute_leveraged_etf_exposure is unobservable there. Pin it on a
    synthetic book where a closed leveraged position still carries a value."""
    portfolio = _portfolio()
    us = portfolio["portfolios"]["us_stocks"]["holdings"]
    live = build_dashboard.compute_leveraged_etf_exposure(portfolio, fx_rate=7.84)

    closed = next(h for h in us if (h.get("shares", 0) or 0) <= 0)
    stale = copy.deepcopy(closed)
    stale["ticker"] = sorted(instrument_registry.leveraged_symbols())[0]
    stale["shares"] = 0
    stale["current_value"] = 1_000_000.0
    us.append(stale)

    assert build_dashboard.compute_leveraged_etf_exposure(
        portfolio, fx_rate=7.84
    ) == live
