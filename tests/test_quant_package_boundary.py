"""The quant/regime/T0 loop belongs to the wheel, not one checkout layout."""

import json
from pathlib import Path

from clawock.decision import signals as quant
from clawock.decision import regime
from clawock.decision import setups as t0
from clawock.decision import signal_review as quant_signal_review
from clawock.decision import setup_review as t0_setup_review


ROOT = Path(__file__).resolve().parents[1]


def _write_portfolio(path, books):
    path.write_text(json.dumps({"portfolios": books}), encoding="utf-8")


def test_all_five_modules_ship_from_the_package_and_scripts_are_retired():
    for module in (quant, regime, t0, quant_signal_review, t0_setup_review):
        assert Path(module.__file__).is_relative_to(ROOT / "src" / "clawock")
        assert not (ROOT / "scripts" / "data" / Path(module.__file__).name).exists()


def test_quant_and_regime_discover_holdings_without_kcnyu_book_keys(
        tmp_path, monkeypatch):
    portfolio = tmp_path / "portfolio.json"
    _write_portfolio(portfolio, {
        "growth_book": {
            "currency": "USD",
            "holdings": [
                {"ticker": "RKLX", "shares": 2},
                {"ticker": "SPCH", "shares": 3},
            ],
        },
        "reserve_book": {"currency": "JPY", "holdings": []},
    })
    monkeypatch.setattr(quant, "PORTFOLIO", portfolio)
    monkeypatch.setattr(regime, "PORTFOLIO", portfolio)

    rows = quant._universe_details()

    assert {row["label"] for row in rows} == {"RKLB", "SPCX"}
    assert regime._held_us_lev_etfs() == ["RKLX", "SPCH"]


def test_t0_derives_market_from_registry_not_the_book_name(tmp_path, monkeypatch):
    portfolio = tmp_path / "portfolio.json"
    quant_file = tmp_path / "quant.json"
    _write_portfolio(portfolio, {
        "growth_book": {
            "currency": "USD",
            "holdings": [{
                "ticker": "SPCH", "name": "fixture", "shares": 1,
                "current_price": 10, "prev_close": 9, "day_open": 9,
                "day_low": 8, "day_high": 11, "today_change_pct": 11.11,
            }],
        },
    })
    quant_file.write_text(json.dumps({"rows": {}}), encoding="utf-8")
    monkeypatch.setattr(t0, "PORTFOLIO", portfolio)
    monkeypatch.setattr(t0, "QUANT", quant_file)
    monkeypatch.setattr(t0.tc, "closed_reason", lambda market: "closed")

    result = t0.compute()

    assert result["rows"]["SPCH"]["market"] == "us"
    assert result["market_closed"] == {"us": True}
