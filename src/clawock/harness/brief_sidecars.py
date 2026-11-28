"""Project brief sidecars from audited observations and authored commentary."""
from __future__ import annotations

import json

from clawock.safe_io import to_strict_finite_number


def _draft(path, context):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    generation = context.get('generation_id')
    if generation and isinstance(value, dict) and value.get('context_generation_id') == generation:
        return value
    return {}


def _commentary(value, label, renderer, *, ticker=None):
    if not isinstance(value, str) or not value.strip():
        return None
    start = len(renderer.issues)
    text = renderer.render(value, label, ticker=ticker)
    return text if len(renderer.issues) == start else None


def sector_rank(ticker, current, peers):
    """Position in this holding's own audited same-session comparison set."""
    current = to_strict_finite_number(current)
    values = {}
    for peer in peers:
        name, change = peer.get('ticker'), to_strict_finite_number(peer.get('pct_1d'))
        if name and name != ticker and change is not None:
            values.setdefault(name, change)
    if current is None or not values:
        return None
    ahead = sum(change > current for change in values.values())
    rank = f'第 {ahead + 1}/{len(values) + 1}'
    if all(change < current for change in values.values()):
        return f'领涨 · {rank}'
    if ahead == len(values):
        return f'落后 · {rank}'
    return rank


def sector_scan(context, attribution_path, renderer, *, narrative=None):
    """Group the generation's observations and attach rendered commentary."""
    draft = _draft(attribution_path, context)
    attribution = draft.get('attribution')
    if not isinstance(attribution, dict):
        attribution = {}
    catalysts = draft.get('catalysts')
    if not isinstance(catalysts, dict):
        catalysts = {}
    themes = draft.get('themes')
    if not isinstance(themes, dict):
        themes = {}
    groups = {}
    sessions = {}
    for ticker, source in (context.get('peer_scan') or {}).items():
        current = to_strict_finite_number(source.get('self_pct_1d'))
        peers = {}
        for peer in [*(source.get('listed_peers') or []), *(source.get('auto_peers') or [])]:
            pct = to_strict_finite_number(peer.get('pct_1d'))
            if pct is not None and peer.get('ticker') and peer['ticker'] != ticker:
                peers.setdefault(peer['ticker'], {
                    'ticker': peer['ticker'], 'name': peer.get('name'), 'pct': pct,
                    'source': peer.get('quote_source'),
                })
        rank = sector_rank(ticker, current, [
            *(source.get('listed_peers') or []), *(source.get('auto_peers') or []),
        ])
        theme = (_commentary(themes.get(ticker), f'板块主题 {ticker}', renderer)
                 or source.get('theme'))
        region, session = source.get('region'), source.get('self_session')
        if region and session:
            sessions[region.lower()] = session
        group = groups.setdefault((region, session, theme or ticker), {
            'theme': theme, 'tickers_in_book': [], 'peers': {}, 'self': [],
        })
        group['tickers_in_book'].append(ticker)
        for peer_ticker, peer in peers.items():
            group['peers'].setdefault(peer_ticker, peer)
        group['self'].append({
            'ticker': ticker, 'pct': current, 'rank_text': rank,
            'attribution': _commentary(attribution.get(ticker), f'板块归因 {ticker}', renderer, ticker=ticker),
        })
    if not groups:
        return None

    sectors = []
    for group in groups.values():
        ranked = sorted(group.pop('peers').values(), key=lambda row: (-row['pct'], row['ticker']))
        group['top_movers'] = ranked[:5]
        for row in group['top_movers']:
            ticker = row['ticker']
            if text := _commentary(catalysts.get(ticker), f'板块催化 {ticker}', renderer):
                row['catalyst'] = text
        sectors.append(group)
    return {'date': context.get('date'), 'generated_at': context.get('generated_at'),
            'context_generation_id': context.get('generation_id'), '_sessions': sessions,
            'narrative': narrative, 'sectors': sectors}


def _exposure(selection, context):
    basis, leg, family = (selection.get(key) for key in ('basis', 'leg', 'family'))
    buckets = selection.get('buckets')
    if (leg not in ('hk', 'us') or not isinstance(buckets, list) or not buckets
            or any(not isinstance(name, str) for name in buckets)
            or len(set(buckets)) != len(buckets)):
        return None
    if basis == 'market_value' and family == 'sectors':
        from clawock.publish.dashboard import compute_sector_exposure
        rows = compute_sector_exposure(context['portfolio']).get(leg) or []
        label, value = 'sector', 'pct'
    elif basis == 'lookthrough' and family in ('factors', 'sectors'):
        rows = ((context.get('lookthrough_exposure') or {}).get(leg) or {}).get(family) or []
        label, value = family[:-1], 'gross_pct'
    else:
        return None
    by_name = {row[label]: row[value] for row in rows}
    if any(name not in by_name for name in buckets):
        return None
    return {
        'basis': basis, 'leg': leg, 'family': family, 'buckets': buckets,
        'as_of': context.get('date'),
        'pct': min(100.0, round(sum(by_name[name] for name in buckets), 2)),
    }


def insights(path, context, renderer):
    draft = _draft(path, context)
    if not draft:
        return None
    out = {}
    review = draft.get('behavioral_review')
    if isinstance(review, dict):
        start = len(renderer.issues)
        verdict = renderer.render(review.get('verdict'), '行为复盘')
        points = []
        if isinstance(review.get('points'), list):
            for row in review['points'][:8]:
                if isinstance(row, dict) and isinstance(row.get('tag'), str):
                    points.append({'tag': row['tag'], 'text': renderer.render(
                        row.get('text'), '行为复盘要点')})
        if len(renderer.issues) == start:
            out['behavioral_review'] = {'verdict': verdict, 'points': points}
    for row in (draft.get('bear_cases') if isinstance(draft.get('bear_cases'), list) else [])[:5]:
        if not isinstance(row, dict):
            continue
        start = len(renderer.issues)
        case = {'ticker': row.get('ticker'), 'context_generation_id': context['generation_id']}
        for field in ('thesis', 'falsifier', 'watch'):
            case[field] = renderer.render(row.get(field), f'空头 {field}')
        if len(renderer.issues) == start:
            out.setdefault('bear_cases', []).append(case)
    hidden = draft.get('hidden_concentration')
    if isinstance(hidden, dict):
        exposure = _exposure(hidden, context)
        start = len(renderer.issues)
        card = {field: renderer.render(hidden.get(field), f'集中度 {field}')
                for field in ('headline', 'detail')}
        if exposure and len(renderer.issues) == start:
            out['hidden_concentration'] = {
                **card, 'factor': ' / '.join(exposure['buckets']), 'basis': exposure['basis'],
                'exposure_pct': exposure['pct'], 'exposure_source': exposure,
            }
    return out
