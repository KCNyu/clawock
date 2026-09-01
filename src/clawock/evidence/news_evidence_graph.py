#!/usr/bin/env python3
"""Normalize news/filings into an expiring evidence graph with confirmation gates.

No article bodies are persisted. The graph stores titles, timestamps, source
metadata and stable hashes. Tavily is not called here; only unresolved,
high-impact nodes are admitted to a small resolution queue.

Writes:
  assets/data/news_evidence_graph.json
  assets/data/news_evidence_history.jsonl
"""

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from clawock import history_store
from clawock.workspace import workspace_root

WS = workspace_root()
POLICY = WS / 'config' / 'news-evidence-policy.json'
PORTFOLIO = WS / 'portfolio.json'
FACTOR_CONFIG = WS / 'config' / 'factor-universe.json'
EM_NEWS = WS / 'assets' / 'data' / 'em_news.json'
US_NEWS = WS / 'assets' / 'data' / 'us_news_digest.json'
SENTIMENT = WS / 'assets' / 'data' / 'sentiment.json'
INFLUENCER = WS / 'assets' / 'data' / 'influencer_feed.json'
CATALYSTS = WS / 'assets' / 'data' / 'catalysts.json'
PEER_RESIDUAL = WS / 'assets' / 'data' / 'peer_residual.json'
CROSS_FACTOR = WS / 'assets' / 'data' / 'cross_sectional_factor.json'
OUT = WS / 'assets' / 'data' / 'news_evidence_graph.json'
HISTORY = WS / 'assets' / 'data' / 'news_evidence_history.jsonl'

HARD_EVENT_TYPES = {
    'filing_10k', 'filing_10q', 'filing_8k', 'regulatory',
    'financing', 'contract', 'product', 'ownership',
}
PRIMARY_SOURCE_TYPES = {
    'sec_filing', 'exchange_announcement', 'issuer_announcement',
    'official_macro_schedule',
}

POSITIVE_WORDS = {
    'beat', 'beats', 'raise', 'raised', 'upgrade', 'upgraded', 'approval',
    'approved', 'contract', 'award', 'buyback', 'record revenue', '获准',
    '中标', '回购', '上调', '增长', '获批', '调入', '纳入',
}
NEGATIVE_WORDS = {
    'miss', 'missed', 'probe', 'investigation', 'fraud', 'lawsuit',
    'downgrade', 'downgraded', 'recall', 'dilution', 'offering', 'default',
    'cut guidance', 'restatement', '减持', '调查', '诉讼', '下调', '召回',
    '亏损', '处罚', '违约', '调出', '剔除',
}

from clawock.safe_io import safe_write_json, safe_write_text


def _load(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {} if default is None else default


def load_policy(path=POLICY):
    policy = _load(path)
    required = {
        'minimum_actionable_reliability', 'minimum_actionable_novelty',
        'expiry_days', 'source_reliability', 'tavily_policy',
    }
    if not required <= set(policy):
        raise ValueError('news evidence policy is incomplete')
    return policy


def normalize_timestamp(value, fallback=None, naive_timezone=timezone.utc):
    """Return UTC ISO timestamp plus input precision."""
    if isinstance(value, (int, float)) and value > 0:
        return {
            'iso': datetime.fromtimestamp(value, tz=timezone.utc).isoformat(),
            'precision': 'second',
        }
    text = str(value or '').strip()
    if text.isdigit() and len(text) >= 9:
        return normalize_timestamp(int(text), fallback=fallback)
    if text:
        candidate = text.replace('Z', '+00:00')
        try:
            parsed = datetime.fromisoformat(candidate)
            precision = 'date' if len(text) == 10 else 'minute'
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=naive_timezone)
            return {'iso': parsed.astimezone(timezone.utc).isoformat(),
                    'precision': precision}
        except ValueError:
            pass
        for fmt in ('%Y/%m/%d %H:%M', '%Y-%m-%d %H:%M',
                    '%a, %d %b %Y %H:%M:%S %Z'):
            try:
                parsed = datetime.strptime(text, fmt).replace(
                    tzinfo=naive_timezone
                )
                return {
                    'iso': parsed.astimezone(timezone.utc).isoformat(),
                    'precision': 'minute',
                }
            except ValueError:
                continue
    if fallback:
        return normalize_timestamp(
            fallback, naive_timezone=naive_timezone
        )
    return {'iso': None, 'precision': 'unknown'}


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:20]


def _event_tokens(title, ticker=''):
    text = str(title or '').lower().replace(str(ticker or '').lower(), ' ')
    text = re.sub(r'https?://\S+', ' ', text)
    text = re.sub(r'\d+(?:\.\d+)?[%亿万mbhk$港美元]*', ' ', text)
    latin = re.findall(r'[a-z][a-z0-9_-]+', text)
    chinese = re.findall(r'[\u3400-\u9fff]{2,}', text)
    # Character bigrams make differently worded Chinese summaries comparable
    # without storing source bodies or requiring a segmentation dependency.
    cjk = [
        chunk[i:i + 2]
        for chunk in chinese
        for i in range(len(chunk) - 1)
    ]
    stop = {
        'the', 'a', 'an', 'and', 'or', 'for', 'to', 'of', 'in', 'on',
        'stock', 'shares', 'company', 'says', 'news', '港股', '公司', '今日',
    }
    tokens = [
        token for token in latin + cjk
        if token not in stop and len(token) > 1
    ]
    return set(tokens)


def novelty_cluster(title, ticker, event_type):
    tokens = _event_tokens(title, ticker)
    if not tokens:
        compact = ''.join(
            re.findall(r'[\w\u3400-\u9fff]', str(title or '').lower())
        )
        tokens = [compact[:80]] if compact else ['untitled']
    signature = f'{event_type}|{"|".join(sorted(tokens)[:40])}'
    return _digest(signature)


def semantically_similar(left, right):
    if left.get('ticker') != right.get('ticker'):
        return False
    if left.get('event_type') != right.get('event_type'):
        return False
    left_tokens = _event_tokens(left.get('title'), left.get('ticker'))
    right_tokens = _event_tokens(right.get('title'), right.get('ticker'))
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    containment = overlap / min(len(left_tokens), len(right_tokens))
    return overlap >= 3 and (
        overlap / union >= 0.22 or containment >= 0.42
    )


def event_id(ticker, event_type, primary_source, published_at, event_time,
             cluster):
    key = '|'.join([
        str(ticker), str(event_type), str(primary_source),
        str(published_at), str(event_time), str(cluster),
    ])
    return f'evt_{_digest(key)}'


