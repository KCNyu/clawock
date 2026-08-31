"""What the shadow book pays to trade, and the two ways this could lie.

Every performance number this repository publishes is gross. `shadow` fills at
`qty * price` and `decision.ledger.condition_execution` records `fill_assumed`
beside every one — the assumption was written down and never priced. These tests
hold the haircut to the two things that make it worth publishing:

* **a zero model is exactly a no-op**, so the gross curve is not quietly
  redefined by the arrival of a cost model;
* **an estimator that declines does not charge zero**, because zero is the most
  liquid value in the cross-section and handing it to the names the model failed
  on is the error that flatters the result.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clawock import costs
from clawock.decision import shadow

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "cost-model.json"

DAY_1 = "2026-07-01"
DAY_2 = "2026-07-02"


def _model(**overrides):
    base = dict(
        assumed_commission_bps={"us": 10.0, "hk": 20.0},
        assumed_minimum_commission={},
        spread_source="fixed",
        spread_bps_by_leg={"us": 8.0, "hk": 20.0},
        spread_share=0.5,
        impact_source="off",
    )
    base.update(overrides)
    return costs.CostModel(**base)


def test_a_zero_model_charges_exactly_nothing():
    charge = costs.trade_cost(1_000_000, "us", DAY_1, {}, costs.CostModel.free())
    assert charge == {"commission": 0.0, "spread": 0.0, "total": 0.0, "bps": 0.0,
                      "spread_source": "off"}


def test_commission_and_half_spread_are_both_charged():
    charge = costs.trade_cost(100_000, "us", DAY_1, {}, _model())
    assert charge["commission"] == pytest.approx(100.0)   # 10bps of 100k
    assert charge["spread"] == pytest.approx(40.0)        # half of 8bps
    assert charge["total"] == pytest.approx(140.0)
    assert charge["bps"] == pytest.approx(14.0)


def test_the_leg_decides_the_rate_and_the_case_of_the_leg_does_not():
    """`US` from the ledger, `us` in the config. The first version looked one up
    in the other's table, found nothing, and charged every trade exactly zero."""
    for leg in ("hk", "HK", "Hk"):
        charge = costs.trade_cost(100_000, leg, DAY_1, {}, _model())
        assert charge["total"] == pytest.approx(300.0), leg
    assert costs.trade_cost(100_000, "us", DAY_1, {}, _model())["total"] < 300.0


def test_a_minimum_commission_dominates_a_small_ticket():
    model = _model(assumed_minimum_commission={"us": 1.0}, spread_bps_by_leg={})
    assert costs.trade_cost(100.0, "us", DAY_1, {}, model)["commission"] == 1.0
    assert costs.trade_cost(1_000_000.0, "us", DAY_1, {}, model)["commission"] == 1000.0


def test_an_unfillable_leg_costs_nothing_and_says_which_kind_of_nothing():
    charge = costs.trade_cost(0, "us", DAY_1, {}, _model())
    assert charge["total"] == 0.0
    assert charge["spread_source"] == "no_fill"


def _trending_bars(days=40, drift=1.02):
    """Bars an estimator can be run against. Trending on purpose: it is the
    shape both spread estimators handle worst."""
    price, out = 100.0, {}
    for index in range(days):
        day = f"2026-06-{index + 1:02d}" if index < 30 else f"2026-07-{index - 29:02d}"
        out[day] = {"high": price * 1.02, "low": price * 0.985,
                    "close": price, "open": price}
        price *= drift
    return out


def test_an_estimator_that_declines_falls_back_instead_of_charging_zero():
    """The load-bearing one. Roll returns None on a trending name — the exact
    names where a zero spread would be least true."""
    bars = _trending_bars()
    last = sorted(bars)[-1]
    model = _model(spread_source="roll")
    half, source = costs.spread_bps(bars, last, model, "us")
    assert source == "fixed_fallback", "Roll should decline on a clean uptrend"
    assert half == pytest.approx(4.0)  # half of the configured 8bps, not zero


def test_the_source_that_actually_ran_travels_with_the_trade():
    bars = _trending_bars()
    last = sorted(bars)[-1]
    charge = costs.trade_cost(100_000, "us", last, bars,
                              _model(spread_source="corwin_schultz"))
    assert charge["spread_source"] in {"corwin_schultz", "fixed_fallback"}
    assert charge["spread"] > 0


def test_a_date_the_bars_do_not_cover_falls_back_rather_than_guessing():
    model = _model(spread_source="corwin_schultz")
    half, source = costs.spread_bps(_trending_bars(), "2029-01-01", model, "us")
    assert source == "fixed_fallback"
    assert half == pytest.approx(4.0)


def test_the_shipped_model_does_not_default_to_the_bar_estimator():
    """Measured, not preferred: over the 27 tickers in the canonical manifest,
    Corwin-Schultz put the half-spread at a median 163bps against real spreads
    of single- to low-double-digit bps. The default records that finding."""
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert raw["spread_source"] == "fixed"
    assert costs.CostModel.load(CONFIG).spread_source == "fixed"
    assert any("163" in note for note in raw["notes"]), (
        "the measurement that chose this default is not written down beside it")


def test_impact_is_off_and_the_payload_says_so():
    """An uncalibrated impact model would look rigorous and be arbitrary."""
    model = costs.CostModel.load(CONFIG)
    assert model.impact_source == "off"
    assert model.as_dict()["impact_source"] == "off"
    assert "calibrat" in model.as_dict()["basis"]


def test_the_assumptions_are_labelled_as_assumptions():
    published = costs.CostModel.load(CONFIG).as_dict()
    assert "assumed_commission_bps" in published
    assert "assumed_minimum_commission" in published
    assert "not an observation" in published["basis"]
    assert published["registered_on"]


