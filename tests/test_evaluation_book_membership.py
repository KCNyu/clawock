"""The regime evaluations read the book they claim to evaluate (#2051).

`evaluate-combined-regime` says "the WHOLE book" but took membership from a
hand-kept map: RKLX, SPCH and SPCX (27.9% of the book that day) were dropped
without a word and the rest renormalised. `evaluate-us-leverage` validated three
2x names none of which was held, while the production dial it is cited for acts
on the registry's US 2x set.
"""
from clawock.decision import regime
from clawock.evaluation import combined_regime, us_leverage


def _book(**legs):
    return {"portfolios": {leg: {"holdings": [
        {"ticker": t, "shares": sh, "current_value": v} for t, sh, v in rows]}
        for leg, rows in legs.items()}}


def test_every_held_position_is_modelled_or_named():
    port = _book(hk_stocks=[("07226", 6200, 17_000), ("00100", 0, 9_999)],
                 us_stocks=[("RKLX", 10, 200), ("SPCH", 300, 2_900), ("CRCL", 2, 180)])
    weights, modelled, book, specs, unmodelled = combined_regime.book_weights(port)

    assert set(weights) == {"07226", "RKLX", "CRCL"}, "a held name missing from the map is resolved"
    assert specs["RKLX"] == ("RKLB", 2, "us2x"), "registry: signal RKLB, 2x, US dial"
    assert [t for t, _ in unmodelled] == ["SPCH"], "no long-history proxy → named, not dropped"
    assert abs(book - (17_000 * 0.128205 + 200 + 2_900 + 180)) < 1e-6
    assert abs(sum(weights.values()) - 1) < 1e-9 and modelled < book


def test_us_leverage_evaluates_the_names_the_dial_acts_on():
    assert {etf for etf, _, _ in us_leverage.NAMES} == set(regime.US_2X_MAP)
    assert {"RKLX", "SPCH"} <= {etf for etf, _, _ in us_leverage.NAMES}