def classify_event(title, explicit=None):
    if explicit:
        return explicit
    text = str(title or '').lower()
    rules = (
        ('regulatory', ('sec ', 'probe', 'investigation', '监管', '调查', '处罚')),
        ('financing', ('offering', 'convertible', 'notes', '融资', '票据', '增发')),
        ('contract', ('contract', 'award', '订单', '中标', '合同')),
        ('product', ('launch', 'release', 'recall', '测试', '发布', '召回')),
        ('analyst_rating', ('upgrade', 'downgrade', 'price target', '覆盖', '评级')),
        ('ownership', ('stake', 'holding', '持股', '减持', '增持')),
        # Southbound/index membership changes. Deliberately NOT in
        # HARD_EVENT_TYPES: escalation additionally requires a negative
        # direction, and widening high_impact here would quietly start
        # escalating removals — a policy change, not a classification fix.
        ('index_inclusion', ('港股通', '沪股通', '深股通', '标的名单',
                             'stock connect', 'index inclusion')),
        ('price_move', ('涨超', '跌幅', 'shares rise', 'shares fall')),
        ('sector_flow', ('sector', '板块', 'etf主力', '资金流入')),
    )
    for event_type, words in rules:
        if any(word in text for word in words):
            return event_type
    return 'other'


def classify_impact(title):
    text = str(title or '').lower()
    positive = any(word in text for word in POSITIVE_WORDS)
    negative = any(word in text for word in NEGATIVE_WORDS)
    if positive and not negative:
        return 'positive'
    if negative and not positive:
        return 'negative'
    if positive and negative:
        return 'conflicting'
    return 'unknown'


def source_type(origin='', source='', url='', title=''):
    domain = (urlparse(url or '').hostname or '').lower().rstrip('.')
    joined = f'{origin} {source} {domain}'.lower()
    is_sec_host = domain == 'sec.gov' or domain.endswith('.sec.gov')
    if is_sec_host or origin == 'sec_filing':
        return 'sec_filing'
    exchange_cues = (
        'announcement', 'circular', 'notice', 'results', '公告', '通告', '業績',
    )
    if ('hkexnews' in joined or 'exchange announcement' in joined
            or (
                'hkex.com.hk' in joined
                and any(cue in str(title or '').lower()
                        for cue in exchange_cues)
            )):
        return 'exchange_announcement'
    if origin in ('issuer', 'issuer_announcement'):
        return 'issuer_announcement'
    if origin == 'official_macro_schedule':
        return 'official_macro_schedule'
    if 'reuters' in joined or 'bloomberg' in joined:
        return 'reuters_bloomberg_wire'
    if origin == 'finnhub':
        return 'finnhub_syndication'
    if origin == 'eastmoney-search':
        return 'eastmoney_company'
    if origin == 'eastmoney-724':
        return 'market_fast_news'
    if origin == 'gnews-rss':
        return 'google_news_rss'
    return 'llm_digest_legacy'


def make_event(policy, *, ticker, title, published_at, origin,
               source='', url='', event_type=None, event_time=None,
               reported_ticker=None, metadata=None):
    # Eastmoney emits timezone-naive China timestamps. Treating those as UTC
    # moves the evidence eight hours into the future and corrupts both cutoff
    # and decay. Other current producers either include an offset/RFC zone or
    # use UTC; keep their existing interpretation.
    source_timezone = (
        timezone(timedelta(hours=8))
        if str(origin or '').startswith('eastmoney') else timezone.utc
    )
    published = normalize_timestamp(
        published_at, naive_timezone=source_timezone
    )
    event_ts = normalize_timestamp(event_time) if event_time else published
    kind = classify_event(title, event_type)
    src_type = source_type(origin, source, url, title)
    primary_source = (
        urlparse(url).netloc or source or origin or 'unknown'
    ).lower()
    cluster = novelty_cluster(title, ticker, kind)
    identifier = event_id(
        ticker, kind, primary_source, published['iso'], event_ts['iso'], cluster
    )
    return {
        'event_id': identifier,
        'ticker': ticker,
        'reported_ticker': reported_ticker or ticker,
        'event_type': kind,
        'title': str(title or '')[:240],
        'publication_time': published,
        'event_time': event_ts,
        'primary_source': primary_source,
        'source_type': src_type,
        'source_reliability': policy['source_reliability'][src_type],
        'source_url': url or None,
        'novelty_cluster': cluster,
        'impact_direction': classify_impact(title),
        'metadata': metadata or {},
        'body_persisted': False,
    }


def _underlying_map():
    config = _load(FACTOR_CONFIG)
    return {
        row['ticker']: row['underlying']
        for row in config.get('leveraged_proxies') or []
    }


def collect_em_events(policy, underlying):
    payload = _load(EM_NEWS)
    events = []
    for reported, block in (payload.get('holdings_news') or {}).items():
        ticker = underlying.get(reported, reported)
        for item in block.get('items') or []:
            events.append(make_event(
                policy,
                ticker=ticker,
                reported_ticker=reported,
                title=item.get('title'),
                published_at=item.get('date') or payload.get('generated_at'),
                origin=item.get('origin') or 'eastmoney-search',
                url=item.get('url') or '',
            ))
    for item in payload.get('market_724') or []:
        events.append(make_event(
            policy,
            ticker='MARKET',
            title=item.get('title'),
            published_at=item.get('date') or payload.get('generated_at'),
            origin=item.get('origin') or 'eastmoney-724',
            url=item.get('url') or '',
            event_type='sector_flow',
        ))
    return events


# Bullet-shaped lines only: headings and prose are legitimately skipped.
_BULLET_RE = re.compile(r'\s*[-*\u2022]\s+\S')


def collect_us_news_events(policy, underlying):
    payload = _load(US_NEWS)
    events = []
    evidence = payload.get('raw_news_evidence') or {}
    for reported, items in evidence.items():
        ticker = underlying.get(reported, reported)
        for item in items:
            events.append(make_event(
                policy,
                ticker=ticker,
                reported_ticker=reported,
                title=item.get('headline'),
                published_at=item.get('datetime') or payload.get('generated_at'),
                origin=item.get('origin') or '',
                source=item.get('source') or '',
                url=item.get('url') or '',
            ))
    if events:
        return events
    # Legacy sidecars kept only an LLM digest. Preserve those bullets as weak,
    # explicitly non-primary nodes until the producer starts shipping evidence.
    # #1258: the regex wants `- **TICKER**: text` exactly. Any drift the model
    # produces (no bold, dash instead of colon, an emoji prefix) used to `continue`
    # in silence, so a digest that dropped every event looked identical to a
    # digest with no events. Count the bullets it could not read and say so —
    # only bullet-shaped lines, since headings and prose are legitimately skipped.
    unmatched = 0
    for line in str(payload.get('digest_markdown') or '').splitlines():
        match = re.match(r'\s*-\s+\*\*([^*]+)\*\*:\s*(.+)', line)
        if not match:
            if _BULLET_RE.match(line):
                unmatched += 1
            continue
        reported = match.group(1).split('/')[0].strip()
        ticker = underlying.get(reported, reported)
        events.append(make_event(
            policy,
            ticker=ticker,
            reported_ticker=reported,
            title=match.group(2),
            published_at=payload.get('generated_at'),
            origin='llm_digest_legacy',
        ))
    if unmatched:
        print(f'  ⚠️ news digest: {unmatched} bullet line(s) did not match the '
              f'`- **TICKER**: text` shape — {len(events)} legacy event(s) kept',
              file=sys.stderr)
    return events


