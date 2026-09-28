"""Model-authored plan prose must surface internal identifiers to the gate."""
import json

from clawock.harness.brief_postflight import (
    _judgment_identifier_issues, _plan_self_reference_issues,
)


def test_rationale_identifier_is_reported_without_blocking_the_daily_brief():
    plan = {"decisions": [{"rationale": "结算仍在进行（session_not_final），复挂风险单", 
                           "condition": {"description": "transaction_group_id=swap"}}]}
    issues = _plan_self_reference_issues(plan)
    assert len(issues) == 1
    assert "session_not_final" in issues[0]
    assert "transaction_group_id" in issues[0]
    assert issues[0].endswith("(advisory)")


def test_published_judgment_prose_reports_identifiers_as_advisory(tmp_path):
    path = tmp_path / 'judgment.json'
    path.write_text(json.dumps({
        'portfolio_assessment': '其他仓位 may_stand=true，维持 hold_and_watch',
        'portfolio_counterargument': '反方担心 regime_delever',
        'narrative': {'bull': '继续持有', 'next_session': ['下次看 allowed_actions'],
                      'risk_voice_first': 'conservative'},
    }))
    issues = _judgment_identifier_issues(path)
    assert len(issues) == 1
    assert all(name in issues[0] for name in
               ('may_stand', 'hold_and_watch', 'regime_delever', 'allowed_actions'))
    assert issues[0].endswith('(advisory)')

    path.write_text(json.dumps({
        'portfolio_assessment': '其他仓位可继续持有',
        'portfolio_counterargument': '反方担心趋势转弱',
        'narrative': {'bull': '继续观察', 'risk_voice_first': 'conservative'},
    }))
    assert _judgment_identifier_issues(path) == []
