"""A brief-lane debate can now cite its evidence, and only what resolves (#1141).

The two lanes disagreed with themselves: `workflows/validators.py` has required
`evidence_ids` on each case of a portable-workflow debate since it shipped,
while the daily brief accepted a debate whose bull case cited nothing. So the
brief's strongest claim could rest on a number that appears in no evidence row,
and nothing caught it.

This wires the same discipline onto the brief lane, with one deliberate
difference: an unresolvable citation is *dropped and counted*, never fatal.
`validate_plan` is a publish gate — a plan that fails it degrades to no brief,
not to a thinner one — and an invented reference inside an annotation is not
worth that trade.
"""

import json
from pathlib import Path


def _context():
    return {
        'news_evidence_graph': {'events': [
            {'event_id': 'evt_real', 'ticker': 'SPCH'},
        ]},
        'risk_guardrail': {
            'breaches': [{'type': 'single_name', 'ticker': 'SPCH'}],
            'hard_stop_watch': [{'type': 'leveraged_hard_stop', 'ticker': '07226'}],
        },
        'quant_signals': {'rows': {
            'SPCH': {'dist_ma200_pct': -12.4, 'rsi14': None},
        }},
    }


def test_only_resolvable_namespaces_survive_normalization():
    from clawock.decision import ledger

    kept = ledger.normalize_debate({
        'bull': 'x',
        'evidence_ids': [
            'news:evt_real',          # good
            'quant:SPCH:rsi14',       # good shape (resolution happens later)
            'news:evt_real',          # duplicate
            'vibes:it felt toppy',    # unknown namespace
            'news:',                  # empty reference
            42,                       # not a string
        ],
    })['evidence_ids']

    assert kept == ['news:evt_real', 'quant:SPCH:rsi14']


def test_the_cap_holds():
    from clawock.decision import ledger

    many = [f'news:evt_{i}' for i in range(20)]
    assert len(ledger.normalize_debate({'bull': 'x', 'evidence_ids': many})
               ['evidence_ids']) == ledger.DEBATE_EVIDENCE_MAX


def test_validation_rejects_a_shape_it_cannot_normalize():
    from clawock.decision import ledger

    errors = ledger.validate_decision({
        'decision_id': 'd1', 'debate': {'bull': 'x', 'evidence_ids': ['vibes:x']},
    })
    assert [e for e in errors if 'evidence_ids' in e]

    errors = ledger.validate_decision({
        'decision_id': 'd1', 'debate': {'bull': 'x', 'evidence_ids': ['news:evt_real']},
    })
    assert not [e for e in errors if 'evidence_ids' in e]


def test_the_context_is_what_decides_whether_a_citation_stands():
    from clawock.harness import brief_postflight

    plan = {'decisions': [
        {'decision_id': 'd1', 'debate': {'bull': 'x', 'evidence_ids': [
            'news:evt_real',                    # in the graph
            'news:evt_invented',                # not in the graph
            'risk:single_name:SPCH',            # a real breach, with its ticker
            'risk:leveraged_hard_stop',         # a real hard stop, unscoped
            'risk:margin_call',                 # no such breach today
            'quant:SPCH:dist_ma200_pct',        # a present signal field
            'quant:SPCH:rsi14',                 # present but null → not citable
        ]}},
    ]}

    pruned, dropped = brief_postflight.prune_debate_citations(plan, _context())

    assert pruned['decisions'][0]['debate']['evidence_ids'] == [
        'news:evt_real', 'risk:single_name:SPCH',
        'risk:leveraged_hard_stop', 'quant:SPCH:dist_ma200_pct',
    ]
    assert dropped == [
        'd1:news:evt_invented', 'd1:risk:margin_call', 'd1:quant:SPCH:rsi14',
    ]


def test_a_debate_that_cited_only_fiction_loses_the_field_entirely():
    from clawock.harness import brief_postflight

    plan = {'decisions': [
        {'decision_id': 'd1', 'debate': {'bear': 'x', 'evidence_ids': ['news:evt_nope']}},
    ]}
    pruned, dropped = brief_postflight.prune_debate_citations(plan, _context())

    debate = pruned['decisions'][0]['debate']
    assert 'evidence_ids' not in debate, (
        'an empty list would publish as "cited nothing" — the same as never '
        'having written the field, but noisier')
    assert debate['bear'] == 'x', 'the argument itself is not the thing in doubt'
    assert dropped == ['d1:news:evt_nope']


def test_no_context_prunes_nothing():
    """A retry with no context must not quietly strip a plan's citations."""
    from clawock.harness import brief_postflight

    plan = {'decisions': [
        {'decision_id': 'd1', 'debate': {'bull': 'x', 'evidence_ids': ['news:evt_real']}},
    ]}
    for empty in (None, {}, {'news_evidence_graph': {}}):
        pruned, dropped = brief_postflight.prune_debate_citations(
            json.loads(json.dumps(plan)), empty)
        assert pruned['decisions'][0]['debate']['evidence_ids'] == ['news:evt_real']
        assert dropped == []


def test_the_skill_documents_the_namespaces_it_will_be_held_to():
    """The model writes this field; a contract it cannot read is not a contract."""
    root = Path(__file__).resolve().parents[1]
    skill = (root / 'skills' / 'daily-deep-brief' / 'SKILL.md').read_text(
        encoding='utf-8')

    from clawock.decision import ledger

    assert 'evidence_ids' in skill
    for namespace in ledger.DEBATE_EVIDENCE_NAMESPACES:
        assert f'{namespace}:' in skill, (
            f'the {namespace} namespace resolves in postflight but is not '
            'documented where the plan is authored')


def test_the_page_shows_what_a_debate_stood_on():
    root = Path(__file__).resolve().parents[1]
    js = (root / 'site' / 'assets' / 'js' / 'dashboard.render.js').read_text(
        encoding='utf-8')

    assert 'evidence_ids' in js and 'dbt-cite' in js, (
        'a citation nobody can see is the same unverifiable claim, one layer in')
