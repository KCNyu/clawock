"""RSI as a strategy plugin.

The arithmetic is the `factors` service's Wilder RSI, the one the quant table
already publishes; this plugin adds no second copy of it. What it adds is the
declaration around it: the registered parameters, the grid an optimiser may
search, and an orientation. `signal_panel` scores `rsi14` unsigned because
"is a high RSI momentum or exhaustion?" has no honest prior on this book, so
the direction is a searched parameter here rather than an assumption.
"""
from __future__ import annotations

from clawock.strategies.registry import StrategySpec

name = 'rsi'
inject = ('strategies', 'factors')

DIRECTIONS = {'reversion': -1.0, 'momentum': 1.0}
#: 14-session Wilder RSI read as exhaustion (>70 overbought, <30 oversold):
#: the reading `decision/signals.py` documents.
REGISTERED = {'period': 14, 'direction': 'reversion'}
SPACE = {'period': [5, 7, 9, 14, 21, 28], 'direction': sorted(DIRECTIONS)}


#: `plugin_host.declarations`. The period is a registered parameter, so the
#: window is stated in terms of it.
SIGNAL_SOURCE = {
    'id': 'rsi',
    'family': 'strategy',
    'summary': 'Wilder RSI centred on 50 and signed by a registered direction; '
               'scored by the optimiser, read by no live path.',
    'inputs': [
        {'name': 'bars', 'what': 'daily closes up to and including the signal session, oldest first',
         'source': 'the bars service of the composition (adjusted_bars in the shipped rows)'},
        {'name': 'params', 'what': 'period (sessions) and direction (momentum or reversion)',
         'source': 'row config params; the grid an optimiser may search is row config space'},
    ],
    'outputs': [
        {'field': 'score', 'unit': 'RSI points from 50, -50 to 50; higher is more bullish',
         'window': 'period sessions, Wilder smoothing',
         'missing': 'null below period + 1 closes; the name is then not ranked that session'},
    ],
    'missing': {
        'policy': 'null',
        'detail': 'A name without enough closes scores null and is left out of that '
                  "session's cross-section; a session with too few ranked names is not scored.",
        'serves_stale': False,
    },
}


def _check(params: dict) -> dict:
    period, direction = params.get('period'), params.get('direction')
    if isinstance(period, bool) or not isinstance(period, int) or period < 2:
        raise ValueError(f'rsi period must be an integer >= 2, got {period!r}')
    if direction not in DIRECTIONS:
        raise ValueError(
            f'rsi direction must be one of {sorted(DIRECTIONS)}, got {direction!r}')
    return {'period': period, 'direction': direction}


def scorer(factors):
    def score(bars, params):
        value = factors.rsi([bar['close'] for bar in bars], params['period'])
        if value is None:
            return None
        return DIRECTIONS[params['direction']] * (value - 50.0)
    return score


def apply(ctx, config):
    params = _check({**REGISTERED, **(config.get('params') or {})})
    space = {**SPACE, **(config.get('space') or {})}
    for period in space['period']:
        for direction in space['direction']:
            _check({'period': period, 'direction': direction})
    spec = StrategySpec(
        name='rsi', params=params, space=space, score=scorer(ctx.get('factors')),
        description='Wilder RSI centred on 50, signed by direction')
    ctx.effect(lambda: ctx.get('strategies').register(spec), 'strategy(rsi)')
