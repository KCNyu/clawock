"""Live free news and disclosure sources, for any harness that wants them.

docs/architecture/harness.md § Live information sources. kcn 2026-09-26: live
news is wanted wherever a judgment is written — the intraday slot, the morning
brief, the close report — and the logic that fetches it must not live inside
any one of them. This module is that logic; the harnesses only choose sources,
limits and labels and decide what reaches their model.

Three layers, kept apart:

* **Adapters** (`SOURCES[...].adapter`) — one request each through the `http`
  seam, answering raw rows. Access and parsing live in
  `market_data.primary_disclosures` (HKEXnews, EDGAR full-text search),
  `market_data.live_news` (Google News, Yahoo Finance RSS, 同花顺 7×24) and
  `market_data.eastmoney_news` (东财 7×24); nothing here parses a feed.
* **Normalisation** (`normalize`) — every row becomes
  `{source, grade, title, published_at | filed_date, url, publisher, signal,
  stale, cite}`: the publisher's own time, a grade from the source's class,
  exchange/regulator noise dropped through `config/filing-triage.json`, and a
  cite that says whether the item came out after `fresh_since` or before it.
* **Trimming** (`summarize`) — a bounded per-ticker view for a core packet; the
  caller keeps the whole of `collect()['tickers']` for its reference layer.

Everything that costs time or requests is a parameter (`Limits`): per-request
timeout, a wall-clock budget for the whole call, per-source concurrency, a
per-source request budget and a cache TTL. Nothing waits past the budget: a
source still running then is reported `timeout`, and a source that fails is
reported by name in `degraded` — not fetched is never "no news".

Adding a source: an adapter in `market_data`, one `Source` row in `SOURCES`,
its planning rule in `plan()`, and a row in the source table of
docs/architecture/intraday-agent.md §6 (plus harness.md if a harness starts or
stops using it).
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timezone
from pathlib import Path

from clawock.safe_io import safe_write_json
from clawock.sessions import ET, HKT


def parse_time(value):
    """Aware datetime from an ISO string, epoch number or None."""
    if value in (None, ''):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    text = str(value).replace('Z', '+00:00')
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    # Producers without an offset (us_news_digest) write host time, HKT.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=HKT)


def session_open(market, now):
    """When the current session opened (09:30 local), as an aware datetime."""
    zone = ET if market == 'us' else HKT
    local = now.astimezone(zone)
    return datetime.combine(local.date(), dtime(9, 30), tzinfo=zone)


def last_close(market, now):
    """The close (16:00 local) of the latest completed session before `now`."""
    from clawock import sessions  # noqa: PLC0415

    zone = ET if market == 'us' else HKT
    day = sessions.latest_completed_session(market, now)
    if day is None:
        return session_open(market, now)
    return datetime.combine(day, dtime(16, 0), tzinfo=zone)


# ── Parameters ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Limits:
    """What one `collect()` may spend. Every harness passes its own."""
    timeout_s: float = 6
    # 同花顺 answers this host in 2–8 s (10 runs 2026-09-26; 3/5 inside 6 s).
    source_timeout_s: dict = field(default_factory=lambda: {'ths_724': 10})
    budget_s: float = 12
    ttl_s: float = 20 * 60
    workers: int = 8
    per_source_concurrency: int = 4
    request_budget: dict = field(default_factory=lambda: {
        'hkexnews': 3, 'sec_fulltext': 1, 'google_news': 8, 'yahoo_rss': 6,
        'ths_724': 1, 'em_724': 1})


@dataclass(frozen=True)
class Labels:
    """How a cite says which side of `fresh_since` an item is on."""
    fresh: str = '盘中实时'
    stale: str = '开盘前旧闻'
    same_day_no_time: str = '今日提交、时刻未知'


INTRADAY_LABELS = Labels()
BRIEF_LABELS = Labels(fresh='上次收盘后', stale='上次收盘前旧闻',
                      same_day_no_time='今日提交、时刻未知')


# ── Layer 1: adapters ─────────────────────────────────────────────────────────

def _json_http(http, timeout):
    return lambda url, headers=None, **_k: json.loads(http(url, headers=headers, timeout=timeout))


def _text_http(http):
    return lambda url, timeout: http(url, timeout=timeout)


def _hkexnews(request, *, http, timeout, now, window_minutes, limits):
    from clawock.market_data import primary_disclosures  # noqa: PLC0415

    items, note, _pages = primary_disclosures.fetch_hkexnews_latest(
        request['args'][0], now=now, window_minutes=window_minutes,
        http=_json_http(http, timeout), max_pages=limits.request_budget.get('hkexnews', 1))
    if note:
        raise RuntimeError(note)
    return items


def _sec_fulltext(request, *, http, timeout, now, window_minutes, limits):
    from clawock.market_data import primary_disclosures  # noqa: PLC0415

    items, note = primary_disclosures.fetch_sec_fulltext(
        request['args'][0], now=now, lookback_days=max(1, -(-window_minutes // 1440)),
        http=_json_http(http, timeout))
    if note:
        raise RuntimeError(note)
    return items


def _google_news(request, *, http, timeout, **_k):
    from clawock.market_data import live_news  # noqa: PLC0415

    query, language = request['args']
    return live_news.google_news(query, language=language, http=_text_http(http),
                                 timeout=timeout)


def _yahoo_rss(request, *, http, timeout, **_k):
    from clawock.market_data import live_news  # noqa: PLC0415

    return live_news.yahoo_headlines(request['args'][0], http=_text_http(http), timeout=timeout)


def _ths_724(request, *, http, timeout, **_k):
    from clawock.market_data import live_news  # noqa: PLC0415

    return live_news.ths_flashes(http=_text_http(http), timeout=timeout)


def _em_724(request, **_k):
    # Every live Eastmoney call goes through its own throttled gateway, not the
    # `http` seam; rows keep Eastmoney's shape for `intraday_information`.
    from clawock.market_data import eastmoney_news  # noqa: PLC0415

    return eastmoney_news.em_fast_news(limit=20) or []


@dataclass(frozen=True)
class Source:
    label: str
    grade: str            # primary | authoritative | soft
    markets: tuple
    scope: str            # book | issuer | theme | market
    adapter: object


SOURCES = {
    'hkexnews': Source('HKEXnews披露易', 'primary', ('hk',), 'book', _hkexnews),
    'sec_fulltext': Source('SEC全文检索', 'primary', ('us',), 'book', _sec_fulltext),
    'google_news': Source('Google新闻', 'soft', ('hk', 'us'), 'issuer', _google_news),
    # Yahoo's HK symbols answered with 2025 headlines (2208.HK) or nothing (the
    # ETFs) on 2026-09-26: US only.
    'yahoo_rss': Source('Yahoo财经', 'soft', ('us',), 'issuer', _yahoo_rss),
    'ths_724': Source('同花顺7×24', 'soft', ('hk', 'us'), 'market', _ths_724),
    'em_724': Source('东财7×24', 'soft', ('hk', 'us'), 'market', _em_724),
}
MARKET_FEEDS = ('ths_724', 'em_724')


# ── Planning ──────────────────────────────────────────────────────────────────

def plan(market, tickers, *, targets, names, sources=None):
    """The requests one call makes, each with the tickers its answer belongs to.

    Asked per issuer and per index theme, not per holding: RKLX and RKLB are
    one query, three HSTECH funds are one. An index fund files nothing, so it
    gets its theme's news and no filing or per-symbol feed — the Finnhub HK
    lesson (15 requests a slot, no item in 81 contexts) is not repeated.
    """
    from clawock.market_data.sentiment import _clean_name  # noqa: PLC0415

    wanted = [s for s in (sources or SOURCES) if market in SOURCES[s].markets]
    issuers, themes = {}, {}
    for ticker in tickers:
        target = targets(ticker) or {}
        if target.get('kind') == 'index_fund':
            terms = target.get('theme_terms') or []
            if terms:
                themes.setdefault(terms[0], []).append(ticker)
            continue
        issuer = str(target.get('issuer') or ticker)
        owners = issuers.setdefault(issuer, [])
        for name in (ticker, issuer):
            if name not in owners:
                owners.append(name)
    every = sorted({t for rows in [*issuers.values(), *themes.values()] for t in rows})
    language = 'zh' if market == 'hk' else 'en'
    out = []
    for source in wanted:
        scope = SOURCES[source].scope
        if scope == 'book' and issuers:
            out.append({'source': source, 'key': 'book', 'args': (sorted(issuers),),
                        'tickers': every, 'by_issuer': issuers})
        elif scope == 'issuer':
            for issuer, owners in issuers.items():
                if source == 'google_news':
                    # Google's `when:1d` keeps the answer inside the window.
                    term = (_clean_name((names or {}).get(issuer) or '') if market == 'hk'
                            else f'{issuer} stock')
                    if term:
                        out.append({'source': source, 'key': term,
                                    'args': (f'{term} when:1d', language), 'tickers': owners})
                else:
                    out.append({'source': source, 'key': issuer, 'args': (issuer,),
                                'tickers': owners})
            if source == 'google_news':
                for theme, owners in themes.items():
                    out.append({'source': source, 'key': theme,
                                'args': (f'{theme} when:1d', language), 'tickers': owners})
        elif scope == 'market':
            out.append({'source': source, 'key': 'market', 'args': (), 'tickers': []})
    for request in out:
        request['entry'] = f"{request['source']}:{request['key']}"
    return out


# ── Layer 2: normalisation ────────────────────────────────────────────────────

def triage(rows, source, market):
    """Exchange/regulator rows minus routine noise, with their triage class."""
    if SOURCES[source].grade != 'primary':
        return rows, []
    from clawock.market_data import mover_evidence, primary_disclosures  # noqa: PLC0415

    kept, suppressed = [], []
    for row in rows:
        text = f"{row.get('title') or ''} {row.get('category') or ''}"
        if market == 'hk':
            text = primary_disclosures.hk_simplified(text)
        signal, rule = mover_evidence.classify(text, market)
        if signal == mover_evidence.NOISE:
            suppressed.append(row.get('title'))
            continue
        kept.append({**row, 'signal': signal, 'triage_rule': rule})
    return kept, suppressed


def cite(row, source, market, now, fresh_since, labels):
    """`(cite, stale)`: the publisher's own time and which side of `fresh_since`."""
    label = SOURCES[source].label if source in SOURCES else source
    if row.get('publisher'):
        label += f"·{row['publisher']}"
    title = str(row.get('title'))[:60]
    when = parse_time(row.get('published_at'))
    if when is not None:
        stale = when < fresh_since
        stamp = when.astimezone(HKT).strftime('%m-%d %H:%M HKT')
        return f"《{title}》（{label}，{stamp} 发布，{labels.stale if stale else labels.fresh}）", stale
    filed = row.get('filed_date')
    today = now.astimezone(ET if market == 'us' else HKT).date().isoformat()
    if filed == today:
        # EDGAR's index knows the day, not the minute: neither fresh nor old.
        return f"《{title}》（{label}，{filed} 提交，{labels.same_day_no_time}）", None
    return f"《{title}》（{label}，{filed} 提交，{labels.stale}）", True


