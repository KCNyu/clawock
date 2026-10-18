"""Session-volume reversion: completed prior bars, never a rolling VWAP proxy."""
from math import sqrt
from clawock.strategies.plugins.intraday_reversion import Reversion, _number

name = 'intraday-vwap'
inject = ('costs',)


class VWAP(Reversion):
    strategy = name

    def target(self, bars, index):
        history = bars[:index]
        for bar in history:
            _number(bar.get('volume'), 'volume', zero=True)
        volume = sum(b['volume'] for b in history)
        if volume <= 0:
            return None
        prices = [(b['open'] + b['high'] + b['low'] + b['close']) / 4 for b in history]
        mean = sum(p * b['volume'] for p, b in zip(prices, history)) / volume
        sigma = sqrt(sum(b['volume'] * (p-mean)**2 for p, b in zip(prices, history)) / volume)
        if sigma > 0 and bars[index]['close'] > mean + self.params['deviations'] * sigma:
            return mean
        return None


def apply(ctx, config):
    ctx.provide('intraday_vwap', VWAP(ctx.get('costs'), config))
