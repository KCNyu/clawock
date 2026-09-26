"""The intraday information lane: tiers 0–2 of docs/architecture/intraday-agent.md §6.

docs/architecture/intraday-agent.md §6. Six files the morning jobs already
write (Eastmoney company news and 7x24, the US digest, sentiment attention,
macro, the graded news evidence graph, the sentiment factor snapshot) were read
by the brief and by no intraday slot: the model judged "情绪面/消息面" with
nothing but the mover probe. They are read here, never refetched — the brief's
rule — and every item carries the time its file was written plus `stale` when
that was before the current session opened: a 08:10 file quoted at 23:00 ET is
eight hours old and must say so.

The one request this adds is Eastmoney's market-level 7x24 list, once per slot.
`mover_evidence` only keeps flashes naming a mover, so on a quiet slot the lane
was empty by construction.

Tier 2 (`collect_live`) reads free public endpoints every slot — HKEXnews,
EDGAR full-text search, Google News, Yahoo Finance RSS, 同花顺 7×24 — because
kcn wants as much live news as there is (2026-09-26), not only where the other
tiers leave a gap. It needs only the book, so the preflight starts it before
the analyzer and its waits overlap the quote refresh. Bounded by construction:
every request in parallel under a per-source concurrency cap, a per-request
timeout, a wall-clock budget for the lane, a per-source request budget and a
cache that serves a re-run of the same slot. Every live item carries its
publisher's own time and says whether it came out during this session
(`盘中实时`) or before it (`开盘前旧闻`); a source that did not answer is
named on the ⛔ line like the morning files.

Output: `summary` for the core packet (bounded per source), `full` for the
reference layer, `degraded` naming sources that could not be read — which the
card states on a ⛔ line (not fetched is not "no news").
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, time as dtime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

from clawock.safe_io import safe_write_json
from clawock.sessions import ET, HKT

MAX_ITEMS_PER_TICKER = 3
MAX_MARKET_ITEMS = 5
MAX_FLASH_ITEMS = 6
FLASH_WINDOW_MINUTES = 240

FILES = {
    'em_news': 'assets/data/em_news.json',
    'us_news_digest': 'assets/data/us_news_digest.json',
    'sentiment': 'assets/data/sentiment.json',
    'macro': 'assets/data/macro.json',
    'news_evidence_graph': 'assets/data/news_evidence_graph.json',
}
# Which market each file serves; None = both.
FILE_MARKET = {'em_news': 'hk', 'us_news_digest': 'us'}


def _read(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None, 'missing'
    except (OSError, ValueError) as exc:
        return None, f'unreadable: {type(exc).__name__}'
    return (value, None) if isinstance(value, dict) else (None, 'unreadable: not an object')


def _parse_time(value):
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


def freshness(written_at, market, now):
    """`{as_of, age_hours, stale}` for a source written at `written_at`."""
    if written_at is None:
        return {'as_of': None, 'age_hours': None, 'stale': True}
    local = written_at.astimezone(HKT)
    return {
        'as_of': local.strftime('%m-%d %H:%M HKT'),
        'age_hours': round((now - written_at).total_seconds() / 3600, 1),
        # Before this session opened, or unprovable: never shown as live.
        'stale': written_at < session_open(market, now),
    }


def graph_grade(event):
    """Evidence grade from the graph's own classification (contract §5)."""
    if 'filing' in str(event.get('source_type') or ''):
        return 'primary'
    if 'reliable_primary_or_wire' not in (event.get('actionable_blockers') or []):
        return 'authoritative'
    return 'soft'


def _cite(title, source, fresh):
    label = f"截至 {fresh['as_of']}" if fresh.get('as_of') else '时间未知'
    if fresh.get('stale'):
        label += '，开盘前旧闻'
    return f"《{str(title)[:60]}》（{source}，{label}）"


# ── Tier 2: free public endpoints, every slot (contract §6) ──────────────────

