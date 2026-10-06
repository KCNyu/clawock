"""A quote refresh must not undo what was written to its region meanwhile (#2629)."""
import copy
import json

from clawock.market_data import hk_analysis as hk
from clawock.portfolio import region_merge


def _region():
    return {"currency": "USD", "cash_usd": 100.0, "total_current_value": 80.0,
            "total_cost": 50.0, "total_pnl": 30.0, "total_pnl_percent": 60.0,
            "today_total_change": 0.0,
            "holdings": [{"ticker": "A", "shares": 10, "cost_basis": 5.0,
                          "current_price": 8.0, "current_value": 80.0, "pnl_abs": 30.0,
                          "trades": [{"date": "2026-10-01", "action": "buy",
                                      "shares": 10, "price": 5.0}]}]}


def _refreshed(before):
    after = copy.deepcopy(before)
    row = after["holdings"][0]
    row.update(current_price=9.0, current_value=90.0, pnl_abs=40.0,
               data_source="synthetic 10:00")
    after.update(total_current_value=90.0, total_pnl=40.0, total_pnl_percent=80.0)
    return after


def test_an_untouched_region_is_written_exactly_as_refreshed():
    before = _region()
    after = _refreshed(before)
    doc = {"last_updated": "old", "portfolios": {"us_stocks": copy.deepcopy(before),
                                                 "gold": {"units": 1}}}

    out = region_merge.overlay(doc, "us_stocks", before, after, last_updated="new")

    assert out["portfolios"]["us_stocks"] is after
    assert out["portfolios"]["gold"] == {"units": 1}
    assert out["last_updated"] == "new"


def test_a_trade_and_cash_written_during_the_fetch_survive_with_the_new_quote():
    before = _region()
    after = _refreshed(before)
    concurrent = copy.deepcopy(before)
    concurrent["cash_usd"] = 60.0
    concurrent["holdings"][0]["shares"] = 15
    concurrent["holdings"][0]["trades"].append(
        {"date": "2026-10-05", "action": "buy", "shares": 5, "price": 8.0})
    concurrent["holdings"].append({"ticker": "NEW", "shares": 1, "cost_basis": 2.0})
    doc = {"last_updated": "old", "portfolios": {"us_stocks": concurrent}}

    region = region_merge.overlay(doc, "us_stocks", before, after)["portfolios"]["us_stocks"]

    row = region["holdings"][0]
    assert region["cash_usd"] == 60.0
    assert len(row["trades"]) == 2 and row["shares"] == 15
    assert [h["ticker"] for h in region["holdings"]] == ["A", "NEW"]
    # The refresh's own leaves landed, and what derives from them was rebuilt
    # on the newer share count rather than carried over from the stale read.
    assert row["current_price"] == 9.0 and row["data_source"] == "synthetic 10:00"
    assert row["current_value"] == 135.0
    assert region["total_current_value"] == 135.0
    assert region["total_cost"] == 77.0          # 15 * 5 + the quote-less row's 1 * 2


def test_hk_refresh_keeps_a_fill_recorded_while_it_was_fetching(tmp_path, monkeypatch):
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps({"portfolios": {"hk_stocks": {"cash_hkd": 1000.0, "holdings": [{
        "ticker": "00100", "shares": 100.0, "cost_basis": 300.0, "current_price": 312.0,
        "prev_close": 312.2, "lot_size": 500,
        "trades": [{"date": "2026-09-01", "action": "buy", "shares": 100.0, "price": 300.0}]}]}}}))
    monkeypatch.setattr(hk, "PORTFOLIO_PATH", str(path))

    def fetch(_codes):
        book = json.loads(path.read_text())
        leg = book["portfolios"]["hk_stocks"]
        leg["cash_hkd"] = 400.0
        leg["holdings"][0]["trades"].append(
            {"date": "2026-10-05", "action": "sell", "shares": 2.0, "price": 300.0})
        path.write_text(json.dumps(book))
        return {"00100": {"name": "MINIMAX-W", "c": 299.6, "pc": 312.2, "o": 312.0,
                          "h": 323.6, "l": 290.4, "lot_size": 500, "volume": 1,
                          "dp": -4.04, "_src": "Tencent"}}

    monkeypatch.setattr(hk, "fetch_hk_quotes", fetch)
    monkeypatch.setattr(hk, "fetch_indices", lambda: {})

    hk.update_hk_portfolio()

    leg = json.loads(path.read_text())["portfolios"]["hk_stocks"]
    assert leg["cash_hkd"] == 400.0
    assert len(leg["holdings"][0]["trades"]) == 2
    assert leg["holdings"][0]["current_price"] == 299.6
