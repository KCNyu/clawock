"""The join between 741 decisions and five signal histories (#1191/#1192/#1193).

The data was never missing — it was in five files with no key between them, which
is why "which information source actually moved a decision" had no answer from
the decision path. These tests hold the join to the two things that make it
usable rather than merely present: it must be **one-sided in time**, and it must
publish **coverage and snapshot age**, because a source that could see 12% of the
decisions is not a source with a weak effect.
"""
import json

import pytest

from clawock.publish import decision_map as dm


def _decision(decision_id, ticker, plan_date, action='cut', leg='us', **extra):
    row = {
        'decision_id': decision_id, 'ticker': ticker, 'plan_date': plan_date,
        'action': action, 'leg': leg, 'driven_by': 'technical',
        'strategy_id': 'core_position', 'confidence': 0.7,
        'rationale': 'momentum broke support; stop hit',
        'evaluation': {'outcome': 'win', 'benefit_t1_pct': 1.0,
                       'benefit_t5_pct': 2.0, 'benefit_t20_pct': 3.0},
    }
    row.update(extra)
    return row


def test_a_snapshot_published_after_the_decision_is_never_used():
    """The look-ahead the rest of the repository spends its effort refusing.

    Taking the nearest snapshot in either direction would let a decision be
    explained by data that did not exist when it was made.
    """
    snapshots = {
        '2026-06-10': {'AAA': {'quant.rsi14': 30.0}},
        '2026-06-20': {'AAA': {'quant.rsi14': 70.0}},
    }
    joined = dm.at_snapshot(_decision('d1', 'AAA', '2026-06-12'), snapshots, {})
    assert joined['values']['quant.rsi14'] == 30.0


def test_a_stale_snapshot_is_dropped_rather_than_joined():
    """A month-old snapshot is a different market, not "the signals at the time"."""
    snapshots = {'2026-05-01': {'AAA': {'quant.rsi14': 30.0}}}
    joined = dm.at_snapshot(_decision('d1', 'AAA', '2026-06-20'), snapshots, {})
    assert joined['values'] == {}


def test_the_age_that_was_used_travels_with_the_value():
    snapshots = {'2026-06-18': {'AAA': {'quant.rsi14': 30.0}}}
    joined = dm.at_snapshot(_decision('d1', 'AAA', '2026-06-20'), snapshots, {})
    assert joined['values']['quant.rsi14'] == 30.0
    assert joined['ages']['quant.rsi14'] == 2


def test_the_nearest_eligible_snapshot_wins_per_signal():
    snapshots = {
        '2026-06-18': {'AAA': {'quant.rsi14': 30.0, 'news.signed_score': 1.0}},
        '2026-06-19': {'AAA': {'quant.rsi14': 40.0}},
    }
    joined = dm.at_snapshot(_decision('d1', 'AAA', '2026-06-20'), snapshots, {})
    assert joined['values'] == {'quant.rsi14': 40.0, 'news.signed_score': 1.0}
    assert joined['ages'] == {'quant.rsi14': 1, 'news.signed_score': 2}


#: A panel result shaped like `panel_scores` returns, so `build` does not have
#: to fit a hidden Markov of bar history to test a join. The real thing is
#: exercised against `signal_panel.evaluate` in its own test below.
STUB_PANEL = {
    'as_of': '2026-06-30', 'first_session': '2026-05-16', 'sessions': 30,
    'rows': 900,
    'selection': {'t1': {'status': 'measured', 'pbo': 0.61, 'n_splits': 70},
                  't5': {'status': 'measured', 'pbo': 0.34, 'n_splits': 70},
                  't20': {'status': 'insufficient_sample', 'pbo': None,
                          'n_splits': None}},
    'by_signal': {'quant.rsi14': {
        horizon: {'mean_ic': 0.1234, 'ic_cluster_ci95': [-0.02, 0.27],
                  'n_observations': 120, 'n_sessions': 20,
                  'status': 'diagnostic', 'ic_clears_zero': False}
        for horizon in dm.HORIZONS}},
    'refutation': {horizon: {'signals': 1, 'collecting': 0, 'fails_placebo': 1,
                             'one_name_flips_it': 0, 'survives_refutation': 0,
                             'interval_clears_zero_but_placebo_does_not': []}
                   for horizon in dm.HORIZONS},
    'method': 'cross-sectional rank IC per session, averaged',
    'interval_caveat': 't20 bands are optimistic',
    'source': 'clawock signal-panel (evaluation.signal_panel.evaluate)',
}


