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
`macro()` adds the trading calendar: a snapshot whose newest index close in a
market is older than that market's latest completed session is stale however
few hours old it is (#2988). 36 hours is longer than a trading day, so the
wall clock alone handed the brief yesterday's closes as today's.
The attention scan and the statement radar keep their own row, `sentiment`.
"""
from __future__ import annotations

import math

import json
from datetime import date, datetime
from pathlib import Path

from clawock.sessions import latest_completed_session, market_tz

from clawock.strategies.freshness import (
    DEFAULT_STALE_AFTER_HOURS, is_stale, payload_age_hours,
)

from clawock.market_data.macro import classify_regime, quote_status, QUOTE_SYMBOLS

name = 'morning-scans'

FILES = {
    'macro': 'assets/data/macro.json',
    'em_news': 'assets/data/em_news.json',
    'sentiment': 'assets/data/sentiment.json',
    'influencer_feed': 'assets/data/influencer_feed.json',
    'us_news_digest': 'assets/data/us_news_digest.json',
    'news_evidence_graph': 'assets/data/news_evidence_graph.json',
}

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
        {'field': 'detail', 'unit': 'object with error and message for unreadable input', 'window': 'this read', 'missing': 'empty object otherwise'},
        {'field': 'document.payload',
         'unit': 'unmodified JSON object; document performs no freshness judgment',
         'window': 'file at read time; downstream reader owns freshness',
         'missing': 'null on missing/unreadable, with status/error/message'},
        {'field': 'document.error / document.message',
         'unit': 'error label and explanatory text',
         'window': 'this read',
         'missing': 'error null when ok/missing; message absent then'},
        {'field': 'macro.as_of / em_news.generated_at', 'unit': 'ISO producer timestamp', 'window': 'scan time', 'missing': 'reading omitted if absent/unreadable'},
        {'field': 'macro.age_hours / em_news.age_hours', 'unit': 'hours rounded to 0.1', 'window': 'since generated_at', 'missing': 'reading omitted if age unknown'},
        {'field': 'macro.<index>.source / session',
         'unit': 'source label and ISO session date read off the row\'s own as_of in its '
                 'market\'s time',
         'window': 'latest source quote',
         'missing': 'source null if absent; session absent on DXY and on rows without a '
                    'readable as_of'},
        {'field': 'macro.treasury_10y_yield_pct', 'unit': 'percent yield', 'window': 'scan latest 10-year Treasury observation', 'missing': 'null'},
        {'field': 'macro.fear_greed',
         'unit': 'object {score: index 0-100, rating: text, as_of: ISO timestamp, '
                 'prev_close/prev_1_week: index points at prior close/week}',
         'window': 'latest CNN observation',
         'missing': 'null'},
        {'field': 'macro.fed_press', 'unit': 'at most 3 {title, date, url} release records', 'window': '7 days before producer scan', 'missing': 'empty list'},
        _out('macro.treasury_curve', '14 percent par yields, same-date 10Y-2Y/3M spreads in bps, source/date',
             'latest Treasury publication; max 7 calendar days; may lag equity session', 'null when unavailable/stale'),
        _out('macro.coverage', 'per-series ok/unavailable/invalid/unknown_date/invalid_date/stale',
             'rechecked at read time for new producer snapshots', 'absent on legacy snapshots'),
        _out('macro.volatility', 'VIX/VIX9D/VIX3M/SKEW daily closes with source, URL and as_of',
             'latest completed US session', 'null per missing or stale series'),
        _out('macro.volatility_term_structure', 'same-session VIX / VIX3M ratio with as_of',
             'latest completed US session; descriptive only', 'null unless both closes exist'),
        {'field': 'macro.regime.score',
         'unit': 'integer sum of three directional checks, -3 to 3',
         'window': 'current F&G, VIX and paired SPX/Nasdaq day changes',
         'missing': 'parent null when no directional check contributes'},
        {'field': 'macro.regime.reasons', 'unit': 'list of text naming contributing checks', 'window': 'snapshot', 'missing': 'parent null without a contributing check'},
        {'field': 'em_news.holdings_news.<ticker>.name', 'unit': 'instrument display name', 'window': 'scan universe', 'missing': 'null'},
        {'field': 'em_news.holdings_news.<ticker>.items[].date / title',
         'unit': 'publication date string and title',
         'window': 'up to 3 scan results per holding',
         'missing': 'empty items list'},
        {'field': 'em_news.market_724[].date / title', 'unit': 'publication date string and title', 'window': 'up to 5 scan results', 'missing': 'empty list'},
        _out('detail.stale_after_hours', 'hours', 'this stale read',
             'present on stale results; the configured cutoff used for this decision'),
        _out('detail.sessions_behind',
             'per market {session, expected}: newest index close vs latest completed session',
             'this stale macro read',
             'present only when a market\'s index rows close before its latest completed '
             'session'),
        _out('status', 'ok, missing, stale or unreadable', 'this read', 'never null'),
        _out('age_hours', 'hours since the payload\'s generated_at', 'this read',
             'null without a readable stamp, and the reading is then stale'),
        _out('macro.<index>.price', 'index points (VIX, DXY, HSI, HSTECH, SPX, Nasdaq)', 'the scan\'s latest print',
             'null when the scan has no row for it'),
        _out('macro.<index>.change_pct', 'percent on the day', 'the scan\'s session',
             'null when the provider gave a close without a day change; the row then names its session'),
        _out('macro.regime.label', 'risk_on, neutral or risk_off', 'the snapshot', 'parent null when no directional check contributes'),
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


def _answer(status, reading=None, age=None, **detail):
    return {'status': status, 'reading': reading or {}, 'age_hours': age, 'detail': detail}


#: The market whose session each index row closes on. DXY trades around the
#: clock, so its stamp names no session and it carries none.
INDEX_MARKETS = {'hsi': 'hk', 'hstech': 'hk', 'vix': 'us', 'spx': 'us', 'nasdaq': 'us'}


def row_session(key, row) -> date | None:
    """The session an index row's own `as_of` names: an ISO date as written, an
    epoch read as a date in the row's market time."""
    if key not in INDEX_MARKETS:
        return None
    stamp = row.get('as_of') if isinstance(row, dict) else None
    if isinstance(stamp, str):
        try:
            return date.fromisoformat(stamp[:10])
        except ValueError:
            return None
    if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) and math.isfinite(stamp):
        try:
            return datetime.fromtimestamp(stamp, market_tz(INDEX_MARKETS[key])).date()
        except (OverflowError, OSError, ValueError):
            return None
    return None