def in_window(row, now, window_minutes):
    when = parse_time(row.get('published_at'))
    if when is not None:
        return -5 <= (now - when).total_seconds() / 60 <= window_minutes
    # The filing search asked for the window's dates only; a row with no time
    # at all can be shown neither as fresh nor as old.
    return bool(row.get('filed_date'))


def normalize(row, source, market, now, *, fresh_since, labels):
    text, stale = cite(row, source, market, now, fresh_since, labels)
    out = {'source': source, 'grade': SOURCES[source].grade,
           **{k: row[k] for k in ('title', 'published_at', 'filed_date', 'publisher',
                                  'signal') if row.get(k)},
           'stale': stale, 'cite': text}
    url = row.get('url') or row.get('source_url')
    if url:
        out['url'] = url
    return out


def _title_key(title):
    return re.sub(r'\W+', '', str(title or '').lower())[:40]


# ── Layer 3: trimming ─────────────────────────────────────────────────────────

GRADE_ORDER = {'primary': 0, 'authoritative': 1, 'soft': 2}
FRESH_ORDER = {False: 0, None: 1, True: 2}
SUMMARY_KEYS = ('grade', 'source', 'title', 'published_at', 'filed_date', 'signal',
                'stale', 'cite')


def summarize(tickers, *, per_ticker=4):
    """The core-packet view: fresh first (kcn: 实时优先), then primary before
    soft, newest first; `per_ticker` rows each. The input is already
    de-duplicated and ordered by `collect`, so this is a cut, not a re-rank."""
    return {ticker: [{k: r[k] for k in SUMMARY_KEYS if k in r} for r in rows[:per_ticker]]
            for ticker, rows in (tickers or {}).items()}