def _decoded(payload, field, index):
    """What `decisions[field][index]` means, through `codes`."""
    raw = payload['decisions'][field][index]
    vocabulary = payload['codes'].get(field)
    return vocabulary[raw] if vocabulary else raw


def _payload(monkeypatch, decisions, snapshots, panel=None):
    monkeypatch.setattr(dm, 'load_signal_snapshots', lambda *a, **k: snapshots)
    monkeypatch.setattr(dm, 'canonical_bar_manifest', lambda: {})
    monkeypatch.setattr(dm, 'leg_sessions', lambda leg: [])
    return dm.build(ledger_rows=decisions, panel=panel or STUB_PANEL)


def test_coverage_is_published_per_signal(monkeypatch):
    """The first number a reader needs, and the one the panel could not give.

    A source joined to two of ten decisions is not weak; it was not there.
    """
    decisions = [_decision(f'd{index}', 'AAA', f'2026-06-{index + 1:02d}')
                 for index in range(10)]
    snapshots = {f'2026-06-{index + 1:02d}': {'AAA': {'quant.rsi14': 50.0}}
                 for index in range(2)}
    payload = _payload(monkeypatch, decisions, snapshots)
    card = payload['info_source_cards'][0]
    assert card['signal'] == 'quant.rsi14'
    # Two snapshots, ten decisions, a five-session age bound: the 06-02 snapshot
    # stays eligible through 06-07, so seven decisions join and three do not.
    # Coverage is the number a reader acts on and it is 70%, not 20% — which is
    # exactly why the age bound is published beside it.
    assert card['decisions_joined'] == 7
    assert card['decision_coverage_pct'] == 70.0
    assert card['median_snapshot_age_sessions'] == 2
    assert card['max_snapshot_age_sessions'] == 5


def test_the_payload_is_columnar_and_the_snapshot_rows_line_up(monkeypatch):
    """Repeating 33 signal names in 741 entries was 80% of the payload."""
    decisions = [_decision(f'd{index}', 'AAA', f'2026-06-{index + 1:02d}')
                 for index in range(5)]
    snapshots = {f'2026-06-{index + 1:02d}': {'AAA': {'quant.rsi14': float(index)}}
                 for index in range(5)}
    payload = _payload(monkeypatch, decisions, snapshots)
    columns = payload['decisions']
    assert len(payload['decision_snapshots']) == len(columns['decision_id'])
    position = payload['signal_order'].index('quant.rsi14')
    for index, decision_id in enumerate(columns['decision_id']):
        expected = float(decision_id[1:])
        assert payload['decision_snapshots'][index][position] == expected


def test_the_timeline_indexes_into_the_columns_instead_of_copying_them(monkeypatch):
    decisions = [_decision('d0', 'AAA', '2026-06-01'),
                 _decision('d1', 'BBB', '2026-06-02')]
    payload = _payload(monkeypatch, decisions, {})
    assert payload['ticker_timelines'] == {'AAA': [0], 'BBB': [1]}
    assert _decoded(payload, 'ticker', 0) == 'AAA'


def test_the_matrix_is_the_board_and_is_not_published_twice(monkeypatch):
    """Two copies of one aggregate are two things that can disagree.

    `decision_signal_matrix` used to be a pointer saying "the matrix is
    `info_source_cards[].by_action`". Once the page became one board, the
    pointer had no reader either.
    """
    payload = _payload(monkeypatch, [_decision('d0', 'AAA', '2026-06-01')],
                       {'2026-06-01': {'AAA': {'quant.rsi14': 50.0}}})
    assert 'decision_signal_matrix' not in payload
    card = payload['info_source_cards'][0]
    assert set(card['by_action']) <= set(payload['actions'])


def test_degradation_drops_prose_before_it_drops_signal_rows(monkeypatch):
    decisions = [_decision(f'd{index}', 'AAA', f'2026-06-{index % 28 + 1:02d}',
                           rationale='x' * 4000) for index in range(60)]
    snapshots = {f'2026-06-{index:02d}': {'AAA': {'quant.rsi14': 50.0}}
                 for index in range(1, 29)}
    payload = dm.degrade(_payload(monkeypatch, decisions, snapshots), max_bytes=60_000)
    assert payload['degradation']['level'] == 'no_rationale_text'
    assert 'rationale' not in payload['decisions']
    assert any(row for row in payload['decision_snapshots'])