LIVE_TIMEOUT_S = 6           # one request
# 同花顺 answers this host in 2–8 s (10 runs 2026-09-26; 3/5 inside 6 s).
SOURCE_TIMEOUT_S = {'ths_724': 10}
# The whole lane, wall clock. It starts before the analyzer (8–18 s) and is
# joined after it, so a lane inside this budget adds nothing to the slot.
LIVE_BUDGET_S = 12
# A re-run of the same slot (cron retry, manual rerun) reuses what this slot
# fetched; the next slot, 30 minutes on, asks again.
LIVE_TTL_S = 20 * 60
LIVE_WINDOW_MINUTES = 24 * 60
LIVE_WORKERS = 8
PER_SOURCE_CONCURRENCY = 4
MAX_LIVE_PER_TICKER = 4
MAX_LIVE_KEPT = 20
MAX_EXTRA_FLASH_ITEMS = 4
# Requests one slot may spend per source. The book today needs 1–3 of each;
# a query beyond the budget is named in `sources`, never silently dropped.
REQUEST_BUDGET = {'hkexnews': 3, 'sec_fulltext': 1, 'google_news': 8,
                  'yahoo_rss': 6, 'ths_724': 1, 'em_724': 1}
LIVE_LABELS = {'hkexnews': 'HKEXnews披露易', 'sec_fulltext': 'SEC全文检索',
               'google_news': 'Google新闻', 'yahoo_rss': 'Yahoo财经',
               'ths_724': '同花顺7×24', 'em_724': '东财7×24'}
PRIMARY_SOURCES = ('hkexnews', 'sec_fulltext')


def _default_fetchers(timeout):
    from functools import partial  # noqa: PLC0415

    from clawock.market_data import eastmoney_news, live_news  # noqa: PLC0415
    from clawock.market_data import mover_evidence, primary_disclosures  # noqa: PLC0415

    http = partial(primary_disclosures._http_json, timeout=timeout)

    def triaged(items, market, suppressed):
        kept = []
        for item in items:
            text = f"{item.get('title') or ''} {item.get('category') or ''}"
            if market == 'hk':
                text = primary_disclosures.hk_simplified(text)
            signal, rule = mover_evidence.classify(text, market)
            if signal == mover_evidence.NOISE:
                suppressed.append(item.get('title'))
                continue
            kept.append({**item, 'signal': signal, 'triage_rule': rule})
        return kept

    def hkexnews(codes, now, suppressed):
        items, note, _pages = primary_disclosures.fetch_hkexnews_latest(
            codes, now=now, window_minutes=LIVE_WINDOW_MINUTES, http=http,
            max_pages=REQUEST_BUDGET['hkexnews'])
        if note:
            raise live_news.SourceError(note)
        return triaged(items, 'hk', suppressed)

    def sec_fulltext(issuers, now, suppressed):
        items, note = primary_disclosures.fetch_sec_fulltext(issuers, now=now, http=http)
        if note:
            raise live_news.SourceError(note)
        return triaged(items, 'us', suppressed)

    return {
        'hkexnews': hkexnews,
        'sec_fulltext': sec_fulltext,
        'google_news': lambda query, language: live_news.google_news(
            query, language=language, timeout=timeout),
        'yahoo_rss': lambda symbol: live_news.yahoo_headlines(symbol, timeout=timeout),
        'ths_724': lambda: live_news.ths_flashes(
            timeout=max(timeout, SOURCE_TIMEOUT_S['ths_724'])),
        # Tier 1's one request, moved into this lane so it waits alongside the
        # rest instead of after the analyzer; `collect` reads it unchanged.
        'em_724': lambda: eastmoney_news.em_fast_news(limit=20) or [],
    }


