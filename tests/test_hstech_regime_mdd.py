"""max_drawdown must stay total on every NAV shape — it is the evidence
replay primitive behind the leverage dial's run cards (#942).

A no-drawdown path used to raise UnboundLocalError (mdd_peak_i was only bound
inside `if dd < mdd`), so any monotonic segment crashed the evaluation CLI
mid-table instead of reporting a 0.0 drawdown.
"""
from clawock.evaluation.hstech_regime import max_drawdown


def test_no_drawdown_returns_zero_with_window_bounds():
    mdd, peak_day, trough_day = max_drawdown(
        [1.0, 1.2, 1.5, 1.6], ["d1", "d2", "d3", "d4"])
    assert mdd == 0.0


def test_flat_series_is_zero_drawdown():
    assert max_drawdown([2.0, 2.0, 2.0]) == 0.0


def test_drawdown_reports_peak_and_trough_dates():
    nav = [1.0, 1.5, 0.75, 1.0]
    mdd, peak_day, trough_day = max_drawdown(
        nav, ["a", "b", "c", "d"])
    assert mdd == (0.75 - 1.5) / 1.5
    assert peak_day == "b"
    assert trough_day == "c"


def test_later_new_high_resets_the_peak_reference():
    nav = [1.0, 0.9, 2.0, 1.4]
    mdd, peak_day, trough_day = max_drawdown(
        nav, ["a", "b", "c", "d"])
    assert mdd == (1.4 - 2.0) / 2.0
    assert peak_day == "c"
    assert trough_day == "d"
