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
    assert body == '00100现持10 股。《公告》（HKEXnews，采集 2026-11-27T10:32:00+08:00）。本档资讯部分可用，共1条。'
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


def test_structured_sector_scan_keeps_grouped_context_and_audited_commentary(tmp_path):
    from clawock.harness.brief_sidecars import sector_scan

    peers = [
        {'ticker': 'C', 'pct_1d': 5, 'quote_source': 'feed'},
        {'ticker': 'D', 'pct_1d': -2},
        {'ticker': 'E', 'pct_1d': 2},
    ]
    common = {'theme': '太空', 'region': 'us', 'self_session': '2026-11-27',
              'listed_peers': peers}
    ctx = {'generation_id': 'current', 'peer_scan': {
        'A': {**common, 'self_pct_1d': 4},
        'B': {**common, 'theme': '卫星', 'self_pct_1d': 1},
    }}
    draft = tmp_path / 'draft.json'
    draft.write_text(json.dumps({
        'context_generation_id': 'current',
        'attribution': {'A': '受板块带动'},
        'themes': {'B': '太空'},
        'catalysts': {'C': '来自[[/ctx/peer_scan/A/listed_peers/0/quote_source]]',
                      'D': '手写 2 条', 'UNSEEN': '未知'},
    }))
    renderer = prose_claims.ClaimRenderer(ctx)
    scan = sector_scan(ctx, draft, renderer, narrative='板块走强')
    assert scan['narrative'] == '板块走强'
    [group] = scan['sectors']
    assert group['tickers_in_book'] == ['A', 'B']
    assert group['self'][0]['rank_text'] == '第 2/4'
    assert group['self'][0]['attribution'] == '受板块带动'
    assert group['top_movers'][0]['catalyst'] == '来自feed'
    assert group['top_movers'][0]['pct'] == 5
    assert not any('catalyst' in row for row in group['top_movers'][1:])
    assert renderer.issues
    stale = sector_scan({**ctx, 'generation_id': 'new'}, draft, renderer)
    assert stale['sectors'][0]['self'][0]['attribution'] is None
    assert not any('catalyst' in row for row in stale['sectors'][0]['top_movers'])


def test_repeated_readings_and_stock_phrases_are_advisory_for_a_report(tmp_path):
    ctx = {
        prose_claims.FIELD: prose_claims.VERSION,
        'raw_wechat_block': '程序生成的行情',
        'holdings': {'07709': {'ticker': '07709', 'current_price': 11.39,
                              'today_change_pct': 5.46, 'shares': 200}},
    }
    base = '▎情绪面\n韩国那边还在跌。\n▎技术面\n'
    closing = '\n▎操作建议\n我会等港股开出来看看。'
    price = '[[/ctx/holdings/07709/current_price]]'
    changed = '[[/ctx/holdings/07709/today_change_pct]]'
    shares = '[[/ctx/holdings/07709/shares]]'
    _, issues = prepare_report(ctx, base + f'业内认为，{changed}，{shares}，{price}。'
                                f'再看看{price}。' + closing, tmp_path)
    assert len(issues) == 1 and categorize(issues) == 'warn'
    assert '一句里连报多项读数' in issues[0]
    assert '重复引用同一数值字段' in issues[0]
    assert '归因没说是谁' in issues[0]

    body, issues = prepare_report(ctx, base + f'港股上一场还涨了 {changed}。' + closing, tmp_path)
    assert '涨了 5.46%' in body
    assert not issues


def test_plan_invalidation_prose_resolves_before_reaching_decision_trace():
    renderer = prose_claims.ClaimRenderer({'watch': {'price': 130.87}})
    plan = {'decisions': [{'ticker': '07709', 'condition': {'type': 'open'},
                          'size': {'shares': 200},
                          'thesis_invalidation': 'ADR 收回 [[/ctx/watch/price]] 就重新评估。'}]}
    row = brief_prose.render_plan(plan, renderer)['decisions'][0]
    assert row['thesis_invalidation'] == 'ADR 收回 130.87 就重新评估。'
    assert row['size'] == plan['decisions'][0]['size']
    assert not renderer.issues