def test_an_older_decision_keeps_its_timeline_marker_when_its_snapshot_is_dropped(
        monkeypatch):
    """A decision that vanishes breaks its own dot, and the timeline is the page."""
    decisions = [_decision(f'd{index}', 'AAA', f'2026-06-{index % 28 + 1:02d}')
                 for index in range(dm.DRAWER_LIMIT * 3)]
    snapshots = {f'2026-06-{index:02d}': {'AAA': {'quant.rsi14': 50.0}}
                 for index in range(1, 29)}
    built = _payload(monkeypatch, decisions, snapshots)
    # The budget is the size the second degradation level actually produces, so
    # the chain is forced exactly that far and no further — one byte less would
    # drop the timelines, which is the level being distinguished from.
    import copy
    at_level_two = copy.deepcopy(built)
    at_level_two['decisions'] = {field: values for field, values
                                 in built['decisions'].items()
                                 if field != 'rationale'}
    rows = at_level_two['decision_snapshots']
    cut = max(0, len(rows) - dm.DRAWER_LIMIT)
    at_level_two['decision_snapshots'] = [None] * cut + rows[cut:]
    # The real dict, not a placeholder: `degradation` is written into the
    # payload it measures, so a shorter stand-in here makes the reconstructed
    # size smaller than the one `degrade` actually weighs — and the slack below
    # then silently stops being the thing that decides the level.
    at_level_two['degradation'] = {
        'level': 'recent_decisions_only',
        'cost': dict(dm.DEGRADATION)['recent_decisions_only'],
        'levels': [name for name, _ in dm.DEGRADATION], 'bytes': 0}
    payload = dm.degrade(built, max_bytes=len(dm.encode(at_level_two).encode())
                         + dm.SIZE_MARGIN + 200)
    assert payload['degradation']['level'] == 'recent_decisions_only'
    assert len(payload['decisions']['decision_id']) == len(decisions)
    assert len(payload['ticker_timelines']['AAA']) == len(decisions)
    kept = sum(1 for row in payload['decision_snapshots'] if row)
    assert 0 < kept <= dm.DRAWER_LIMIT


def test_the_cards_republish_the_panel_instead_of_recomputing_it(monkeypatch):
    """One implementation of a rank IC, not two.

    A second one here would let the panel print a signal's t5 IC as +0.19 while
    the card beside the decisions it stood next to said +0.17, with nothing to
    say which was wrong.
    """
    payload = _payload(monkeypatch, [_decision('d0', 'AAA', '2026-06-01')],
                       {'2026-06-01': {'AAA': {'quant.rsi14': 50.0}}})
    card = next(c for c in payload['info_source_cards']
                if c['signal'] == 'quant.rsi14')
    for horizon in dm.HORIZONS:
        assert card['panel'][horizon] == STUB_PANEL['by_signal']['quant.rsi14'][horizon]
    # Verbatim, including the digits: rounding here would be a third version of
    # a number that already exists twice on the site.
    assert card['panel']['t5']['mean_ic'] == 0.1234


def test_no_rank_correlation_is_computed_in_this_module():
    """The gate behind the claim above, and the only one that survives a rewrite.

    Names, not text: the docstring is allowed to *say* `spearman` while
    explaining why nothing here computes one, and a substring check over the
    file would fail on its own documentation.
    """
    import io
    import tokenize

    with open(dm.__file__, encoding='utf-8') as handle:
        names = {token.string for token in tokenize.generate_tokens(
            io.StringIO(handle.read()).readline)
            if token.type == tokenize.NAME}
    banned = {name for name in names
              if any(mark in name.lower()
                     for mark in ('spearman', 'rank_ic', 'pearson', 'corrcoef'))}
    assert banned == set(), (
        f'{sorted(banned)} in decision_map: the IC would have a second '
        'implementation and the two can disagree')


def test_a_signal_the_panel_never_scored_reads_as_absent_not_as_zero(monkeypatch):
    payload = _payload(monkeypatch, [_decision('d0', 'AAA', '2026-06-01')],
                       {'2026-06-01': {'AAA': {'quant.rsi14': 50.0,
                                               'news.hard_catalyst': 1.0}}})
    absent = next(c for c in payload['info_source_cards']
                  if c['signal'] == 'news.hard_catalyst')
    assert absent['panel'] is None


