"""Materialize the brief's draft prose before it enters the public plan or Pages."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from clawock.decision import ledger
from clawock.portfolio.guardrail import plan_trim_projections

PLAN_TEXT_PATHS = (
    ('rationale',), ('condition', 'description'), ('size', 'note'),
    ('hypothesis',), ('method',), ('thesis_invalidation',), ('thesis_reset', 'reason'),
    *(('debate', field) for field in ledger.DEBATE_TEXT_FIELDS),
)


def plan_draft_path(workspace, date):
    return Path(workspace) / 'memory' / '.tmp' / f'{date}-plan-draft.json'


def _decision_facts(context, row):
    plan = {'decisions': [row]}
    return {
        'ticker': row.get('ticker'),
        'size': {key: (row.get('size') or {}).get(key) for key in ('shares', 'pct')},
        'condition': {key: (row.get('condition') or {}).get(key)
                      for key in ('price', 'valid_for_sessions')},
        'confidence': row.get('confidence'),
        'trim_at_trigger': next(iter(plan_trim_projections(context, plan)), {}),
        'trim_at_mark': next(iter(plan_trim_projections(context, plan, at_book_mark=True)), {}),
    }


def render_plan(plan, renderer):
    out = deepcopy(plan)
    for index, row in enumerate(out.get('decisions') or []):
        if not isinstance(row, dict):
            continue
        label = f'plan decisions[{index}]'
        facts = _decision_facts(renderer.roots['ctx'], row)
        start = len(renderer.references)
        for path in PLAN_TEXT_PATHS:
            node = row if len(path) == 1 else row.get(path[0])
            field = path[-1]
            if isinstance(node, dict) and field in node:
                node[field] = renderer.render(node[field], f'{label} {field}', decision=facts)
        debate = row.get('debate')
        if isinstance(debate, dict) and isinstance(debate.get('frames'), list):
            debate['frames'] = [renderer.render(value, f'{label} frames', decision=facts)
                                for value in debate['frames']]
        row['prose_claims'] = {
            'version': 1,
            'trim': {path: facts[basis][key] for path in renderer.references[start:]
                     for _, basis, key in [path.strip('/').split('/')]
                     if key in ('shares_to_review_line', 'remaining_shares_at_review_line',
                                'post_trim_weight_pct')},
        }
    return out


def render_judgment(overlay, renderer):
    from clawock.decision.packet import ROW_TEXT_FIELDS

    out = deepcopy(overlay)
    for key in ('portfolio_assessment', 'portfolio_counterargument'):
        if key in out:
            out[key] = renderer.render(out[key], f'judgment {key}')
    narrative = out.get('narrative')
    if isinstance(narrative, dict):
        for key, value in narrative.items():
            if key == 'risk_voice_first':
                continue
            label = f'judgment narrative.{key}'
            narrative[key] = ([renderer.render(item, label) for item in value]
                              if isinstance(value, list) else renderer.render(value, label))
    for index, row in enumerate(out.get('ticker_judgments') or []):
        if isinstance(row, dict):
            for key in ROW_TEXT_FIELDS:
                if key in row:
                    row[key] = renderer.render(row[key], f'judgment ticker_judgments[{index}].{key}')
    return out
