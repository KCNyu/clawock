"""Tier 3 of the intraday information lane: one web search per new anomaly.

docs/architecture/intraday-agent.md §6. The mover probe reads exchange/SEC
filings and broker/media feeds; when those have nothing, "why did 07226 fall
4%" had no answer beyond 「暂无法归因」. The host already pays for Tavily
(`skills/tavily-search`, OpenClaw's own search provider) and the SKILLs kept it
out of intraday slots because the model would call it every slot. The harness
calls it instead, only when `anomalies` is non-empty, **once per ticker per
session** (the cache below), in the `intraday` bucket.

Budget: the bucket is 120 credits a month; 18 slots × 22 days is ~400, so one
query per slot would run out in a week. Distinct movers per session are what is
spent — see `monthly_estimate`.

A search that cannot run (no key, budget exhausted, network, timeout) or finds
nothing is returned as such and the card states it on a ⛔ line: not searched
and "no news" must never look the same.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

BUCKET = 'intraday'
MONTHLY_CAP = 120
TIMEOUT_S = 25
MAX_ITEMS = 3
PRIMARY_HOSTS = ('hkexnews.hk', 'sec.gov', 'nasdaqtrader.com')
AUTHORITATIVE_HOSTS = ('reuters.com', 'bloomberg.com', 'wsj.com', 'ft.com', 'cnbc.com',
                       'caixin.com', 'yicai.com', 'stcn.com', 'cls.cn', 'eastmoney.com',
                       'scmp.com', 'aastocks.com', 'etnet.com.hk', 'hkej.com')


def _grade(url):
    host = re.sub(r'^https?://', '', str(url or '')).split('/')[0].lower()
    if any(host.endswith(h) for h in PRIMARY_HOSTS):
        return 'primary'
    if any(host.endswith(h) for h in AUTHORITATIVE_HOSTS):
        return 'authoritative'
    return 'soft'


def parse_output(text):
    """(status, reason, items) from search.mjs stdout."""
    text = text or ''
    if '## Web search unavailable' in text:
        reason = text.split('## Web search unavailable', 1)[1].strip().split('\n')[0]
        return 'unavailable', reason[:160], []
    items = []
    for match in re.finditer(r'^- \*\*(.+?)\*\*[^\n]*\n\s+(https?://\S+)\n(?:\s+(.+))?',
                             text, re.MULTILINE):
        title, url, snippet = match.group(1), match.group(2), (match.group(3) or '')
        items.append({'title': title.strip()[:120], 'url': url,
                      'one_liner': snippet.strip()[:120], 'grade': _grade(url)})
        if len(items) >= MAX_ITEMS:
            break
    return ('ok' if items else 'empty'), None, items


def query_for(ticker, market, name=None, target=None):
    """What to ask: the issuer a fund looks through to, or its index/theme."""
    target = target or {}
    if target.get('kind') == 'index_fund':
        subject = (target.get('theme_terms') or [target.get('via') or ticker])[0]
        return f'{subject}指数 今日 走势 原因' if market == 'hk' else f'{subject} index move today'
    subject = target.get('issuer') or ticker
    if market == 'hk':
        return f'{name or ""} {subject} 港股 今日 股价 异动 原因'.strip()
    return f'{subject} {name or ""} stock move today why'.strip()


def _default_run(workspace, query):
    script = Path(workspace) / 'skills' / 'tavily-search' / 'scripts' / 'search.mjs'
    if not script.exists():
        return 'unavailable', 'tavily-search skill not installed', []
    try:
        done = subprocess.run(
            ['node', str(script), query, '-n', str(MAX_ITEMS), '--topic', 'news',
             '--days', '1', '--bucket', BUCKET],
            capture_output=True, text=True, timeout=TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 'unavailable', f'{type(exc).__name__}', []
    return parse_output(done.stdout)


def search_anomalies(workspace, market, session, anomalies, *, names=None, targets=None,
                     run=None, now=None, cache_path=None):
    """`{ticker: result}` for this slot's anomalies; at most one query per
    ticker per session, the rest served from the cache. Never raises."""
    now = now or datetime.now(timezone.utc)
    run = run or (lambda query: _default_run(workspace, query))
    cache_path = Path(cache_path or (Path(workspace) / 'memory' / '.tmp'
                                     / f'intraday-anomaly-search-{market}.json'))
    try:
        cache = json.loads(cache_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        cache = {}
    if cache.get('session') != session:
        cache = {'session': session, 'tickers': {}}
    out = {}
    for anomaly in anomalies or []:
        ticker = str(anomaly.get('ticker') or '')
        if not ticker or ticker in out:
            continue
        cached = cache['tickers'].get(ticker)
        # A search that could not run is retried next slot; one that ran
        # (found or empty) is this session's answer.
        if cached and cached.get('status') in ('ok', 'empty'):
            out[ticker] = {**cached, 'cached': True}
            continue
        query = query_for(ticker, market, (names or {}).get(ticker),
                          (targets or {}).get(ticker))
        try:
            status, reason, items = run(query)
        except Exception as exc:  # noqa: BLE001 — enrichment never reds a slot
            status, reason, items = 'unavailable', type(exc).__name__, []
        result = {'status': status, 'query': query, 'as_of': now.isoformat(timespec='minutes'),
                  'items': items, 'bucket': BUCKET, 'cached': False}
        if reason:
            result['reason'] = reason
        cache['tickers'][ticker] = result
        out[ticker] = result
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding='utf-8')
    except OSError:
        pass
    return out


def degraded_lines(results):
    """Tickers whose search did not answer, for the card's ⛔ line."""
    bad = [f"{ticker}（{'未取到' if r['status'] == 'unavailable' else '无结果'}）"
           for ticker, r in (results or {}).items() if r.get('status') in ('unavailable', 'empty')]
    return bad


def monthly_estimate(distinct_movers_per_session, sessions_per_month=22, markets=2):
    """Credits a month at one query per distinct mover per session per market."""
    return distinct_movers_per_session * sessions_per_month * markets