def collect_sentiment_news_events(policy, underlying):
    """Import Google News headline metadata, including HK exchange results."""
    payload = _load(SENTIMENT)
    events = []
    for block in payload.get('tickers') or []:
        reported = block.get('ticker')
        ticker = underlying.get(reported, reported)
        for section in ('google_news_en', 'google_news_zh'):
            for item in block.get(section) or []:
                published_at = (
                    item.get('published') or payload.get('generated_at')
                )
                published = normalize_timestamp(published_at).get('iso')
                try:
                    if (
                        datetime.now(timezone.utc)
                        - datetime.fromisoformat(published)
                        > timedelta(days=policy['novelty_lookback_days'])
                    ):
                        continue
                except Exception:
                    pass
                events.append(make_event(
                    policy,
                    ticker=ticker,
                    reported_ticker=reported,
                    title=item.get('title'),
                    published_at=published_at,
                    origin='gnews-rss',
                    source=item.get('source') or 'Google News',
                    url=item.get('url') or '',
                ))
    return events


def collect_influencer_events(policy, underlying):
    """Import named-ticker statements; sector inference never becomes a node.

    The influencer producer explicitly separates direct ticker extraction from
    broad sector matches. Only the former is attributable enough for an alpha
    feature. `relevance` and stance are preserved as metadata, while the source
    tier keeps secondary Musk coverage weak and direct Trump/Substack URLs
    auditable rather than promoting every mention to primary evidence.
    """
    payload = _load(INFLUENCER)
    events = []
    seen = set()
    for item in payload.get('items') or []:
        title = item.get('text') or item.get('summary_cn')
        for reported in item.get('tickers') or []:
            ticker = underlying.get(reported, reported)
            key = (ticker, title, item.get('published'))
            if not ticker or key in seen:
                continue
            seen.add(key)
            events.append(make_event(
                policy,
                ticker=ticker,
                reported_ticker=reported,
                title=title,
                published_at=(
                    item.get('published') or payload.get('generated_at')
                ),
                origin=item.get('origin') or 'llm_digest_legacy',
                source=item.get('source') or item.get('author') or '',
                url=item.get('url') or '',
                metadata={
                    'channel': 'influencer_feed',
                    'author': item.get('author'),
                    'stance': item.get('stance'),
                    'relevance': item.get('relevance'),
                    'direct_ticker_only': True,
                },
            ))
    return events


def collect_catalyst_events(policy, underlying):
    payload = _load(CATALYSTS)
    events = []
    generated = payload.get('generated_at')
    for row in payload.get('earnings') or []:
        reported = row.get('ticker')
        ticker = underlying.get(reported, reported)
        events.append(make_event(
            policy,
            ticker=ticker,
            reported_ticker=reported,
            title=f'{ticker} scheduled earnings',
            published_at=generated,
            event_time=row.get('date'),
            origin='official_macro_schedule',
            source='Finnhub earnings calendar',
            event_type='earnings_schedule',
            metadata={
                key: row.get(key) for key in (
                    'eps_estimate', 'revenue_estimate_m', 'quarter', 'year'
                )
            },
        ))
    for section in ('fomc', 'macro_events'):
        for row in payload.get(section) or []:
            events.append(make_event(
                policy,
                ticker='MARKET',
                title=row.get('detail') or row.get('type'),
                published_at=generated,
                event_time=row.get('date'),
                origin='official_macro_schedule',
                source='official published schedule',
                event_type='macro_schedule',
            ))
    return events


def _active_us_underlyings(portfolio, underlying):
    tickers = []
    for holding in (
        portfolio.get('portfolios', {}).get('us_stocks', {}).get('holdings', [])
    ):
        if holding.get('shares', 0) <= 0:
            continue
        ticker = underlying.get(holding.get('ticker'), holding.get('ticker'))
        if ticker and ticker not in tickers:
            tickers.append(ticker)
    return tickers


def collect_sec_events(policy, portfolio, underlying, enabled=True):
    if not enabled:
        return [], {'status': 'skipped'}
    try:
        from clawock.market_data.filings import get_filings
    except Exception as exc:
        return [], {'status': 'import_failed', 'error': str(exc)[:120]}
    events, errors = [], {}
    cutoff = date.today() - timedelta(days=30)
    for ticker in _active_us_underlyings(portfolio, underlying):
        try:
            filings = get_filings(
                ticker,
                form_types=['10-K', '10-Q', '8-K', '6-K', '20-F', '40-F'],
                limit=12,
            )
        except Exception as exc:
            errors[ticker] = str(exc)[:100]
            continue
        for filing in filings:
            filed = str(filing.get('filing_date') or '')[:10]
            try:
                if date.fromisoformat(filed) < cutoff:
                    continue
            except ValueError:
                continue
            form = str(filing.get('form') or '').upper()
            event_type = (
                'filing_10k' if form in ('10-K', '20-F', '40-F')
                else 'filing_10q' if form == '10-Q'
                else 'filing_8k'
            )
            description = (
                filing.get('description') or filing.get('items')
                or f'{form} filing'
            )
            events.append(make_event(
                policy,
                ticker=ticker,
                title=f'{ticker} {form}: {description}',
                published_at=filed,
                event_time=filing.get('report_date') or filed,
                origin='sec_filing',
                source='SEC EDGAR',
                url=filing.get('primary_doc_url') or '',
                event_type=event_type,
                metadata={
                    'form': form,
                    'accession': filing.get('accession'),
                    'items': filing.get('items'),
                },
            ))
    return events, {
        'status': 'ok' if not errors else 'partial',
        'tickers_queried': _active_us_underlyings(portfolio, underlying),
        'errors': errors,
    }


