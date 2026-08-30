"""Labelling an outcome the book could actually have realised.

The problem
-----------
`signal_panel.forward_returns` scores every signal against a close-to-close
return `h` sessions later. That is the outcome of a position nobody in this book
holds. The book runs a **chandelier stop** — `22d high − 3×ATR(14)`, published as
`stop_distance_pct`, negative meaning breached — and a breach is a standard exit,
not a paper loss to sit through. So a name that fell 18% intraday on day two and
closed the week up 3% is scored `+3%` by the panel and would have been `−18%` in
the account.

That is not a small correction and it is not a symmetric one: it flatters
precisely the volatile names, and volatility is what
`bar.garch_vol_expansion` says this month's winners had.

The fix is López de Prado's triple barrier: for each event, walk forward and
record **which barrier is touched first** — the profit target above, the stop
below, or the horizon. The label is the return at that touch, so the path
decides the outcome rather than being averaged out of it.

What this module is not
-----------------------
It does not fit anything, and `meta.py` beside it does not either. Meta-labelling
in the source material is a classifier that sizes bets from a primary model's
signals; here the primary side comes from a pre-registered rule and the sizing
map is a formula, because a fitted sizing model on this sample size is the kind
of search this repository refuses. What is ported is the **labelling**, which is
a measurement, and the CUSUM sampler that decides which days are worth labelling.
"""
from __future__ import annotations

import math
import statistics


def daily_volatility(closes, span=20):
    """EWMA of daily return standard deviation, keyed by index.

    The unit the barriers are set in. A fixed 5% barrier means something
    different for a 12%-vol name and a 130%-vol one, and this book holds both.
    """
    if len(closes) < 2:
        return []
    returns = [closes[index] / closes[index - 1] - 1 for index in range(1, len(closes))]
    decay = 2.0 / (span + 1)
    out = [None]
    mean = returns[0]
    variance = 0.0
    for index, value in enumerate(returns):
        mean = decay * value + (1 - decay) * mean
        deviation = value - mean
        variance = decay * deviation * deviation + (1 - decay) * variance
        out.append(math.sqrt(variance) if index >= span else None)
    return out


def cusum_events(closes, threshold, *, dates=None):
    """Symmetric CUSUM filter: the sessions where something actually happened.

    A signal evaluated every session produces mostly redundant samples — three
    quiet days in a row are one observation dressed as three, and they dominate
    any average taken over them. The filter accumulates log returns in both
    directions and fires when either side crosses `threshold`, resetting that
    side; the result is an event index that is dense in the moving stretches and
    sparse in the flat ones.

    `threshold` is in the same units as a log return, so it is normally set as a
    multiple of `daily_volatility`.
    """
    dates = list(dates or range(len(closes)))
    positive = negative = 0.0
    events = []
    for index in range(1, len(closes)):
        if not closes[index] or not closes[index - 1]:
            continue
        step = math.log(closes[index] / closes[index - 1])
        limit = threshold[index] if isinstance(threshold, list) else threshold
        if limit is None or limit <= 0:
            continue
        positive = max(0.0, positive + step)
        negative = min(0.0, negative + step)
        if positive > limit:
            positive = 0.0
            events.append(dates[index])
        elif negative < -limit:
            negative = 0.0
            events.append(dates[index])
    return events


def chandelier_stop(bars, index, *, lookback=22, atr_window=14, multiple=3.0):
    """The book's own exit rule: `22d high − 3 × ATR(14)`.

    Reimplemented here rather than imported from `decision.signals` because that
    module computes it for the live snapshot from a different bar shape; this one
    has to be evaluable at any historical index, which is what makes the barrier
    path-dependent rather than a level fixed at entry.
    """
    if index < max(lookback, atr_window):
        return None
    highs = [bar['high'] for bar in bars[index - lookback + 1:index + 1]]
    ranges = []
    for position in range(index - atr_window + 1, index + 1):
        previous_close = bars[position - 1]['close']
        bar = bars[position]
        ranges.append(max(bar['high'] - bar['low'],
                          abs(bar['high'] - previous_close),
                          abs(bar['low'] - previous_close)))
    if not ranges:
        return None
    return max(highs) - multiple * statistics.fmean(ranges)


