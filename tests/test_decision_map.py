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


def _payload(monkeypatch, decisions, snapshots):
    monkeypatch.setattr(dm, 'load_signal_snapshots', lambda *a, **k: snapshots)
    monkeypatch.setattr(dm, 'canonical_bar_manifest', lambda: {})
    monkeypatch.setattr(dm, 'leg_sessions', lambda leg: [])
    return dm.build(ledger_rows=decisions)


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
    assert payload['decisions']['ticker'][0] == 'AAA'


def test_the_matrix_points_at_the_cards_rather_than_restating_them(monkeypatch):
    """Two copies of one aggregate are two things that can disagree."""
    payload = _payload(monkeypatch, [_decision('d0', 'AAA', '2026-06-01')], {})
    assert payload['decision_signal_matrix']['source'] == 'info_source_cards[].by_action'
    assert 'rows' not in payload['decision_signal_matrix']


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
    at_level_two['degradation'] = {'level': 'recent_decisions_only', 'cost': '',
                                   'levels': [], 'bytes': 0}
    payload = dm.degrade(built, max_bytes=len(dm.encode(at_level_two).encode())
                         + dm.SIZE_MARGIN + 200)
    assert payload['degradation']['level'] == 'recent_decisions_only'
    assert len(payload['decisions']['decision_id']) == len(decisions)
    assert len(payload['ticker_timelines']['AAA']) == len(decisions)
    kept = sum(1 for row in payload['decision_snapshots'] if row)
    assert 0 < kept <= dm.DRAWER_LIMIT


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


def test_rebuilding_is_deterministic_apart_from_the_timestamp(monkeypatch):
    decisions = [_decision(f'd{index}', 'AAA', f'2026-06-{index + 1:02d}')
                 for index in range(6)]
    snapshots = {'2026-06-03': {'AAA': {'quant.rsi14': 50.0}}}
    first = _payload(monkeypatch, decisions, snapshots)
    second = _payload(monkeypatch, decisions, snapshots)
    first.pop('generated_at'), second.pop('generated_at')
    assert dm.encode(first) == dm.encode(second)
