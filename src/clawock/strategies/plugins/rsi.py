"""RSI as a strategy plugin.

The arithmetic is `decision.signals._rsi14`, the Wilder RSI the quant table
already publishes; this plugin adds no second copy of it. What it adds is the
declaration around it: the registered parameters, the grid an optimiser may
search, and an orientation. `signal_panel` scores `rsi14` unsigned because
"is a high RSI momentum or exhaustion?" has no honest prior on this book, so
the direction is a searched parameter here rather than an assumption.
"""
from __future__ import annotations

from clawock.decision import signals
from clawock.strategies.registry import StrategySpec

name = 'rsi'
inject = ('strategies',)

DIRECTIONS = {'reversion': -1.0, 'momentum': 1.0}
#: 14-session Wilder RSI read as exhaustion (>70 overbought, <30 oversold):
#: the reading `decision/signals.py` documents.
REGISTERED = {'period': 14, 'direction': 'reversion'}
SPACE = {'period': [5, 7, 9, 14, 21, 28], 'direction': sorted(DIRECTIONS)}


def _check(params: dict) -> dict:
    period, direction = params.get('period'), params.get('direction')
    if isinstance(period, bool) or not isinstance(period, int) or period < 2:
        raise ValueError(f'rsi period must be an integer >= 2, got {period!r}')
    if direction not in DIRECTIONS:
        raise ValueError(
            f'rsi direction must be one of {sorted(DIRECTIONS)}, got {direction!r}')
    return {'period': period, 'direction': direction}


def score(bars, params):
    value = signals._rsi14([bar['close'] for bar in bars], params['period'])
    if value is None:
        return None
    return DIRECTIONS[params['direction']] * (value - 50.0)


def apply(ctx, config):
    params = _check({**REGISTERED, **(config.get('params') or {})})
    space = {**SPACE, **(config.get('space') or {})}
    for period in space['period']:
        for direction in space['direction']:
            _check({'period': period, 'direction': direction})
    spec = StrategySpec(
        name='rsi', params=params, space=space, score=score,
        description='Wilder RSI centred on 50, signed by direction')
    ctx.effect(lambda: ctx.get('strategies').register(spec), 'strategy(rsi)')
