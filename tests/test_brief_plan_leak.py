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



def test_every_ticker_judgment_field_the_page_prints_is_checked(tmp_path):
    """#2139: the gate is only as wide as the list it reads. Mark each string field of a
    judgment row in turn, render the page and the card, and require the gate to report the
    mark exactly when it was published — a newly printed field fails here."""
    from test_brief_render import CONTEXT, PLAN, _judgment
    from clawock.harness import brief_render
    from clawock.harness.brief_postflight import JUDGMENT_ROW_PROSE

    # The contract's enums, printed as a badge / never printed: not model prose.
    enums = {"ticker", "verdict", "disposition"}
    fields = [key for key, value in _judgment()["ticker_judgments"][0].items()
              if isinstance(value, str) and key not in enums]
    path = tmp_path / "judgment.json"
    printed = set()
    for key in fields:
        judgment = _judgment()
        mark = f"leak_{key}_mark"
        judgment["ticker_judgments"][0][key] = f"说明 {mark}"
        published = (brief_render.render_brief(CONTEXT, judgment, PLAN, date="2026-08-31")
                     + brief_render.render_card(CONTEXT, judgment, PLAN, date="2026-08-31"))
        path.write_text(json.dumps(judgment, ensure_ascii=False))
        reported = "\n".join(_judgment_identifier_issues(path))
        assert (mark in reported) == (mark in published), (key, mark in published)
        if mark in published:
            printed.add(key)
    assert printed, "no judgment field reached the page: the fixture no longer renders rows"
    assert set(JUDGMENT_ROW_PROSE) == printed