def test_the_selection_pbo_is_published_once_for_the_panel_not_per_signal(monkeypatch):
    """PBO is a property of choosing among the signals, not of any one of them."""
    payload = _payload(monkeypatch, [_decision('d0', 'AAA', '2026-06-01')], {})
    assert payload['signal_panel']['selection'] == STUB_PANEL['selection']
    assert payload['signal_panel']['refutation'] == STUB_PANEL['refutation']
    assert 'by_signal' not in payload['signal_panel']
    for card in payload['info_source_cards']:
        assert 'pbo' not in (card.get('panel') or {})


def test_the_kpi_numbers_are_echoed_so_the_banner_can_be_checked(monkeypatch):
    """Counted at build time and published, not counted in the browser."""
    decisions = [
        _decision('d0', 'AAA', '2026-06-01'),
        _decision('d1', 'AAA', '2026-06-02'),
        _decision('d2', 'BBB', '2026-06-02'),
        _decision('d3', 'BBB', '2026-06-20'),
    ]
    snapshots = {'2026-06-01': {'AAA': {'quant.rsi14': 50.0}},
                 '2026-06-02': {'AAA': {'quant.rsi14': 51.0}}}
    payload = _payload(monkeypatch, decisions, snapshots)
    kpi = payload['kpi']
    assert kpi['decisions'] == 4
    assert kpi['sessions'] == 3                # 06-01, 06-02, 06-20
    assert kpi['ticker_sessions'] == 4         # every ticker x date pair distinct
    assert kpi['tickers'] == 2
    assert kpi['signals_referenced'] == len(payload['info_source_cards'])
    # AAA joins on both its dates; BBB never has a snapshot of its own.
    assert kpi['decisions_with_any_signal'] == 2
    assert kpi['decision_signal_coverage_pct'] == 50.0
    assert kpi['panel_as_of'] == STUB_PANEL['as_of']


def test_the_two_dates_the_page_shows_are_both_named(monkeypatch):
    """The map's last decision and the panel's last session are different facts.

    Forcing them equal would be a lie in whichever direction it was forced:
    signals are written on days no decision was made.
    """
    payload = _payload(monkeypatch, [_decision('d0', 'AAA', '2026-06-01')], {})
    assert payload['as_of'] == '2026-06-01'
    assert payload['signal_panel']['as_of'] == STUB_PANEL['as_of']
    assert payload['kpi']['panel_as_of'] == payload['signal_panel']['as_of']


def test_panel_scores_reshapes_signal_panel_without_touching_its_numbers():
    """The adapter, against a real `evaluate` payload rather than a mock of it."""
    evaluation = {
        'coverage': {'last_session': '2026-08-25', 'first_session': '2026-05-16',
                     'sessions': 83, 'rows': 10032},
        'signals': {'quant.rsi14': {
            horizon: {'mean_ic': -0.2037, 'ic_cluster_ci95': [-0.31, -0.09],
                      'n_observations': 517, 'n_sessions': 42,
                      'status': 'diagnostic', 'ic_clears_zero': True,
                      'directional_hit_rate': 0.44}
            for horizon in dm.HORIZONS}},
        'selection': {horizon: {'status': 'measured', 'pbo': 0.34,
                                'n_splits': 70, 'selected_signals': {'a': 3}}
                      for horizon in dm.HORIZONS},
        'refutation_summary': {
            horizon: {'signals': 1, 'collecting': 0, 'fails_placebo': 0,
                      'one_name_flips_it': 0, 'survives_refutation': 1,
                      'interval_clears_zero_but_placebo_does_not': []}
            for horizon in dm.HORIZONS},
        'method': 'cross-sectional rank IC per session, averaged',
        'interval_caveat': 't20 bands are optimistic',
    }
    panel = dm.panel_scores(evaluation=evaluation)
    row = panel['by_signal']['quant.rsi14']['t5']
    assert row['mean_ic'] == -0.2037
    assert row['ic_cluster_ci95'] == [-0.31, -0.09]
    assert row['ic_clears_zero'] is True
    # Only the published fields travel: the hit rate has its own registration
    # rules and belongs on the panel, not on a card about decision adjacency.
    assert set(row) == set(dm.PANEL_FIELDS)
    assert panel['as_of'] == '2026-08-25'
    assert panel['selection']['t5'] == {'status': 'measured', 'pbo': 0.34,
                                        'n_splits': 70}
    # Counts travel; the per-signal placebo detail does not — thirty-three
    # signals of it would cost more payload than the page has to spend.
    assert panel['refutation']['t5']['survives_refutation'] == 1
    assert set(panel['refutation']['t5']) == {
        'signals', 'collecting', 'fails_placebo', 'one_name_flips_it',
        'survives_refutation', 'interval_clears_zero_but_placebo_does_not'}


