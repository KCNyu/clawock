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


def test_brief_numeric_gate_reads_judgment_and_plan_with_their_own_ticker(tmp_path):
    from clawock.harness.brief_postflight import _brief_numeric_issues
    ctx = {'reflections': {'RKLX': {'n': 11, 'win_rate': .45},
                          'SPCH': {'n': 7, 'win_rate': .43},
                          '07226': {'n': 13, 'win_rate': .62}}}
    prose = '真正要处理的是 SPCH。13 个 episode 胜率 62%'
    path = tmp_path / 'judgment.json'
    path.write_text(json.dumps({'ticker_judgments': [{'ticker': 'RKLX', 'rationale': prose}]}))
    assert 'RKLX 自己是 11 个 / 45%' in _brief_numeric_issues(path, {}, ctx)[0]
    path.write_text('{}')
    plan = {'decisions': [{'ticker': 'RKLX', 'rationale': prose}]}
    assert 'RKLX 自己是 11 个 / 45%' in _brief_numeric_issues(path, plan, ctx)[0]


def test_packet_rejects_wrong_episode_pair_in_public_projection():
    from clawock.decision.packet import validate_judgment_overlay, compile_pages_projection
    packet = {'tickers': {'RKLX': {'history': {'settled_episodes': 11, 'win_rate': .45}},
                          'SPCH': {'history': {'settled_episodes': 7, 'win_rate': .43}}}}
    overlay = {'ticker_judgments': [{'ticker': 'RKLX',
        'rationale': '真正要处理的是 SPCH。13 个 episode 胜率 62%'}]}
    issues = validate_judgment_overlay(packet, overlay)
    assert any('RKLX 自己是 11 个 / 45%' in issue for issue in issues)
    projection = compile_pages_projection(packet, overlay, overlay_issues=issues)
    assert projection['judgment_status'] == 'invalid'
    assert any('RKLX 自己是 11 个 / 45%' in issue for issue in projection['judgment_issues'])


def test_a_rationale_restating_its_own_size_is_not_an_unsourced_number(tmp_path):
    # #2636: the three active calls of 2026-10-05 were each flagged for the
    # share count their own `size.shares` carried.
    from clawock.harness.brief_postflight import _brief_numeric_issues

    path = tmp_path / 'j.json'
    path.write_text('{}')
    plan = {'decisions': [{'ticker': '07226', 'rationale': '减 1500 股后杠杆下降',
                           'size': {'shares': 1500, 'pct': 20.83, 'note': '约 9999 股'}}]}
    assert _brief_numeric_issues(path, plan, {}) == []
    plan['decisions'][0]['rationale'] = '减 1700 股后杠杆下降'
    assert '1700股' in _brief_numeric_issues(path, plan, {})[0]
    # `size.note` is prose, not a source for other prose.
    plan['decisions'][0]['rationale'] = '减 9999 股后杠杆下降'
    assert '9999股' in _brief_numeric_issues(path, plan, {})[0]