def live_plan(market, tickers, *, targets, names):
    """The requests one slot makes, each with the tickers its answer belongs to.

    Asked per issuer and per index theme, not per holding: RKLX and RKLB are
    one query, three HSTECH funds are one. An index fund files nothing, so it
    gets its theme's news and no filing or per-symbol feed — the Finnhub HK
    lesson (15 requests a slot, no item in 81 contexts) is not repeated.
    """
    issuers, themes = {}, {}
    for ticker in tickers:
        target = targets(ticker) or {}
        if target.get('kind') == 'index_fund':
            terms = target.get('theme_terms') or []
            if terms:
                themes.setdefault(terms[0], []).append(ticker)
            continue
        issuer = str(target.get('issuer') or ticker)
        issuers.setdefault(issuer, [])
        for name in (ticker, issuer):
            if name not in issuers[issuer]:
                issuers[issuer].append(name)
    every = sorted({t for rows in [*issuers.values(), *themes.values()] for t in rows})
    # Google's `when:1d` keeps its answer inside the window this lane shows.
    plan = []
    from clawock.market_data.sentiment import _clean_name  # noqa: PLC0415

    if market == 'hk':
        if issuers:
            plan.append({'source': 'hkexnews', 'key': 'book', 'args': (sorted(issuers),),
                         'tickers': every, 'by_issuer': issuers})
        for issuer, owners in issuers.items():
            name = _clean_name((names or {}).get(issuer) or '')
            if name:
                plan.append({'source': 'google_news', 'key': name, 'args': (f'{name} when:1d', 'zh'),
                             'tickers': owners})
        for theme, owners in themes.items():
            plan.append({'source': 'google_news', 'key': theme, 'args': (f'{theme} when:1d', 'zh'),
                         'tickers': owners})
    else:
        if issuers:
            plan.append({'source': 'sec_fulltext', 'key': 'book', 'args': (sorted(issuers),),
                         'tickers': every, 'by_issuer': issuers})
        for issuer, owners in issuers.items():
            plan.append({'source': 'google_news', 'key': f'{issuer} stock',
                         'args': (f'{issuer} stock when:1d', 'en'), 'tickers': owners})
            # Yahoo's HK symbols answered with 2025 headlines (2208.HK) or
            # nothing (the ETFs) on 2026-09-26; US only.
            plan.append({'source': 'yahoo_rss', 'key': issuer, 'args': (issuer,),
                         'tickers': owners})
        for theme, owners in themes.items():
            plan.append({'source': 'google_news', 'key': theme, 'args': (f'{theme} when:1d', 'en'),
                         'tickers': owners})
    plan.append({'source': 'ths_724', 'key': 'market', 'args': (), 'tickers': []})
    plan.append({'source': 'em_724', 'key': 'market', 'args': (), 'tickers': []})
    return plan


def _load_store(path, session):
    try:
        doc = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        doc = {}
    if not isinstance(doc, dict) or doc.get('session') != session:
        doc = {'session': session, 'entries': {}}
    doc.setdefault('entries', {})
    return doc


def _title_key(title):
    return re.sub(r'\W+', '', str(title or '').lower())[:40]


def _merge(old, new):
    """This slot's rows first, then the session's earlier ones it no longer lists."""
    seen, out = set(), []
    for row in [*new, *old]:
        key = row.get('url') or _title_key(row.get('title'))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out[:MAX_LIVE_KEPT]


def _run(plan, fetchers, now, budget_s, clock):
    """Every request of `plan` at once; `{index: (status, rows, error, elapsed)}`."""
    gates = {source: threading.Semaphore(PER_SOURCE_CONCURRENCY) for source in LIVE_LABELS}
    started = clock()

    def call(request):
        with gates[request['source']]:
            begin = clock()
            suppressed = []
            fn = fetchers[request['source']]
            args = request['args']
            if request['source'] in PRIMARY_SOURCES:
                rows = fn(*args, now, suppressed)
            else:
                rows = fn(*args)
            return rows, suppressed, round(clock() - begin, 2)

    pool = ThreadPoolExecutor(max_workers=LIVE_WORKERS)
    futures = {pool.submit(call, request): index for index, request in enumerate(plan)}
    done, _pending = wait(futures, timeout=max(0.0, budget_s - (clock() - started)))
    # Never joined past the budget: a straggler finishes (or times out) on its
    # own thread, bounded by the per-request timeout.
    pool.shutdown(wait=False, cancel_futures=True)
    out = {}
    for future, index in futures.items():
        if future not in done:
            out[index] = ('timeout', [], [], f'over {budget_s}s lane budget', None)
            continue
        try:
            rows, suppressed, elapsed = future.result()
        except Exception as exc:  # noqa: BLE001 — a dead feed is a stated gap
            out[index] = ('failed', [], [], f'{type(exc).__name__}: {exc}'[:120], None)
            continue
        out[index] = ('ok', list(rows or []), suppressed, None, elapsed)
    return out


