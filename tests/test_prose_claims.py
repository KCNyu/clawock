import json

from clawock import prose_claims
from clawock.decision import brief_prose
from clawock.harness import brief_versions
from clawock.harness._watchdog_common import telegram_with_receipt
from clawock.harness.report import categorize, prepare_report


def test_exact_paths_keep_subject_measure_and_capture_time_together():
    ctx = {
        'holdings': {'00100': {'ticker': '00100', 'shares': 10},
                     '00700': {'ticker': '00700', 'shares': 30}},
        'live_information': {'items': [{'title': '公告', 'source': 'HKEXnews',
                                        'capturedAt': '2026-11-27T10:32:00+08:00'}]},
        'session_review': {'status': 'partial'},
    }
    renderer = prose_claims.ClaimRenderer(ctx)
    body = renderer.render(
        '[[/ctx/holdings/00100/ticker]]现持[[/ctx/holdings/00100/shares]]。'
        '[[/ctx/live_information/items/0|cite]]。'
        '本档资讯[[/ctx/session_review/status|status]]，'
        '共[[/ctx/live_information/items|count]]条。', '报告')
    assert body == '00100现持10 股。《公告》（HKEXnews，2026-11-27T10:32:00+08:00）。本档资讯部分可用，共1条。'
    assert not renderer.issues
    renderer.render('现持30股，较另一期多十股。', '报告')
    renderer.render('现持[[/ctx/holdings/00100/size]]。', '报告')
    assert len(renderer.issues) == 2
    assert '手写数值' in renderer.issues[0] and '本代没有' in renderer.issues[1]


def test_structured_trigger_holds_exact_owner_and_only_current_may_anchor_forecast():
    ctx = {'trigger_prices': {'00100': [{'price': '10.20', 'current': True}],
                              '00700': [{'price': '300.00', 'source': 'watch_levels'}]}}
    renderer = prose_claims.ClaimRenderer(ctx)
    prefix = '下一触发：'
    assert renderer.triggers(
        prefix + '[[/ctx/trigger_prices/00100/0|above=10.71]]；[[/ctx/trigger_prices/00700/0|below]]',
        prefix) == prefix + '00100 站上10.71；00700 跌破300.00'
    assert renderer.triggers(
        prefix + '[[/ctx/trigger_prices/00100/0|above=10.72]]；[[/ctx/trigger_prices/00700/0|below=299]]',
        prefix) == ''
    assert '±5%' in renderer.issues[0] and '同标的现价' in renderer.issues[1]


def test_new_report_uses_reference_gate_while_historical_report_can_still_be_read(tmp_path):
    ctx = {'raw_wechat_block': 'data', 'holdings': {'00700': {'shares': 30}}}
    draft = '▎情绪面\n等待方向。\n▎技术面\n等收线。\n▎操作建议\n腾讯继续持有。'
    scoped = {**ctx, prose_claims.FIELD: prose_claims.VERSION}
    good, findings = prepare_report(scoped, draft + '持有[[/ctx/holdings/00700/shares]]。', tmp_path)
    assert '持有30 股' in good and categorize(findings) == 'pass'
    _, findings = prepare_report(scoped, draft + '持有30股。', tmp_path)
    assert categorize(findings) == 'fail'
    _, findings = prepare_report(ctx, draft + '持有30股。', tmp_path)
    assert categorize(findings) == 'pass'


def test_decision_sizing_is_local_to_each_plan_row_and_pinned_for_dsh():
    ctx = {'risk_guardrail': {'concentration_reviews': [{
        'ticker': 'RKLX', 'leg': 'US', 'currency': 'USD',
        'trim_inputs': {'shares': 100, 'value': 500, 'total': 1000,
                        'price': 5, 'lot_size': 1, 'target_pct': 35},
    }]}}
    plan = {'decisions': [
        {'ticker': 'RKLX', 'action': 'trim', 'size': {'shares': shares},
         'condition': {'type': 'price_above', 'price': 10},
         'rationale': '卖[[/decision/size/shares]]后占[[/decision/trim_at_trigger/post_trim_weight_pct]]'}
        for shares in (20, 60)
    ]}
    renderer = prose_claims.ClaimRenderer(ctx)
    resolved = brief_prose.render_plan(plan, renderer)
    assert not renderer.issues
    first, second = resolved['decisions']
    assert first['rationale'] == '卖20 股后占61.54%'
    assert second['rationale'] == '卖60 股后占44.44%'
    assert first['prose_claims']['trim'] == {'/decision/trim_at_trigger/post_trim_weight_pct': 61.54}


def test_delivery_proof_is_shared_and_artifact_proof_detects_rewrite(tmp_path):
    receipt = tmp_path / 'telegram.json'
    calls = []

    def send():
        calls.append('send')
        return True, ''

    assert telegram_with_receipt(receipt, send, sender='watchdog')[0]
    assert telegram_with_receipt(receipt, send, sender='postflight')[0]
    assert calls == ['send']
    assert json.loads(receipt.read_text())['sender'] == 'watchdog'
    day = '2026-11-27'
    memory = tmp_path / 'memory'
    (memory / '.tmp').mkdir(parents=True)
    for name in (f'{day}-pre-open.md', f'{day}-plan.json', f'.tmp/brief-card-{day}.txt'):
        (memory / name).write_text('approved')
    brief_versions.record_artifacts(tmp_path, day, 'generation-id')
    assert brief_versions.artifacts_verified(tmp_path, day)
    (memory / f'{day}-plan.json').write_text('another plan')
    assert not brief_versions.artifacts_verified(tmp_path, day)