def deduplicate_events(events):
    """Collapse same ticker/type/novelty cluster; best source becomes canonical."""
    grouped = []
    for event in events:
        matched = next(
            (
                rows for rows in grouped
                if (
                    rows[0]['ticker'] == event['ticker']
                    and rows[0]['event_type'] == event['event_type']
                    and (
                        rows[0]['novelty_cluster']
                        == event['novelty_cluster']
                        or any(
                            semantically_similar(row, event)
                            for row in rows
                        )
                    )
                )
            ),
            None,
        )
        if matched is None:
            grouped.append([event])
        else:
            matched.append(event)
    out = []
    for rows in grouped:
        rows.sort(
            key=lambda row: (
                row['source_reliability'],
                row['publication_time'].get('iso') or '',
            ),
            reverse=True,
        )
        canonical = dict(rows[0])
        canonical['duplicate_event_ids'] = [
            row['event_id'] for row in rows[1:]
        ]
        canonical['evidence_sources'] = sorted({
            row['primary_source'] for row in rows
        })
        canonical['corroborating_source_count'] = len(
            canonical['evidence_sources']
        )
        canonical['duplicate_novelty_clusters'] = sorted({
            row['novelty_cluster'] for row in rows[1:]
            if row['novelty_cluster'] != canonical['novelty_cluster']
        })
        out.append(canonical)
    return sorted(
        out,
        key=lambda row: row['publication_time'].get('iso') or '',
        reverse=True,
    )


def _load_history():
    # 归档 + 热窗 = 完整序列。只读工作文件就是 #951 要避免的那种截断：
    # 越过 novelty_lookback 的 cluster 会从「旧事重提」(0.8) 变成「全新」(1.0)。
    return history_store.load_series(HISTORY)


def apply_novelty(policy, events, history, now):
    prior = [
        event
        for snapshot in history
        for event in snapshot.get('events') or []
    ]
    seen_current = []
    for event in sorted(
        events, key=lambda row: row['publication_time'].get('iso') or ''
    ):
        candidates = [
            row for row in prior + seen_current
            if row.get('ticker') == event['ticker']
            and (
                row.get('novelty_cluster') == event['novelty_cluster']
                or event['novelty_cluster']
                in (row.get('duplicate_novelty_clusters') or [])
                or row.get('novelty_cluster')
                in (event.get('duplicate_novelty_clusters') or [])
                or semantically_similar(row, event)
            )
        ]
        if any(row.get('event_id') == event['event_id'] for row in candidates):
            novelty, reason = 0.0, 'exact_event_seen'
        elif candidates:
            prior_types = {
                row.get('source_type') for row in candidates
                if row.get('source_type')
            }
            prior_primary = bool(
                prior_types & PRIMARY_SOURCE_TYPES
            )
            if (event['source_type'] in PRIMARY_SOURCE_TYPES
                    and prior_types and not prior_primary):
                event['novelty_score'] = 1.0
                event['novelty_reason'] = 'primary_source_resolution'
                seen_current.append({
                    'event_id': event['event_id'],
                    'ticker': event['ticker'],
                    'novelty_cluster': event['novelty_cluster'],
                    'duplicate_novelty_clusters': (
                        event.get('duplicate_novelty_clusters') or []
                    ),
                    'event_type': event['event_type'],
                    'title': event['title'],
                    'source_type': event['source_type'],
                    'source_reliability': event['source_reliability'],
                    'published_at': event['publication_time'].get('iso'),
                })
                continue
            observed = [
                normalize_timestamp(row.get('published_at')).get('iso')
                for row in candidates
            ]
            latest = max(value for value in observed if value) if any(
                observed
            ) else None
            try:
                age = (
                    now - datetime.fromisoformat(latest)
                ).total_seconds() / 86400
            except Exception:
                age = 0
            if age <= 2:
                novelty, reason = 0.1, 'same_cluster_within_2d'
            elif age <= 7:
                novelty, reason = 0.25, 'same_cluster_within_7d'
            elif age <= policy['novelty_lookback_days']:
                novelty, reason = 0.5, 'same_cluster_within_30d'
            else:
                novelty, reason = 0.8, 'cluster_old_but_recurrent'
        else:
            novelty, reason = 1.0, 'new_cluster'
        event['novelty_score'] = novelty
        event['novelty_reason'] = reason
        seen_current.append({
            'event_id': event['event_id'],
            'ticker': event['ticker'],
            'novelty_cluster': event['novelty_cluster'],
            'duplicate_novelty_clusters': (
                event.get('duplicate_novelty_clusters') or []
            ),
            'event_type': event['event_type'],
            'title': event['title'],
            'source_type': event['source_type'],
            'source_reliability': event['source_reliability'],
            'published_at': event['publication_time'].get('iso'),
        })
    return events


def apply_expiry(policy, events, now):
    for event in events:
        days = policy['expiry_days'].get(
            event['event_type'], policy['expiry_days']['other']
        )
        event_iso = event['event_time'].get('iso')
        publication_iso = event['publication_time'].get('iso')
        basis_iso = (
            event_iso
            if event['event_type'] in ('earnings_schedule', 'macro_schedule')
            else publication_iso
        )
        try:
            basis = datetime.fromisoformat(basis_iso)
            if basis.tzinfo is None:
                basis = basis.replace(tzinfo=timezone.utc)
            expires = basis + timedelta(days=days)
            if basis > now:
                status = 'upcoming'
            elif expires < now:
                status = 'expired'
            else:
                status = 'active'
            event['expires_at'] = expires.isoformat()
            event['status'] = status
        except Exception:
            event['expires_at'] = None
            event['status'] = 'unverifiable_time'
        event['expiry_days'] = days
    return events


def _portfolio_holdings(portfolio):
    return {
        holding.get('ticker'): holding
        for leg in ('hk_stocks', 'us_stocks')
        for holding in (
            portfolio.get('portfolios', {}).get(leg, {}).get('holdings', [])
        )
        if holding.get('shares', 0) > 0
    }


def _peer_row(peer_payload, event):
    live = peer_payload.get('live') or {}
    if event['reported_ticker'] in live:
        return live[event['reported_ticker']]
    matches = [
        row for row in live.values()
        if row.get('signal_ticker') == event['ticker']
    ]
    return matches[0] if matches else {}


