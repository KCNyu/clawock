"""The intraday information lane, tier 0 and one free market-level fetch.

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

Output: `summary` for the core packet (bounded per source), `full` for the
reference layer, `degraded` naming sources that could not be read — which the
card states on a ⛔ line (not fetched is not "no news").
"""
from __future__ import annotations

import json
from datetime import datetime, time as dtime, timezone
from pathlib import Path

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


def collect(workspace, market, tickers, *, now=None, fast_news=None):
    """`{summary, full, degraded}` for this leg's `tickers`. Never raises."""
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
    flashes, flash_status = [], 'ok'
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

    summary = {
        'sources': sources,
        'tickers': per_ticker,
        'attention': attention,
        'market': market_view,
        'market_flashes': flashes,
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
    return {'summary': summary, 'full': full, 'degraded': degraded}


def stale_titles(summary):
    """Title fragments of stale items, for the postflight label check."""
    out = []
    sources = (summary or {}).get('sources') or {}
    for rows in ((summary or {}).get('tickers') or {}).values():
        for row in rows:
            cite = row.get('cite') or ''
            if '开盘前旧闻' in cite and row.get('title'):
                out.append(str(row['title']))
    if (sources.get('em_news') or {}).get('stale'):
        out += [str(r.get('title')) for r in (summary or {}).get('morning_flashes') or []
                if r.get('title')]
    return out
