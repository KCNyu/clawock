"""The `daily_bars` service: the daily series the live factor row is computed on.

Every live reader of `decision.signals.fetch_bars` gets its bars here: the
quant refresh, both intraday radars, the provisional setups, the watch list,
the strategy escalations, and `evaluate-add-shapes --source tencent`.

Config: `adjustment`.

* `qfq` (shipped): Tencent's per-market forward-adjusted endpoint,
  `{hk,us}fqkline/get`. The answer's shape and what each key means are written
  down at `market_data.tencent_daily.fetch_daily_with_basis`. A name the
  provider has no corporate action for is answered raw, which is the same
  series. A name answered raw without that record is still served, because the
  factor row has no better series for it, and named on stderr.
* `raw`: the two requests this module made before 2026-10-12, unchanged.
  Neither returns adjusted prices: `kline/kline` is raw by design, and the
  market-less `fqkline/get` answers a `qfq` request under `day`. Setting the
  row back to `raw` is the rollback.

A failed request is an empty list with a stderr reason. The quant refresh
publishes an explicit missing row, without copying previous measurements.
"""
from __future__ import annotations

import sys

import requests

from clawock import sessions as trading_calendar
from clawock.market_data import tencent_daily

name = 'daily-bars'

ADJUSTMENTS = ('qfq', 'raw')
TENCENT = 'https://web.ifzq.gtimg.cn/appstock/app/kline/kline'
TENCENT_FQ = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/121.0 Safari/537.36')


def _raw(code, cnt):
    today = trading_calendar.hkt_today().isoformat()
    if code.startswith('hk'):
        url = f'{TENCENT}?param={code},day,2024-01-01,{today},{cnt}'
    else:
        url = f'{TENCENT_FQ}?param={code},day,,,{cnt},qfq'
    d = requests.get(url, headers={'User-Agent': UA}, timeout=20).json()
    node = (d.get('data') or {}).get(code, {})
    return tencent_daily.parse_daily_bars(node.get('qfqday') or node.get('day') or [])


def _qfq(code, cnt):
    bars, basis, actions = tencent_daily.fetch_daily_with_basis(
        code, cnt, headers={'User-Agent': UA})
    if bars and basis == tencent_daily.UNCONFIRMED:
        print(f'  warn: {code} answered raw without an empty action record '
              f'({len(actions)} action(s) on record); served unadjusted', file=sys.stderr)
    return bars


class DailyBars:
    def __init__(self, adjustment: str):
        self.adjustment = adjustment
        self._fetch = _qfq if adjustment == 'qfq' else _raw

    def fetch(self, code, cnt=400):
        """Completed and current daily bars, oldest first; [] when the request fails."""
        try:
            return self._fetch(code, cnt)
        except Exception as e:
            print(f'  warn: {code} fetch failed: {e}', file=sys.stderr)
            return []

    def describe(self) -> dict:
        return {'adjustment': self.adjustment}


SIGNAL_SOURCE = {'id': 'daily-bars',
 'family': 'technical',
 'summary': 'Daily OHLCV input adapter; no trading permission.',
 'inputs': [{'name': 'provider',
             'what': 'daily OHLCV series',
             'source': 'Tencent per-market qfq or raw endpoint selected by row adjustment'}],
 'outputs': [{'field': 'bars[].date',
              'unit': 'ISO session date',
              'window': 'oldest first, requested cnt (default 400); may include current '
                        'candle',
              'missing': 'no row when fetch fails'},
             {'field': 'bars[].open / high / low / close',
              'unit': 'quote-currency price; qfq or raw basis per config, unconfirmed raw '
                      'basis named on stderr',
              'window': 'each daily candle',
              'missing': 'invalid price rows dropped; failed fetch is empty list with stderr '
                         'reason'},
             {'field': 'bars[].volume',
              'unit': 'not supplied by this adapter',
              'window': 'daily candle',
              'missing': 'always omitted; adapter returns OHLC only'}],
 'missing': {'policy': 'omitted',
             'detail': 'Failed fetch returns [] with stderr reason; caller must not reuse old '
                       'numbers.',
             'serves_stale': False}}


def apply(ctx, config):
    adjustment = config.get('adjustment', 'qfq')
    if adjustment not in ADJUSTMENTS:
        raise ValueError(f'daily-bars adjustment must be one of {ADJUSTMENTS}, got {adjustment!r}')
    ctx.provide('daily_bars', DailyBars(adjustment))