def collect_live(workspace, market, *, now=None, session=None, cache_path=None,
                 tickers=None, fetchers=None, targets=None, names=None,
                 budget_s=LIVE_BUDGET_S, timeout=LIVE_TIMEOUT_S, clock=None):
    """Tier 2 for this leg's book. Never raises.

    Returns `{requests, entries, plan, em_724, as_of, elapsed_s, degraded}`;
    `collect(..., live=)` turns it into the summary and reference rows.
    """
    now = now or datetime.now(timezone.utc)
    clock = clock or time.monotonic
    began = clock()
    try:
        if tickers is None:
            from clawock.market_data.sentiment import load_tickers  # noqa: PLC0415
            region = 'hk_stocks' if market == 'hk' else 'us_stocks'
            tickers = [row['ticker'] for row in load_tickers(Path(workspace))
                       if row['region'] == region]
        if targets is None or names is None:
            from clawock.market_data import mover_evidence  # noqa: PLC0415
            targets = targets or (lambda t: mover_evidence.probe_targets(t, market))
            if names is None:
                issuers = {str((targets(t) or {}).get('issuer') or t) for t in tickers}
                names = mover_evidence.holding_names(sorted(issuers))
        plan = live_plan(market, tickers, targets=targets, names=names)
    except Exception as exc:  # noqa: BLE001 — no book, no plan: say so
        return {'requests': [], 'entries': {}, 'plan': [], 'em_724': None,
                'as_of': now.isoformat(), 'elapsed_s': 0.0,
                'degraded': [f'实时资讯（{type(exc).__name__}）']}
    fetchers = {**_default_fetchers(timeout), **(fetchers or {})}

    budget_left = dict(REQUEST_BUDGET)
    store = _load_store(cache_path, session) if cache_path else {'entries': {}}
    entries = store['entries']
    to_fetch, requests = [], []
    for request in plan:
        entry_key = f"{request['source']}:{request['key']}"
        request['entry'] = entry_key
        cached = entries.get(entry_key) or {}
        fetched = _parse_time(cached.get('fetched_at'))
        if (cached.get('status') == 'ok' and fetched is not None
                and 0 <= (now - fetched).total_seconds() < LIVE_TTL_S):
            requests.append({'source': request['source'], 'key': request['key'],
                             'status': 'cached', 'items': len(cached.get('items') or [])})
            continue
        if budget_left.get(request['source'], 0) <= 0:
            requests.append({'source': request['source'], 'key': request['key'],
                             'status': 'over_budget', 'items': 0})
            continue
        budget_left[request['source']] -= 1
        to_fetch.append(request)

    results = _run(to_fetch, fetchers, now, budget_s, clock) if to_fetch else {}
    em_724 = None
    for index, request in enumerate(to_fetch):
        status, rows, suppressed, error, elapsed = results[index]
        if request['source'] == 'em_724':
            em_724 = {'rows': rows, 'status': status, 'error': error}
        old = (entries.get(request['entry']) or {}).get('items') or []
        entry = {'fetched_at': now.isoformat(), 'status': status,
                 'items': _merge(old, rows) if status == 'ok' else old}
        if error:
            entry['error'] = error
        if request['source'] != 'em_724':
            entries[request['entry']] = entry
        requests.append({'source': request['source'], 'key': request['key'],
                         'status': status, 'items': len(rows), 'elapsed_s': elapsed,
                         **({'suppressed_noise': len(suppressed)} if suppressed else {}),
                         **({'error': error} if error else {})})
    if cache_path:
        try:
            safe_write_json(str(cache_path), store)
        except OSError:
            pass  # the cache is an optimisation; this slot's answers stand
    return {
        'requests': requests, 'entries': entries,
        'plan': [{k: r[k] for k in ('source', 'key', 'tickers', 'entry')}
                 | ({'by_issuer': r['by_issuer']} if r.get('by_issuer') else {})
                 for r in plan],
        'em_724': em_724, 'as_of': now.isoformat(),
        'elapsed_s': round(clock() - began, 2),
        'degraded': _live_degraded(requests),
    }


