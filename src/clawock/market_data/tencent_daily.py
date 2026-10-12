"""Tencent dated daily closes with one malformed-row policy."""
from datetime import date

import requests

from .daily_prices import clean_bars, positive_price

TENCENT = 'https://web.ifzq.gtimg.cn/appstock/app/kline/kline'


def parse_daily_closes(rows):
    """Skip unusable close cells; keep the provider's dates and valid closes."""
    out = []
    for row in rows:
        try:
            close = positive_price(row[2])
            if close is not None:
                out.append((row[0], close))
        except (IndexError, ValueError, TypeError, KeyError):
            continue
    return out


def parse_daily_bars(rows):
    """Tencent [date, open, close, high, low, ...] using the daily-price policy."""
    out = []
    for row in rows:
        try:
            out.append({'date': row[0], 'open': row[1], 'close': row[2],
                        'high': row[3], 'low': row[4]})
        except (IndexError, ValueError, TypeError, KeyError):
            continue
    return clean_bars(out)


def fetch_hk_daily_closes(sym, start, end=None, lim=2000, *, headers=None,
                          adjusted_first=False):
    """Return dated HK closes; transport errors propagate to the caller."""
    end = end or date.today().isoformat()
    url = f'{TENCENT}?param={sym},day,{start},{end},{lim}'
    kwargs = {'timeout': 20}
    if headers is not None:
        kwargs['headers'] = headers
    payload = requests.get(url, **kwargs).json()
    node = (payload.get('data') or {}).get(sym, {})
    keys = ('qfqday', 'day') if adjusted_first else ('day', 'qfqday')
    return parse_daily_closes(node.get(keys[0]) or node.get(keys[1]) or [])


TENCENT_ADJUSTED = 'https://web.ifzq.gtimg.cn/appstock/app/{market}fqkline/get'

#: What one answer says about corporate actions. Read from the answer, never
#: assumed from the request.
ADJUSTED = 'adjusted'
NO_ACTION_ON_RECORD = 'no_action_on_record'
UNCONFIRMED = 'unconfirmed'


def _action(row):
    """The provider's corporate-action slot on one row, or None when absent."""
    return row[6] if isinstance(row, list) and len(row) > 6 and isinstance(row[6], dict) else None


def fetch_daily_with_basis(sym, count=800, *, headers=None):
    """(bars, basis, actions) from the per-market forward-adjusted endpoint.

    Request, checked against live answers on 2026-10-12:
    https://web.ifzq.gtimg.cn/appstock/app/usfqkline/get?param=usTQQQ.OQ,day,,,400,qfq
    https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?param=hk02208,day,,,400,qfq
    The answer is `data[sym]` with the series under one of two keys, and each
    row is `[date, open, close, high, low, volume, <action>, ...]`:

    * `qfqday`: forward-adjusted. US rows have six cells, seven on a session
      with an action (`{"FHcontent": "每股分配0.198美元", "hgcgContent":
      "每1股拆分成2股", "cqr": "2025-11-20"}`: dividend text, split text,
      ex-date). HK rows have nine cells and carry the slot on every row. US
      history is scaled by a ratio; HK history has the dividend subtracted.
    * `day`: raw prices. The provider answers this way for a name it has no
      action for, and then every row carries the slot, empty (`{}`; eleven
      cells, nine on some HK names).

    Hence the three bases:

    * `adjusted`: sent under `qfqday`.
    * `no_action_on_record`: sent under `day`, every row carries the action
      slot and every slot is empty. The provider's own action record for the
      window is empty, so the raw series is the adjusted one. This is one
      provider's record, not an independent confirmation.
    * `unconfirmed`: sent under `day` with rows that lack the slot, or with an
      action on record that the series was not adjusted for.

    The market-less `fqkline/get` path answers the same request under `day`
    with raw prices even for a name that split, which is why it is not used.
    Transport errors propagate.
    """
    market = sym[:2]
    if market not in ('hk', 'us'):
        raise ValueError(f'no adjusted daily endpoint for {sym!r}')
    url = f'{TENCENT_ADJUSTED.format(market=market)}?param={sym},day,,,{count},qfq'
    kwargs = {'timeout': 20}
    if headers is not None:
        kwargs['headers'] = headers
    payload = requests.get(url, **kwargs).json()
    node = (payload.get('data') or {}).get(sym) or {}
    if not isinstance(node, dict):
        node = {}
    adjusted = bool(node.get('qfqday'))
    rows = node.get('qfqday') or node.get('day') or []
    actions = [{'date': row[0], 'dividend': str(slot.get('FHcontent') or ''),
                'split': str(slot.get('hgcgContent') or '')}
               for row in rows for slot in (_action(row),) if slot]
    if adjusted:
        basis = ADJUSTED
    elif rows and not actions and all(_action(row) is not None for row in rows):
        basis = NO_ACTION_ON_RECORD
    else:
        basis = UNCONFIRMED
    return parse_daily_bars(rows), basis, actions


def fetch_adjusted_daily_bars(sym, count=800, *, headers=None):
    """(bars, adjusted): `adjusted` is True only for a `qfqday` answer."""
    bars, basis, _ = fetch_daily_with_basis(sym, count, headers=headers)
    return bars, basis == ADJUSTED