def sessions_behind(scan, at=None) -> dict:
    """Markets whose newest index close predates their latest completed session.

    A market with no dated index row is not judged here; the wall-clock cutoff
    still applies to the whole file.
    """
    behind = {}
    for market in ('hk', 'us'):
        seen = [row_session(key, scan.get(key)) for key, home in INDEX_MARKETS.items()
                if home == market]
        seen = [day for day in seen if day is not None]
        expected = latest_completed_session(market, at) if seen else None
        if expected is not None and max(seen) < expected:
            behind[market] = {'session': max(seen).isoformat(), 'expected': expected.isoformat()}
    return behind


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
        return is_stale(age, self.stale_after_hours)

    def _reading(self, workspace, scan, build, behind=None, at=None):
        found = self.document(self.path(workspace, scan))
        if found['status'] == MISSING:
            return _answer(MISSING)
        if found['status'] == UNREADABLE:
            return _answer(UNREADABLE, error=found['error'], message=found['message'])
        age = payload_age_hours(found['payload'], at)
        if self.is_stale(age):
            return _answer(STALE, age=age, stale_after_hours=self.stale_after_hours)
        lagging = behind(found['payload'], at) if behind else None
        if lagging:
            return _answer(STALE, age=age, stale_after_hours=self.stale_after_hours,
                           sessions_behind=lagging)
        try:
            return build(found['payload'], age)
        except Exception as exc:
            return _answer(UNREADABLE, error=type(exc).__name__, message=str(exc))

    def macro(self, workspace, at=None) -> dict:
        """The macro snapshot, trimmed for the brief and classified."""
        def build(scan, age):
            scan = dict(scan)
            # New producers carry per-series health. Recheck at consumption:
            # a fresh file or SPX row must not make yesterday's VIX current.
            coverage = {}
            if 'coverage' in scan:
                coverage = {key: quote_status(key, scan.get(key), at=at) for key in QUOTE_SYMBOLS}
                for key, status in coverage.items():
                    if status != 'ok':
                        scan[key] = None
            volatility = {}
            for key, row in (scan.get('volatility') or {}).items():
                status = quote_status(key, row, at=at)
                coverage[f'volatility.{key}'] = status
                volatility[key] = row if status == 'ok' else None
            from clawock.market_data.cboe import term_structure

            def quote(key):
                row = scan.get(key)
                if not row:
                    return None
                out = {'price': row.get('price'), 'change_pct': row.get('change_pct'),
                       'source': row.get('source')}
                # Every index row names the session it closes on (#2347, #2988).
                session = row_session(key, row)
                if session is not None:
                    out['session'] = session.isoformat()
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
            from clawock.market_data.treasury import observation_status
            curve = scan.get('treasury_curve')
            if 'treasury_curve' in scan:
                status = observation_status((curve or {}).get('as_of'), at=at)
                coverage['treasury_curve'] = status
                reading['treasury_curve'] = curve if status == 'ok' else None
            if coverage:
                reading['coverage'] = coverage
            if volatility:
                reading['volatility'] = volatility
                reading['volatility_term_structure'] = term_structure(volatility.get('vix'), volatility.get('vix3m'))
            reading['regime'] = classify_regime(reading)
            return _answer(OK, reading, age)
        return self._reading(workspace, 'macro', build, behind=sessions_behind, at=at)

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
    hours = config.get('stale_after_hours', DEFAULT_STALE_AFTER_HOURS)
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not math.isfinite(hours) or not hours > 0:
        raise ValueError(f'morning-scans stale_after_hours must be a positive number, got {hours!r}')
    ctx.provide('scans', Scans(hours))