def apply_confirmation(policy, events, portfolio, peer_payload, factor_payload):
    holdings = _portfolio_holdings(portfolio)
    factor_rows = factor_payload.get('live_rankings') or {}
    activations = peer_payload.get('rule_activation') or {}
    for event in events:
        holding = (
            holdings.get(event['reported_ticker'])
            or holdings.get(event['ticker'])
            or {}
        )
        price_pct = holding.get('today_change_pct')
        expected_sign = (
            1 if event['impact_direction'] == 'positive'
            else -1 if event['impact_direction'] == 'negative'
            else 0
        )
        price_aligned = bool(
            expected_sign and isinstance(price_pct, (int, float))
            and price_pct * expected_sign >= policy['price_confirmation_abs_pct']
        )
        factor_row = factor_rows.get(event['ticker']) or {}
        median_dollar_volume = factor_row.get('liquidity')
        # A leveraged product's tape may confirm direction, but its volume is
        # not comparable with the underlying's median dollar volume.
        same_instrument = (
            event['reported_ticker'] == event['ticker']
            or holding.get('ticker') == event['ticker']
        )
        current_volume = holding.get('volume') if same_instrument else None
        current_price = (
            holding.get('current_price') if same_instrument else None
        )
        volume_ratio = (
            current_volume * current_price / median_dollar_volume
            if all(isinstance(value, (int, float)) and value > 0 for value in
                   (current_volume, current_price, median_dollar_volume))
            else None
        )
        volume_aligned = bool(
            price_aligned and volume_ratio is not None
            and volume_ratio >= policy['volume_confirmation_ratio']
        )
        peer = _peer_row(peer_payload, event)
        residual = peer.get('residual_blend_1d')
        dispersion = peer.get('peer_dispersion_1d')
        peer_observed = bool(
            expected_sign and isinstance(residual, (int, float))
            and isinstance(dispersion, (int, float)) and dispersion > 0
            and residual * expected_sign
            >= policy['peer_residual_sigma'] * dispersion
        )
        usable_peer_rules = [
            rule for rule in peer.get('triggered_rules') or []
            if (activations.get(rule) or {}).get('usable_for_decisions')
        ]
        peer_usable = bool(peer_observed and usable_peer_rules)
        event['confirmation'] = {
            'price_change_pct': price_pct,
            'price_aligned': price_aligned,
            'volume_ratio_vs_20d_median': (
                round(volume_ratio, 4) if volume_ratio is not None else None
            ),
            'volume_aligned': volume_aligned,
            'peer_residual_1d': residual,
            'peer_dispersion_1d': dispersion,
            'peer_residual_observed': peer_observed,
            'peer_usable_rules': usable_peer_rules,
            'peer_confirmation_usable': peer_usable,
            'confirmed': bool(price_aligned or volume_aligned or peer_usable),
        }
    return events


def gate_events(policy, events):
    for event in events:
        title = event['title'].lower()
        noise_patterns = (
            r'\betf\b', r'\bfund price\b', r'\bprice and chart\b',
            r'\bprofile\b', r'\bstartrader\b', r'基金', r'融资盘点',
            r'行情', r'科普', r'营销',
        )
        instrument_noise = any(
            re.search(pattern, title, re.IGNORECASE)
            for pattern in noise_patterns
        )
        high_impact = (
            event['event_type'] in HARD_EVENT_TYPES
            and not instrument_noise
            and event['ticker'] != 'MARKET'
        )
        reliable = (
            event['source_reliability']
            >= policy['minimum_actionable_reliability']
        )
        novel = event['novelty_score'] >= policy['minimum_actionable_novelty']
        current = event['status'] in ('active', 'upcoming')
        confirmed = event['confirmation']['confirmed']
        disconfirming = event['impact_direction'] == 'negative'
        event['high_impact'] = high_impact
        event['actionable_escalation'] = bool(
            high_impact and reliable and novel and current
            and confirmed and disconfirming
        )
        blockers = []
        for name, passed in (
            ('hard_company_event', high_impact),
            ('reliable_primary_or_wire', reliable),
            ('novel', novel),
            ('not_expired', current),
            ('price_volume_or_validated_peer_confirmation', confirmed),
            ('disconfirming_negative', disconfirming),
        ):
            if not passed:
                blockers.append(name)
        event['actionable_blockers'] = blockers
        event['decision_permission'] = (
            'catalyst_escalation_allowed'
            if event['actionable_escalation']
            else 'display_or_watch_only'
        )
    return events


def _event_information_component(event, now, overlay_policy):
    """Signed, decayed information magnitude; polarity alone is never enough."""
    published = (event.get('publication_time') or {}).get('iso')
    try:
        observed = datetime.fromisoformat(published)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        # The snapshot is point-in-time. A timestamp after its cutoff is not
        # "maximally fresh"; it is unavailable information and must be absent.
        if observed > now:
            return None
        age_hours = (now - observed).total_seconds() / 3600
    except Exception:
        return None
    if age_hours > overlay_policy['maximum_event_age_hours']:
        return None
    direction = {'positive': 1, 'negative': -1}.get(
        event.get('impact_direction'), 0
    )
    if not direction or event.get('ticker') == 'MARKET':
        return None
    novelty = float(event.get('novelty_score') or 0)
    reliability = float(event.get('source_reliability') or 0)
    sources = max(1, int(event.get('corroborating_source_count') or 1))
    corroboration = min(1.0, 0.5 + 0.25 * (sources - 1))
    freshness = math.exp(
        -math.log(2) * age_hours
        / float(overlay_policy['freshness_half_life_hours'])
    )
    confirmation = event.get('confirmation') or {}
    # An aligned move is evidence the event is real but also that part of it has
    # already reached price. Preserve the signal while reducing unpriced room.
    price_nonreaction = 0.6 if confirmation.get('price_aligned') else 1.0
    magnitude = novelty * reliability * corroboration * freshness * price_nonreaction
    return {
        'event_id': event.get('event_id'),
        'published_at': published,
        'direction': direction,
        'novelty': round(novelty, 4),
        'reliability': round(reliability, 4),
        'corroborating_sources': sources,
        'freshness': round(freshness, 4),
        'price_nonreaction': price_nonreaction,
        'signed_score': round(direction * magnitude, 6),
    }


def _corroboration_weight(sources):
    """Source-count weight, with one source as the reproducible floor.

    Kept as one function so the live path and the baseline-comparable path
    cannot drift apart into two slightly different weightings.
    """
    return min(1.0, 0.5 + 0.25 * (max(1, int(sources or 1)) - 1))


def _event_attention_component(event, now, overlay_policy):
    """Unsigned, source-weighted attention available at the snapshot cutoff.

    Most collected headlines cannot be assigned a trustworthy buy/sell polarity
    from a title.  Treating those rows as zero discarded the very attention
    information the producers had collected; asking an LLM to invent polarity
    would be worse.  Attention is therefore a separate feature: it can support
    an interaction with relative-price strength, but can never authorise an add
    by itself.
    """
    published = (event.get('publication_time') or {}).get('iso')
    try:
        observed = datetime.fromisoformat(published)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        if observed > now:
            return None
        age_hours = (now - observed).total_seconds() / 3600
    except Exception:
        return None
    if age_hours > overlay_policy['maximum_event_age_hours']:
        return None
    if event.get('ticker') == 'MARKET':
        return None
    novelty = float(event.get('novelty_score') or 0)
    reliability = float(event.get('source_reliability') or 0)
    sources = max(1, int(event.get('corroborating_source_count') or 1))
    corroboration = _corroboration_weight(sources)
    freshness = math.exp(
        -math.log(2) * age_hours
        / float(overlay_policy['freshness_half_life_hours'])
    )
    value = novelty * reliability * corroboration * freshness
    # ``update_history`` does not persist ``corroborating_source_count``, so a
    # historical baseline can only ever be rebuilt at the one-source floor.
    # Acceleration therefore compares floor-weighted against floor-weighted;
    # scoring the live side at full corroboration against that baseline moved
    # the ratio in one direction only. Full weight still drives the
    # cross-sectional attention score and its rank, where both sides are live.
    comparable = novelty * reliability * _corroboration_weight(1) * freshness
    return {
        'event_id': event.get('event_id'),
        'published_at': published,
        'novelty': round(novelty, 4),
        'reliability': round(reliability, 4),
        'corroborating_sources': sources,
        'freshness': round(freshness, 4),
        'attention_value': round(value, 6),
        'baseline_comparable_value': round(comparable, 6),
        'channel': (event.get('metadata') or {}).get('channel') or 'news',
        'source_type': event.get('source_type') or 'unknown',
    }