def _live_degraded(requests):
    """One ⛔ phrase per source that did not fully answer this slot."""
    by_source = {}
    for row in requests:
        if row['source'] == 'em_724':
            continue  # `collect` reports tier 1 in its own words
        by_source.setdefault(row['source'], []).append(row)
    out = []
    for source, rows in by_source.items():
        bad = [row for row in rows if row['status'] in ('failed', 'timeout', 'over_budget')]
        if not bad:
            continue
        reasons = '、'.join(dict.fromkeys(
            {'timeout': '超时', 'over_budget': '超出每档请求预算'}.get(row['status'])
            or str(row.get('error') or 'failed').split(':')[0] for row in bad))
        count = f'{len(bad)}/{len(rows)} ' if len(rows) > 1 else ''
        out.append(f'{LIVE_LABELS[source]}（{count}{reasons}）')
    return out


def _live_cite(row, market, now):
    """`(cite, stale)`: the publisher's own time, and whether it predates the open."""
    label = LIVE_LABELS.get(row['source'], row['source'])
    if row.get('publisher'):
        label += f"·{row['publisher']}"
    title = str(row.get('title'))[:60]
    when = _parse_time(row.get('published_at'))
    if when is not None:
        stale = when < session_open(market, now)
        stamp = when.astimezone(HKT).strftime('%m-%d %H:%M HKT')
        return f"《{title}》（{label}，{stamp} 发布，{'开盘前旧闻' if stale else '盘中实时'}）", stale
    filed = row.get('filed_date')
    today = now.astimezone(ET if market == 'us' else HKT).date().isoformat()
    if filed == today:
        # EDGAR's index knows the day, not the minute: neither live nor old.
        return f"《{title}》（{label}，{filed} 提交，今日提交、时刻未知）", None
    return f"《{title}》（{label}，{filed} 提交，开盘前旧闻）", True


def _in_window(row, now):
    when = _parse_time(row.get('published_at'))
    if when is not None:
        age = (now - when).total_seconds() / 60
        return -5 <= age <= LIVE_WINDOW_MINUTES
    if row.get('filed_date'):
        return True  # the search asked for yesterday and today (ET) only
    return False  # no time at all cannot be shown as live or old


