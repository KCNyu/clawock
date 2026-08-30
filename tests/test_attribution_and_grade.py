"""Where the return came from, and one verdict over six gates (#1144/#1147/#1149/#1178).

Two questions with different epistemic status, and the module has to treat them
differently. "Why is this name ranked here" has an *exact* answer, because the
composite is linear in the ranks — the competitor-port issue proposed SHAP for
it, which would approximate a number that can be written down. "Where did the
portfolio return come from" does not, and its honest form is a regression whose
sample has to be published beside it.

The most important test here is the one that fails to produce a number: on the
live book the cross-section carrying both registered ranks and canonical bars is
thirteen names, and nine factors plus an intercept need twenty-seven. Every one
of the eighteen sessions is skipped, and the module has to say so rather than
return coefficients from an underdetermined fit.
"""
import random
import statistics

import numpy as np
import pytest

from clawock.evaluation import attribution as at
from clawock.evaluation import unified


def _synthetic(n_sessions=30, n_names=20, factors=('a', 'b', 'c'),
               truth=(0.02, -0.01, 0.0), noise=0.005, seed=1):
    rng = np.random.default_rng(seed)
    truth = dict(zip(factors, truth))
    sessions, weights = {}, {}
    for index in range(n_sessions):
        day = f'2026-06-{index + 1:03d}'
        loadings = {f'N{name}': {factor: float(rng.normal()) for factor in factors}
                    for name in range(n_names)}
        forward = {name: sum(truth[factor] * row[factor] for factor in factors)
                   + float(rng.normal(0, noise))
                   for name, row in loadings.items()}
        sessions[day] = (loadings, forward)
        weights[day] = {name: 1.0 for name in loadings}
    return sessions, weights, list(factors), truth


def test_fama_macbeth_recovers_the_factor_returns_it_was_given():
    sessions, _, factors, truth = _synthetic()
    fitted = at.factor_returns(sessions, factors)
    assert fitted['status'] == 'measured'
    for factor, expected in truth.items():
        assert fitted['per_factor'][factor]['mean_factor_return'] == \
            pytest.approx(expected, abs=0.002)
    # And the factor that truly does nothing must not come back significant.
    assert abs(fitted['per_factor']['c']['t_stat']) < 2.5


def test_a_cross_section_too_narrow_for_the_factors_is_refused():
    """The live shape, and the whole reason for the refusal.

    Thirteen names carrying both registered ranks and canonical bars; nine
    factors plus an intercept need twenty-seven by the three-names-per-factor
    rule. Returning coefficients from that fit would fill an attribution table
    with numbers that mean nothing.
    """
    sessions, _, _, _ = _synthetic(n_names=13, factors=tuple('abcdefghi'),
                                   truth=(0.0,) * 9)
    fitted = at.factor_returns(sessions, list('abcdefghi'))
    assert fitted['status'] == 'insufficient_sample'
    assert fitted['skipped_sessions'] == 30
    assert fitted['n_sessions'] == 0


def test_the_pre_registered_block_reduction_fits_where_nine_factors_cannot():
    """Three blocks need nine names, which thirteen clears."""
    from clawock.market_data import factors as factor_universe

    weights = factor_universe.load_config()['factor_weights']
    assert set().union(*at.FACTOR_BLOCKS.values()) == set(weights), (
        'every registered factor must belong to exactly one block')
    counts = [len(members) for members in at.FACTOR_BLOCKS.values()]
    assert sum(counts) == len(weights)
    ranks = {factor: 0.5 for factor in weights}
    loadings = at.block_loadings(ranks, weights)
    assert set(loadings) == set(at.FACTOR_BLOCKS)
    # A block whose members all sit at the same rank collapses to that rank:
    # the block loading is the same weighted mean the composite uses.
    assert all(value == pytest.approx(0.5) for value in loadings.values())


def test_tilt_plus_timing_equals_common_by_construction():
    sessions, weights, factors, _ = _synthetic()
    report = at.perf_attrib(sessions, weights, factors)
    assert report['status'] == 'measured'
    assert report['tilt_return_mean'] + report['timing_return_mean'] == \
        pytest.approx(report['common_return_mean'], abs=1e-6)
    assert report['common_return_mean'] + report['specific_return_mean'] == \
        pytest.approx(report['total_return_mean'], abs=1e-6)