def _history_information_rows(history, overlay_policy):
    rows = []
    for snapshot in history:
        as_of = str(snapshot.get('as_of') or '')[:10]
        by_ticker = {}
        for event in snapshot.get('events') or []:
            score = event.get('information_signed_score')
            ticker = str(event.get('ticker') or '')
            if ticker and isinstance(score, (int, float)):
                by_ticker[ticker] = by_ticker.get(ticker, 0.0) + float(score)
        for ticker, score in by_ticker.items():
            rows.append({'as_of': as_of, 'ticker': ticker, 'score': score})
    return rows


def _history_attention_rows(history, overlay_policy):
    """Daily own-name attention baselines from facts frozen in each snapshot."""
    rows = []
    for snapshot in history:
        as_of = str(snapshot.get('as_of') or '')[:10]
        if not as_of:
            continue
        scores = {}
        for event in snapshot.get('events') or []:
            try:
                cutoff = datetime.fromisoformat(
                    str(snapshot.get('observed_at')
                        or f'{as_of}T23:59:59+00:00')
                )
                if cutoff.tzinfo is None:
                    cutoff = cutoff.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
            component = _event_attention_component({
                'event_id': event.get('event_id'),
                'ticker': event.get('ticker'),
                'publication_time': {'iso': event.get('published_at')},
                'novelty_score': event.get('novelty_score'),
                'source_reliability': event.get('source_reliability'),
                'source_type': event.get('source_type'),
                'corroborating_source_count': 1,
            }, cutoff, overlay_policy)
            if component is not None:
                ticker = str(event.get('ticker') or '')
                scores[ticker] = (
                    scores.get(ticker, 0.0)
                    + component['baseline_comparable_value']
                )
        for ticker, score in scores.items():
            rows.append({'as_of': as_of, 'ticker': ticker, 'score': score})
    return rows


def _history_information_dates(
    history, *, activation_only=False, registered_at=None
):
    """Registered point-in-time snapshots, including days with zero signal."""
    return sorted({
        str(snapshot.get('as_of') or '')[:10]
        for snapshot in history
        if snapshot.get('information_overlay_schema_version') == 1
        and (
            not activation_only
            or not registered_at
            or str(snapshot.get('as_of') or '')[:10] >= registered_at
        )
        and (
            not activation_only
            or not snapshot.get('information_overlay_backfill')
            or (snapshot.get('information_overlay_backfill') or {}).get(
                'activation_eligible'
            ) is True
        )
        and snapshot.get('as_of')
    })


