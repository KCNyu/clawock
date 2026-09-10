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
            'breaches': [
                {'type': 'single_name', 'leg': 'US', 'ticker': 'SPCH'},
                # A leg-level cap: the breach is on the book, not on a name,
                # so the row carries no ticker (real shape, `guardrail.py`).
                {'type': 'leveraged_exposure', 'leg': 'HK', 'ticker': None},
            ],
            'hard_stop_watch': [
                {'type': 'leveraged_hard_stop', 'leg': 'HK', 'ticker': '07226'},
            ],
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
            'risk:leveraged_hard_stop:07226',   # the same stop, scoped to its name
            'risk:leveraged_exposure:HK',       # a leg-level cap, scoped to its leg
            'risk:leveraged_exposure:07226',    # that cap has no ticker to borrow
            'risk:margin_call',                 # no such breach today
            'quant:SPCH:dist_ma200_pct',        # a present signal field
            'quant:SPCH:rsi14',                 # present but null → not citable
        ]}},
    ]}

    pruned, dropped = brief_postflight.prune_debate_citations(plan, _context())

    assert pruned['decisions'][0]['debate']['evidence_ids'] == [
        'news:evt_real', 'risk:single_name:SPCH',
        'risk:leveraged_hard_stop', 'risk:leveraged_hard_stop:07226',
        'risk:leveraged_exposure:HK', 'quant:SPCH:dist_ma200_pct',
    ]
    assert dropped == [
        'd1:news:evt_invented', 'd1:risk:leveraged_exposure:07226',
        'd1:risk:margin_call', 'd1:quant:SPCH:rsi14',
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


def _guardrail_from_the_real_producer():
    """A guardrail built by the module that builds the morning's, not by hand.

    Every hand-written fixture in this file agreed with the resolver about the
    shape of a `risk_guardrail` row. Production did not: `hard_stop_watch` rows
    carried no `type` at all, so the resolver skipped all of them and every
    hard-stop citation the model wrote was dropped as "unresolvable" — 14 of
    the 28 dropped refs sampled between 09-01 and 09-07. A fixture cannot catch
    that. Only the producer's own output can.
    """
    from clawock.portfolio import guardrail as guardrail_mod

    def holding(ticker, value, *, leveraged=False, pnl_pct=0.0, shares=100):
        cost_value = value / (1 + pnl_pct / 100)
        return {
            'ticker': ticker, 'name': ticker, 'shares': shares,
            'cost_basis': cost_value / shares, 'current_value': value,
            'is_leveraged_etf': leveraged,
        }

    # One 2x name deep enough under water to trip the hard stop, sized so the
    # leg also breaches its single-name and leveraged-exposure caps; a second
    # leg holding a name inside the review band.
    hk = [holding('07226', 700.0, leveraged=True, pnl_pct=-27.1),
          holding('00700', 300.0)]
    us = [holding('SPCH', 500.0, leveraged=True, pnl_pct=-18.2),
          holding('AAPL', 450.0), holding('MSFT', 50.0)]
    return guardrail_mod.compute_risk_guardrail(
        hk, us,
        guardrail_mod.compute_concentration(hk),
        guardrail_mod.compute_concentration(us),
        {'us': {'beta_spx': 5.5}},
    )


def test_every_guardrail_row_the_producer_emits_can_be_cited():
    from clawock.harness import brief_postflight

    guardrail = _guardrail_from_the_real_producer()
    citable = brief_postflight._citable_refs({'risk_guardrail': guardrail})

    rows = [(key, row)
            for key in ('breaches', 'hard_stop_watch', 'concentration_reviews')
            for row in guardrail.get(key) or []]
    assert rows, 'the fixture stopped tripping any cap — it proves nothing now'
    assert any(key == 'hard_stop_watch' for key, _ in rows), (
        'the family that was uncitable for a week must stay in this fixture')

    for key, row in rows:
        kind = row.get('type')
        assert kind, f'{key} row has no type, so no citation can name it: {row}'
        assert f'risk:{kind}' in citable
        if row.get('ticker'):
            assert f"risk:{kind}:{row['ticker']}" in citable
        else:
            # No ticker to point at: the leg is the only scope the row has,
            # and without it the model borrows a ticker out of the prose.
            assert f"risk:{kind}:{row['leg']}" in citable


def test_every_row_the_producer_emits_advertises_an_id_the_resolver_accepts():
    """The model copies an id now; this is what keeps the copy resolvable.

    The skill used to teach the grammar — namespace, the full `type`
    vocabulary, ticker form vs leg form, "do not invent a name" — and a gate
    here kept that vocabulary equal to the producer's. It was not enough: on
    2026-09-08 the day's only two dropped citations were both
    `risk:single_name:00100`, aimed at a row whose own type is
    `single_name_review`. Right row, and a name another row legitimately
    carries. Composing an identifier from a grammar is the step that fails, so
    the row now carries the finished string and the skill says to copy it.

    Which moves the invariant: not "the skill lists what the producer emits",
    but "every row the producer emits advertises an id, and every advertised id
    resolves". Built from the producer plus `attach_breach_ids`, because that
    pair is what the morning's context actually contains.
    """
    from clawock.decision import risk as discipline
    from clawock.harness import brief_postflight

    guardrail = discipline.attach_breach_ids(_guardrail_from_the_real_producer())
    citable = brief_postflight._citable_refs({'risk_guardrail': guardrail})

    rows = [(key, row) for key in discipline.GUARDRAIL_ROW_KEYS
            for row in guardrail.get(key) or []]
    assert rows, 'the fixture stopped tripping any cap — it proves nothing now'
    assert any(key == 'concentration_reviews' for key, _ in rows), (
        'the family the model got wrong on 09-08 must stay in this fixture')

    for key, row in rows:
        advertised = row.get('evidence_id')
        assert advertised, f'{key} row carries no evidence_id to copy: {row}'
        assert advertised in citable, (
            f'{key} advertises {advertised!r}, which resolves to nothing')
        # Scoped, always: an unscoped `risk:<type>` on a book with two legs
        # points at whichever row the reader guesses.
        assert advertised.count(':') == 2, advertised

    skill = (Path(__file__).resolve().parents[1]
             / 'skills' / 'daily-deep-brief' / 'SKILL.md').read_text(
                 encoding='utf-8')
    assert '`evidence_id`' in skill, (
        'the skill must tell the model which field to copy')


def test_one_hard_stop_has_one_name_across_every_surface_that_shows_it():
    """Three surfaces described the same row, and none of them agreed.

    The rendered brief table printed `hard_stop`, the decision packet's
    constraint said `leveraged_hard_stop`, and the guardrail row the resolver
    reads carried no `type` at all — so whichever name the model copied, its
    citation was dropped. `risk:hard_stop:*` was the single most common dropped
    form (11 of 28 sampled).
    """
    from clawock.decision import packet as packet_mod
    from clawock.harness import brief_postflight, brief_render

    guardrail = _guardrail_from_the_real_producer()
    stop = (guardrail.get('hard_stop_watch') or [])[0]
    name, ticker = stop['type'], stop['ticker']

    rendered = brief_render.risk_section({'risk_guardrail': guardrail})
    assert f'| {name} |' in rendered, rendered

    risks = packet_mod._risk_map({'risk_guardrail': guardrail}, {ticker})
    assert [r['type'] for r in risks[ticker] if r['kind'] == 'hard_stop'] == [name]

    citable = brief_postflight._citable_refs({'risk_guardrail': guardrail})
    assert f'risk:{name}:{ticker}' in citable


def test_the_key_a_row_is_filed_under_resolves_to_that_row():
    """`hard_stop_watch` is the list; `leveraged_hard_stop` is the row's type.

    The context hands the model both names — the key wrapping the row and the
    type inside it — and on 2026-09-10 it copied the outer one twice
    (`risk:hard_stop_watch:RKLX`, `risk:hard_stop_watch:SPCH`), two of that
    morning's nine dropped citations. The row those name is unambiguous, so the
    resolver now accepts the key as an alias for it.
    """
    from clawock.decision import risk as discipline
    from clawock.harness import brief_postflight

    guardrail = discipline.attach_breach_ids(_guardrail_from_the_real_producer())
    citable = brief_postflight._citable_refs({'risk_guardrail': guardrail})

    stops = guardrail.get('hard_stop_watch') or []
    assert stops, 'the fixture stopped tripping a hard stop — it proves nothing'
    for stop in stops:
        canonical = f"risk:{stop['type']}:{stop['ticker']}"
        alias = f"risk:hard_stop_watch:{stop['ticker']}"
        assert canonical in citable
        assert alias in citable, (
            f'{alias} is the name the model copied on 09-10 and it still '
            f'resolves to nothing')


def test_a_mixed_list_lends_its_name_to_nobody():
    """The alias is only unambiguous where the list is.

    `breaches` holds `single_name`, `leveraged_exposure`, `beta`,
    `factor_concentration` — `risk:breaches:07226` names a row without saying
    which, and a citation that vague is the thing this resolver exists to
    refuse. Computed from the rows, not from a list of key names, so a family
    that later becomes homogeneous (or stops being) does not need a second
    edit here to stay right.
    """
    from clawock.harness import brief_postflight

    guardrail = {
        'breaches': [
            {'type': 'single_name', 'leg': 'HK', 'ticker': '07226'},
            {'type': 'beta', 'leg': 'US', 'ticker': None},
        ],
        'hard_stop_watch': [
            {'type': 'leveraged_hard_stop', 'leg': 'US', 'ticker': 'RKLX'},
        ],
        'concentration_reviews': [],
    }
    citable = brief_postflight._citable_refs({'risk_guardrail': guardrail})

    assert 'risk:breaches:07226' not in citable
    assert 'risk:breaches' not in citable
    assert 'risk:single_name:07226' in citable
    assert 'risk:hard_stop_watch:RKLX' in citable

    # One type in the list, spelled differently: still one row, still an alias.
    guardrail['breaches'] = [{'type': 'single_name', 'leg': 'HK',
                              'ticker': '07226'}]
    citable = brief_postflight._citable_refs({'risk_guardrail': guardrail})
    assert 'risk:breaches:07226' in citable


def test_a_news_event_advertises_the_id_it_wants_copied():
    """The `risk:` half learned this on 09-08; the `news:` half had not.

    A real event id is `evt_3ffdc891b1dd9eb52b84` — opaque, and nothing in it
    says which story it is. On 2026-09-10 the model cited
    `news:00100-humain-m3-2026-09-04` and `news:02208-h1-report-2026-09-08`:
    `<ticker>-<topic>-<date>`, the format a human would choose. Both resolved
    to nothing. Asking for an opaque token it cannot check is asking for a
    plausible one, so the projected event now carries the finished string.
    """
    from clawock.decision import risk as discipline
    from clawock.harness import brief_postflight

    events = discipline.attach_event_ids([
        {'event_id': 'evt_3ffdc891b1dd9eb52b84', 'ticker': '00100'},
        {'event_id': 'evt_77a4a4ba2707f628518c', 'ticker': '02208'},
    ])
    assert [e['evidence_id'] for e in events] == [
        'news:evt_3ffdc891b1dd9eb52b84', 'news:evt_77a4a4ba2707f628518c']

    citable = brief_postflight._citable_refs(
        {'news_evidence_graph': {'events': events}})
    for event in events:
        assert event['evidence_id'] in citable
    # The invented shape is still dropped — this is a copy aid, not an amnesty.
    assert 'news:00100-humain-m3-2026-09-04' not in citable


def test_the_projection_the_model_reads_is_the_one_that_advertises():
    """An `evidence_id` on the source graph and not on the 40-row projection
    would be a field nobody reads: the model is handed the projection."""
    import inspect
    from clawock.harness import brief_preflight

    source = inspect.getsource(brief_preflight)
    block = source[source.index("'events': "):]
    block = block[:block.index('],') + 2]
    assert 'attach_event_ids' in block, (
        'the projection handed to the model must be the one carrying the ids')


def test_every_namespace_the_skill_teaches_says_copy_not_compose():
    """Three namespaces, one discipline. `quant:` is deliberately excluded: its
    reference IS composed, from a ticker and a field the model reads off the
    row, and both halves are legible — nothing opaque to copy wrong."""
    skill = (Path(__file__).resolve().parents[1]
             / 'skills' / 'daily-deep-brief' / 'SKILL.md').read_text(
                 encoding='utf-8')
    block = skill[skill.index('`evidence_ids`（≤6 条'):]
    block = block[:block.index('**没有可引的证据就不填**')]
    for namespace in ('news', 'risk'):
        line = block[block.index(f'- `{namespace}:'):]
        line = line[:line.index('\n')]
        assert '`evidence_id`' in line, (
            f'the {namespace}: namespace still teaches a grammar to compose: '
            f'{line}')
