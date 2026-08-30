"""What a daily bar can say, and where it must stay silent (#1172/#1173).

The two competitor-port issues behind this asked for an execution layer — a
matching engine, slippage models, an option pricer, an implied-volatility
surface. clawock places no orders, holds no order book and receives no option
quotes, so none of that has an input. What it has is a daily OHLCV bar, and the
literature on what a daily bar reveals about the two things an order book would
have said directly: what this name costs to move, and how much it is about to
move.

These tests are mostly about the second half of the module's job — **refusing**.
Roll's spread has no real root on a trending name, and the convention of
flooring those at zero assigns the most liquid value in the cross-section to
exactly the names where the model does not apply. Every estimator here returns
`None` in its own undefined regime, and the tests below are what stop that from
quietly becoming a zero again.
"""
import math
import random
import statistics

import pytest

from clawock.market_data import bar_signals as bs


def _bars(returns, *, volume=1e6, spread=0.0, start=100.0):
    """Bars from a return path, optionally with a bid-ask bounce added."""
    bars, price = [], start
    for index, value in enumerate(returns):
        price *= (1 + value)
        quoted = price * (1 + (spread / 2 if index % 2 else -spread / 2))
        bars.append({'date': f'2026-01-{index + 1:04d}', 'open': quoted,
                     'close': quoted, 'high': price * 1.01, 'low': price * 0.99,
                     'volume': volume})
    return bars


def _garch_path(omega, alpha, beta, n, seed):
    rnd = random.Random(seed)
    variance = omega / (1 - alpha - beta)
    out = []
    for _ in range(n):
        value = rnd.gauss(0, math.sqrt(variance))
        out.append(value)
        variance = omega + alpha * value * value + beta * variance
    return out


def test_roll_refuses_a_trending_name_instead_of_calling_it_liquid():
    """The defect the convention hides.

    A steadily rising price has *positively* autocorrelated changes, so
    `-cov` is negative and the estimator has no real root. Flooring it at zero
    would rank this name as the tightest spread in the cross-section.
    """
    trending = _bars([0.01] * 40, spread=0.0)
    assert bs.roll_spread(trending, len(trending) - 1) is None


def _roll_bars(n, half_spread, sigma, seed):
    """Roll's own model: a random-walk efficient price, and a random side."""
    rnd = random.Random(seed)
    price, out = 100.0, []
    for index in range(n):
        price *= 1 + rnd.gauss(0, sigma)
        quoted = price * (1 + half_spread * rnd.choice((-1, 1)))
        out.append({'date': f'd{index}', 'open': quoted, 'close': quoted,
                    'high': price * 1.01, 'low': price * 0.99, 'volume': 1e6})
    return out


def test_roll_recovers_a_spread_it_was_given():
    """And it must still work where the model does apply.

    Averaged over six paths of Roll's own data-generating process, not one:
    the estimator is a square root of a covariance and a single path is noisy
    enough that a tight single-seed band would be fitting the test to a seed.
    """
    for half_spread in (0.01, 0.005):
        estimates = [bs.roll_spread(_roll_bars(300, half_spread, 0.002, seed),
                                    299, sessions=120)
                     for seed in range(6)]
        assert all(value is not None for value in estimates)
        recovered = statistics.fmean(estimates)
        truth = 2 * half_spread * 100
        assert abs(recovered - truth) < 0.4 * truth


def test_amihud_refuses_a_window_that_is_mostly_missing_volume():
    """Otherwise it ranks the vendor's coverage, not the names."""
    rnd = random.Random(2)
    bars = _bars([rnd.gauss(0, 0.01) for _ in range(40)])
    for index in range(20, 40):
        bars[index]['volume'] = None
    assert bs.amihud_illiquidity(bars, len(bars) - 1) is None


def test_amihud_is_higher_for_the_name_that_moves_more_per_dollar():
    rnd = random.Random(7)
    path = [rnd.gauss(0, 0.02) for _ in range(60)]
    thin = bs.amihud_illiquidity(_bars(path, volume=1e5), 59)
    deep = bs.amihud_illiquidity(_bars(path, volume=1e8), 59)
    assert thin > deep * 100


def test_corwin_schultz_drops_its_negative_estimates_rather_than_flooring_them():
    """A gap breaks the model, and a floored zero would read as a tight spread.

    The estimator identifies the spread from the difference between two days of
    range and twice one day of range. A large overnight gap makes the two-day
    range far larger than either day's, the implied alpha goes negative, and the
    conventional fix — floor at zero — would call the gapping name the tightest
    in the cross-section. Those days are dropped; when every day is like that
    the answer is `None`.
    """
    gapping = []
    price = 100.0
    for index in range(40):
        price *= 2.0                       # a 100% gap every session
        gapping.append({'date': f'd{index}', 'open': price, 'close': price,
                        'high': price * 1.001, 'low': price * 0.999,
                        'volume': 1e6})
    assert bs.corwin_schultz_spread(gapping, 39) is None


