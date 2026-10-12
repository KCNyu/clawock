"""The `bars` service over the settled daily store (`memory/bars`).

That store is raw and never adjusted — it exists so the ledger can settle
historical trigger prices — and this plugin says so in `describe()` instead of
presenting it as a research-grade series. A plugin over an adjusted source would
provide the same service name and nothing downstream would change.
"""
from __future__ import annotations

from clawock.evidence import run_card
from clawock.market_data import bars as bar_store
from clawock.market_data.daily_prices import clean_bars

name = 'ledger-bars'


class LedgerBars:
    def __init__(self, tickers=None):
        self._only = set(tickers) if tickers else None
        self._docs: dict[str, dict] = {}

    def _doc(self, ticker: str) -> dict:
        if ticker not in self._docs:
            self._docs[ticker] = bar_store.load_bars(ticker)
        return self._docs[ticker]

    def tickers(self) -> list[str]:
        stored = sorted(path.stem for path in bar_store.BARS_DIR.glob('*.json'))
        return [ticker for ticker in stored
                if self._only is None or ticker in self._only]

    def series(self, ticker: str) -> list[dict]:
        """Completed sessions, oldest first, malformed rows dropped."""
        rows = [dict(bar, date=day)
                for day, bar in sorted((self._doc(ticker).get('bars') or {}).items())]
        return clean_bars(rows)

    def describe(self) -> dict:
        tickers = self.tickers()
        adjustments = sorted({str(self._doc(ticker).get('adjustment') or 'unknown')
                              for ticker in tickers})
        return {
            'source': 'memory/bars',
            'tickers': len(tickers),
            'adjustment': adjustments[0] if len(adjustments) == 1 else adjustments,
            'corporate_actions_adjusted': adjustments == ['qfq'],
            'digest': run_card.series_digest(
                (f'{ticker}:{bar["date"]}', bar['close'])
                for ticker in tickers for bar in self.series(ticker)),
        }


def apply(ctx, config):
    ctx.provide('bars', LedgerBars(config.get('tickers')))
