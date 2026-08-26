"""A simulated alpha printed without its denominator (#1088).

`assets/data/shadow_portfolio.json` on 2026-08-26:

    "cumulative_diff": {"USD": -510.09, "HKD": 24547.83}
    "fill_counts": {"real_trade": 0, "ohlc_assumption": 28,
                    "canonical_close_fallback": 0, "skipped": 238}

`estimand` claims the net value of following **every** triggered active call.
HK$24,548 rested on 28 filled legs out of 266 — 10.5% — and the number was
printed with nothing beside it saying so. The denominator sat in a different
object, and `skipped` was one bucket for three different causes.

With the causes kept, the same run reads:

    skipped:skipped_no_inventory  225
    skipped:skipped_no_cash        13

i.e. the simulated policy was mostly trying to sell what it never held. That is
a much sharper statement than "10.5% coverage", and it was one dict projection
away from being visible the whole time.
"""
from __future__ import annotations

import pytest

shadow = pytest.importorskip("clawock.decision.shadow")


def _curves(filled, skipped, reasons=None):
    types = {"real_trade": 0, "ohlc_assumption": filled,
             "canonical_close_fallback": 0, "skipped": skipped}
    types.update(reasons or {})
    return {"HKD": {"counts": {"fill_types": types}}}


def test_the_denominator_sits_with_the_number_it_qualifies():
    view = shadow._coverage_view(_curves(28, 238))
    assert view["filled_legs"] == 28
    assert view["skipped_legs"] == 238
    assert view["fill_rate"] == pytest.approx(0.1053, abs=1e-4)
    assert view["representative"] is False


def test_a_fully_filled_simulation_is_representative():
    view = shadow._coverage_view(_curves(266, 0))
    assert view["fill_rate"] == 1.0
    assert view["representative"] is True


def test_the_threshold_is_published_not_implied():
    """A reader must not have to guess what "representative" was measured against."""
    view = shadow._coverage_view(_curves(1, 1))
    assert view["minimum_representative_fill_rate"] == (
        shadow.MIN_REPRESENTATIVE_FILL_RATE)
    assert 0 < shadow.MIN_REPRESENTATIVE_FILL_RATE <= 1


def test_reason_buckets_never_double_count_the_total():
    """`skipped:*` are a breakdown OF `skipped`, not extra filled legs.

    Counting them as fills would inflate the very rate this exists to deflate.
    """
    view = shadow._coverage_view(_curves(
        28, 238, {"skipped:skipped_no_inventory": 225,
                  "skipped:skipped_no_cash": 13}))
    assert view["filled_legs"] == 28
    assert view["skipped_legs"] == 238


def test_an_empty_simulation_does_not_claim_a_rate():
    view = shadow._coverage_view({})
    assert view["fill_rate"] is None
    assert view["representative"] is False


def test_the_projection_keeps_every_reason_it_was_given():
    """The hand-listed dict is what dropped them; a new skip status must survive."""
    import inspect
    source = inspect.getsource(shadow)
    assert 'str(key).startswith("skipped:")' in source, (
        "the per-currency fill_types projection must forward reason buckets, "
        "or a new skip status is invisible the day it is added")
