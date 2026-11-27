"""Project brief sidecars from audited observations and authored commentary."""
from __future__ import annotations

import json

from clawock.safe_io import to_strict_finite_number


def _draft(path, context):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if isinstance(value, dict) and value.get('context_generation_id') == context.get('generation_id'):
        return value
    return {}


def sector_scan(context, attribution_path, renderer):
    """Quote the peer feeds in the generation and rank within the observed peers."""
    draft = _draft(attribution_path, context)
    attribution = draft.get('attribution')
    if not isinstance(attribution, dict):
        attribution = {}
    sectors = []
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
        ranked = sorted(peers.values(), key=lambda row: (-row['pct'], row['ticker']))
        rank = None
        if ranked and current is not None:
            rank = ('领涨' if current > ranked[0]['pct']
                    else '落后' if current < ranked[-1]['pct'] else '区间内')
        text = attribution.get(ticker)
        start = len(renderer.issues)
        text = renderer.render(text, f'板块归因 {ticker}')
        if len(renderer.issues) != start:
            text = None
        if source.get('region') and source.get('self_session'):
            sessions[source['region'].lower()] = source['self_session']
        sectors.append({
            'theme': source.get('theme'), 'tickers_in_book': [ticker],
            'top_movers': ranked[:3],
            'self': [{'ticker': ticker, 'pct': current, 'rank_text': rank, 'attribution': text}],
        })
    if not sectors:
        return None
    return {'date': context.get('date'), 'generated_at': context.get('generated_at'),
            'context_generation_id': context.get('generation_id'), '_sessions': sessions,
            'sectors': sectors}


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
