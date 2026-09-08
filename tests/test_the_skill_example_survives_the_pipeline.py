"""Every key the skill's example teaches must still be there afterwards.

The daily brief is written by a model reading `skills/daily-deep-brief/SKILL.md`,
and the fastest thing to copy in a long document is the JSON example. So the
example is not documentation — it is the input contract, and a key in it that
the normalizer discards is a lesson the model learns and the pipeline throws
away. Silently: `normalize_authored_plan` keeps the fields it knows and says
nothing about the rest.

Three of them were live on 2026-09-08, all measured, none of them noticed:

  condition.note        the builder reads `condition.description`. `note` is
                        what the example showed from the v2 rewrite on
                        2026-07-15, and condition prose collapsed from 170/208
                        (June) to 53/264 (July) and 30/194 (August) — the plan
                        says `price_above` and nothing about what it means.
  contested             read by `publish/dashboard.py` to compute
                        `contested_rate`. Absent from all 436 decisions of the
                        last 40 plans, so the site published
                        `contested_rate: null · contested_coverage: 0`.
  thesis_invalidation   the skill calls it mandatory for an active cut/trim/add.
                        No slot in the row builder; 0 of 809 ledger rows carry
                        one, while `check_research_artifacts` warns that the
                        thesis kill switch is unarmed.

A field with no consumer is a different problem (#1308). This is the reverse:
consumers that are already there, waiting on a field the pipeline deletes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'daily-deep-brief' / 'SKILL.md'


def _example_plan() -> dict:
    """The plan JSON the skill shows the model, parsed from the skill itself."""
    text = SKILL.read_text(encoding='utf-8')
    for block in re.findall(r'```json\n(.*?)```', text, re.S):
        if '"decisions"' not in block:
            continue
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(payload.get('decisions'), list) and payload['decisions']:
            return payload
    raise AssertionError('the skill no longer shows a decisions example')


def test_the_example_the_model_copies_is_valid_json():
    plan = _example_plan()

    assert len(plan['decisions']) >= 2, (
        'the example must keep showing more than one shape of decision')


def test_no_key_the_example_teaches_is_dropped_by_normalization(tmp_path):
    from clawock.decision.ledger import normalize_authored_plan

    plan = _example_plan()
    normalized = normalize_authored_plan(plan, tmp_path / 'decisions.jsonl')

    for authored, kept in zip(plan['decisions'], normalized['decisions']):
        where = f"{authored.get('ticker')} {authored.get('action')}"
        assert not [k for k in authored if k not in kept], (
            f'{where}: the example teaches keys the pipeline drops: '
            f'{[k for k in authored if k not in kept]}')
        for block in ('condition', 'size'):
            authored_block = authored.get(block) or {}
            kept_block = kept.get(block) or {}
            lost = [k for k in authored_block if k not in kept_block]
            assert not lost, f'{where}: {block} loses {lost}'


def test_the_two_fields_with_waiting_consumers_reach_the_row(tmp_path):
    """`contested` feeds `contested_rate`; `thesis_invalidation` is the kill
    switch's per-decision half. Both are in the example, both were dropped."""
    from clawock.decision.ledger import normalize_authored_plan

    plan = _example_plan()
    plan['decisions'][0]['contested'] = True
    plan['decisions'][0]['thesis_invalidation'] = '若 DAU 回升则停止减仓'
    row = normalize_authored_plan(plan, tmp_path / 'decisions.jsonl')['decisions'][0]

    assert row['contested'] is True
    assert row['thesis_invalidation'] == '若 DAU 回升则停止减仓'

    # Absent stays absent rather than becoming a default: "the model did not say"
    # and "the model said no" are different facts, and the coverage series that
    # will now start moving has to be able to tell them apart.
    plan['decisions'][1].pop('contested', None)
    blank = normalize_authored_plan(plan, tmp_path / 'decisions.jsonl')['decisions'][1]
    assert blank['contested'] is None
    assert blank['thesis_invalidation'] is None