# ── The call ──────────────────────────────────────────────────────────────────

def _load_store(path, session):
    try:
        doc = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        doc = {}
    if not isinstance(doc, dict) or doc.get('session') != session:
        doc = {'session': session, 'entries': {}}
    doc.setdefault('entries', {})
    return doc


def _merge(old, new, keep):
    """This call's rows first, then earlier ones (same session) it no longer lists."""
    seen, out = set(), []
    for row in [*new, *old]:
        key = row.get('url') or _title_key(row.get('title'))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out[:keep]


def _run(requests, *, http, now, window_minutes, limits, fetchers, clock):
    """Every request at once; `{index: (status, rows, suppressed, error, elapsed)}`."""
    gates = {name: threading.Semaphore(limits.per_source_concurrency) for name in SOURCES}
    started = clock()

    def call(request):
        source = request['source']
        with gates[source]:
            begin = clock()
            timeout = limits.source_timeout_s.get(source, limits.timeout_s)
            if fetchers and source in fetchers:
                rows = fetchers[source](*request['args'])
            else:
                rows = SOURCES[source].adapter(
                    request, http=http, timeout=timeout, now=now,
                    window_minutes=window_minutes, limits=limits)
            return list(rows or []), round(clock() - begin, 2)

    pool = ThreadPoolExecutor(max_workers=max(1, limits.workers))
    futures = {pool.submit(call, request): index for index, request in enumerate(requests)}
    done, _pending = wait(futures, timeout=max(0.0, limits.budget_s - (clock() - started)))
    # Never joined past the budget: a straggler finishes (or times out) on its
    # own thread, bounded by the per-request timeout.
    pool.shutdown(wait=False, cancel_futures=True)
    out = {}
    for future, index in futures.items():
        if future not in done:
            out[index] = ('timeout', [], f'over {limits.budget_s}s budget', None)
            continue
        try:
            rows, elapsed = future.result()
        except Exception as exc:  # noqa: BLE001 — a dead feed is a stated gap
            out[index] = ('failed', [], f'{type(exc).__name__}: {exc}'[:120], None)
            continue
        out[index] = ('ok', rows, None, elapsed)
    return out