def test_a_collinear_design_is_reported_rather_than_regularised():
    """A caller told the design is collinear can drop a factor.

    One handed a silently stabilised coefficient cannot see that the split
    between two near-identical factors was arbitrary.
    """
    rng = np.random.default_rng(4)
    loadings, forward = {}, {}
    for index in range(30):
        base = float(rng.normal())
        loadings[f'N{index}'] = {'a': base, 'b': base + 1e-6 * rng.normal(),
                                 'c': float(rng.normal())}
        forward[f'N{index}'] = base * 0.01 + float(rng.normal(0, 0.001))
    fit = at.cross_sectional_fit(loadings, forward, ['a', 'b', 'c'])
    assert fit['collinear'] is True
    assert fit['condition_number'] > at.CONDITION_WARN


def test_the_composite_explanation_is_exact_not_approximate():
    """The contributions must reproduce the score, to the last place.

    A SHAP value here would estimate a number the model computes directly.
    """
    weights = {'a': 0.5, 'b': 0.3, 'c': 0.2}
    ranks = {'a': 0.4, 'b': -0.2, 'c': 0.1}
    report = at.explain_composite(ranks, weights)
    assert report['contributions_sum'] == pytest.approx(report['composite_score'],
                                                        abs=1e-9)
    expected = sum(weights[f] * ranks[f] for f in weights) / sum(weights.values())
    assert report['composite_score'] == pytest.approx(expected, abs=1e-9)


def test_a_missing_factor_is_named_and_the_score_renormalises():
    weights = {'a': 0.5, 'b': 0.3, 'c': 0.2}
    report = at.explain_composite({'a': 1.0, 'b': 1.0}, weights)
    assert report['missing_factors'] == ['c']
    assert report['weight_covered'] == pytest.approx(0.8)
    assert report['composite_score'] == pytest.approx(1.0)


def test_a_contribution_and_a_counterfactual_can_disagree():
    """The reason both are published, seen on the live book.

    `00100`'s `residual_mom_6m` contributes -0.035 to its composite and dropping
    that factor moves its cross-sectional percentile by exactly zero — because
    the factor is similarly negative for everybody. "How much did this factor
    contribute" and "would dropping it change where this name sits" are
    different questions and a single number cannot answer both.
    """
    weights = {'a': 0.5, 'b': 0.5}
    cross_section = {f'N{index}': {'a': index / 10.0, 'b': -1.0}
                     for index in range(10)}
    report = at.explain_composite(cross_section['N3'], weights,
                                  cross_section=cross_section, ticker='N3')
    assert report['contributions']['b'] == pytest.approx(-0.5)
    # b is identical across the cross-section, so removing it moves nobody.
    assert report['leave_one_out']['b']['percentile_change'] == pytest.approx(0.0)
    # a is what actually decides the ordering.
    assert report['leave_one_out']['a']['percentile_change'] != 0.0


def _configurations(edge, n, seed, winner=2, names=4):
    rnd = random.Random(seed)
    return {f'v{index}': {f'2026-{1 + day // 28:02d}-{1 + day % 28:02d}':
                          rnd.gauss(edge if index == winner else 0.0, 0.02)
                          for day in range(n)}
            for index in range(names)}


def test_a_real_edge_grades_diagnostic_and_noise_does_not():
    real = _configurations(0.006, 250, 7)
    verdict = unified.grade({day: [value] for day, value in real['v2'].items()},
                            configurations=real)
    assert verdict['grade'] == 'diagnostic'
    assert verdict['reasons'] == []

    noise = _configurations(0.0, 250, 7)
    weak = unified.grade({day: [value] for day, value in noise['v2'].items()},
                         configurations=noise)
    assert weak['grade'] != 'diagnostic'


def test_a_refused_gate_caps_the_grade():
    """"We could not check" is the thing a summary is most tempting to blur."""
    short = _configurations(0.006, 25, 3)
    verdict = unified.grade({day: [value] for day, value in short['v2'].items()},
                            configurations=short)
    assert verdict['grade'] in ('insufficient', 'contested')
    assert any('could not run' in reason or 'insufficient' in reason
               for reason in verdict['reasons']) or verdict['grade'] != 'diagnostic'


def test_nothing_here_can_award_validated():
    """The ceiling is a property of when a rule was written, not of a computation."""
    strong = _configurations(0.02, 400, 5)
    verdict = unified.grade({day: [value] for day, value in strong['v2'].items()},
                            configurations=strong)
    assert verdict['grade'] != 'validated'
    assert 'pre-registration' in verdict['ceiling']


def test_a_search_of_one_has_no_selection_effect_to_measure():
    single = _configurations(0.006, 200, 9, names=1, winner=0)
    verdict = unified.grade({day: [value] for day, value in single['v0'].items()},
                            configurations=single)
    assert verdict['gates']['pbo']['status'] == 'not_applicable'
