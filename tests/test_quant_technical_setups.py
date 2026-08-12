"""Behavior contracts for prospective, no-lookahead technical entry setups."""

from clawock.decision.signals import compute_signals


def _bars(closes):
    rows = []
    for index, close in enumerate(closes):
        rows.append({
            "date": f"d{index:03d}",
            "open": close * 0.997,
            "close": close,
            "high": close * 1.005,
            "low": close * 0.995,
        })
    return rows


def test_confirmed_breakout_is_emitted_with_trigger_and_invalidation():
    closes = [50 + i * 0.25 for i in range(220)]
    bars = _bars(closes)
    prior_high = max(row["high"] for row in bars[-20:])
    bars.append({
        "date": "breakout", "open": prior_high * 0.995,
        "close": prior_high * 1.01, "high": prior_high * 1.015,
        "low": prior_high * 0.99,
    })

    result = compute_signals(bars)
    setup = next(
        row for row in result["technical_setups"]
        if row["setup_id"] == "confirmed_breakout"
    )

    assert setup["entry_price"] == round(prior_high, 3)
    assert setup["invalidation_price"] < setup["entry_price"]
    assert setup["max_tranches"] == 2


def test_loss_or_one_green_close_alone_does_not_create_average_down_setup():
    closes = [120 - i * 0.2 for i in range(219)] + [70]
    bars = _bars(closes)
    bars.append({
        "date": "small-bounce", "open": 70, "close": 70.2,
        "high": 71, "low": 69.5,
    })

    result = compute_signals(bars)

    assert not any(
        row["setup_id"] == "oversold_reclaim"
        for row in result["technical_setups"]
    )


def test_oversold_average_down_requires_reclaim_and_is_one_small_tranche():
    closes = [100 + i * 0.1 for i in range(210)]
    closes += [120, 118, 116, 114, 112, 110, 108, 106, 104, 100]
    bars = _bars(closes)
    prior = bars[-1]
    reclaim = prior["high"] * 1.02
    bars.append({
        "date": "reclaim", "open": prior["close"], "close": reclaim,
        "high": reclaim * 1.01, "low": prior["low"] * 0.99,
    })

    result = compute_signals(bars)
    setup = next(
        row for row in result["technical_setups"]
        if row["setup_id"] == "oversold_reclaim"
    )

    assert setup["max_tranches"] == 1
    assert setup["tranche_pct_of_position"] == 0.05
    assert setup["entry_price"] == round(reclaim, 3)
    assert setup["invalidation_price"] < setup["entry_price"]