# ── the curve ───────────────────────────────────────────────────────────────

def _leg_fixture(model):
    """One buy, then a rise, so the net book's forgone growth is visible."""
    portfolio = {"portfolios": {"us_stocks": {
        "decision_leg": "US", "currency": "USD", "market": "us",
        "cash_usd": 100_000, "holdings": []}}}
    decisions = [{
        "decision_id": "d1", "plan_date": DAY_1,
        "created_at": f"{DAY_1}T08:00:00+08:00", "leg": "US", "ticker": "AAA",
        "action": "add_only_on_trigger", "size": {"shares": 1000},
        "evaluation": {"triggered": True, "trigger_session": DAY_1,
                       "execution_price": 10, "fill_model": "daily_ohlc_trigger"},
        "execution": {"status": "not_followed"},
    }]
    bars = {"AAA": {DAY_1: {"close": 10}, DAY_2: {"close": 20}}}
    return shadow.simulate_leg(
        portfolio, decisions, "US", as_of_date=DAY_2,
        bar_loader=lambda ticker, day: (bars.get(ticker) or {}).get(day),
        bar_map_loader=lambda ticker: bars.get(ticker) or {},
        matched={}, cost_model=model)


def test_a_free_model_leaves_the_gross_curve_untouched():
    """The gross number is the one every earlier claim was made with."""
    result = _leg_fixture(costs.CostModel.free())
    assert result["net"]["curve"] == result["curve"]
    assert result["net"]["cumulative_diff"] == result["cumulative_diff"]
    assert result["net"]["total_charged"] == 0.0
    assert result["net"]["charged_legs"] == 1


def test_the_two_books_end_exactly_the_fees_apart_and_say_why():
    """Not an approximation — an invariant of how this simulator is built.

    Quantities are decided in the first pass against a cash budget that knows
    nothing about fees, and the second pass only replays them. So a fee removes
    cash and never a share, and the second-order effect a real book would feel —
    a smaller fill when the cash cap binds — is not modelled. The payload has to
    say that rather than let a reader assume it was.
    """
    model = _model(assumed_commission_bps={"us": 100.0}, spread_bps_by_leg={})
    result = _leg_fixture(model)
    charged = result["net"]["total_charged"]
    assert charged > 0
    gap = result["final"]["followed_sim"] - result["net"]["followed_sim"]
    assert gap == pytest.approx(charged)
    assert "never a share" in result["net"]["limitation"]


def test_the_haircut_lands_on_the_date_it_happened():
    """The curve has to be right at every point, not only at the end — which is
    what a subtraction on the final number would have given."""
    model = _model(assumed_commission_bps={"us": 100.0}, spread_bps_by_leg={})
    result = _leg_fixture(model)
    gross = {point["date"]: point["followed_sim"] for point in result["curve"]}
    net = {point["date"]: point["followed_sim"] for point in result["net"]["curve"]}
    assert set(gross) == set(net)
    charged = result["net"]["total_charged"]
    for date in gross:
        assert gross[date] - net[date] == pytest.approx(charged), date


def test_every_filled_leg_is_charged_on_both_sides():
    result = _leg_fixture(_model())
    charges = result["net"]["charges"]
    assert len(charges) == result["net"]["charged_legs"] == 1
    assert charges[0]["direction"] == "buy"
    assert charges[0]["notional"] > 0
    assert charges[0]["total"] == pytest.approx(
        sum(charges[0][part] for part in ("commission", "spread")))


def test_the_assumptions_ride_with_the_curve_they_moved():
    result = _leg_fixture(_model())
    assumptions = result["net"]["assumptions"]
    assert assumptions["spread_share"] == 0.5
    assert assumptions["impact_source"] == "off"
    assert "gross" in result["net"]["reading"]


def test_a_leg_built_without_a_model_publishes_no_net_block():
    """A checkout without the pre-registered file degrades to gross-only rather
    than to a silently different assumption."""
    assert _leg_fixture(None)["net"] is None


def test_the_published_assumptions_are_the_pre_registered_ones():
    """The run-card question, asked of a daily artifact instead.

    A run card exists so a claim's parameters can be recovered after the fact.
    The shadow sidecar is rebuilt every day, so a card per build would be a
    year of near-identical files; the assumptions ride *inside* the payload
    instead, beside every number they moved. That only counts as provenance if
    what shipped is what was registered — a default quietly winning over
    `config/cost-model.json` would publish a net curve nobody pre-registered.
    """
    registered = costs.CostModel.load(CONFIG).as_dict()
    payload = shadow.build_shadow_portfolio(
        {"portfolios": {"us_stocks": {
            "decision_leg": "US", "currency": "USD", "market": "us",
            "cash_usd": 100_000, "holdings": []}}},
        [], as_of=f"{DAY_2}T17:00:00+08:00", matched={})
    assert payload["cost_assumptions"] == registered, (
        "the sidecar published assumptions that are not the pre-registered ones")
    assert "net_cumulative_diff" in payload, (
        "the net headline must exist beside the gross one even with no trades")


def test_every_published_assumption_is_reachable_from_the_config_file():
    """No knob may reach a published number without passing through the file.

    The failure this catches is a hardcoded rate: `as_dict` grows a field, the
    payload starts carrying it, and nothing in `config/cost-model.json` can
    change it — at which point 'pre-registered' is decoration.
    """
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    published = costs.CostModel.load(CONFIG).as_dict()
    derived = {"basis"}  # prose about the assumptions, not an assumption
    for field, value in published.items():
        if field in derived:
            continue
        assert field in raw, f"{field} is published but cannot be set in the file"
        assert raw[field] == value, f"{field} was transformed on its way out"
