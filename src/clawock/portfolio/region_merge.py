"""Write a refreshed region back without undoing what was written meanwhile.

The quote writers read the book, fetch for up to a minute and a half, then
write their region. Writing the object they read replaced every trade, cash or
realized change another writer landed in that window, silently (#2629).
`overlay` runs inside `safe_io.mutate_json`, on the document re-read under the
lock: when the region is still the one the fetch started from, the refreshed
region is written as is; when it moved, only the leaves the refresh changed are
laid over the newer region and its derived fields are rebuilt from the result.
"""
from __future__ import annotations

import copy

from clawock.portfolio.math import ledger_rows

_MISSING = object()


def _changed(before, after):
    """{key: new value or _MISSING} for every key the refresh touched."""
    return {key: after.get(key, _MISSING) for key in set(before) | set(after)
            if before.get(key, _MISSING) != after.get(key, _MISSING)}


def _apply(target, delta):
    for key, value in delta.items():
        if value is _MISSING:
            target.pop(key, None)
        else:
            target[key] = value


def _rows(region):
    """Holdings keyed by (ticker, nth row of that ticker)."""
    seen, out = {}, {}
    for row in ledger_rows(region.get('holdings')):
        ticker = row.get('ticker')
        nth = seen.get(ticker, 0)
        seen[ticker] = nth + 1
        out[(ticker, nth)] = row
    return out


def _rebuild(doc, key, region):
    from clawock.portfolio import aggregates
    from clawock.portfolio.realized import recompute as recompute_realized
    scoped = {'last_updated': doc.get('last_updated'), 'portfolios': {key: region}}
    recompute_realized(scoped)
    aggregates.recompute(
        scoped, percent_rounding=aggregates.load_policy(aggregates.POLICY),
        price_rounding=aggregates.load_policy(aggregates.POLICY, 'price_rounding_by_book'))


def overlay(doc, key, before, after, *, last_updated=None):
    """The document to write: `after` for region `key`, on top of `doc` as it is now."""
    current = (doc.get('portfolios') or {}).get(key)
    if current == before or not isinstance(current, dict):
        region = after
    else:
        region = copy.deepcopy(current)
        _apply(region, {k: v for k, v in _changed(before, after).items() if k != 'holdings'})
        was, now = _rows(before), _rows(after)
        for identity, row in _rows(region).items():
            if identity in was and identity in now:
                _apply(row, _changed(was[identity], now[identity]))
        doc = {**doc, 'last_updated': last_updated or doc.get('last_updated')}
        _rebuild(doc, key, region)
        print(f'  ⚠ {key} changed on disk during the fetch: quote fields merged '
              f'onto the newer book, totals rebuilt')
    return {**doc, 'last_updated': last_updated or doc.get('last_updated'),
            'portfolios': {**doc.get('portfolios', {}), key: region}}
