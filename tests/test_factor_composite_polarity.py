"""A composite that ranks backwards has to say which of two things it is (#1133).

`clawock signal-panel` scored `factor.composite_score` at -0.20 [-0.290, -0.095]
over eighteen sessions — an interval clearing zero, on the same panel where
`news.signed_score` is +0.19. Two explanations produce exactly that number and
demand opposite responses: a constituent entering with a reversed polarity is a
defect to fix, and a month where quality and momentum ranked inversely is
evidence to re-check later. Inverting a composite because it measured negative
on eighteen sessions is the search this repository refuses everywhere else.

The discriminator is structural rather than statistical: a polarity error lives
in **one** factor. These tests hold `composite_polarity` to that — it must call a
concentrated negative IC a polarity suspicion, a broad one a regime, and it must
never change a sign.
"""
import json

from clawock.evaluation import signal_panel
from clawock.market_data import factors


def _signals(per_factor, composite=-0.2, horizon='t5'):
    signals = {
        'factor.composite_score': {horizon: {
            'mean_ic': composite, 'n_sessions': 18, 'n_observations': 238,
            'ic_clears_zero': True}},
    }
    for name, (ic, clears) in per_factor.items():
        signals[f'factor.rank.{name}'] = {horizon: {
            'mean_ic': ic, 'n_sessions': 18, 'n_observations': 238,
            'ic_clears_zero': clears}}
    return signals


def test_one_factor_carrying_the_whole_negative_ic_is_a_polarity_suspicion():
    """The defect shape: eight factors near zero and one deeply negative."""
    per_factor = {f'f{index}': (0.005 * (index % 3 - 1), False) for index in range(8)}
    per_factor['broken'] = (-0.42, True)
    result = signal_panel.composite_polarity(_signals(per_factor), 't5')
    assert result['verdict'] == 'polarity_suspect'
    assert result['worst_factor'] == 'broken'
    assert result['worst_factor_share_of_negative_ic'] > 0.6


def test_several_factors_negative_together_is_a_regime():
    """The live shape as of 2026-08-30, and the reason the composite is left alone."""
    result = signal_panel.composite_polarity(_signals({
        'drawdown_resilience': (-0.1467, True),
        'residual_mom_6m': (-0.1267, True),
        'relative_strength': (-0.1025, True),
        'low_volatility': (-0.0852, True),
        'residual_mom_3m': (-0.0573, False),
        'residual_mom_1m': (-0.0027, False),
        'liquidity': (0.0064, False),
    }), 't5')
    assert result['verdict'] == 'regime'
    assert result['n_negative_clearing_zero'] == 4
    assert 'month, not a defect' in result['reading']


def test_the_declared_direction_is_read_from_the_composite_weights():
    """Not restated. A second copy of the weights would drift out of agreement
    with the composite whose declaration this table claims to be checking."""
    weights = factors.load_config()['factor_weights']
    result = signal_panel.composite_polarity(
        _signals({name: (-0.1, True) for name in weights}), 't5', weights=weights)
    assert {row['factor'] for row in result['constituents']} == set(weights)
    for row in result['constituents']:
        assert row['weight'] == weights[row['factor']]
        # Every constituent enters the composite with a positive weight over a
        # centered rank, so every declaration is "higher is better".
        assert row['declared_direction'] == 'higher_is_better'


def test_a_positive_composite_has_nothing_to_discriminate():
    result = signal_panel.composite_polarity(
        _signals({'a': (0.1, True), 'b': (0.2, True)}, composite=0.15), 't5')
    assert result['verdict'] == 'composite_is_not_negative_at_this_horizon'


def test_missing_constituents_name_the_command_that_produces_them():
    """The failure this whole change exists to remove.

    Before the fix the registered history carried only the composite, so the
    question could not be answered from the record at all. If that state comes
    back, the panel must say what to run rather than printing an empty table.
    """
    result = signal_panel.composite_polarity(
        {'factor.composite_score': {'t5': {'mean_ic': -0.2, 'n_sessions': 18,
                                           'n_observations': 238,
                                           'ic_clears_zero': True}}}, 't5')
    assert result['status'] == 'no_constituents'
    assert 'backfill-history-ranks' in result['reason']


def test_the_registered_history_actually_carries_the_constituents_now():
    """The persistence half, checked against the real file.

    `rank_snapshot` always computed `sector_neutral_ranks`; `_history_snapshot`
    dropped them. Every registered snapshot must now carry them, or the
    discriminator above has nothing to read.
    """
    from clawock import history_store
    rows = history_store.load_series(factors.HISTORY)
    assert rows, 'registered factor history is empty'
    for snapshot in rows:
        for ticker, row in (snapshot.get('rows') or {}).items():
            ranks = row.get('sector_neutral_ranks')
            assert isinstance(ranks, dict) and ranks, (snapshot.get('as_of'), ticker)
            assert row.get('ranks_provenance') in (
                'recorded_at_snapshot', 'reconstructed_point_in_time_from_bars')


def test_a_reconstruction_that_does_not_reproduce_the_composite_is_not_the_same_data():
    """The check that makes the backfill usable as evidence.

    The reconstructed ranks are re-weighted and compared against the composite
    that was actually registered. Anything but a near-perfect rank correlation
    means the reconstruction is a second dataset wearing the first one's name,
    and every constituent IC computed from it would be meaningless.
    """
    from clawock import history_store
    config = factors.load_config()
    fidelity = factors.reconstruction_fidelity(
        history_store.load_series(factors.HISTORY), config)
    assert fidelity, 'no snapshot had enough rows to check'
    worst = min(row['spearman'] for row in fidelity if row['spearman'] is not None)
    # The gap from 1.0 is `quality_profitability`, which is deliberately not
    # reconstructed: the fundamentals cache holds today's filings, not the ones
    # that had been filed on a Friday in July, and using them would be a
    # look-ahead in the one factor whose whole point is that it moves slowly.
    assert worst > 0.95, worst


def test_the_panel_scores_each_constituent_separately():
    payload = {'rows': {'AAA': {
        'composite_score': -0.1, 'market_percentile': 0.4,
        'sector_neutral_ranks': {'liquidity': 0.5, 'breadth': -0.25}}}}
    signals = dict((signal, value) for _, signal, value in
                   signal_panel.factor_signals(payload))
    assert signals == {'factor.composite_score': -0.1,
                       'factor.market_percentile': 0.4,
                       'factor.rank.liquidity': 0.5,
                       'factor.rank.breadth': -0.25}


def test_the_discriminator_never_returns_an_inverted_sign():
    """It reports; it does not act. The issue said so in as many words."""
    result = signal_panel.composite_polarity(
        _signals({'broken': (-0.42, True), 'other': (0.01, False)}), 't5')
    assert json.dumps(result).count('invert') <= 1  # only the discipline note
    assert 'never inverts a sign' in result['discipline']
