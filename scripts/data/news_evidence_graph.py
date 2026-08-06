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
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from workspace import workspace_root  # noqa: E402

# Code lives in the checkout; only DATA lives in the workspace. `workspace_root`
# is overridable, so resolving our own modules through WS would read them out of
# someone else's data directory — or silently pick up whatever happens to be
# there. Same expression WS is seeded from, kept separate on purpose (#269).
_CHECKOUT = Path(__file__).resolve().parents[2]
WS = workspace_root(Path(__file__).resolve().parents[2])
POLICY = WS / 'config' / 'news-evidence-policy.json'
PORTFOLIO = WS / 'portfolio.json'
FACTOR_CONFIG = WS / 'config' / 'factor-universe.json'
EM_NEWS = WS / 'assets' / 'data' / 'em_news.json'
US_NEWS = WS / 'assets' / 'data' / 'us_news_digest.json'
SENTIMENT = WS / 'assets' / 'data' / 'sentiment.json'
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

sys.path.insert(0, str(_CHECKOUT / 'scripts' / 'data'))
from safe_io import safe_write_json, safe_write_text  # noqa: E402


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


def normalize_timestamp(value, fallback=None):
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
                parsed = parsed.replace(tzinfo=timezone.utc)
            return {'iso': parsed.astimezone(timezone.utc).isoformat(),
                    'precision': precision}
        except ValueError:
            pass
        for fmt in ('%Y/%m/%d %H:%M', '%Y-%m-%d %H:%M',
                    '%a, %d %b %Y %H:%M:%S %Z'):
            try:
                parsed = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
                return {'iso': parsed.isoformat(), 'precision': 'minute'}
            except ValueError:
                continue
    if fallback:
        return normalize_timestamp(fallback)
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
    published = normalize_timestamp(published_at)
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
    for line in str(payload.get('digest_markdown') or '').splitlines():
        match = re.match(r'\s*-\s+\*\*([^*]+)\*\*:\s*(.+)', line)
        if not match:
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
        from fetch_us_filings import get_filings
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
    if not HISTORY.exists():
        return []
    out = []
    for line in HISTORY.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


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


def update_history(as_of, events):
    snapshots = [
        row for row in _load_history()
        if str(row.get('as_of') or '')[:10] != as_of
    ]
    snapshots.append({
        'as_of': as_of,
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
                'published_at': event['publication_time'].get('iso'),
                'status': event['status'],
                'actionable_escalation': event['actionable_escalation'],
            }
            for event in events
        ],
    })
    snapshots.sort(key=lambda row: row['as_of'])
    safe_write_text(
        str(HISTORY),
        '\n'.join(json.dumps(row, ensure_ascii=False, separators=(',', ':'))
                  for row in snapshots) + '\n',
    )
    return snapshots


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
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
    sec, sec_status = collect_sec_events(
        policy, portfolio, underlying, enabled=not args.no_sec
    )
    events = [
        *sec,
        *collect_em_events(policy, underlying),
        *collect_us_news_events(policy, underlying),
        *collect_sentiment_news_events(policy, underlying),
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
    queue = tavily_queue(policy, events)
    update_history(now.date().isoformat(), events)
    out = {
        'schema_version': 1,
        'generated_at': now.isoformat(),
        'as_of': now.date().isoformat(),
        'events': events,
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
