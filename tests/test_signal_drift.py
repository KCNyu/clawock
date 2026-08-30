"""A distribution can move while every observation stays believable (#1169/#1174).

`market_data/integrity.py` decides whether one bar is possible. It cannot see
the failure that matters for the research layer: a signal whose individual
values are all fine and whose *distribution* has shifted, silently changing what
every pre-registered threshold on it means.

The tests below are mostly about the mistake this module exists not to make. All
three drift statistics assume independent observations, and the panel has about
twenty-one names per session that move together. A textbook KS p-value on pooled
rows reports `p < 1e-9` for an ordinary directional week, and an alert that fires
every week is not an alert.
"""
import random
import statistics

import pytest

from clawock.evaluation import drift


def _rows(per_session):
    return [{'as_of': session, 'ticker': f'T{index}', 'signal': 'x', 'value': value}
            for session, values in per_session.items()
            for index, value in enumerate(values)]


def _panel(n_sessions, mean, sigma, *, names=20, seed=1, start=1):
    rnd = random.Random(seed)
    return {f'2026-06-{index:03d}': [rnd.gauss(mean, sigma) for _ in range(names)]
            for index in range(start, start + n_sessions)}


def test_the_three_statistics_disagree_on_purpose():
    """Which one fires says what kind of move it was.

    KS is sensitive to a shift in the middle and largely blind to a change in
    spread; Wasserstein answers "by how much" in the signal's own units. A
    single verdict would throw that away.
    """
    rnd = random.Random(2)
    reference = [rnd.gauss(0, 1) for _ in range(4000)]
    shifted = [rnd.gauss(0.6, 1) for _ in range(1000)]     # the middle moved
    widened = [rnd.gauss(0.0, 2) for _ in range(1000)]     # the tails moved

    # They rank the two moves in opposite orders, which is the point: KS sees
    # the shifted middle as the bigger event, Wasserstein sees the travelled
    # tails as the bigger one. A single verdict would have to pick one and would
    # then be silently blind to the other kind of drift.
    assert drift.ks_statistic(reference, shifted) > drift.ks_statistic(reference, widened)
    assert drift.wasserstein_distance(reference, widened) > \
        drift.wasserstein_distance(reference, shifted)
    # And Wasserstein recovers the size of the mean shift in the signal's units.
    assert drift.wasserstein_distance(reference, shifted) == pytest.approx(0.6, abs=0.1)


def test_psi_lands_in_its_conventional_band():
    rnd = random.Random(5)
    reference = [rnd.gauss(0, 1) for _ in range(3000)]
    stable = [rnd.gauss(0, 1) for _ in range(600)]
    moved = [rnd.gauss(1.0, 1) for _ in range(600)]
    assert drift.population_stability_index(reference, stable) < 0.10
    assert drift.population_stability_index(reference, moved) > 0.25


def test_the_session_permutation_does_not_cry_wolf_on_a_correlated_market():
    """The whole reason the textbook p-value is not used.

    Twenty names a session, all sharing one common factor, and no drift at all.
    Pooled rows look like four hundred independent observations to a textbook
    test; they are closer to twenty. The session-permutation null has to return
    an unremarkable p-value here.
    """
    rnd = random.Random(9)
    per_session = {}
    for index in range(1, 31):
        common = rnd.gauss(0, 1.0)
        per_session[f'2026-06-{index:03d}'] = [
            common + rnd.gauss(0, 0.3) for _ in range(20)]
    days = sorted(per_session)
    reference = {day: per_session[day] for day in days[:20]}
    current = {day: per_session[day] for day in days[20:]}
    p_value = drift.session_permutation_p(
        reference, current, drift.ks_statistic, permutations=400)
    assert p_value > 0.05, p_value


def test_the_session_permutation_still_finds_a_real_shift():
    """And it must not be blind — a genuine move has to come back significant."""
    per_session = {**_panel(20, 0.0, 1.0, seed=3, start=1),
                   **_panel(10, 2.5, 1.0, seed=4, start=100)}
    days = sorted(per_session)
    p_value = drift.session_permutation_p(
        {day: per_session[day] for day in days[:20]},
        {day: per_session[day] for day in days[20:]},
        drift.ks_statistic, permutations=400)
    assert p_value <= 0.01, p_value


def test_a_tie_heavy_signal_can_still_be_flagged():
    """The defect this rule was written wrong the first time.

    The sector-neutral ranks take about seven distinct values, so equal-mass PSI
    bins collide and PSI is refused. Requiring a PSI band made every rank signal
    unflaggable no matter how far it moved — quiet in the wrong direction.
    """
    rnd = random.Random(6)
    levels = [-0.5, -0.25, 0.0, 0.25, 0.5]
    per_session = {}
    for index in range(1, 21):
        per_session[f'2026-06-{index:03d}'] = [rnd.choice(levels) for _ in range(20)]
    for index in range(21, 31):
        per_session[f'2026-06-{index:03d}'] = [rnd.choice(levels[-2:]) for _ in range(20)]
    report = drift.panel_drift(_rows(per_session), recent_sessions=10, permutations=300)
    assert report['signals']['x']['psi'] is None
    assert report['n_psi_unavailable'] == 1
    assert 'x' in report['flagged']


def test_a_stable_signal_is_not_flagged():
    per_session = {**_panel(20, 0.0, 1.0, seed=11, start=1),
                   **_panel(10, 0.0, 1.0, seed=12, start=100)}
    report = drift.panel_drift(_rows(per_session), recent_sessions=10, permutations=300)
    assert report['flagged'] == []
    assert report['discriminating'] is True


def test_flagging_almost_everything_is_reported_as_not_discriminating():
    """The number that says whether the table is an alert or a description.

    On the live panel this came back 0.78 — twenty-five of thirty-two — against
    a reference window holding one regime change. That is not a threshold to
    tune down; a detector that fires on nearly everything cannot discriminate,
    and the payload has to say so rather than let a reader treat the list as a
    shortlist.
    """
    per_session = {}
    for signal in range(6):
        for index in range(1, 21):
            per_session.setdefault(f'2026-06-{index:03d}', {})[signal] = 0.0
    rows = []
    rnd = random.Random(7)
    for signal in range(6):
        for index in range(1, 21):
            for name in range(20):
                rows.append({'as_of': f'2026-06-{index:03d}', 'ticker': f'T{name}',
                             'signal': f's{signal}', 'value': rnd.gauss(0, 1)})
        for index in range(21, 31):
            for name in range(20):
                rows.append({'as_of': f'2026-06-{index:03d}', 'ticker': f'T{name}',
                             'signal': f's{signal}', 'value': rnd.gauss(4.0, 1)})
    report = drift.panel_drift(rows, recent_sessions=10, permutations=300)
    assert report['flagged_share'] > 0.9
    assert report['discriminating'] is False
    assert 'does not span enough regimes' in report['reading']


def test_a_short_history_is_refused_rather_than_scored():
    per_session = _panel(9, 0.0, 1.0, seed=13)
    report = drift.panel_drift(_rows(per_session), recent_sessions=10)
    assert report['signals']['x']['status'] == 'insufficient_sample'
    assert report['n_measured'] == 0


def test_a_constant_signal_reports_no_movement_rather_than_breaking():
    per_session = {f'2026-06-{index:03d}': [0.0] * 20 for index in range(1, 31)}
    report = drift.panel_drift(_rows(per_session), recent_sessions=10, permutations=100)
    row = report['signals']['x']
    assert row['ks'] == 0.0
    assert row['wasserstein'] == 0.0
    assert 'x' not in report['flagged']