def collect(market, tickers, *, targets=None, names=None, window_minutes=24 * 60,
            now=None, http=None, sources=None, limits=None, fresh_since=None,
            labels=INTRADAY_LABELS, cache_path=None, session=None, keep=20,
            fetchers=None, clock=None):
    """Live items for `tickers` of one market. Never raises.

    `targets(ticker)` says what a holding is (issuer / look-through / index
    fund, `mover_evidence.probe_targets` by default); `names` maps an issuer to
    its display name (Chinese names are what HK news uses). `fresh_since`
    (default: this session's open) is what an item's cite is measured against.
    `cache_path` + `session` let a re-run inside `limits.ttl_s` reuse answers
    and keep the session's earlier items when a feed stops listing them.
    `fetchers` replaces adapters by source name (tests, replays).

    Returns `{as_of, elapsed_s, sources, tickers, flashes, requests, degraded,
    raw}`: `sources[name]` is `{status, as_of, stale, requests, cached, items}`;
    `tickers[t]` every in-window item (normalised, de-duplicated, ordered);
    `flashes` the market-level feeds' items except 东财 7×24, whose rows are
    in `raw['em_724']` for the caller that already renders them.
    """
    now = now or datetime.now(timezone.utc)
    clock = clock or time.monotonic
    limits = limits or Limits()
    began = clock()
    fresh_since = fresh_since or session_open(market, now)
    as_of = now.astimezone(HKT).strftime('%m-%d %H:%M HKT')
    tickers = [str(t) for t in tickers or [] if t]
    try:
        if targets is None or names is None:
            from clawock.market_data import mover_evidence  # noqa: PLC0415
            targets = targets or (lambda t: mover_evidence.probe_targets(t, market))
            if names is None:
                issuers = {str((targets(t) or {}).get('issuer') or t) for t in tickers}
                names = mover_evidence.holding_names(sorted(issuers))
        requests = plan(market, tickers, targets=targets, names=names, sources=sources)
    except Exception as exc:  # noqa: BLE001 — no plan: say so
        return {'as_of': as_of, 'elapsed_s': 0.0, 'sources': {}, 'tickers': {},
                'flashes': [], 'requests': [], 'raw': {},
                'degraded': [f'实时资讯（{type(exc).__name__}）']}
    if http is None:
        from clawock.market_data.live_news import http_text as http  # noqa: PLC0415

    store = _load_store(cache_path, session) if cache_path else {'entries': {}}
    entries = store['entries']
    budget_left = dict(limits.request_budget)
    to_fetch, log = [], {}
    for position, request in enumerate(requests):
        request['position'] = position
        cached = entries.get(request['entry']) or {}
        fetched = parse_time(cached.get('fetched_at'))
        if (request['source'] != 'em_724' and cached.get('status') == 'ok'
                and fetched is not None
                and 0 <= (now - fetched).total_seconds() < limits.ttl_s):
            log[position] = {'source': request['source'], 'key': request['key'],
                             'status': 'cached', 'items': len(cached.get('items') or [])}
            continue
        if budget_left.get(request['source'], 0) <= 0:
            log[position] = {'source': request['source'], 'key': request['key'],
                             'status': 'over_budget', 'items': 0}
            continue
        budget_left[request['source']] -= 1
        to_fetch.append(request)

    results = _run(to_fetch, http=http, now=now, window_minutes=window_minutes,
                   limits=limits, fetchers=fetchers, clock=clock) if to_fetch else {}
    raw = {}
    for index, request in enumerate(to_fetch):
        status, rows, error, elapsed = results[index]
        suppressed = []
        if status == 'ok':
            rows, suppressed = triage(rows, request['source'], market)
        if request['source'] == 'em_724':
            raw['em_724'] = {'rows': rows, 'status': status, 'error': error}
        else:
            old = (entries.get(request['entry']) or {}).get('items') or []
            entries[request['entry']] = {
                'fetched_at': now.isoformat(), 'status': status,
                'items': _merge(old, rows, keep) if status == 'ok' else old,
                **({'error': error} if error else {})}
        log[request['position']] = {
            'source': request['source'], 'key': request['key'], 'status': status,
            'items': len(rows), 'elapsed_s': elapsed,
            **({'suppressed_noise': len(suppressed)} if suppressed else {}),
            **({'error': error} if error else {})}
    log = [log[position] for position in sorted(log)]
    if cache_path:
        try:
            safe_write_json(str(cache_path), store)
        except OSError:
            pass  # the cache is an optimisation; this call's answers stand

    by_ticker, flashes = {}, []
    for request in requests:
        if request['source'] == 'em_724':
            continue
        for row in (entries.get(request['entry']) or {}).get('items') or []:
            if not in_window(row, now, window_minutes):
                continue
            item = normalize(row, request['source'], market, now,
                             fresh_since=fresh_since, labels=labels)
            if request['source'] in MARKET_FEEDS:
                flashes.append(item)
                continue
            owners = request['tickers']
            if request.get('by_issuer'):
                owners = request['by_issuer'].get(str(row.get('issuer'))) or []
            # A holding and the issuer it looks through to (RKLX → RKLB).
            for ticker in owners:
                by_ticker.setdefault(ticker, []).append(item)
    for ticker, rows in by_ticker.items():
        seen, unique = set(), []
        for row in rows:
            key = _title_key(row.get('title'))
            if key not in seen:
                seen.add(key)
                unique.append(row)
        unique.sort(key=lambda r: str(r.get('published_at') or r.get('filed_date') or ''),
                    reverse=True)
        unique.sort(key=lambda r: (FRESH_ORDER[r['stale']], GRADE_ORDER.get(r['grade'], 3)))
        by_ticker[ticker] = unique
    flashes.sort(key=lambda r: str(r.get('published_at') or ''), reverse=True)

    health = {}
    for row in log:
        if row['source'] == 'em_724':
            continue
        src = health.setdefault(row['source'], {
            'status': 'ok', 'as_of': as_of, 'stale': False, 'requests': 0,
            'cached': 0, 'items': 0, '_states': []})
        if row['status'] == 'cached':
            src['cached'] += 1
        elif row['status'] != 'over_budget':
            src['requests'] += 1
        src['items'] += row.get('items') or 0
        src['_states'].append(row['status'])
    for src in health.values():
        states = src.pop('_states')
        bad = [s for s in states if s in ('failed', 'timeout', 'over_budget')]
        src['status'] = 'ok' if not bad else bad[0] if len(bad) == len(states) else 'partial'
    return {'as_of': as_of, 'elapsed_s': round(clock() - began, 2), 'sources': health,
            'tickers': by_ticker, 'flashes': flashes, 'requests': log, 'raw': raw,
            'degraded': degraded_lines(log)}