def build_information_overlay(policy, events, history, now):
    """Ticker surprise and cross-sectional rank from already-collected evidence."""
    overlay_policy = policy['information_overlay']
    components = {}
    attention_components = {}
    covered_tickers = set()
    for event in events:
        ticker = str(event.get('ticker') or '')
        published = (event.get('publication_time') or {}).get('iso')
        try:
            observable = datetime.fromisoformat(published)
            if observable.tzinfo is None:
                observable = observable.replace(tzinfo=timezone.utc)
        except Exception:
            observable = None
        if ticker and ticker != 'MARKET' and observable and observable <= now:
            covered_tickers.add(ticker)
        component = _event_information_component(event, now, overlay_policy)
        attention = _event_attention_component(event, now, overlay_policy)
        if attention is not None:
            attention_components.setdefault(ticker, []).append(attention)
        if component is None:
            continue
        event['information_signed_score'] = component['signed_score']
        components.setdefault(ticker, []).append(component)

    historical = _history_information_rows(history, overlay_policy)
    historical_attention = _history_attention_rows(history, overlay_policy)
    history_dates = _history_information_dates(history)
    activation_dates = _history_information_dates(
        history,
        activation_only=True,
        registered_at=overlay_policy['registered_at'],
    )
    # Cross-sectional coverage is the names the current source snapshots can
    # observe, not only names whose headline classifier emitted a direction.
    # A covered name with no qualifying event is a real zero signal. Dropping
    # those names makes activation depend on how excitable today's headlines
    # are and can leave a well-covered universe permanently warming up.
    eligible_tickers = sorted(covered_tickers)
    activation_checks = {
        'history_dates': {
            'actual': len(activation_dates),
            'required': overlay_policy['minimum_history_dates'],
            'pass': len(activation_dates) >= overlay_policy['minimum_history_dates'],
        },
        'cross_section_tickers': {
            'actual': len(eligible_tickers),
            'required': overlay_policy['minimum_cross_section_tickers'],
            'pass': len(eligible_tickers) >= overlay_policy['minimum_cross_section_tickers'],
        },
    }
    active = all(check['pass'] for check in activation_checks.values())

    raw = {
        ticker: sum(row['signed_score'] for row in components.get(ticker, []))
        for ticker in eligible_tickers
    }
    attention_raw = {
        ticker: sum(
            row['attention_value']
            for row in attention_components.get(ticker, [])
        )
        for ticker in eligible_tickers
    }
    # The numerator of the acceleration ratio. Deliberately not attention_raw:
    # the denominator is rebuilt from snapshots that cannot carry corroboration.
    attention_comparable = {
        ticker: sum(
            row['baseline_comparable_value']
            for row in attention_components.get(ticker, [])
        )
        for ticker in eligible_tickers
    }
    # Mid-rank ties. Ticker spelling must never decide which equal-score name
    # lands above an activation threshold.
    ranks = {}
    ordered_scores = sorted(raw.values())
    for ticker, score in raw.items():
        positions = [
            index for index, value in enumerate(ordered_scores)
            if value == score
        ]
        ranks[ticker] = (
            statistics.fmean(index + 0.5 for index in positions)
            / len(ordered_scores)
        )
    attention_ranks = {}
    for region_tickers in (
        [ticker for ticker in eligible_tickers if ticker.isdigit()],
        [ticker for ticker in eligible_tickers if not ticker.isdigit()],
    ):
        ordered_attention = sorted(
            attention_raw[ticker] for ticker in region_tickers
        )
        for ticker in region_tickers:
            score = attention_raw[ticker]
            positions = [
                index for index, value in enumerate(ordered_attention)
                if value == score
            ]
            attention_ranks[ticker] = (
                statistics.fmean(index + 0.5 for index in positions)
                / len(ordered_attention)
            )
    ticker_rows = {}
    for ticker in eligible_tickers:
        by_day = {
            row['as_of']: row['score']
            for row in historical if row['ticker'] == ticker
        }
        # No qualifying event on a registered day is a real zero observation,
        # not missing data. Event-day-only baselines overstate normal intensity.
        own = [by_day.get(day, 0.0) for day in history_dates]
        attention_by_day = {
            row['as_of']: row['score']
            for row in historical_attention if row['ticker'] == ticker
        }
        own_attention = [attention_by_day.get(day, 0.0) for day in history_dates]
        attention_baseline = (
            statistics.fmean(own_attention) if own_attention else 0.0
        )
        attention_prior = float(overlay_policy.get('attention_score_prior', 0.1))
        attention_acceleration = (
            (attention_comparable[ticker] + attention_prior)
            / (attention_baseline + attention_prior)
        )
        source_types = {
            row.get('source_type')
            for row in attention_components.get(ticker, [])
            if row.get('source_type')
        }
        mean = statistics.fmean(own) if own else None
        stdev = statistics.pstdev(own) if len(own) >= 2 else None
        surprise = (
            (raw[ticker] - mean) / stdev
            if mean is not None and stdev and stdev > 0 else None
        )
        ticker_rows[ticker] = {
            'ticker': ticker,
            'as_of': now.isoformat(),
            'signed_score': round(raw[ticker], 6),
            'cross_section_rank': round(ranks[ticker], 4),
            'own_history_dates': len(history_dates),
            'prospective_history_dates': len(activation_dates),
            'own_surprise_z': round(surprise, 4) if surprise is not None else None,
            'event_count': len(components.get(ticker, [])),
            'attention_score': round(attention_raw[ticker], 6),
            'attention_comparable_score': round(attention_comparable[ticker], 6),
            'attention_rank': round(attention_ranks[ticker], 4),
            'attention_rank_scope': 'HK' if ticker.isdigit() else 'US',
            'attention_event_count': len(attention_components.get(ticker, [])),
            'attention_baseline': round(attention_baseline, 6),
            'attention_acceleration': round(attention_acceleration, 4),
            'attention_source_type_count': len(source_types),
            'attention_components': sorted(
                attention_components.get(ticker, []),
                key=lambda row: row['published_at'], reverse=True
            )[:8],
            'sizing_tilt': (
                'positive'
                if (active
                    and ranks[ticker] >= overlay_policy['positive_rank_upsize_threshold']
                    and raw[ticker] > 0)
                else 'negative'
                if (active and (
                    ranks[ticker] <= overlay_policy['negative_rank_downsize_threshold']
                    or raw[ticker] < 0
                ))
                else 'neutral' if active else 'inactive'
            ),
            'event_components': sorted(
                components.get(ticker, []),
                key=lambda row: row['published_at'], reverse=True
            )[:8],
            'status': 'active' if active else 'warming_up',
            'usable_for_decisions': active,
        }
    return {
        'schema_version': 1,
        'as_of': now.isoformat(),
        'registered_at': overlay_policy['registered_at'],
        'status': 'active' if active else 'warming_up',
        'usable_for_decisions': active,
        'activation': {
            'checks': activation_checks,
            'blockers': [name for name, check in activation_checks.items()
                         if not check['pass']],
            'discipline': overlay_policy['discipline'],
        },
        'sizing_thresholds': {
            'positive_rank': overlay_policy['positive_rank_upsize_threshold'],
            'negative_rank': overlay_policy['negative_rank_downsize_threshold'],
        },
        'sizing_policy': overlay_policy['sizing'],
        'tickers': ticker_rows,
    }


def tavily_queue(policy, events):
    queue = []
    for event in events:
        unresolved = (
            event['high_impact']
            and event['status'] == 'active'
            and event['novelty_score'] >= policy['minimum_actionable_novelty']
            and event['source_type'] not in PRIMARY_SOURCE_TYPES
            and (
                event['source_reliability']
                < policy['minimum_actionable_reliability']
                or event['impact_direction'] in ('unknown', 'conflicting')
            )
        )
        if not unresolved:
            continue
        queue.append({
            'event_id': event['event_id'],
            'ticker': event['ticker'],
            'reason': 'high_impact_without_primary_resolution',
            'query': (
                f'{event["ticker"]} {event["event_type"]} '
                f'{event["title"]} official filing announcement'
            )[:300],
            'allowed_tool': 'tavily-search',
            'bucket': 'brief',
        })
    return queue


def build_graph(events):
    nodes, edges = [], []
    tickers, sources, clusters = set(), set(), set()
    for event in events:
        nodes.append({
            'id': event['event_id'],
            'kind': 'event',
            'event_type': event['event_type'],
            'status': event['status'],
        })
        ticker_id = f'ticker:{event["ticker"]}'
        source_id = f'source:{event["primary_source"]}'
        cluster_id = f'cluster:{event["novelty_cluster"]}'
        if ticker_id not in tickers:
            nodes.append({'id': ticker_id, 'kind': 'ticker'})
            tickers.add(ticker_id)
        if source_id not in sources:
            nodes.append({'id': source_id, 'kind': 'source',
                          'source_type': event['source_type']})
            sources.add(source_id)
        if cluster_id not in clusters:
            nodes.append({'id': cluster_id, 'kind': 'novelty_cluster'})
            clusters.add(cluster_id)
        edges.extend([
            {'from': event['event_id'], 'to': ticker_id, 'type': 'about'},
            {'from': event['event_id'], 'to': source_id, 'type': 'reported_by'},
            {'from': event['event_id'], 'to': cluster_id, 'type': 'belongs_to'},
        ])
    return {'nodes': nodes, 'edges': edges}


def update_history(as_of, events, prior=None):
    snapshots = [
        row for row in (_load_history() if prior is None else prior)
        if str(row.get('as_of') or '')[:10] != as_of
    ]
    snapshots.append({
        'as_of': as_of,
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'information_overlay_schema_version': 1,
        'events': [
            {
                'event_id': event['event_id'],
                'ticker': event['ticker'],
                'novelty_cluster': event['novelty_cluster'],
                'duplicate_novelty_clusters': (
                    event.get('duplicate_novelty_clusters') or []
                ),
                'event_type': event['event_type'],
                'title': event['title'],
                'source_type': event['source_type'],
                'source_reliability': event['source_reliability'],
                'novelty_score': event.get('novelty_score'),
                'impact_direction': event.get('impact_direction'),
                'published_at': event['publication_time'].get('iso'),
                'status': event['status'],
                'actionable_escalation': event['actionable_escalation'],
                'information_signed_score': event.get('information_signed_score'),
            }
            for event in events
        ],
    })
    # 热窗写工作文件、冷段进 archive；返回的仍是完整序列（#951）。
    return history_store.write_series(HISTORY, snapshots)


