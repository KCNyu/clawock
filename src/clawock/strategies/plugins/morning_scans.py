"""The `scans` service: every file a scheduled scan leaves for the desk, read one way.

Six JSON files are written by scheduled jobs and read by production paths:
macro, Eastmoney news, the attention scan, the statement radar, the US news
digest and the news evidence graph. Each reader used to open its own path
and decide for itself what a missing or unparseable file meant, and they did
not agree: one said `{}`, one said "loaded" for any file that existed, one
raised. This is the one read.

    document(path) -> {'status': 'ok' | 'missing' | 'unreadable',
                       'payload': dict | None, 'error': str | None}

`path(workspace, name)` is the registry of where each file lives, so a reader
names the scan and not the path. The answer never carries an old payload in
place of a new one: a file that is absent or cannot be parsed has no payload.

Freshness is the reader's question, because the readers differ on purpose: the
brief refuses a scan older than `stale_after_hours`, the intraday lane judges
each source against the session's open. `reading()` is the brief's rule,
shared with `macro()` and `em_news()`, which also do the brief's trimming.
The attention scan and the statement radar keep their own row, `sentiment`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from clawock.market_data.macro import classify_regime

name = 'morning-scans'

FILES = {
    'macro': 'assets/data/macro.json',
    'em_news': 'assets/data/em_news.json',
    'sentiment': 'assets/data/sentiment.json',
    'influencer_feed': 'assets/data/influencer_feed.json',
    'us_news_digest': 'assets/data/us_news_digest.json',
    'news_evidence_graph': 'assets/data/news_evidence_graph.json',
}
STALE_AFTER_HOURS = 36
CLOCK_SKEW_HOURS = 2

OK, MISSING, STALE, UNREADABLE = 'ok', 'missing', 'stale', 'unreadable'


def _out(field, unit, window, missing):
    return {'field': field, 'unit': unit, 'window': window, 'missing': missing}


#: `plugin_host.declarations`.
SIGNAL_SOURCE = {
    'id': 'morning-scans',
    'family': 'sentiment',
    'summary': 'The macro snapshot and the Eastmoney news scan as the brief reads them, and '
               'the one read of every scheduled scan file for the paths that judge freshness '
               'themselves.',
    'inputs': [
        {'name': 'macro.json', 'what': 'VIX, DXY, 10-year yield, Fear & Greed, four indices, Fed releases',
         'source': 'market_data.macro, run off-host by macro-scan'},
        {'name': 'em_news.json', 'what': 'per-holding Chinese news and the market 7x24 feed',
         'source': 'the em-news job, run in the brief preflight and committed with it'},
        {'name': 'the other scan files', 'what': 'attention, statements, US digest, evidence graph',
         'source': 'their own scheduled jobs; read here as documents only'},
    ],
    'outputs': [
        _out('status', 'ok, missing, stale or unreadable', 'this read', 'never null'),
        _out('age_hours', 'hours since the payload\'s generated_at', 'this read',
             'null without a readable stamp, and the reading is then stale'),
        _out('macro.<index>.price', 'index points, or percent for the yield', 'the scan\'s latest print',
             'null when the scan has no row for it'),
        _out('macro.<index>.change_pct', 'percent on the day', 'the scan\'s session',
             'null when the provider gave a close without a day change; the row then names its session'),
        _out('macro.regime', 'risk_on, neutral or risk_off', 'the snapshot', 'classified from what is present'),
        _out('em_news.holdings_news', 'up to 3 dated titles per holding', 'the scan', 'empty when none'),
        _out('em_news.market_724', 'up to 5 dated titles', 'the scan', 'empty when none'),
        _out('em_news.degraded', 'up to 8 source labels that did not answer', 'the scan',
             'absent when every source answered'),
    ],
    'missing': {
        'policy': 'omitted',
        'detail': 'An absent, unparseable, unstamped or too-old file gives an empty reading and a '
                  'status that says which. document() gives no payload for a file it cannot '
                  'parse. Yesterday\'s scan is never served in place of today\'s.',
        'serves_stale': False,
    },
}


def payload_age_hours(payload, now=None):
    stamp = (payload or {}).get('generated_at')
    if not stamp:
        return None
    try:
        at = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
    except ValueError:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - at).total_seconds() / 3600


def _answer(status, reading=None, age=None, **detail):
    return {'status': status, 'reading': reading or {}, 'age_hours': age, 'detail': detail}


class Scans:
    def __init__(self, stale_after_hours):
        self.stale_after_hours = stale_after_hours

    def files(self) -> dict[str, str]:
        return dict(FILES)

    def path(self, workspace, scan: str) -> Path:
        if scan not in FILES:
            raise KeyError(f'no scan named {scan!r}; known: {sorted(FILES)}')
        return Path(workspace) / FILES[scan]

    def document(self, path) -> dict:
        """One scan file as a JSON object, or the reason there is none."""
        try:
            value = json.loads(Path(path).read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {'status': MISSING, 'payload': None, 'error': None}
        except (OSError, ValueError) as exc:
            return {'status': UNREADABLE, 'payload': None, 'error': type(exc).__name__,
                    'message': str(exc)}
        if not isinstance(value, dict):
            return {'status': UNREADABLE, 'payload': None, 'error': 'not an object',
                    'message': f'the file holds a {type(value).__name__}, not an object'}
        return {'status': OK, 'payload': value, 'error': None}

    def is_stale(self, age) -> bool:
        return age is None or age > self.stale_after_hours or age < -CLOCK_SKEW_HOURS

    def _reading(self, workspace, scan, build):
        found = self.document(self.path(workspace, scan))
        if found['status'] == MISSING:
            return _answer(MISSING)
        if found['status'] == UNREADABLE:
            return _answer(UNREADABLE, error=found['error'], message=found['message'])
        age = payload_age_hours(found['payload'])
        if self.is_stale(age):
            return _answer(STALE, age=age)
        try:
            return build(found['payload'], age)
        except Exception as exc:
            return _answer(UNREADABLE, error=type(exc).__name__, message=str(exc))

    def macro(self, workspace) -> dict:
        """The macro snapshot, trimmed for the brief and classified."""
        def build(scan, age):
            def quote(key):
                row = scan.get(key)
                if not row:
                    return None
                out = {'price': row.get('price'), 'change_pct': row.get('change_pct'),
                       'source': row.get('source')}
                # A row without a day change is some session's close, not this
                # morning's print: say which (#2347).
                if row.get('change_pct') is None and isinstance(row.get('as_of'), str):
                    out['session'] = row['as_of']
                return out
            reading = {
                'as_of': scan.get('generated_at'),
                'age_hours': round(age, 1),
                'vix': quote('vix'),
                'dxy': quote('dxy'),
                'treasury_10y_yield_pct': (scan.get('treasury_10y') or {}).get('yield_pct'),
                'fear_greed': scan.get('fear_greed'),
                'hsi': quote('hsi'),
                'hstech': quote('hstech'),
                'spx': quote('spx'),
                'nasdaq': quote('nasdaq'),
                'fed_press': (scan.get('fed_press') or [])[:3],
            }
            reading['regime'] = classify_regime(reading)
            return _answer(OK, reading, age)
        return self._reading(workspace, 'macro', build)

    def em_news(self, workspace) -> dict:
        """Eastmoney's per-holding news and market feed, trimmed for the brief."""
        def build(scan, age):
            reading = {
                'holdings_news': {
                    ticker: {'name': row.get('name'),
                             'items': [{'date': item.get('date'), 'title': item.get('title')}
                                       for item in (row.get('items') or [])[:3]]}
                    for ticker, row in (scan.get('holdings_news') or {}).items()},
                'market_724': [{'date': item.get('date'), 'title': item.get('title')}
                               for item in (scan.get('market_724') or [])[:5]],
                'generated_at': scan.get('generated_at'),
                'age_hours': round(age, 1) if age is not None else None,
            }
            if scan.get('degraded'):
                # Which sources did not answer, for the model to say the layer
                # is thin today.
                reading['degraded'] = list(scan['degraded'])[:8]
            return _answer(OK, reading, age)
        return self._reading(workspace, 'em_news', build)

    def describe(self) -> dict:
        return {'stale_after_hours': self.stale_after_hours, 'files': sorted(FILES)}


def apply(ctx, config):
    hours = config.get('stale_after_hours', STALE_AFTER_HOURS)
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not hours > 0:
        raise ValueError(f'morning-scans stale_after_hours must be a positive number, got {hours!r}')
    ctx.provide('scans', Scans(hours))