def assemble_live(live, market, tickers, now):
    """Per-ticker live rows (summary and full), flashes, and per-source health."""
    tickers = set(tickers)
    full = {}
    for request in live.get('plan') or []:
        if request['source'] in ('ths_724', 'em_724'):
            continue
        entry = (live.get('entries') or {}).get(request['entry']) or {}
        for row in entry.get('items') or []:
            if not _in_window(row, now):
                continue
            owners = request['tickers']
            if request.get('by_issuer'):
                owners = request['by_issuer'].get(str(row.get('issuer'))) or []
            cite, stale = _live_cite({**row, 'source': request['source']}, market, now)
            item = {'source': request['source'],
                    'grade': 'primary' if request['source'] in PRIMARY_SOURCES else 'soft',
                    **{k: row[k] for k in ('title', 'published_at', 'filed_date', 'url',
                                           'publisher', 'signal') if row.get(k)},
                    'stale': stale, 'cite': cite}
            for ticker in owners:
                if ticker in tickers:
                    full.setdefault(ticker, []).append(item)
    order = {'primary': 0, 'authoritative': 1, 'soft': 2}
    freshness_rank = {False: 0, None: 1, True: 2}
    summary = {}
    for ticker, rows in full.items():
        seen, unique = set(), []
        for row in rows:
            key = _title_key(row.get('title'))
            if key not in seen:
                seen.add(key)
                unique.append(row)
        # This session's items first (kcn: 实时优先), then primary before soft,
        # newest first.
        unique.sort(key=lambda r: str(r.get('published_at') or r.get('filed_date') or ''),
                    reverse=True)
        unique.sort(key=lambda r: (freshness_rank[r['stale']], order.get(r['grade'], 3)))
        full[ticker] = unique
        summary[ticker] = [{k: r[k] for k in ('grade', 'source', 'title', 'published_at',
                                              'filed_date', 'signal', 'stale', 'cite')
                            if k in r} for r in unique[:MAX_LIVE_PER_TICKER]]
    flashes = []
    ths = (live.get('entries') or {}).get('ths_724:market') or {}
    for row in ths.get('items') or []:
        when = _parse_time(row.get('published_at'))
        if when is None or not (-5 <= (now - when).total_seconds() / 60 <= FLASH_WINDOW_MINUTES):
            continue
        flashes.append({'title': row.get('title'), 'time': when.astimezone(HKT).strftime(
            '%Y-%m-%d %H:%M'), 'source': 'ths_724',
            'cite': f"《{str(row.get('title'))[:60]}》（同花顺7×24，"
                    f"{when.astimezone(HKT).strftime('%Y-%m-%d %H:%M')}）"})
    sources = {}
    for row in live.get('requests') or []:
        if row['source'] == 'em_724':
            continue
        src = sources.setdefault(row['source'], {
            'status': 'ok', 'as_of': freshness(_parse_time(live.get('as_of')), market, now)['as_of'],
            'stale': False, 'requests': 0, 'cached': 0, 'items': 0, 'tier': 2})
        if row['status'] == 'cached':
            src['cached'] += 1
        elif row['status'] != 'over_budget':
            src['requests'] += 1
        src['items'] += row.get('items') or 0
        src.setdefault('_states', []).append(row['status'])
    for src in sources.values():
        states = src.pop('_states')
        bad = [s for s in states if s in ('failed', 'timeout', 'over_budget')]
        src['status'] = ('ok' if not bad else bad[0] if len(bad) == len(states)
                         else 'partial')
    return {'summary': summary, 'full': full, 'flashes': flashes, 'sources': sources}


def _near_duplicate(title, others):
    key = _title_key(title)
    return any(SequenceMatcher(None, key, _title_key(o)).ratio() >= 0.6 for o in others)


