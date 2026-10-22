"""The 2026-10-21 brief must not scale weight by shares (#3134)."""
import json
from pathlib import Path

import pytest

from clawock.portfolio.guardrail import _single_name_policy, plan_trim_projections, trim_projection
from clawock.harness import brief_render, brief_postflight
from clawock.harness.validation import check_numeric_claims, is_advisory


def scenario():
    holding = {'ticker': '00100', 'shares': 140, 'lot_size': 20}
    breaches, reviews = _single_name_policy('HK', [
        {'ticker': '00100', 'value': 24010, 'weight_pct': 46.84}],
        [holding], 51254.2, 'HKD')
    assert not breaches
    context = {'risk_guardrail': {'concentration_reviews': reviews}}
    plan = {'decisions': [{'ticker': '00100', 'action': 'trim_on_rebound',
                          'size': {'shares': 40},
                          'condition': {'type': 'price_above', 'price': 178.1}}]}
    return context, plan


def test_review_and_trigger_scenarios_solve_the_changing_denominator():
    ctx, plan = scenario()
    review = ctx['risk_guardrail']['concentration_reviews'][0]
    assert review['trim_to_review_line']['shares'] == 60
    projection = plan_trim_projections(ctx, plan)[0]
    assert projection['post_trim_weight_pct'] == 39.53
    assert projection['shares_to_review_line'] == 60
    plan['decisions'][0]['size']['shares'] = 60
    assert plan_trim_projections(ctx, plan)[0]['post_trim_weight_pct'] == 34.34
    plan['decisions'][0]['condition'] = {'type': 'open'}
    plan['decisions'][0]['size']['shares'] = 40
    assert plan_trim_projections(ctx, plan)[0]['post_trim_weight_pct'] == 38.63


def test_next_brief_renders_the_true_scenario_without_rewriting_history():
    ctx, plan = scenario()
    rendered = brief_render.risk_section(ctx, plan)
    assert '39.53%' in rendered and '仍高于 35% 复核线' in rendered
    assert '达到该线需卖 60 股' in rendered
    assert '33%' not in rendered


@pytest.mark.parametrize('prose', [
    '00100 卖 40 股后回到 33% 附近。',
    '00100 把港股腿的单票支配度从 46.84% 压回 35% 复核线下方。',
])
def test_wrong_dominance_blocks_publication_even_if_number_exists_elsewhere(tmp_path, prose):
    ctx, plan = scenario()
    ctx['unrelated'] = {'pct': 33}
    plan['decisions'][0]['rationale'] = prose
    issues = brief_postflight._brief_numeric_issues(tmp_path / 'missing.json', plan, ctx)
    assert any('仓位支配度不符' in i and not is_advisory(i) for i in issues)
    assert brief_postflight.categorize(issues) == 'fail'


def test_true_claim_and_unrelated_percentage_keep_their_meaning(tmp_path):
    ctx, plan = scenario()
    plan['decisions'][0]['rationale'] = '00100 卖 40 股后回到 39.53%，支配度仍高于 35% 复核线。'
    assert not brief_postflight._brief_numeric_issues(tmp_path / 'missing.json', plan, ctx)
    issues = check_numeric_claims('00100 收入增长 33%。', ctx)
    assert all(is_advisory(i) for i in issues)


def test_empty_leg_has_no_invented_zero_percent():
    result = trim_projection(shares=100, value=1000, total=1000, price=10)
    assert result['shares'] == 100 and result['post_trim_weight_pct'] is None


def test_price_return_in_same_sentence_is_not_a_concentration_claim(tmp_path):
    ctx, plan = scenario()
    ctx['quote_return_pct'] = -2.3
    plan['decisions'][0]['rationale'] = (
        '00100 下跌 -2.3%，港股腿支配度为 46.84%，卖 40 股后回到 39.53%。')
    assert not brief_postflight._brief_numeric_issues(tmp_path / 'missing.json', plan, ctx)


def test_review_line_cannot_authorize_a_false_post_sale_result(tmp_path):
    ctx, plan = scenario()
    plan['decisions'][0]['rationale'] = '00100 卖 40 股后回到 35%。'
    issues = brief_postflight._brief_numeric_issues(tmp_path / 'missing.json', plan, ctx)
    assert brief_postflight.categorize(issues) == 'fail'


def test_historical_record_is_only_read_for_regression():
    root = Path(__file__).resolve().parents[1]
    snap = json.loads((root / 'memory/snapshots/2026-10-20.json').read_text())
    leg = snap['portfolios']['hk_stocks']
    h = next(h for h in leg['holdings'] if h['ticker'] == '00100')
    result = trim_projection(shares=h['shares'], value=h['current_value'],
                             total=leg['total_current_value'], price=178.1,
                             lot_size=h['lot_size'], sell_shares=40)
    assert result['post_trim_weight_pct'] == 39.53
    assert result['shares_to_review_line'] == 60


def test_historical_lede_aliases_do_not_leak_between_names():
    import re
    from clawock.portfolio.guardrail import compute_concentration, compute_risk_guardrail
    from clawock.harness.validation import _concentration_claim_issues
    root = Path(__file__).resolve().parents[1]
    snap = json.loads((root / 'memory/snapshots/2026-10-20.json').read_text())
    hk = snap['portfolios']['hk_stocks']['holdings']
    us = snap['portfolios']['us_stocks']['holdings']
    guard = compute_risk_guardrail(hk, us, compute_concentration(hk), compute_concentration(us), {})
    plan = json.loads((root / 'memory/2026-10-21-plan.json').read_text())
    ctx = {'risk_guardrail': guard}
    ctx['plan_trim_projections'] = plan_trim_projections(ctx, plan)
    md = (root / 'memory/2026-10-21-pre-open.md').read_text()
    lede = re.search(r'brief-lede" markdown="1">\n\n(.*?)\n\n\*\*反方', md, re.S)[1]
    issues = _concentration_claim_issues(lede, ctx)
    assert issues == ['仓位支配度不符: 00100 减仓后 39.53% 仍高于复核线']
    old_claim = next(line for line in md.splitlines() if '卖 40 股后回到 33%' in line)
    assert any('00100' in i for i in _concentration_claim_issues('- **00100**\n' + old_claim, ctx))
    assert not _concentration_claim_issues(
        '- **SPCH** MiniMax 港股腿支配度 46.84%，SPCH 仓位占比 87.22%。', ctx)
    assert not _concentration_claim_issues('MiniMax 收入增长 161%。SPCH 上涨 20.8%。', ctx)
    assert not _concentration_claim_issues('XMINIMAX 收入增长 161%，支配度 3%。', ctx)


def test_timeline_discloses_current_scenario_without_rewriting_or_rejecting(monkeypatch):
    from clawock.publish import dashboard
    ctx, plan = scenario()
    row = dict(plan['decisions'][0], decision_id='audit', rationale='卖 40 股后回到 33% 附近。')
    monkeypatch.setattr(dashboard.decision_v2, 'load_decisions', lambda: [row])
    result = dashboard.compute_plan_timeline([], context=ctx)[0]
    assert result['rationale'] == row['rationale']
    assert result['trim_projection']['post_trim_weight_pct'] == 39.53
    assert result['trim_projection']['shares_to_review_line'] == 60
    assert result['plan_warnings'] and '33%' in result['plan_warnings'][0]
    row['rationale'] = '卖 40 股后回到 39.53%，收入增长 33%。'
    assert not dashboard.compute_plan_timeline([], context=ctx)[0]['plan_warnings']
    row['size']['shares'] = 1000
    assert dashboard.compute_plan_timeline([], context=ctx)[0]['trim_projection'] is None
