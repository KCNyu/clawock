"""Reconcile the archived breakeven, rank, and news regressions."""

import pytest

from clawock import prose_claims
from clawock.decision import brief_prose
from clawock.harness import brief_render
from clawock.portfolio import breakeven_claims as drag
from clawock.prose_validation import peer_style_issues


ROWS = [{"ticker": "07709", "vol_unavailable_reason": "标的波动率不可用"},
        {"ticker": "RKLX", drag.DRAG_FIELD: 11.69},
        {"ticker": "07226", drag.DRAG_FIELD: 0.98},
        {"ticker": "SPCH", drag.DRAG_FIELD: 4.4}]
BREAKEVEN = {'rows': ROWS, drag.DRAG_SUM_FIELD: 17.07,
             'priced_chop_drag_tickers': ['RKLX', '07226', 'SPCH']}
CTX = {'breakeven_math': BREAKEVEN}


def test_monthly_decay_does_not_borrow_other_tickers_or_guess_missing_volatility():
    assert drag.priced_drag_total(ROWS) == 17.07
    assert any('07709 这只的衰减算不出来' in i for i in
               drag.validate_drag('07709 的两倍腿每月白付 4.4% 的横盘衰减。', CTX))
    assert not drag.validate_drag('SPCH 的横盘衰减为每月 4.4%。', CTX)
    assert drag.validate_drag('RKLX 的横盘衰减为每月 4.4%。', CTX)
    assert drag.validate_drag('07709 有横盘衰减，每月 4.4%。', CTX)
    assert drag.validate_drag('三只两倍腿每月合付 16.67% 的横盘衰减。', CTX)
    assert drag.validate_drag('三只两倍腿每月合付 16.67%。', CTX)
    assert not drag.validate_drag('已测的合计月衰减算术和为每月 17.07%。', CTX)
    assert not drag.validate_drag('07709 这只的衰减算不出来。', CTX)
    card = brief_render.breakeven_section(CTX)
    assert '07709：这只的衰减算不出来' in card
    assert '17.07%' in card


def test_structured_plan_and_judgment_check_same_ticker_and_repeat_across_fields():
    cite = '[[/ctx/breakeven_math/rows/3/chop_drag_pct_per_month]]'
    renderer = prose_claims.ClaimRenderer(CTX)
    plan = {'decisions': [{'ticker': 'SPCH', 'rationale': f'横盘衰减每月 {cite}。'}]}
    brief_prose.render_plan(plan, renderer)
    brief_prose.render_judgment({'ticker_judgments': [
        {'ticker': 'SPCH', 'assessment': f'每月 {cite} 的横盘衰减。'},
    ]}, renderer)
    assert not renderer.issues
    assert any('重复引用同一数值字段' in i for i in renderer.advisories)
    brief_prose.render_judgment({'ticker_judgments': [
        {'ticker': '07709', 'assessment': f'每月 {cite} 的横盘衰减。'},
    ]}, renderer)
    assert any('07709 这只的衰减算不出来' in i for i in renderer.issues)


def test_structured_drag_rejects_same_number_from_another_field():
    renderer = prose_claims.ClaimRenderer({**CTX, 'unrelated_pct': 4.4})
    renderer.render('SPCH 的横盘衰减为每月 [[/ctx/unrelated_pct]]。', '简报')
    assert any('须引用同票测算字段' in i for i in renderer.issues)


def test_legacy_unverified_decay_refuses_workspace_publication(tmp_path):
    context = {**CTX, 'date': '2026-11-27'}
    plan = {'decisions': [{'ticker': '07709', 'rationale': '每月 4.4% 的横盘衰减。'}]}
    path = tmp_path / 'memory' / '2026-11-27-pre-open.md'
    path.parent.mkdir()
    path.write_text('original')
    issues, body = brief_render.render_from_workspace(
        tmp_path, '2026-11-27', context=context, plan=plan, judgment={})
    assert body is None and path.read_text() == 'original'
    assert any('07709 这只的衰减算不出来' in issue for issue in issues)


def test_rank_is_computed_from_the_same_holding_peer_set():
    scan = {'sectors': [{'self': [{'ticker': 'RKLX', 'rank_text': '落后'}]}]}
    context = {'peer_scan': {'RKLX': {'self_pct_1d': 4.73, 'listed_peers': [
        {'ticker': 'RKLB', 'pct_1d': 2.26}, {'ticker': 'XYZ', 'pct_1d': None},
    ]}}}
    revised = []
    brief_render.bind_sector_self(scan, context, rank_updates=revised)
    assert revised == ['RKLX']
    assert scan['sectors'][0]['self'][0]['rank_text'] == '领涨 · 第 1/2'
    # A broken quote removes the rank rather than trusting the draft column.
    brief_render.bind_sector_self(scan, {})
    assert scan['sectors'][0]['self'][0]['rank_text'] is None


def test_news_uses_live_citation_after_filtering_options_and_quote_pages():
    titles = ['RKLX Feb 2028 25.000 call quote',
              'Stock Price, Analysis, News and Trading Ideas']
    live = {'title': 'RKLB launches Electron', 'cite': '《RKLB launches Electron》（Reuters，已发布）'}
    context = {
        'sentiment': {'tickers': [{'ticker': 'RKLX', 'news_top': titles},
                                  {'ticker': 'SPCH', 'news_top': titles}]},
        'live_information': {'us': {'summary': {'RKLX': [live]}}},
    }
    judgment = {'ticker_judgments': [{'ticker': 'RKLX'}]}
    assert live['cite'] in brief_render.tier1_section(context, judgment)
    social = brief_render.sentiment_section(context, judgment)
    assert not any(title in social for title in titles)
    assert live['cite'] in social and '没有可用新闻' in social


def test_shared_judgment_fields_only_show_once_per_ticker():
    plan = {'decisions': [{'ticker': '00100', 'action': action, 'rationale': f'理由 {action}'}
                         for action in ('trim_on_rebound', 'hold_and_watch')]}
    judgment = {'ticker_judgments': [{'ticker': '00100', 'assessment': '业务情况够用',
                                      'counterargument': '证据可能偏旧',
                                      'next_evidence': '看交易量能否跟上', 'rationale': '等待公告'}]}
    card = brief_render.judge_section(plan, judgment)
    assert 'trim_on_rebound' in card and 'hold_and_watch' in card
    for line in ('业务情况够用', '证据可能偏旧', '看交易量能否跟上', '等待公告'):
        assert card.count(line) == 1


@pytest.mark.parametrize('bad', [
    '这一格还是老样子，继续观察。', '题材加、自己减，落后合理。',
    '被市场抛售，所以掉队。', '跟板块 beta，没有自己的消息。',
])
def test_peer_read_warns_on_vague_or_template_language(bad):
    assert peer_style_issues(bad)
    assert not peer_style_issues('港股同业成交放大，腾讯这一场的量还没跟上。')


def test_numerical_gate_spares_conversational_classifier_but_checks_real_counts():
    renderer = prose_claims.ClaimRenderer({'move': {'today_change_pct': 4.5}})
    plain = '标的完成一次 Electron 发射。下一场留意同一份公告。'
    assert renderer.render(plain, '报告') == plain and not renderer.issues
    renderer.render('涨了 16.04%。', '报告')
    assert not renderer.issues
    assert any('未绑定读数「16.04%」' in note for note in renderer.advisories)
    assert renderer.render('上涨 [[/ctx/move/today_change_pct]]%', '报告') == '上涨 4.5%'