def _backfill_information_components(policy, snapshots, cutoff):
    """Score legacy snapshots with only facts persisted at their cutoff.

    #503 introduced the continuous overlay after these point-in-time event
    snapshots already existed.  Replaying the deterministic formula is not a
    current-news backfill: every input below (published_at, novelty, source and
    confirmation-independent price nonreaction) was frozen in that day's row.
    We mark it explicitly so it can seed baselines but never masquerade as a
    pre-registered live activation date.
    """
    overlay_policy = policy['information_overlay']
    seen = []
    for snapshot in sorted(snapshots, key=lambda row: row.get('as_of') or ''):
        as_of = str(snapshot.get('as_of') or '')[:10]
        if not as_of:
            continue
        try:
            observed_at = datetime.fromisoformat(f'{as_of}T23:59:59+00:00')
        except ValueError:
            continue
        for event in snapshot.get('events') or []:
            prior = [
                row for row in seen
                if row.get('ticker') == event.get('ticker')
                and (
                    row.get('event_id') == event.get('event_id')
                    or row.get('novelty_cluster') == event.get('novelty_cluster')
                    or row.get('novelty_cluster') in (
                        event.get('duplicate_novelty_clusters') or []
                    )
                )
            ]
            novelty = event.get('novelty_score')
            if novelty is None:
                novelty = 0.0 if prior else 1.0
                # This is a deterministic replay from the exact cluster IDs
                # frozen at the old cutoff. Persist it so unsigned attention
                # history is comparable instead of treating all legacy days as
                # zero merely because the field did not exist yet.
                event['novelty_score'] = novelty
            direction = event.get('impact_direction') or classify_impact(
                event.get('title')
            )
            if event.get('information_signed_score') is None:
                component = _event_information_component({
                    'event_id': event.get('event_id'),
                    'ticker': event.get('ticker'),
                    'impact_direction': direction,
                    'publication_time': {'iso': event.get('published_at')},
                    'novelty_score': novelty,
                    'source_reliability': event.get('source_reliability'),
                    'corroborating_source_count': 1,
                    'confirmation': {},
                }, observed_at, overlay_policy)
                if component is not None:
                    event['information_signed_score'] = component['signed_score']
            seen.append(event)
        snapshot['information_overlay_schema_version'] = 1
        snapshot.setdefault('observed_at', observed_at.isoformat())
        if as_of < overlay_policy['registered_at']:
            snapshot['information_overlay_backfill'] = {
                'method': 'deterministic_point_in_time_replay_v1',
                'created_at': cutoff.isoformat(),
                'activation_eligible': False,
            }
    return snapshots


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='clawock news-evidence', description=__doc__)
    parser.add_argument('--no-sec', action='store_true',
                        help='skip live SEC metadata refresh')
    parser.add_argument('--policy', default=str(POLICY))
    args = parser.parse_args(argv)
    policy = load_policy(args.policy)
    portfolio = _load(PORTFOLIO)
    underlying = _underlying_map()
    now = datetime.now(timezone.utc)
    # Exclude today's snapshot while computing novelty so same-day idempotent
    # reruns replace rather than self-penalize.
    history = [
        row for row in _load_history()
        if str(row.get('as_of') or '')[:10] != now.date().isoformat()
    ]
    history = _backfill_information_components(policy, history, now)
    sec, sec_status = collect_sec_events(
        policy, portfolio, underlying, enabled=not args.no_sec
    )
    events = [
        *sec,
        *collect_em_events(policy, underlying),
        *collect_us_news_events(policy, underlying),
        *collect_sentiment_news_events(policy, underlying),
        *collect_influencer_events(policy, underlying),
        *collect_catalyst_events(policy, underlying),
    ]
    events = deduplicate_events(events)
    events = apply_novelty(policy, events, history, now)
    events = apply_expiry(policy, events, now)
    events = apply_confirmation(
        policy,
        events,
        portfolio,
        _load(PEER_RESIDUAL),
        _load(CROSS_FACTOR),
    )
    events = gate_events(policy, events)
    information_overlay = build_information_overlay(
        policy, events, history, now
    )
    queue = tavily_queue(policy, events)
    update_history(now.date().isoformat(), events, prior=history)
    out = {
        'schema_version': 1,
        'generated_at': now.isoformat(),
        'as_of': now.date().isoformat(),
        'events': events,
        'information_overlay': information_overlay,
        'actionable_events': [
            event['event_id'] for event in events
            if event['actionable_escalation']
        ],
        'tavily_resolution_queue': queue,
        'graph': build_graph(events),
        'source_status': {
            'sec': sec_status,
            'eastmoney': 'loaded' if EM_NEWS.exists() else 'missing',
            'us_news_digest': 'loaded' if US_NEWS.exists() else 'missing',
            'sentiment_news': 'loaded' if SENTIMENT.exists() else 'missing',
            'influencer_feed': 'loaded' if INFLUENCER.exists() else 'missing',
            'catalysts': 'loaded' if CATALYSTS.exists() else 'missing',
            'peer_residual': 'loaded' if PEER_RESIDUAL.exists() else 'missing',
        },
        'summary': {
            'events': len(events),
            'active': sum(event['status'] == 'active' for event in events),
            'upcoming': sum(event['status'] == 'upcoming' for event in events),
            'expired': sum(event['status'] == 'expired' for event in events),
            'primary_source_events': sum(
                event['source_type'] in PRIMARY_SOURCE_TYPES for event in events
            ),
            'actionable_escalations': sum(
                event['actionable_escalation'] for event in events
            ),
            'information_overlay_status': information_overlay['status'],
            'tavily_resolution_queue': len(queue),
        },
        'policy': {
            'registered_at': policy['registered_at'],
            'minimum_actionable_reliability': (
                policy['minimum_actionable_reliability']
            ),
            'minimum_actionable_novelty': (
                policy['minimum_actionable_novelty']
            ),
            'tavily_policy': policy['tavily_policy'],
            'licensing': (
                'metadata and headlines only; no article body or source summary '
                'is persisted in the evidence graph'
            ),
            'positive_news_discipline': (
                'positive/confirming news is hold-only and cannot trigger add/trim'
            ),
        },
    }
    safe_write_json(str(OUT), out)
    print(
        f'news graph: {len(events)} events, '
        f'{out["summary"]["primary_source_events"]} primary, '
        f'{out["summary"]["actionable_escalations"]} actionable, '
        f'{len(queue)} Tavily-resolution'
    )
    print(f'wrote {OUT.relative_to(WS)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