def collect(workspace, market, tickers, *, now=None, fast_news=None, live=None):
    """`{summary, full, degraded}` for this leg's `tickers`. Never raises.

    `live` is `collect_live`'s answer (tier 2, started earlier); without it the
    lane is tiers 0–1 exactly as before.
    """
    now = now or datetime.now(timezone.utc)
    tickers = [str(t) for t in tickers or [] if t]
    ws = Path(workspace)
    summary, full, degraded, sources = {}, {}, [], {}

    loaded = {}
    for name, rel in FILES.items():
        if FILE_MARKET.get(name) not in (None, market):
            continue
        doc, error = _read(ws / rel)
        if error:
            degraded.append(f'{name}（{error}）')
            sources[name] = {'status': error}
            continue
        written = _parse_time(doc.get('generated_at'))
        sources[name] = {'status': 'ok', **freshness(written, market, now)}
        loaded[name] = doc

    snap_date = now.astimezone(HKT).date().isoformat()
    snap, error = _read(ws / 'assets' / 'data' / 'factor-snapshots' / 'sentiment'
                        / f'{snap_date}.json')
    if error:
        sources['sentiment_snapshot'] = {'status': error}
    else:
        sources['sentiment_snapshot'] = {
            'status': 'ok', **freshness(_parse_time(snap.get('generated_at')), market, now)}

    per_ticker = {ticker: [] for ticker in tickers}
    full_ticker = {ticker: [] for ticker in tickers}

    graph = loaded.get('news_evidence_graph') or {}
    for event in graph.get('events') or []:
        ticker = str(event.get('ticker') or '')
        if ticker not in per_ticker:
            continue
        row = {
            'source': 'news_evidence_graph', 'source_type': event.get('source_type'),
            'grade': graph_grade(event), 'direction': event.get('impact_direction'),
            'title': event.get('title'),
            'published_at': ((event.get('publication_time') or {}).get('iso')),
            'url': event.get('source_url'),
        }
        full_ticker[ticker].append(row)
    em = loaded.get('em_news') or {}
    for ticker, entry in (em.get('holdings_news') or {}).items():
        if ticker in full_ticker:
            for item in entry.get('items') or []:
                full_ticker[ticker].append({
                    'source': 'em_news', 'grade': 'soft', 'direction': None,
                    'title': item.get('title'), 'published_at': item.get('date'),
                    'url': item.get('url')})
    digest = loaded.get('us_news_digest') or {}
    held_via = {via: base for base, vias in (digest.get('held_via') or {}).items()
                for via in vias}
    for base, items in (digest.get('raw_news_evidence') or {}).items():
        for ticker in {base, *[v for v, b in held_via.items() if b == base]}:
            if ticker in full_ticker:
                for item in items or []:
                    full_ticker[ticker].append({
                        'source': 'us_news_digest', 'grade': 'soft', 'direction': None,
                        'title': item.get('headline'), 'about': base,
                        'published_at': (_parse_time(item.get('datetime')) or now).isoformat()
                        if item.get('datetime') else None,
                        'url': item.get('url')})
    order = {'primary': 0, 'authoritative': 1, 'soft': 2}
    for ticker, rows in full_ticker.items():
        # Newest first, then (stable) by grade: primary before soft.
        rows.sort(key=lambda r: str(r.get('published_at') or ''), reverse=True)
        rows.sort(key=lambda r: order.get(r['grade'], 3))
        per_ticker[ticker] = [
            {**{k: r[k] for k in ('grade', 'direction', 'title', 'published_at') if r.get(k)},
             'cite': _cite(r.get('title'), r['source'], sources.get(r['source']) or {})}
            for r in rows[:MAX_ITEMS_PER_TICKER]]

    attention = {}
    for row in (loaded.get('sentiment') or {}).get('tickers') or []:
        if str(row.get('ticker')) in per_ticker:
            attention[row['ticker']] = {
                'reddit_mentions_7d': row.get('reddit_mentions_7d'),
                'reddit_status': row.get('reddit_status'),
                'google_news_en': len(row.get('google_news_en') or []),
                'google_news_zh': len(row.get('google_news_zh') or []),
            }

    macro = loaded.get('macro') or {}
    market_view = {key: {k: (macro.get(key) or {}).get(k) for k in ('price', 'change_pct')}
                   for key in (('hsi', 'hstech') if market == 'hk' else ('spx', 'nasdaq', 'vix'))
                   if macro.get(key)}
    if macro.get('fear_greed'):
        market_view['fear_greed'] = {k: macro['fear_greed'].get(k) for k in ('score', 'rating')}

    # Tier 1: market-level 7x24, one free request, not filtered by movers.
    # Fetched inside the tier 2 lane when there is one (same request, earlier).
    flashes, flash_status = [], 'ok'
    em_live = (live or {}).get('em_724') if fast_news is None else None
    if em_live is not None:
        rows = em_live.get('rows') or []
        if em_live.get('status') != 'ok':
            flash_status = f"failed: {em_live.get('status')}"
    else:
        try:
            if fast_news is None:
                from clawock.market_data import eastmoney_news  # noqa: PLC0415
                fast_news = eastmoney_news.em_fast_news
            rows = fast_news(limit=20) or []
        except Exception as exc:  # noqa: BLE001 — colour, never fatal
            rows, flash_status = [], f'failed: {type(exc).__name__}'
    if not rows and flash_status == 'ok':
        # The endpoint answers [] on its own failures; a live 7x24 list is
        # never empty, so empty is reported as not fetched.
        flash_status = 'empty_or_failed'
    for row in rows:
        when = _parse_time(str(row.get('date') or '').replace(' ', 'T'))
        age = (now - when).total_seconds() / 60 if when else None
        if age is not None and (age < -5 or age > FLASH_WINDOW_MINUTES):
            continue
        flashes.append({'title': row.get('title'), 'time': row.get('date'),
                        'cite': f"《{str(row.get('title'))[:60]}》（东财7×24，{row.get('date')}）"})
        if len(flashes) >= MAX_FLASH_ITEMS:
            break
    sources['em_724_live'] = {'status': flash_status, 'requests': 1}
    if flash_status != 'ok':
        degraded.append(f'东财7×24（{flash_status}）')

    # Tier 2: live per-ticker rows and a second 7x24 feed. Kept apart from the
    # morning rows (`tickers`), so a live item can never inherit a morning
    # file's time and a morning item can never pass as live.
    live_view = None
    if live is not None:
        live_view = assemble_live(live, market, tickers, now)
        sources.update(live_view['sources'])
        degraded.extend(live.get('degraded') or [])
        extra = [f for f in live_view['flashes']
                 if not _near_duplicate(f['title'], [x['title'] for x in flashes])]
        flashes = sorted([*flashes, *extra[:MAX_EXTRA_FLASH_ITEMS]],
                         key=lambda f: str(f.get('time') or ''), reverse=True)

    summary = {
        'sources': sources,
        'tickers': per_ticker,
        'attention': attention,
        'market': market_view,
        'market_flashes': flashes,
        **({'live': live_view['summary'], 'live_rule': (
            '实时源（HKEXnews/SEC全文检索/Google新闻/Yahoo财经/同花顺）每条带发布方自己的时间：'
            '「盘中实时」=本时段开盘后发布，「开盘前旧闻」照样要带时间引用，'
            'SEC全文检索只有提交日（「时刻未知」，不许说成刚刚）。'
            '没列出的票=本档实时源没有它的条目；源没取到的写在 ⛔ 行。')}
           if live_view is not None else {}),
        'morning_flashes': [
            {'title': i.get('title'), 'cite': _cite(i.get('title'), 'em_news 7×24',
                                                     sources.get('em_news') or {})}
            for i in (em.get('market_724') or [])[:MAX_MARKET_ITEMS]],
        'rule': ('引用任何一条都照抄它的 cite（含「截至」时间）；stale=true 的是开盘前写的，'
                 '不许说成盘中/最新消息。grade: primary 一手披露 > authoritative 权威 > soft 软消息/情绪。'),
    }
    full = {'tickers': full_ticker, 'sentiment': [
        row for row in (loaded.get('sentiment') or {}).get('tickers') or []
        if str(row.get('ticker')) in per_ticker], 'macro': macro,
        'graph_market_events': [e for e in graph.get('events') or []
                                if e.get('ticker') == 'MARKET'],
        'em_market_724': em.get('market_724') or [], 'market_flashes_raw': rows}
    if live_view is not None:
        full['live'] = {'tickers': live_view['full'], 'requests': live.get('requests') or [],
                        'elapsed_s': live.get('elapsed_s'), 'as_of': live.get('as_of')}
    return {'summary': summary, 'full': full, 'degraded': degraded}


def stale_titles(summary):
    """Title fragments of stale items, for the postflight label check."""
    out = []
    sources = (summary or {}).get('sources') or {}
    for rows in [*((summary or {}).get('tickers') or {}).values(),
                 *((summary or {}).get('live') or {}).values()]:
        for row in rows:
            cite = row.get('cite') or ''
            if '开盘前旧闻' in cite and row.get('title'):
                out.append(str(row['title']))
    if (sources.get('em_news') or {}).get('stale'):
        out += [str(r.get('title')) for r in (summary or {}).get('morning_flashes') or []
                if r.get('title')]
    return out
