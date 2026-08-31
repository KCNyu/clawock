"""How far, not just which way (#1159).

The ledger has graded direction since it existed and has never carried a
magnitude. These pin the two properties that make adding one safe: the field is
optional, so a plan without it is still a valid plan and the 08:00 brief still
goes out; and an absent forecast is never silently turned into a forecast of
zero, which is a real and scorable claim.
"""
from __future__ import annotations

from clawock.decision import ledger
from clawock.publish import dashboard


def _decision(expected=None, realized=None, status='settled'):
    return {
        'expected_move_pct': expected,
        'evaluation': {'underlying_return_t1_pct': realized, 'status': status},
    }


def test_absent_and_zero_are_different_forecasts():
    assert ledger.normalize_expected_move(None) is None
    assert ledger.normalize_expected_move(0) == 0.0, (
        '"I expect this to go nowhere" is a forecast, and a scorable one'
    )
    assert ledger.normalize_expected_move('-8.25') == -8.25


def test_a_typo_is_discarded_rather_than_scored():
    """-800 for -8 would otherwise dominate every average it entered."""
    assert ledger.normalize_expected_move(-800) is None
    assert ledger.normalize_expected_move(float('inf')) is None
    assert ledger.normalize_expected_move('not a number') is None
    assert ledger.normalize_expected_move(True) is None, (
        'bool is an int in Python, and `True` is not a 1% forecast'
    )


def test_a_plan_without_the_field_is_still_a_valid_plan():
    """The whole reason it is optional: a failing plan means no brief at all."""
    decision = ledger.legacy_action_to_decision(
        {'ticker': 'AAA', 'action': 'cut', 'confidence': 0.8}, '2026-08-31')

    assert decision['expected_move_pct'] is None
    plan = {'schema_version': ledger.SCHEMA_VERSION, 'date': '2026-08-31',
            'plan_date': '2026-08-31',
            'decisions': ledger.assign_episode_ids([decision])}

    assert ledger.validate_plan(plan) == [], (
        'an optional field that can fail validation is a required field with '
        'extra steps, and a failing plan publishes no brief at all'
    )


def test_the_field_survives_normalization_when_the_plan_states_it():
    decision = ledger.legacy_action_to_decision(
        {'ticker': 'AAA', 'action': 'cut', 'expected_move_pct': -6.5}, '2026-08-31')

    assert decision['expected_move_pct'] == -6.5


def test_the_metric_is_a_coverage_series_before_it_is_a_calibration():
    """Today's answer is 0/749, and that is the point — the same place #1117's
    debate coverage started the day before it was 8/8."""
    rows = [_decision(), _decision(), _decision(-8.0, -2.0)]

    metrics = dashboard.compute_magnitude_metrics(rows)

    assert metrics['decisions'] == 3
    assert metrics['with_expected_move'] == 1
    assert metrics['scored_t1'] == 1
    assert metrics['mean_abs_error_pct'] == 6.0
    assert metrics['mean_error_pct'] == -6.0, (
        'signed: a book that is systematically too dramatic about size shows up '
        'here and in no other number on the dashboard'
    )
    assert metrics['direction_agreement'] == 1.0


def test_an_unsettled_or_unmeasured_decision_is_not_scored():
    rows = [_decision(-8.0, None), _decision(-8.0, -2.0, status='pending'),
            _decision(None, -2.0)]

    metrics = dashboard.compute_magnitude_metrics(rows)

    assert metrics['with_expected_move'] == 2
    assert metrics['scored_t1'] == 0
    assert metrics['mean_abs_error_pct'] is None, (
        'a forecast whose outcome is not in yet is not a forecast that was wrong'
    )
