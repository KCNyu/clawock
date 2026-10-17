"""Web search through DeepSeek and Tavily side by side.

docs/reference/tool-operations.md § Web search providers. kcn 2026-10-18: the
two are parallel sources used together — neither is the other's backup and
neither is retired. One call asks every provider it names **at the same time**;
each answers on its own `{status, reason?, items}` and its rows carry
`provider`, so a reader can always tell which said what, and one provider
failing, rate-limited or empty says nothing about the other.

Each provider keeps its own limit, enforced where it is spent:

| provider | access | limit | where it is enforced |
|---|---|---|---|
| `deepseek` | `market_data.deepseek_search` | 5 QPS per account (Search and Fetch each); ¥5/1,000 successful requests | the host-wide gate in that module |
| `tavily` | `skills/tavily-search/scripts/search.mjs` | 1,000 credits a month in buckets (`intraday` 120) | the script's credit ledger, plus each caller's own call policy |

So a caller decides per provider how often it asks — `anomaly_search` asks
DeepSeek every slot and Tavily once per ticker per session — never "Tavily
only when DeepSeek fails".
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from clawock.sessions import HKT

PROVIDERS_ORDER = ('deepseek', 'tavily')
TAVILY_TIMEOUT_S = 25


@dataclass(frozen=True)
class Provider:
    label: str
    limit: str


PROVIDERS = {
    'deepseek': Provider('DeepSeek', '5 QPS per account; no credit budget'),
    'tavily': Provider('Tavily', '1000 credits/month shared, by --bucket'),
}


def _grade(url):
    from clawock.evidence.live_sources import host_grade  # noqa: PLC0415

    return host_grade(url)


# ── Providers: each `(query, **options) -> (status, reason, items)` ───────────

def run_deepseek(query, *, count=5, days=None, ori_question=None, timeout=8, **_k):
    """`ok`/`empty` with rows, or `unavailable` with the reason. Never raises."""
    from clawock.market_data import deepseek_search  # noqa: PLC0415

    if days and 'after:' not in query:
        since = (datetime.now(HKT) - timedelta(days=days)).date()
        # The operator goes last and must survive DeepSeek's 128-character cap.
        query = f'{query[:100]} after:{since.isoformat()}'
    try:
        rows = deepseek_search.search(query, count=count, ori_question=ori_question,
                                      timeout=timeout)
    except deepseek_search.SearchError as exc:
        return 'unavailable', exc.reason, []
    items = []
    for row in rows:
        if deepseek_search.is_quote_page(row):
            continue
        items.append({'title': row['title'][:120], 'url': row['url'],
                      'one_liner': str(row.get('snippet') or row.get('summary') or '')[:160],
                      'grade': _grade(row['url']),
                      **{k: row[k] for k in ('publisher', 'published_at', 'filed_date',
                                             'authority', 'rerank_score') if k in row}})
    return ('ok' if items else 'empty'), None, items


def parse_tavily(text, limit=5):
    """(status, reason, items) from `search.mjs` stdout (Markdown)."""
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
        if len(items) >= limit:
            break
    return ('ok' if items else 'empty'), None, items


def run_tavily(query, *, bucket, workspace=None, count=5, days=None, topic='news',
               timeout=TAVILY_TIMEOUT_S, **_k):
    """One `search.mjs` call charged to `bucket` (its ledger refuses past the
    bucket's monthly cap and says so). Never raises."""
    from clawock.workspace import workspace_root  # noqa: PLC0415

    if not bucket:
        return 'unavailable', 'no Tavily bucket given', []
    script = Path(workspace or workspace_root()) / 'skills' / 'tavily-search' / 'scripts' / 'search.mjs'
    if not script.exists():
        return 'unavailable', 'tavily-search skill not installed', []
    argv = ['node', str(script), query, '-n', str(count), '--topic', topic, '--bucket', bucket]
    if days and topic == 'news':
        argv += ['--days', str(days)]
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 'unavailable', type(exc).__name__, []
    return parse_tavily(done.stdout, limit=count)


RUNNERS = {'deepseek': run_deepseek, 'tavily': run_tavily}


def search_all(query, *, providers=PROVIDERS_ORDER, runners=None, options=None):
    """`{provider: {status, reason?, items, elapsed_s}}`, every provider asked at
    once. `options[provider]` are that provider's own keyword arguments (count,
    days, bucket…). Never raises; a provider's failure stays its own."""
    runners = {**RUNNERS, **(runners or {})}
    options = options or {}

    def one(name):
        began = time.monotonic()
        try:
            status, reason, items = runners[name](query, **(options.get(name) or {}))
        except Exception as exc:  # noqa: BLE001 — one provider never sinks another
            status, reason, items = 'unavailable', type(exc).__name__, []
        answer = {'status': status, 'items': [{**i, 'provider': name} for i in items],
                  'elapsed_s': round(time.monotonic() - began, 2)}
        if reason:
            answer['reason'] = reason
        return name, answer

    names = [p for p in providers if p in runners]
    if not names:
        return {}
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        return dict(pool.map(one, names))


def merged_items(answers, *, per_provider=None):
    """Every provider's rows in one list, grade first (primary, authoritative,
    soft), each still tagged with its `provider`; a URL two providers found is
    listed once with both names in `providers`."""
    order = {'primary': 0, 'authoritative': 1, 'soft': 2}
    by_url, out = {}, []
    for name in PROVIDERS_ORDER:
        for item in ((answers or {}).get(name) or {}).get('items', [])[:per_provider]:
            seen = by_url.get(item['url'])
            if seen is not None:
                seen.setdefault('providers', [seen['provider']]).append(name)
                continue
            row = dict(item)
            by_url[row['url']] = row
            out.append(row)
    out.sort(key=lambda r: order.get(r.get('grade'), 3))
    return out


def degraded(answers):
    """`DeepSeek未取到（超出QPS）`-style phrases, one per provider that did not
    answer or found nothing — for that provider only."""
    out = []
    for name in PROVIDERS_ORDER:
        answer = (answers or {}).get(name)
        if not answer or answer.get('status') not in ('unavailable', 'empty'):
            continue
        label = PROVIDERS[name].label
        if answer['status'] == 'unavailable':
            reason = str(answer.get('reason') or '').split('.')[0][:60]
            out.append(f'{label}未取到' + (f'（{reason}）' if reason else ''))
        else:
            out.append(f'{label}无结果')
    return out


# ── `clawock web-search` ──────────────────────────────────────────────────────

def _markdown(query, answers):
    lines = [f'# Web search: {query}', '']
    for name, answer in answers.items():
        label = PROVIDERS[name].label
        head = f"## {label} — {answer['status']}"
        if answer.get('reason'):
            head += f"（{answer['reason']}）"
        lines += [head, '']
        for item in answer['items']:
            meta = ' · '.join(str(x) for x in (
                item.get('publisher'), (item.get('published_at') or item.get('filed_date') or '')[:16],
                item.get('grade')) if x)
            lines += [f"- **{item['title']}** ({meta})", f"  {item['url']}",
                      f"  {item.get('one_liner') or ''}".rstrip(), '']
        if answer['status'] == 'empty':
            lines += ['(searched; no results)', '']
        if answer['status'] == 'unavailable':
            lines += [f'(not searched — {label} was not reached; this is not "no news")', '']
    return '\n'.join(lines)


def main(argv=None) -> int:
    """`clawock web-search`: one query to DeepSeek and Tavily at once.

    Each provider's result is printed under its own heading with its own status.
    Exit 0 even when a provider fails — its failure is printed, not raised."""
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog='clawock web-search',
                                     description=__doc__.splitlines()[0])
    parser.add_argument('query', nargs='?', default='',
                        help='search terms (DeepSeek: ≤128 chars, site:/lang:/after: work)')
    parser.add_argument('--providers', default=','.join(PROVIDERS_ORDER),
                        help=f"comma-separated subset of {','.join(PROVIDERS_ORDER)} (default: both)")
    parser.add_argument('-n', '--count', type=int, default=5, help='results per provider')
    parser.add_argument('--days', type=int, default=0, help='only the last N days')
    parser.add_argument('--bucket', default='research',
                        help='Tavily credit bucket: brief/report/intraday/research/extract')
    parser.add_argument('--question', default=None,
                        help='the question behind the search (DeepSeek ori_question)')
    parser.add_argument('--fetch', metavar='URL', default=None,
                        help='fetch one page as Markdown through DeepSeek Fetch instead')
    parser.add_argument('--json', action='store_true', help='JSON instead of Markdown')
    args = parser.parse_args(argv)

    if args.fetch:
        from clawock.market_data import deepseek_search  # noqa: PLC0415
        try:
            page = deepseek_search.fetch(args.fetch)
        except deepseek_search.SearchError as exc:
            print(f'## Fetch unavailable\n\nDeepSeek Fetch: {exc.reason}'
                  f"{f' (HTTP {exc.status})' if exc.status else ''} — not fetched, not empty.")
            return 0
        print(json.dumps(page, ensure_ascii=False) if args.json
              else f"# {page['title']}\n\n{page['content']}")
        return 0
    query = args.query.strip()
    if not query:
        parser.error('a query or --fetch URL is required')
    chosen = tuple(p for p in args.providers.split(',') if p)
    unknown = [p for p in chosen if p not in PROVIDERS]
    if unknown:
        parser.error(f'unknown provider(s): {", ".join(unknown)}')
    days = args.days or None
    answers = search_all(query, providers=chosen, options={
        'deepseek': {'count': args.count, 'days': days, 'ori_question': args.question},
        'tavily': {'count': args.count, 'days': days, 'bucket': args.bucket},
    })
    if args.json:
        print(json.dumps({'query': query, 'providers': answers}, ensure_ascii=False))
    else:
        print(_markdown(query, answers))
    return 0


if __name__ == '__main__':
    sys.exit(main())