def degraded_lines(log):
    """One ⛔ phrase per source that did not fully answer (东财 is its caller's)."""
    by_source = {}
    for row in log:
        if row['source'] != 'em_724':
            by_source.setdefault(row['source'], []).append(row)
    out = []
    for source, rows in by_source.items():
        bad = [row for row in rows if row['status'] in ('failed', 'timeout', 'over_budget')]
        if not bad:
            continue
        reasons = '、'.join(dict.fromkeys(
            {'timeout': '超时', 'over_budget': '超出请求预算'}.get(row['status'])
            or str(row.get('error') or 'failed').split(':')[0] for row in bad))
        count = f'{len(bad)}/{len(rows)} ' if len(rows) > 1 else ''
        out.append(f'{SOURCES[source].label}（{count}{reasons}）')
    return out


def book_tickers(workspace, market):
    """Active holdings of one market from `portfolio.json` (shares > 0)."""
    from clawock.market_data.sentiment import load_tickers  # noqa: PLC0415

    region = 'hk_stocks' if market == 'hk' else 'us_stocks'
    return [row['ticker'] for row in load_tickers(Path(workspace)) if row['region'] == region]


def main(argv=None) -> int:
    """`clawock live-sources`: one bounded call per market, JSON on stdout.

    The subprocess face of `collect()` for harnesses whose preflight runs
    every collector as its own `clawock` process (the brief's DAG). Exit 0
    even when sources fail — their failures are in `degraded`.
    """
    import argparse  # noqa: PLC0415

    from clawock.workspace import workspace_root  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog='clawock live-sources',
                                     description=__doc__.splitlines()[0])
    parser.add_argument('--market', choices=('hk', 'us', 'both'), default='both')
    parser.add_argument('--sources', default='',
                        help=f"comma-separated subset of {','.join(SOURCES)} (default: all)")
    parser.add_argument('--fresh-since', choices=('session_open', 'last_close'),
                        default='session_open')
    parser.add_argument('--window-minutes', type=int, default=24 * 60)
    parser.add_argument('--budget-s', type=float, default=Limits.budget_s)
    parser.add_argument('--timeout-s', type=float, default=Limits.timeout_s)
    parser.add_argument('--per-ticker', type=int, default=4)
    parser.add_argument('--json', action='store_true', help='accepted for symmetry; output is JSON')
    args = parser.parse_args(argv)

    chosen = tuple(s for s in args.sources.split(',') if s) or None
    unknown = [s for s in chosen or () if s not in SOURCES]
    if unknown:
        parser.error(f'unknown source(s): {", ".join(unknown)}')
    now = datetime.now(timezone.utc)
    limits = Limits(budget_s=args.budget_s, timeout_s=args.timeout_s)
    labels = BRIEF_LABELS if args.fresh_since == 'last_close' else INTRADAY_LABELS
    markets = ('hk', 'us') if args.market == 'both' else (args.market,)
    workspace = workspace_root()

    def one(market):
        try:
            tickers = book_tickers(workspace, market)
        except Exception as exc:  # noqa: BLE001
            return {'degraded': [f'实时资讯（{type(exc).__name__}）'], 'tickers': {},
                    'summary': {}, 'sources': {}, 'requests': []}
        since = last_close(market, now) if args.fresh_since == 'last_close' else None
        result = collect(market, tickers, now=now, sources=chosen, limits=limits,
                         window_minutes=args.window_minutes, fresh_since=since,
                         labels=labels)
        result.pop('raw', None)
        result['summary'] = summarize(result['tickers'], per_ticker=args.per_ticker)
        return result

    with ThreadPoolExecutor(max_workers=len(markets)) as pool:
        answers = dict(zip(markets, pool.map(one, markets)))
    print(json.dumps(answers, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