def apply_barriers(bars, entry_index, *, horizon, profit_multiple=2.0,
                   stop_multiple=1.0, volatility=None, side=1,
                   use_chandelier=False):
    """Walk forward from `entry_index` and return the first barrier touched.

    Barriers are set in units of the name's own daily volatility unless
    `use_chandelier` is on, in which case the lower barrier is the book's real
    stop and is **recomputed at every step** — a trailing stop that moves with
    the position is a different rule from a level fixed at entry, and the second
    one is the one that is easy to implement and wrong.

    Intraday touches count. A stop that is only checked at the close is not the
    stop this book runs, and checking it at the close is exactly what turns an
    18% intraday drawdown into a +3% week.
    """
    if entry_index + 1 >= len(bars):
        return None
    entry = bars[entry_index]['close']
    if not entry:
        return None
    unit = volatility if volatility else None
    if unit is None or unit <= 0:
        return None
    upper = entry * (1 + side * profit_multiple * unit)
    lower_fixed = entry * (1 - side * stop_multiple * unit)

    last = min(entry_index + horizon, len(bars) - 1)
    for index in range(entry_index + 1, last + 1):
        bar = bars[index]
        lower = lower_fixed
        if use_chandelier:
            trailing = chandelier_stop(bars, index - 1)
            if trailing is not None:
                lower = max(lower_fixed, trailing) if side > 0 else lower_fixed
        touched_up = bar['high'] >= upper if side > 0 else bar['low'] <= upper
        touched_down = bar['low'] <= lower if side > 0 else bar['high'] >= lower
        if touched_down and touched_up:
            # Both inside one session's range: the bar does not say which came
            # first, so the conservative reading is the adverse one. Guessing the
            # favourable order is how a backtest quietly buys itself an edge.
            return {'barrier': 'stop', 'index': index,
                    'return': side * (lower / entry - 1), 'ambiguous_bar': True}
        if touched_down:
            return {'barrier': 'stop', 'index': index,
                    'return': side * (lower / entry - 1), 'ambiguous_bar': False}
        if touched_up:
            return {'barrier': 'target', 'index': index,
                    'return': side * (upper / entry - 1), 'ambiguous_bar': False}
    close = bars[last]['close']
    return {'barrier': 'horizon', 'index': last,
            'return': side * (close / entry - 1), 'ambiguous_bar': False}


def label_series(bars, *, horizon, profit_multiple=2.0, stop_multiple=1.0,
                 span=20, side=1, use_chandelier=False, entries=None):
    """Triple-barrier labels for every entry, with the counts that read them.

    `barrier_mix` is the part worth publishing beside any average taken over
    these: a label set that is 70% `stop` describes a rule that mostly gets
    stopped out, and its mean return is a summary of that fact rather than of
    the signal's predictive content.
    """
    closes = [bar.get('close') for bar in bars]
    volatilities = daily_volatility(closes, span=span)
    entries = entries if entries is not None else range(len(bars))
    labels = []
    for index in entries:
        if index >= len(volatilities):
            continue
        result = apply_barriers(
            bars, index, horizon=horizon, profit_multiple=profit_multiple,
            stop_multiple=stop_multiple, volatility=volatilities[index],
            side=side, use_chandelier=use_chandelier)
        if result:
            labels.append({'entry_index': index, **result})
    mix = {}
    for label in labels:
        mix[label['barrier']] = mix.get(label['barrier'], 0) + 1
    return {
        'labels': labels,
        'n': len(labels),
        'barrier_mix': mix,
        'ambiguous_bars': sum(1 for label in labels if label['ambiguous_bar']),
        'params': {'horizon': horizon, 'profit_multiple': profit_multiple,
                   'stop_multiple': stop_multiple, 'volatility_span': span,
                   'trailing_stop': use_chandelier},
    }
