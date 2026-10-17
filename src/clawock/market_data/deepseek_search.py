"""DeepSeek Search / Fetch: web search any harness or model may call.

Source access only (docs/reference/tool-operations.md § DeepSeek Search/Fetch):
`search()` and `fetch()` are one request each to DeepSeek's own index and
fetcher, answering normalised rows — or raising `SearchError`, so a caller can
say the search did not run instead of printing an empty list as "no news".
Grading, windows, labels and per-call budgets belong to the callers
(`evidence.live_sources`, `evidence.web_search`, which runs it side by side
with Tavily for `evidence.anomaly_search` and `clawock web-search`).

kcn 2026-10-17: like Tavily, but usable everywhere — every slot, every entry,
no credit budget; a source next to Tavily, not its replacement or backup. What still binds is the account: **5 QPS for Search and 5 for
Fetch, per account, whichever key**. Every request on this host therefore
passes one cross-process gate (`_Gate`, a lock file per endpoint), so an
intraday slot, the brief and a model's own `clawock web-search` cannot together
exceed it. Price: ¥5 per 1,000 successful requests each (an empty search or a
fetch without text is free). 408/429/5xx are retried inside the caller's deadline; 400/401/402/
403/404/413 are not (the API's own rule: do not repeat an unchanged request).

The key is DeepSeek's chat key: `DEEPSEEK_API_KEY` from the environment
(OpenClaw exports its `env` block, which holds it, to every cron and session),
else the dsh credentials seam's `refs:` block — the same value. Never logged.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from clawock.sessions import HKT

#: DeepSeek's index dates by the Beijing day; Hong Kong keeps the same offset.
_CST = HKT

BASE_URL = 'https://api.deepseek.com/v1/tools'
QPS = 5
TIMEOUT_S = 8
MAX_COUNT = 50
RETRY_STATUSES = (408, 429, 500, 502, 503, 504)
DSH_CREDENTIALS = Path(os.environ.get('CLAWOCK_DSH_CREDENTIALS',
                                      Path.home() / '.dsh' / '.credentials.yaml'))
GATE_DIR = Path(os.environ.get('CLAWOCK_DEEPSEEK_GATE_DIR',
                               Path.home() / '.cache' / 'clawock' / 'deepseek-search'))
#: DeepSeek stamps a page it knows only the day of at 00:00 Beijing time.
_DAY_ONLY = re.compile(r'T16:00:00(?:\.0+)?(?:Z|\+00:00)$')


class SearchError(RuntimeError):
    """The request did not answer: no key, refused, rate-limited, down, timed out.

    `status` is the HTTP code (None for a local or network failure) and
    `reason` a short label safe to print on a card."""

    def __init__(self, reason, status=None):
        super().__init__(reason)
        self.reason, self.status = reason, status


# ── Key ───────────────────────────────────────────────────────────────────────

def _dsh_ref(name):
    """`name` from the dsh credentials seam's top-level `refs:` mapping."""
    try:
        lines = DSH_CREDENTIALS.read_text(encoding='utf-8').splitlines()
    except OSError:
        return None
    in_refs = False
    for line in lines:
        if re.match(r'^refs:\s*$', line):
            in_refs = True
            continue
        if not in_refs:
            continue
        if re.match(r'^\S', line):
            break
        match = re.match(r'^\s+([A-Z][A-Z0-9_]*):\s*(.*?)\s*$', line)
        if match and match.group(1) == name:
            value = re.sub(r'^([\'"])(.*)\1$', r'\2', match.group(2))
            return value or None
    return None


def api_key():
    """DeepSeek's key, or None: the environment first, then the dsh seam."""
    return os.environ.get('DEEPSEEK_API_KEY') or _dsh_ref('DEEPSEEK_API_KEY')


# ── Account-wide rate gate ────────────────────────────────────────────────────

class _Gate:
    """At most `qps` request starts per second on this host, across processes.

    The lock file holds the start times of the last second; a caller holds the
    lock while it waits, so waits queue in order. A gate that cannot be opened
    (read-only home) degrades to no gate — the 429 retry still bounds it."""

    def __init__(self, endpoint, qps=QPS, *, clock=time.time, sleep=time.sleep):
        self.path, self.qps = GATE_DIR / f'{endpoint}.json', qps
        self.clock, self.sleep = clock, sleep

    def wait(self, deadline):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(self.path, 'a+', encoding='utf-8')
        except OSError:
            return
        with handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.seek(0)
            try:
                starts = [float(t) for t in json.loads(handle.read() or '[]')]
            except (ValueError, TypeError):
                starts = []
            now = self.clock()
            starts = [t for t in starts if now - t < 1.0]
            if len(starts) >= self.qps:
                pause = starts[-self.qps] + 1.0 - now
                if time.monotonic() + pause > deadline:
                    raise SearchError('本机限速排队超时', 429)
                self.sleep(max(0.0, pause))
                now = self.clock()
                starts = [t for t in starts if now - t < 1.0]
            starts.append(now)
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(starts[-self.qps:]))


def _post(endpoint, body, key, timeout):
    request = urllib.request.Request(
        f'{BASE_URL}/{endpoint}', data=json.dumps(body).encode('utf-8'), method='POST',
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))


