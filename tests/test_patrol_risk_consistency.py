"""Shared concentration judgments and windowed audit disclosure."""
from datetime import timedelta

import pytest

from clawock.decision import ledger, settlement
from clawock.portfolio.guardrail import compute_concentration, hhi_verdict
from clawock.publish import dashboard
from clawock.sessions import hkt_today


@pytest.mark.parametrize('values', [[52, 34, 7, 7], [40, 35, 25], [25, 25, 25, 25], [10] * 10,
                                  [39.999, 35, 25.001]])
def test_brief_and_dashboard_share_unrounded_concentration_judgment(values):
    held = [{'ticker': str(i), 'name': str(i), 'shares': 1, 'cost_basis': v,
             'current_value': v, 'is_active': True} for i, v in enumerate(values)]
    brief = compute_concentration(held)
    board = dashboard.compute_hhi(held)
    assert dashboard.hhi_verdict is hhi_verdict
    assert brief['verdict'].endswith(board['verdict']['label'])
    if values == [52, 34, 7, 7]:
        assert board['verdict']['level'] == 'danger'


def test_audit_coverage_uses_headline_window_and_pending_reasons(monkeypatch, capsys):
    today = hkt_today()
    rows = []
    for key, days, benefit in [('old', 50, 1), ('new', 1, 2), ('pending', 1, None)]:
        evaluation = ({'status': 'settled', 'triggered': True, 'outcome': 'win', 'benefit_t1_pct': benefit}
                      if benefit is not None else {'status': 'pending', 'pending_reason': 'session_not_final'})
        rows.append({'decision_id': key, 'episode_id': key, 'action': 'cut', 'ticker': 'TEST',
                     'plan_date': (today - timedelta(days=days)).isoformat(), 'evaluation': evaluation})
    monkeypatch.setattr(ledger, 'load_decisions', lambda: rows)
    monkeypatch.setattr(ledger, 'settle_decisions', lambda rows: 0)
    assert settlement.main([]) == 0
    output = capsys.readouterr().out
    coverage = output.split('--- active episode coverage, last 30d')[1]
    assert 'fully graded               1' in coverage
    assert 'fully unresolved           1' in coverage
    assert 'total active episodes      2' in coverage
    assert 'graded coverage         50.0%' in coverage
    assert 'pending:session_not_final' in coverage
    assert 'n=1' in output


def test_audit_coverage_rows_add_up_to_the_total(monkeypatch, capsys):
    """#3160: the never-triggered bucket (#3151) is printed, so the rows sum to the total."""
    today = hkt_today().isoformat()
    rows = [
        {'decision_id': 'won', 'episode_id': 'won', 'action': 'cut', 'ticker': 'TEST', 'plan_date': today,
         'evaluation': {'status': 'settled', 'triggered': True, 'outcome': 'win', 'benefit_t1_pct': 1}},
        {'decision_id': 'idle', 'episode_id': 'idle', 'action': 'cut', 'ticker': 'TEST', 'plan_date': today,
         'evaluation': {'status': 'not_triggered'}},
        {'decision_id': 'shut', 'episode_id': 'shut', 'action': 'cut', 'ticker': 'TEST', 'plan_date': today,
         'evaluation': {'status': 'not_evaluable', 'not_evaluable_reason': 'market_closed'}},
    ]
    monkeypatch.setattr(ledger, 'load_decisions', lambda: rows)
    monkeypatch.setattr(ledger, 'settle_decisions', lambda rows: 0)
    assert settlement.main([]) == 0
    coverage = capsys.readouterr().out.split('--- active episode coverage, last 30d')[1].split('---')[0]
    counts = {}
    for line in coverage.splitlines():
        label, _, rest = line.strip().partition('  ')
        if rest.split() and rest.split()[0].isdigit():
            counts[label] = int(rest.split()[0])
    total = counts.pop('total active episodes')
    assert counts == {'fully graded': 1, 'partially graded': 0, 'fully unresolved': 1, 'never triggered': 1}
    assert sum(counts.values()) == total == 3
    assert 'reasons (overlapping)' in coverage