def test_corwin_schultz_grows_with_the_intraday_range_it_is_given():
    def bars(range_pct):
        rnd = random.Random(4)
        price, out = 100.0, []
        for index in range(60):
            price *= 1 + rnd.gauss(0, 0.002)
            out.append({'date': f'd{index}', 'open': price, 'close': price,
                        'high': price * (1 + range_pct),
                        'low': price * (1 - range_pct), 'volume': 1e6})
        return out
    narrow = bs.corwin_schultz_spread(bars(0.002), 59)
    wide = bs.corwin_schultz_spread(bars(0.02), 59)
    assert narrow is not None and wide is not None
    assert wide > narrow


def test_garch_recovers_the_persistence_it_was_simulated_with():
    """The quantity the sample actually identifies.

    On 250 observations the split between alpha and beta is not identified —
    two seeds of the same process give (0.12, 0.76) and (0.03, 0.93) — but their
    sum is. The forecast depends on the sum, so that is what is tested and what
    the module publishes as `garch_persistence`.
    """
    for alpha, beta in ((0.10, 0.85), (0.05, 0.90)):
        recovered = []
        for seed in range(6):
            fit = bs.fit_garch11(_garch_path(0.00002, alpha, beta, 1500, seed))
            assert fit is not None
            recovered.append(fit['persistence'])
        assert abs(statistics.fmean(recovered) - (alpha + beta)) < 0.09


def test_garch_refuses_a_short_sample_rather_than_reporting_near_unit_persistence():
    """The classic small-sample artefact.

    Fitting persistence to a hundred days returns alpha + beta near one whatever
    the data did, and that reads as "extremely persistent volatility" instead of
    "not enough data".
    """
    assert bs.fit_garch11(_garch_path(0.00002, 0.1, 0.85, 100, 1)) is None


def test_garch_tracks_a_volatility_regime_change():
    """The forecast has to lead the trailing window, or it adds nothing.

    A calm stretch followed by a violent one: right at the break, the GARCH
    forecast must already be above the long-run level that a 250-day trailing
    standard deviation is still averaging in.
    """
    rnd = random.Random(9)
    calm = [rnd.gauss(0, 0.005) for _ in range(400)]
    violent = [rnd.gauss(0, 0.03) for _ in range(30)]
    fit = bs.fit_garch11(calm + violent)
    assert fit is not None
    assert fit['annualised_forecast'] > fit['long_run_annualised']


def test_the_row_keeps_its_undefined_entries_rather_than_dropping_them():
    """"Does not apply here" and "not covered" are different statements."""
    trending = _bars([0.01] * 300)
    row = bs.bar_signal_row(trending, len(trending) - 1)
    assert 'roll_spread_pct' in row
    assert row['roll_spread_pct'] is None
    assert row['amihud_illiquidity'] is not None


def test_availability_separates_a_thin_session_from_an_inapplicable_model():
    rows = {'A': {'roll_spread_pct': None, 'ewma_volatility': 0.3},
            'B': {'roll_spread_pct': 0.4, 'ewma_volatility': 0.5}}
    report = bs.availability(rows)
    assert report['n_tickers'] == 2
    assert report['defined']['roll_spread_pct'] == 1
    assert report['defined']['ewma_volatility'] == 2
    assert 'roll_spread_pct' in report['conditionally_defined']


def test_nothing_here_joins_the_pre_registered_composite():
    """The hard boundary.

    `factor_weights` must exactly match `RAW_FACTORS` and sum to one; adding a
    constituent is a re-registration and a research decision. If a bar-derived
    estimator ever appears in the weights, this fails.
    """
    from clawock.market_data import factors
    weights = factors.load_config()['factor_weights']
    assert set(weights) == set(factors.RAW_FACTORS)
    bar_fields = set(bs.bar_signal_row(_bars([0.001] * 300), 299))
    assert not (bar_fields & set(weights))


def test_the_panel_namespaces_them_apart_from_the_composite():
    from clawock.evaluation import signal_panel
    payload = {'rows': {'AAA': {'ewma_volatility': 0.4, 'roll_spread_pct': None}}}
    emitted = signal_panel.bar_signals(payload)
    assert emitted == [('AAA', 'bar.ewma_volatility', 0.4)]
