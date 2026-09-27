"""Model-authored plan prose must surface internal identifiers to the gate."""
from clawock.harness.brief_postflight import _plan_self_reference_issues


def test_rationale_identifier_is_reported_without_blocking_the_daily_brief():
    plan = {"decisions": [{"rationale": "结算仍在进行（session_not_final），复挂风险单", 
                           "condition": {"description": "transaction_group_id=swap"}}]}
    issues = _plan_self_reference_issues(plan)
    assert len(issues) == 1
    assert "session_not_final" in issues[0]
    assert "transaction_group_id" in issues[0]
    assert issues[0].endswith("(advisory)")
