"""Downside Donchian continuation using inventory, not a short sale or new long."""
from clawock.strategies.plugins.intraday_reversion import Reversion

name = 'intraday-breakout'
inject = ('costs',)


class Breakout(Reversion):
    strategy = name

    def target(self, bars, index):
        history = bars[index-self.params['window']:index]
        bottom = min(b['low'] for b in history)
        width = max(b['high'] for b in history) - bottom
        close = bars[index]['close']
        target = close - width
        if width > 0 and close < bottom and target > 0:
            return target
        return None


def apply(ctx, config):
    ctx.provide('intraday_breakout', Breakout(ctx.get('costs'), config))
