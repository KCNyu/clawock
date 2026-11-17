import json

from clawock.decision.plan_prose import judgment_plan_share_conflicts


def _plan():
    return {'decisions': [{'ticker': 'SPCH', 'action': 'hold_and_watch',
                           'rationale': '升级线出现就减到 282 股。'}]}


def test_targets_are_compared_with_the_plan_not_sold_shares():
    assert judgment_plan_share_conflicts(_plan(), {'ticker_judgments': [
        {'ticker': 'SPCH', 'falsifier': '立刻减到 279 股。'}]})
    assert not judgment_plan_share_conflicts(_plan(), {'ticker_judgments': [
        {'ticker': 'SPCH', 'falsifier': '立刻减到 282 股。卖出 38 股。'}]})
    assert not judgment_plan_share_conflicts(_plan(), {'ticker_judgments': [
        {'ticker': 'OTHER', 'falsifier': '减到 279 股。'}]})
    assert not judgment_plan_share_conflicts(_plan(), {'portfolio_assessment':
                                                       'SPCH 不是减到 279 股。'})


def test_cross_ticker_and_portfolio_prose_is_checked():
    for overlay in ({'portfolio_counterargument': 'SPCH 砍到 279 股。'},
                    {'ticker_judgments': [{'ticker': 'OTHER',
                                           'assessment': 'SPCH 减到 279 股。'}]}):
        assert judgment_plan_share_conflicts(_plan(), overlay)


def test_postflight_conflict_is_critical_and_renderer_does_not_overwrite(tmp_path):
    from clawock.harness import brief_postflight, brief_render
    day = '2026-11-17'
    paths = brief_render.artifact_paths(tmp_path, day)
    overlay = {'ticker_judgments': [{'ticker': 'SPCH', 'falsifier': '减到 279 股。'}]}
    for key, value in (('judgment', overlay), ('context', {}), ('plan', _plan())):
        paths[key].parent.mkdir(parents=True, exist_ok=True)
        paths[key].write_text(json.dumps(value))
    issues = brief_postflight._brief_numeric_issues(paths['judgment'], _plan(), {})
    assert brief_postflight.categorize(issues) == 'fail'
    paths['brief'].write_text('existing')
    issues, body = brief_render.render_from_workspace(tmp_path, day)
    assert issues and body is None
    assert paths['brief'].read_text() == 'existing'


def test_projection_marks_conflicting_overlay_invalid(tmp_path):
    from clawock.decision import packet
    overlay = {'schema_version': 1, 'context_generation_id': 'generation',
               'ticker_judgments': [{'ticker': 'SPCH', 'falsifier': '减到 279 股。'}]}
    source = {'_meta': {'generation_id': 'generation'}, 'tickers': {'SPCH': {}}}
    path = tmp_path / 'overlay.json'
    path.write_text(json.dumps(overlay))
    projection, issues = packet.write_pages_projection(source, path, tmp_path / 'out.json', plan=_plan())
    assert any('判断与计划股数冲突' in i for i in issues)
    assert projection['judgment_status'] == 'invalid'


def test_another_named_ticker_does_not_inherit_the_row_target():
    plan = _plan()
    plan['decisions'].append({'ticker': 'OTHER', 'rationale': '继续持有。'})
    assert not judgment_plan_share_conflicts(plan, {'ticker_judgments': [
        {'ticker': 'SPCH', 'assessment': 'OTHER 减到 279 股。'}]})
