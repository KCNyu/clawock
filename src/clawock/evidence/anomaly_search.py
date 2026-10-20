"""Tier 3 of the intraday information lane: web search per anomaly, two providers.

docs/architecture/intraday-agent.md §6. The mover probe reads exchange/SEC
filings and broker/media feeds; when those have nothing, "why did 07226 fall
4%" had no answer beyond 「暂无法归因」. The harness asks the web instead, only
when `anomalies` is non-empty — through **DeepSeek and Tavily side by side**
(`evidence.web_search`; kcn 2026-10-18: parallel sources, neither the other's
backup). Each provider has its own call policy, set by its own limit:

* **DeepSeek** — no credit budget, 5 QPS per account (the host-wide gate in
  `market_data.deepseek_search`). Asked again for a still-moving ticker once
  its last answer is `DEEPSEEK_TTL_S` old, so every slot sees what was
  published since the previous one; a failed refresh keeps the session's last
  good rows and says it failed.
* **Tavily** — the `intraday` bucket is 120 credits a month; 18 slots × 22 days
  is ~400, so one query per slot would run out in a week. Asked **once per
  ticker per session** (a search that could not run is retried next slot); see
  `monthly_estimate`. DeepSeek being cheap does not loosen this.

Both are asked in the same slot for a ticker that needs them; neither waits on
the other's answer. A provider that cannot run (no key, budget, 429, network)
or finds nothing is reported as that provider's state on the card's ⛔ line —
not searched and "no news" must never look the same, and one provider's gap
is never the other's.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from clawock.evidence import web_search
from clawock.evidence.web_search import parse_tavily as _parse_tavily
from clawock.safe_io import safe_write_json

BUCKET = 'intraday'
MONTHLY_CAP = 120
TIMEOUT_S = 25
MAX_ITEMS = 3
DEEPSEEK_TTL_S = 25 * 60
DEEPSEEK_TIMEOUT_S = 8


def parse_output(text):
    """(status, reason, items) from Tavily's search.mjs stdout."""
    return _parse_tavily(text, limit=MAX_ITEMS)


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


def _since(session):
    """The day before the session (Beijing days in DeepSeek's index): the
    evening before an HK open and a US session's own afternoon both count."""
    try:
        day = date.fromisoformat(str(session)[-10:])
    except ValueError:
        day = datetime.now(timezone.utc).date()
    return (day - timedelta(days=1)).isoformat()


def _tavily_run(workspace):
    def run(query):
        return web_search.run_tavily(query, bucket=BUCKET, workspace=workspace,
                                     count=MAX_ITEMS, days=1, timeout=TIMEOUT_S)
    return run


def _deepseek_run(session):
    def run(query, question=None):
        # The operator goes last and must survive DeepSeek's 128-character cap.
        return web_search.run_deepseek(f'{query[:100]} after:{_since(session)}', count=MAX_ITEMS + 2,
                                       ori_question=question, timeout=DEEPSEEK_TIMEOUT_S)
    return run


def _question(anomaly, name, ticker):
    move = anomaly.get('move_pct')
    if not isinstance(move, (int, float)):
        return None
    return f"为什么{name or ticker}今天{'涨' if move > 0 else '跌'}了{abs(move):.1f}%"


def _due(cached, provider, now):
    """Whether this slot asks `provider` again for a ticker."""
    if not cached:
        return True
    if cached.get('status') == 'unavailable':
        return True
    if provider == 'tavily':
        return False  # once per ticker per session
    try:
        asked = datetime.fromisoformat(cached['as_of'])
    except (KeyError, TypeError, ValueError):
        return True
    return (now - asked).total_seconds() >= DEEPSEEK_TTL_S


def _answer(status, reason, items, query, now):
    out = {'status': status, 'query': query, 'as_of': now.isoformat(timespec='minutes'),
           'items': items[:MAX_ITEMS], 'cached': False}
    if reason:
        out['reason'] = reason
    return out


def _combined(providers):
    """The ticker's overall state: ok if any provider found rows; unavailable
    only when none ran; otherwise empty."""
    states = [p.get('status') for p in providers.values()]
    if any(p.get('items') or p.get('item_count') for p in providers.values()):
        return 'ok'
    if states and all(s == 'unavailable' for s in states):
        return 'unavailable'
    return 'empty'


