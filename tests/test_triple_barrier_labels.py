"""Scoring a signal against a trade this book would not have held (#1164).

`signal_panel.forward_returns` scores every signal on the close `h` sessions
later. That is the outcome of a position nobody here holds: the book runs a
chandelier stop — `22d high - 3 x ATR(14)`, published as `stop_distance_pct` —
and a breach is a standard exit. On the live panel **72% of five-session windows
end at that stop**, so the fixed-horizon column is mostly describing trades that
were closed before it measured them.

These tests hold the labelling to the three properties that decide whether the
path-aware column is worth trusting: the stop has to trail, an intraday touch
has to count, and a bar that contains both barriers must not be resolved in the
favourable direction.
"""
import math

import pytest

from clawock.labeling import triple_barrier as tb


def _bars(closes, *, highs=None, lows=None):
    highs = highs or [value * 1.005 for value in closes]
    lows = lows or [value * 0.995 for value in closes]
    return [{'date': f'2026-01-{index + 1:04d}', 'close': close,
             'high': high, 'low': low}
            for index, (close, high, low) in enumerate(zip(closes, highs, lows))]


def _volatile_run(n=80, seed=3):
    import random
    rnd = random.Random(seed)
    closes, price = [], 100.0
    for _ in range(n):
        price *= 1 + rnd.gauss(0, 0.02)
        closes.append(price)
    return _bars(closes)


def test_an_intraday_touch_counts():
    """A stop checked only at the close is not the stop being run.

    Day two dips 18% intraday and closes the week up 3%. The fixed-horizon
    outcome is +3%; the account's is the stop.
    """
    closes = [100.0] * 8
    lows = [100.0] * 8
    lows[2] = 82.0
    bars = _bars(closes, lows=lows)
    result = tb.apply_barriers(bars, 1, horizon=5, volatility=0.05,
                               profit_multiple=2.0, stop_multiple=1.0)
    assert result['barrier'] == 'stop'
    assert result['index'] == 2
    assert result['return'] < 0


def test_the_stop_trails_instead_of_sitting_where_the_entry_was():
    """A level fixed at entry is a different rule, and the easy wrong one.

    The name runs up 40% and then gives back 15%. A stop one volatility unit
    below the *entry* is never touched; the book's trailing chandelier is.
    """
    closes = [100.0 * (1.02 ** index) for index in range(30)]
    closes += [closes[-1] * (0.97 ** index) for index in range(1, 6)]
    bars = _bars(closes)
    common = dict(horizon=9, volatility=0.08, profit_multiple=99.0,
                  stop_multiple=1.0)
    fixed = tb.apply_barriers(bars, 25, use_chandelier=False, **common)
    trailing = tb.apply_barriers(bars, 25, use_chandelier=True, **common)
    # The entry-level stop is never reached: the pullback gives back less than
    # the position had already gained. The trailing one is, because it moved up
    # with the price.
    assert fixed['barrier'] == 'horizon'
    assert trailing['barrier'] == 'stop'
    assert trailing['index'] < fixed['index']
    # And it exits with the gain intact rather than giving it back, which is
    # what a trailing stop is for — the direction of the difference is not the
    # claim here, the fact that the two labels disagree at all is.
    assert trailing['return'] > fixed['return']


def test_a_bar_holding_both_barriers_resolves_against_the_position():
    """Guessing the favourable order is how a backtest buys itself an edge.

    One session whose range spans the target and the stop. The bar does not say
    which came first, and the label must take the adverse one and say it was
    ambiguous.
    """
    bars = _bars([100.0] * 6, highs=[100.0, 130.0, 100.0, 100.0, 100.0, 100.0],
                 lows=[100.0, 70.0, 100.0, 100.0, 100.0, 100.0])
    result = tb.apply_barriers(bars, 0, horizon=5, volatility=0.10,
                               profit_multiple=2.0, stop_multiple=1.0)
    assert result['barrier'] == 'stop'
    assert result['ambiguous_bar'] is True


def test_the_barrier_mix_is_published_with_the_labels():
    """A label set that is 70% `stop` describes a rule, not a signal."""
    result = tb.label_series(_volatile_run(), horizon=5, use_chandelier=True)
    assert result['n'] > 0
    assert set(result['barrier_mix']) <= {'stop', 'target', 'horizon'}
    assert sum(result['barrier_mix'].values()) == result['n']
    assert result['params']['trailing_stop'] is True


def test_barriers_scale_with_the_name_rather_than_being_a_fixed_percentage():
    """This book holds a 12%-vol name and a 130%-vol one at the same time."""
    calm = tb.daily_volatility([100.0 * (1 + 0.001 * ((-1) ** index))
                                for index in range(80)])
    wild = tb.daily_volatility([100.0 * (1 + 0.05 * ((-1) ** index))
                                for index in range(80)])
    assert wild[-1] > calm[-1] * 10


def test_cusum_fires_on_movement_and_stays_quiet_when_nothing_happens():
    flat = [100.0] * 200
    assert tb.cusum_events(flat, 0.02) == []
    moving = [100.0 * (1.01 ** index) for index in range(200)]
    events = tb.cusum_events(moving, 0.02)
    assert 50 < len(events) < 200


def test_cusum_is_symmetric():
    up = [100.0 * (1.02 ** index) for index in range(60)]
    down = [100.0 * (0.98 ** index) for index in range(60)]
    assert len(tb.cusum_events(up, 0.05)) == len(tb.cusum_events(down, 0.05))


def test_the_panel_carries_both_outcome_definitions():
    """The pair is the point; either alone answers a different question."""
    from clawock.evaluation import signal_panel
    rows = [{'as_of': f'2026-06-{session:02d}', 'ticker': f'T{name}',
             'signal': 'x', 'value': float(name),
             't5': float(name), 'p5': float(name) / 2, 'b5': 'stop'}
            for session in range(1, 13) for name in range(6)]
    result = signal_panel.evaluate(rows)
    section = result['signals']['x']
    assert section['t5']['mean_ic'] is not None
    assert section['path_aware']['p5']['mean_ic'] is not None
    assert result['barriers']['p5']['stopped_share'] == 1.0


def test_a_signal_made_of_the_barrier_itself_is_flagged_as_circular():
    """`quant.stop_distance_pct` scoring -0.63 against a stop label is not a finding.

    The signal is the distance to the chandelier stop and the label is whether
    that stop was touched, so a name near it is stopped out by construction. The
    panel has to say so rather than leave it as the most negative row in the
    table.
    """
    from clawock.evaluation import signal_panel
    rows = [{'as_of': f'2026-06-{session:02d}', 'ticker': f'T{name}',
             'signal': 'quant.stop_distance_pct', 'value': float(name),
             't5': float(name), 'p5': -float(name), 'b5': 'stop'}
            for session in range(1, 13) for name in range(6)]
    section = signal_panel.evaluate(rows)['signals']['quant.stop_distance_pct']
    assert section['path_aware']['circular_against_barrier']
    assert 'barrier is this signal' in section['path_aware']['circular_against_barrier']
