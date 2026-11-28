"""Materialize the brief's draft prose before it enters the public plan or Pages."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from clawock.decision import ledger
from clawock.portfolio.guardrail import plan_trim_projections
from clawock.portfolio.breakeven_claims import validate_drag

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
            out[key] = renderer.render(out[key], f'judgment {key}', scope='portfolio')
    narrative = out.get('narrative')
    if isinstance(narrative, dict):
        for key, value in narrative.items():
            if key == 'risk_voice_first':
                continue
            label = f'judgment narrative.{key}'
            narrative[key] = ([renderer.render(item, label, scope='portfolio') for item in value]
                              if isinstance(value, list) else renderer.render(value, label, scope='portfolio'))
    for index, row in enumerate(out.get('ticker_judgments') or []):
        if isinstance(row, dict):
            for key in ROW_TEXT_FIELDS:
                if key in row:
                    row[key] = renderer.render(row[key], f'judgment ticker_judgments[{index}].{key}', ticker=row.get('ticker'))
    return out


def legacy_drag_issues(context, plan, judgment):
    """Validate older archived prose using its own book data and row subjects."""
    issues = set()
    for row in plan.get('decisions') or []:
        for path in PLAN_TEXT_PATHS:
            node = row
            for key in path:
                node = node.get(key) if isinstance(node, dict) else None
            issues.update(validate_drag(node, context, ticker=row.get('ticker')))
    for key in ('portfolio_assessment', 'portfolio_counterargument'):
        issues.update(validate_drag(judgment.get(key), context))
    narrative = judgment.get('narrative') or {}
    for value in narrative.values() if isinstance(narrative, dict) else ():
        for entry in value if isinstance(value, list) else [value]:
            issues.update(validate_drag(entry, context))
    for row in judgment.get('ticker_judgments') or []:
        for value in row.values():
            issues.update(validate_drag(value, context, ticker=row.get('ticker')))
    return sorted(issues)