def search_anomalies(workspace, market, session, anomalies, *, names=None, targets=None,
                     runners=None, providers=web_search.PROVIDERS_ORDER, now=None,
                     cache_path=None):
    """`{ticker: result}` for this slot's anomalies. Never raises.

    `result` is `{status, items, providers: {deepseek: {...}, tavily: {...}},
    bucket, cached}`: `items` every provider's rows (each tagged `provider`,
    grade first), `providers[p]` that provider's own `{status, reason?, query,
    as_of, items, cached}`. `runners[p]` replaces a provider (tests)."""
    now = now or datetime.now(timezone.utc)
    runners = {'deepseek': _deepseek_run(session), 'tavily': _tavily_run(workspace),
               **(runners or {})}
    cache_path = Path(cache_path or (Path(workspace) / 'memory' / '.tmp'
                                     / f'intraday-anomaly-search-{market}.json'))
    try:
        cache = json.loads(cache_path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        cache = {}
    except (OSError, ValueError) as error:
        # A cache that is there but unreadable means this session's movers
        # are searched again (and Tavily is billed again), so say it.
        print(f'⚠ anomaly-search cache unreadable ({cache_path}): {error}', file=sys.stderr)
        cache = {}
    if cache.get('session') != session or cache.get('schema') != 2:
        cache = {'schema': 2, 'session': session, 'tickers': {}}

    jobs = {}  # (ticker, provider) -> (query, question)
    wanted = []
    for anomaly in anomalies or []:
        ticker = str(anomaly.get('ticker') or '')
        if not ticker or ticker in wanted:
            continue
        wanted.append(ticker)
        name = (names or {}).get(ticker)
        query = query_for(ticker, market, name, (targets or {}).get(ticker))
        held = (cache['tickers'].get(ticker) or {}).get('providers') or {}
        for provider in providers:
            if provider in runners and _due(held.get(provider), provider, now):
                jobs[(ticker, provider)] = (query, _question(anomaly, name, ticker))

    def call(key):
        ticker, provider = key
        query, question = jobs[key]
        try:
            if provider == 'deepseek':
                status, reason, items = runners[provider](query, question)
            else:
                status, reason, items = runners[provider](query)
        except Exception as exc:  # noqa: BLE001 — enrichment never reds a slot
            status, reason, items = 'unavailable', type(exc).__name__, []
        return key, _answer(status, reason, [{**i, 'provider': provider} for i in items],
                            query, now)

    # One lane per provider: DeepSeek's requests go out together (the gate
    # spaces them); Tavily's stay one after another, as its ledger expects.
    def lane(provider):
        keys = [k for k in jobs if k[1] == provider]
        if provider == 'deepseek':
            with ThreadPoolExecutor(max_workers=max(1, min(4, len(keys)))) as pool:
                return list(pool.map(call, keys))
        return [call(k) for k in keys]

    fresh = {}
    if jobs:
        with ThreadPoolExecutor(max_workers=len(providers)) as pool:
            for answers in pool.map(lane, providers):
                fresh.update(dict(answers))

    out = {}
    for ticker in wanted:
        entry = cache['tickers'].setdefault(ticker, {'providers': {}})
        held = entry.setdefault('providers', {})
        view = {}
        for provider in providers:
            answer = fresh.get((ticker, provider))
            old = held.get(provider)
            if answer is None:
                if old:
                    view[provider] = {**old, 'cached': True}
                continue
            if answer['status'] == 'unavailable' and old and old.get('items'):
                # The refresh failed: the session's last rows stand, and the
                # failure is still this provider's state for this slot.
                answer = {**answer, 'items': old['items'], 'items_as_of': old.get('as_of')}
            held[provider] = answer
            view[provider] = answer
        # Rows once, in `items` (each says its provider); `providers` keeps
        # each provider's own state and how many rows it gave.
        states = {p: {**{k: v for k, v in answer.items() if k != 'items'},
                      'item_count': len(answer.get('items') or [])}
                  for p, answer in view.items()}
        out[ticker] = {'status': _combined(view), 'items': web_search.merged_items(view),
                       'providers': states, 'bucket': BUCKET,
                       'cached': all(v.get('cached') for v in view.values()) if view else False}
    try:
        safe_write_json(str(cache_path), cache, indent=1)
    except OSError as error:
        # The cache is an optimisation and this slot's answers stand, but the
        # next slot searches every mover again, so say it.
        print(f'⚠ anomaly-search cache not written ({cache_path}): {error}', file=sys.stderr)
    return out


def degraded_lines(results):
    """Per ticker, the providers whose search did not answer, for the card's ⛔
    line: `07226（DeepSeek未取到（超出QPS）、Tavily无结果）`."""
    bad = []
    for ticker, result in (results or {}).items():
        providers = result.get('providers')
        if providers is None:  # a single-answer result (a lane that crashed)
            if result.get('status') in ('unavailable', 'empty'):
                bad.append(f"{ticker}（{'未取到' if result['status'] == 'unavailable' else '无结果'}）")
            continue
        phrases = web_search.degraded(providers)
        if phrases:
            bad.append(f"{ticker}（{'、'.join(phrases)}）")
    return bad


def monthly_estimate(distinct_movers_per_session, sessions_per_month=22, markets=2):
    """Tavily credits a month at one query per distinct mover per session per
    market (DeepSeek is per request, not budgeted in credits)."""
    return distinct_movers_per_session * sessions_per_month * markets
