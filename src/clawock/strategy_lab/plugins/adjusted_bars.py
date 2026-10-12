"""The `bars` service over forward-adjusted daily bars.

`memory/bars` is raw by contract: it settles historical trigger prices, and a
trigger is a nominal price. A return computed across a split or a dividend on
that store is the corporate action, not the market, which is why the registered
gate refuses any proposal measured on it. This plugin provides the same service
from Tencent's forward-adjusted daily series, for the same names.

What it claims, and how it knows
--------------------------------
`corporate_actions_adjusted` is true only when every series it serves arrived
under the provider's `qfqday` key. A name answered under `day` is left out and
listed: the provider does that both for a name with no corporate action on
record and for one it did not adjust, and nothing in the answer tells the two
apart. A name it did not answer is left out the same way, so the claim is never
an average over a mix.

The series is fetched per run and not stored, so two runs can see different
bars: a forward adjustment rewrites history every time a name pays a dividend.
`describe()` carries a digest of exactly what was served, and each name is cut
at its last session in `memory/bars`, which never holds an unfinished one.

`differs_from_raw` counts the names whose adjusted closes depart from the
settled raw closes over the sessions both hold: the names for which the choice
of source changed the input at all.
"""
from __future__ import annotations

from clawock.evidence import run_card
from clawock.market_data import bars as bar_store
from clawock.market_data import tencent_daily

name = 'adjusted-bars'

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/121.0 Safari/537.36')
#: Closes within this ratio are the same price; the provider prints 2-3 decimals.
SAME_PRICE = 5e-4


def _fetch(symbol: str, count: int):
    return tencent_daily.fetch_adjusted_daily_bars(
        symbol, count, headers={'User-Agent': UA})


class AdjustedBars:
    def __init__(self, tickers=None, *, sessions=800, fetch=_fetch):
        self._only = set(tickers) if tickers else None
        self._sessions, self._fetch = sessions, fetch
        self._loaded: dict[str, list[dict]] | None = None
        self._legs: dict[str, str] = {}
        self._left_out: dict[str, str] = {}
        self._differs = 0

    def _load(self) -> dict[str, list[dict]]:
        if self._loaded is not None:
            return self._loaded
        self._loaded = {}
        for path in sorted(bar_store.BARS_DIR.glob('*.json')):
            ticker = path.stem
            if self._only is not None and ticker not in self._only:
                continue
            doc = bar_store.load_bars(ticker)
            settled = doc.get('bars') or {}
            if doc.get('retired') or not doc.get('tencent') or not settled:
                self._left_out[ticker] = 'retired or not in the settled store'
                continue
            try:
                rows, adjusted = self._fetch(doc['tencent'], self._sessions)
            except Exception as exc:  # one name's outage must not pass as coverage
                self._left_out[ticker] = f'fetch failed: {type(exc).__name__}'
                continue
            if not adjusted:
                self._left_out[ticker] = 'provider sent no adjusted series'
                continue
            last = max(settled)
            rows = [bar for bar in rows if bar['date'] <= last]
            if not rows:
                self._left_out[ticker] = 'no adjusted session up to the settled store'
                continue
            self._loaded[ticker] = rows
            self._legs[ticker] = str(doc.get('leg') or '')
            self._differs += any(
                bar['date'] in settled
                and abs(bar['close'] / settled[bar['date']]['close'] - 1) > SAME_PRICE
                for bar in rows)
        return self._loaded

    def tickers(self) -> list[str]:
        return sorted(self._load())

    def series(self, ticker: str) -> list[dict]:
        """Completed sessions, oldest first, forward-adjusted."""
        return self._load()[ticker]

    def leg(self, ticker: str) -> str:
        self._load()
        return self._legs.get(ticker, '')

    def describe(self) -> dict:
        loaded = self._load()
        return {
            'source': 'tencent forward-adjusted daily (qfq), cut at memory/bars',
            'tickers': len(loaded),
            'adjustment': 'qfq',
            'corporate_actions_adjusted': bool(loaded),
            'left_out': dict(sorted(self._left_out.items())),
            'differs_from_raw': self._differs,
            'digest': run_card.series_digest(
                (f'{ticker}:{bar["date"]}', bar['close'])
                for ticker in sorted(loaded) for bar in loaded[ticker]),
        }


def apply(ctx, config):
    ctx.provide('bars', AdjustedBars(
        config.get('tickers'), sessions=int(config.get('sessions') or 800)))