def test_the_panel_block_is_dropped_before_the_timelines_are(monkeypatch):
    """What it costs to recover decides the order.

    `clawock signal-panel` reprints the IC block on demand; nothing reprints the
    timeline, and the timeline is what the page is for. Without this step the
    fall was one 9KB stumble from a slightly shorter map to a table of
    aggregates.
    """
    decisions = [_decision(f'd{index}', 'AAA', f'2026-06-{index % 28 + 1:02d}')
                 for index in range(400)]
    snapshots = {f'2026-06-{index:02d}': {'AAA': {'quant.rsi14': 50.0}}
                 for index in range(1, 29)}
    built = _payload(monkeypatch, decisions, snapshots)
    assert dm.DEGRADATION[3][0] == 'no_panel_scores'
    assert [name for name, _ in dm.DEGRADATION].index('no_panel_scores') < \
        [name for name, _ in dm.DEGRADATION].index('cards_and_matrix_only')

    # Squeeze until exactly the panel step is needed.
    full = len(dm.encode(built).encode('utf-8'))
    stripped = dm.degrade(json.loads(dm.encode(built)), max_bytes=full // 3)
    assert stripped['degradation']['level'] in ('no_panel_scores',
                                                'cards_and_matrix_only')
    if stripped['degradation']['level'] == 'no_panel_scores':
        assert stripped['ticker_timelines']
    assert all(card.get('panel') is None
               for card in stripped['info_source_cards'])
    # And it says so, so the page does not report a dropped block as a finding.
    assert stripped['signal_panel']['dropped'] == 'payload budget'


def test_a_kind_counts_a_decision_once_however_many_of_its_signals_joined(monkeypatch):
    """The roll-up the board's parent rows read, and the reason it is published.

    A decision that joined `quant.rsi14` and `quant.trend` is one decision quant
    saw. Summing the signal rows in the browser — the obvious thing to do with
    the old payload — would have counted it twice and claimed quant a coverage
    it does not have, on the page whose whole first number is coverage.
    """
    decisions = [_decision(f'd{index}', 'AAA', f'2026-06-{index + 1:02d}')
                 for index in range(4)]
    snapshots = {f'2026-06-{index + 1:02d}':
                 {'AAA': {'quant.rsi14': 50.0, 'quant.trend': 1.0}}
                 for index in range(4)}
    payload = _payload(monkeypatch, decisions, snapshots)

    kind = next(card for card in payload['source_kind_cards']
                if card['signal'] == 'quant')
    signals = [card for card in payload['info_source_cards']
               if card['source_kind'] == 'quant']
    assert len(signals) == 2
    assert sum(card['decisions_joined'] for card in signals) == 8
    assert kind['decisions_joined'] == 4
    assert kind['decision_coverage_pct'] == 100.0
    assert sorted(kind['signals']) == ['quant.rsi14', 'quant.trend']
    # And the buckets are over the same distinct set, not the doubled one.
    assert kind['by_action']['cut']['count'] == 4


def test_a_kind_bucket_is_never_larger_than_the_book(monkeypatch):
    """The invariant that survives a rewrite: distinct decisions, so <= total."""
    decisions = [_decision(f'd{index}', 'AAA', f'2026-06-{index + 1:02d}')
                 for index in range(6)]
    snapshots = {f'2026-06-{index + 1:02d}':
                 {'AAA': {'quant.rsi14': 50.0, 'quant.trend': 1.0,
                          'news.hard_catalyst': 1.0}}
                 for index in range(6)}
    payload = _payload(monkeypatch, decisions, snapshots)
    total = payload['kpi']['decisions']
    for card in payload['source_kind_cards']:
        assert card['decisions_joined'] <= total
        assert sum(bucket['count'] for bucket in card['by_action'].values()) <= total


def test_repeated_columns_are_a_vocabulary_plus_indices(monkeypatch):
    """51KB of a 200KB budget was 741 copies of about a dozen strings."""
    decisions = [_decision('d0', 'AAA', '2026-06-01', action='cut'),
                 _decision('d1', 'AAA', '2026-06-01', action='cut'),
                 _decision('d2', 'BBB', '2026-06-02', action='watch')]
    payload = _payload(monkeypatch, decisions, {})
    assert payload['codes']['action'] == ['cut', 'watch']
    assert payload['decisions']['action'] == [0, 0, 1]
    assert payload['codes']['ticker'] == ['AAA', 'BBB']
    assert set(payload['codes']) == set(dm.CODED_COLUMNS)
    # Round-trips: the column still says what it said.
    for index, expected in enumerate(('cut', 'cut', 'watch')):
        assert _decoded(payload, 'action', index) == expected
    # Columns that are not coded stay values.
    assert 'confidence' not in payload['codes']
    assert payload['decisions']['confidence'][0] == 0.7


def test_coding_shrinks_the_payload_it_was_added_for(monkeypatch):
    decisions = [_decision(f'd{index}', 'AAA', '2026-06-01',
                           action='hold_and_watch', strategy_id='core_position')
                 for index in range(200)]
    payload = _payload(monkeypatch, decisions, {})
    plain = dict(payload, decisions=dict(
        payload['decisions'],
        **{field: [payload['codes'][field][value]
                   for value in payload['decisions'][field]]
           for field in dm.CODED_COLUMNS}))
    plain.pop('codes')
    assert len(dm.encode(payload)) < len(dm.encode(plain)) * 0.75


def test_the_encoding_that_is_measured_is_the_encoding_that_is_written():
    """The gate has to check the bytes that ship.

    It measured a compact encoding while the writer pretty-printed, and the file
    that shipped was 343KB against a budget the build reported as met at 175KB.
    """
    payload = {'a': 1, 'b': [1, 2, 3]}
    assert dm.encode(payload) == json.dumps(payload, ensure_ascii=False,
                                            separators=(',', ':'))
    assert '\n' not in dm.encode(payload)


def test_the_size_margin_covers_the_self_referential_byte_count():
    """`degradation.bytes` is written into the payload it measures."""
    assert dm.SIZE_MARGIN > len(str(dm.MAX_BYTES))


def test_the_published_payload_is_under_budget_and_names_its_level():
    from pathlib import Path
    path = Path(dm.OUT)
    if not path.exists():
        pytest.skip('decision_map.json has not been generated in this checkout')
    raw = path.read_bytes()
    assert len(raw) <= dm.MAX_BYTES, len(raw)
    payload = json.loads(raw)
    assert payload['schema_version'] == dm.SCHEMA_VERSION
    assert payload['degradation']['level'] in [name for name, _ in dm.DEGRADATION]
    assert payload['generated_at']

    # The panel block, as it actually shipped. `panel_scores` copies the fields
    # out of `signal_panel.evaluate` and rounds nothing, so any extra key here
    # would mean the shipped file grew a number this module invented.
    panel = payload.get('signal_panel') or {}
    if not panel.get('dropped'):
        assert panel['source'].startswith('clawock signal-panel')
        assert len(panel['as_of']) == 10
        for card in payload['info_source_cards']:
            if card.get('panel') is None:
                continue
            assert set(card['panel']) == set(dm.HORIZONS)
            for row in card['panel'].values():
                assert set(row) == set(dm.PANEL_FIELDS)
    kpi = payload['kpi']
    assert kpi['decisions'] == payload['coverage']['decisions']
    assert kpi['sessions'] == payload['coverage']['sessions']
    assert 0 <= kpi['decision_signal_coverage_pct'] <= 100


def test_rebuilding_is_deterministic_apart_from_the_timestamp(monkeypatch):
    decisions = [_decision(f'd{index}', 'AAA', f'2026-06-{index + 1:02d}')
                 for index in range(6)]
    snapshots = {'2026-06-03': {'AAA': {'quant.rsi14': 50.0}}}
    first = _payload(monkeypatch, decisions, snapshots)
    second = _payload(monkeypatch, decisions, snapshots)
    first.pop('generated_at'), second.pop('generated_at')
    assert dm.encode(first) == dm.encode(second)