_REASONS = {400: '请求参数无效', 401: 'key无效', 402: '余额不足', 403: '被安全策略拒绝',
            404: '页面无可用正文', 408: '超时', 413: '请求过大', 429: '超出QPS',
            500: '服务端错误', 502: '服务端错误', 503: '服务端错误', 504: '下游超时'}


def call(endpoint, body, *, timeout=TIMEOUT_S, budget_s=None, key=None, post=None,
         gate=None, sleep=time.sleep):
    """POST one tool request; the parsed JSON body or `SearchError`.

    `budget_s` (default `timeout`) is the whole call including gate waits and
    retries; `post(endpoint, body, key, timeout)` replaces the network (tests)."""
    key = key or api_key()
    if not key:
        raise SearchError('缺少DEEPSEEK_API_KEY')
    post = post or _post
    gate = gate if gate is not None else _Gate(endpoint)
    deadline = time.monotonic() + (budget_s or timeout)
    attempt = 0
    while True:
        attempt += 1
        if gate:
            gate.wait(deadline)
        left = deadline - time.monotonic()
        if left <= 0.2:
            raise SearchError('超时')
        try:
            return post(endpoint, body, key, min(timeout, left))
        except urllib.error.HTTPError as exc:
            status, error = exc.code, SearchError(_REASONS.get(exc.code, f'HTTP {exc.code}'),
                                                  exc.code)
        except (OSError, ValueError) as exc:  # URLError, timeout, bad JSON
            status, error = None, SearchError(type(exc).__name__)
        retryable = status in RETRY_STATUSES or status is None
        pause = 0.4 * attempt
        if not retryable or attempt >= 3 or time.monotonic() + pause + 0.5 > deadline:
            raise error
        sleep(pause)


# ── Normalisation ─────────────────────────────────────────────────────────────

def _date_fields(value):
    """`published_at` for a real timestamp, `filed_date` for a day-only one."""
    if not value:
        return {}
    text = str(value)
    if _DAY_ONLY.search(text):
        try:
            day = datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(_CST)
        except ValueError:
            return {}
        return {'filed_date': day.date().isoformat()}
    try:
        when = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return {}
    return {'published_at': (when if when.tzinfo else when.replace(tzinfo=timezone.utc))
            .isoformat()}


def normalize(result):
    """One search hit as `{title, url, publisher, published_at | filed_date,
    snippet, summary, content?, authority, rerank_score}`; None without title/url.

    `authority` is DeepSeek's 0–4 (−1 unknown) and `rerank_score` its 0–3
    relevance; both are kept as reported, not turned into our grade."""
    title, url = str(result.get('title') or '').strip(), str(result.get('url') or '').strip()
    if not title or not url:
        return None
    row = {'title': title, 'url': url, **_date_fields(result.get('date'))}
    if result.get('site_name'):
        row['publisher'] = str(result['site_name'])[:40]
    for key, limit in (('snippet', 240), ('summary', 900), ('content', None)):
        text = str(result.get(key) or '').strip()
        if text:
            row[key] = text if limit is None else text[:limit]
    for key in ('authority', 'rerank_score'):
        if isinstance(result.get(key), (int, float)):
            row[key] = round(float(result[key]), 2) if key == 'rerank_score' else int(result[key])
    return row


_QUOTE_PAGE = re.compile(r'stock price|price, quote|quote & news|stock quote|股价、新闻|股價、新聞|'
                         r'最新价格|行情走势|实时行情|个股概[览要]|股票价格|報價和記錄', re.I)


def is_quote_page(row):
    """A ticker's quote/profile page, not an article: the index dates it by
    the crawl day, so it would read as today's news. Titles that are a name
    and a code and nothing else count too."""
    title = str(row.get('title') or '')
    return bool(_QUOTE_PAGE.search(title)) or len(re.sub(r'[\W\d_]', '', title)) <= 6


def search(query, *, count=10, need_content=False, ori_question=None, timeout=TIMEOUT_S,
           budget_s=None, min_score=0.0, **kwargs):
    """Search hits for `query` (DeepSeek syntax: site:, -site:, "…", lang:,
    after:, before:). An empty list is a search that ran and found nothing."""
    query = str(query or '').strip()[:128]
    if not query:
        raise SearchError('空查询', 400)
    body = {'query': query, 'count': max(1, min(MAX_COUNT, int(count))),
            'need_content': bool(need_content)}
    if ori_question:
        body['ori_question'] = str(ori_question)[:128]
    answer = call('search', body, timeout=timeout, budget_s=budget_s, **kwargs)
    rows = [normalize(r) for r in (answer or {}).get('results') or [] if isinstance(r, dict)]
    return [r for r in rows if r and r.get('rerank_score', 3) >= min_score]


def fetch(url, *, timeout=20, budget_s=None, **kwargs):
    """`{title, content}` (Markdown) for one page. JS-rendered or anti-crawl
    pages (雪球, 富途, 公众号) often answer 404 — say so, never "no news"."""
    answer = call('fetch', {'url': str(url)}, timeout=timeout, budget_s=budget_s, **kwargs)
    return {'title': str((answer or {}).get('title') or ''),
            'content': str((answer or {}).get('content') or '')}
