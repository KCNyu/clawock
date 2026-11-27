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
    assert '达到该线需卖 60 股，卖后剩 80 股' in rendered
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


@pytest.mark.parametrize('verb', ['落回', '回落', '降回', '压回', '落到', '降至'])
def test_the_movement_verb_is_a_shape_not_a_whitelist(tmp_path, verb):
    """#3417: the model wrote 落回, which was outside the hand-kept list, while
    the same sentence with 降到 was caught."""
    ctx, plan = scenario()
    plan['decisions'][0]['rationale'] = (
        f'00100 减 60 股后港股腿单名占比{verb} 35% 复核线以下。')
    issues = brief_postflight._brief_numeric_issues(tmp_path / 'missing.json', plan, ctx)
    assert any('仓位支配度不符' in i and not is_advisory(i) for i in issues), issues
    assert brief_postflight.categorize(issues) == 'fail'


def test_a_high_water_mark_is_not_a_destination(tmp_path):
    ctx, plan = scenario()
    plan['decisions'][0]['rationale'] = '00100 港股腿单名占比高达 46.84%，还在复核线上方。'
    assert not brief_postflight._brief_numeric_issues(tmp_path / 'missing.json', plan, ctx)


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


def test_each_projection_says_which_price_it_sold_at():
    """2026-10-22: the brief (morning book) and the timeline (current book) printed
    33.78% and 35.89% for one plan; each line now names its price and book."""
    ctx, plan = scenario()
    assert plan_trim_projections(ctx, plan)[0]['price_basis'] == 'plan_trigger'
    rendered = brief_render.risk_section(ctx, plan)
    assert '按计划触发价 178.1 HKD 卖 40 股' in rendered and '账本取本次简报生成时' in rendered
    plan['decisions'][0]['condition'] = {'type': 'open'}
    assert plan_trim_projections(ctx, plan)[0]['price_basis'] == 'book_mark'
    assert '按简报时现价' in brief_render.risk_section(ctx, plan)


@pytest.mark.parametrize('prose', [
    '反弹站上 178.1 时减 40 股；按成交价算，00100 在港股腿的占比落到 35%。',
    '00100 减 40 股，占比降至 35%。',
    '00100 减 40 股后占比回到 35%。',
    '00100 涨到 178.1 卖 40 股，卖完回到 35%。',
    '00100 按触发价算仍高于 35% 的单名复核线，40 股才够，具体支配度以成交价重算。',
])
def test_real_phrasing_families_reach_both_gates(tmp_path, prose):
    from clawock.portfolio.guardrail import plan_trim_warnings
    ctx, plan = scenario()
    decision = plan['decisions'][0]
    decision['condition']['description'] = prose
    assert plan_trim_warnings(decision, plan_trim_projections(ctx, plan)[0])
    issues = brief_postflight._brief_numeric_issues(tmp_path / 'missing.json', plan, ctx)
    assert brief_postflight.categorize(issues) == 'fail'
    from clawock.harness.validation import _concentration_claim_issues
    ctx['plan_trim_projections'] = plan_trim_projections(ctx, plan)
    assert _concentration_claim_issues(prose, ctx)


@pytest.mark.parametrize('prose', [
    '00100 减 40 股；占比落到 39.53%，收入增长 35%。',
    '00100 当前仓位占比为 46.84%，收益率降到 35%。',
    '00100 不能声称占比落到 35%。',
    '00100 卖完回到 39.53%。',
    '00100 卖完这一格在港股腿回到 40%，收益率降到 35%。',
    '00100 卖完回报约 35%。',
    '00100 不会卖完回到 35%。',
    '00100 40 股不够回到复核线，60 股才够。',
    '00100 并非 40 股才够回到复核线。',
])
def test_claim_negatives_and_correct_results(prose):
    from clawock.portfolio.guardrail import plan_trim_warnings
    from clawock.harness.validation import _concentration_claim_issues
    ctx, plan = scenario()
    projection = plan_trim_projections(ctx, plan)[0]
    ctx['plan_trim_projections'] = [projection]
    assert not plan_trim_warnings({'rationale': prose}, projection)
    assert not _concentration_claim_issues(prose, ctx)


def test_october_28_frozen_condition_and_timeline(monkeypatch, tmp_path):
    from clawock.publish import dashboard
    root = Path(__file__).resolve().parents[1]
    plan = json.loads((root / 'memory/2026-10-28-plan.json').read_text())
    row = next(d for d in plan['decisions'] if d['ticker'] == '00100')
    _, reviews = _single_name_policy('HK', [
        {'ticker': '00100', 'value': 25228, 'weight_pct': 49.36}],
        [{'ticker': '00100', 'shares': 140, 'lot_size': 20}], 51105.2, 'HKD')
    ctx = {'risk_guardrail': {'concentration_reviews': reviews}}
    monkeypatch.setattr(dashboard.decision_v2, 'load_decisions', lambda: [row])
    result = dashboard.compute_plan_timeline([], context=ctx)[0]
    assert result['trim_projection']['post_trim_weight_pct'] == 30.77
    assert any('34.3%' in w for w in result['plan_warnings'])
    assert result['condition'] == row['condition']
    assert brief_postflight.categorize(brief_postflight._brief_numeric_issues(
        tmp_path / 'missing.json', {'decisions': [row]}, ctx)) == 'fail'


def test_other_ticker_destination_does_not_leak():
    from clawock.harness.validation import _concentration_claim_issues
    ctx, plan = scenario()
    ctx['risk_guardrail']['concentration_reviews'].append(
        {'ticker': 'SPCH', 'weight_pct': 90, 'review_pct': 35})
    ctx['plan_trim_projections'] = plan_trim_projections(ctx, plan)
    assert not _concentration_claim_issues(
        '00100 收入增长 35%，SPCH 减仓后占比落到 90%。', ctx)


def test_october_27_sufficiency_claim_is_checked_in_both_gates(tmp_path):
    from clawock.portfolio.guardrail import plan_trim_warnings
    root = Path(__file__).resolve().parents[1]
    plan = json.loads((root / 'memory/2026-10-27-plan.json').read_text())
    row = next(d for d in plan['decisions'] if d['ticker'] == '00100')
    _, reviews = _single_name_policy('HK', [
        {'ticker': '00100', 'value': 25228, 'weight_pct': 49.36}],
        [{'ticker': '00100', 'shares': 140, 'lot_size': 20}], 51105.2, 'HKD')
    ctx = {'risk_guardrail': {'concentration_reviews': reviews}}
    plan = {'decisions': [row]}
    projection = plan_trim_projections(ctx, plan)[0]
    assert projection['shares_to_review_line'] == 80
    assert any('60 股足够' in w for w in plan_trim_warnings(row, projection))
    assert brief_postflight.categorize(brief_postflight._brief_numeric_issues(
        tmp_path / 'missing.json', plan, ctx)) == 'fail'


@pytest.mark.parametrize('ticker,leg,currency,lot,shares,mark,other,weight,trigger_weight', [
    ('SPCH', 'US', 'USD', 1, 320, 6.305, 487.05, 34.67, 36.74),
    ('00100', 'HK', 'HKD', 20, 160, 101.40, 23900.4, 33.74, 35.10),
])
def test_november_25_trigger_claim_uses_trigger_while_rationale_uses_book(
        tmp_path, monkeypatch, ticker, leg, currency, lot, shares, mark, other, weight, trigger_weight):
    from clawock.harness.validation import _concentration_claim_issues
    from clawock.publish import dashboard

    root = Path(__file__).resolve().parents[1]
    plan = json.loads((root / 'memory/2026-11-25-plan.json').read_text())
    row = next(d for d in plan['decisions'] if d['ticker'] == ticker and d['action'].startswith('trim'))
    value = shares * mark
    total = value + other
    _, reviews = _single_name_policy(
        leg, [{'ticker': ticker, 'value': value, 'weight_pct': round(value / total * 100, 2)}],
        [{'ticker': ticker, 'shares': shares, 'lot_size': lot}], total, currency)
    context = {'risk_guardrail': {'concentration_reviews': reviews}}
    plan = {'decisions': [row]}
    context['plan_trim_projections'] = plan_trim_projections(context, plan)
    context['plan_book_trim_projections'] = plan_trim_projections(context, plan, at_book_mark=True)
    monkeypatch.setattr(dashboard.decision_v2, 'load_decisions', lambda: [row])

    assert context['plan_book_trim_projections'][0]['post_trim_weight_pct'] == weight
    assert not _concentration_claim_issues(f'- **{ticker}** ·\n' + row['rationale'], context)
    timeline = dashboard.compute_plan_timeline([], context=context)[0]
    assert timeline['trim_projection']['post_trim_weight_pct'] == trigger_weight
    assert len(timeline['plan_warnings']) == 1
    assert all(f'{number}%' in timeline['plan_warnings'][0] for number in (weight, trigger_weight))
    issues = brief_postflight._brief_numeric_issues(tmp_path / 'missing.json', plan, context)
    assert any('仓位支配度不符' in issue and str(trigger_weight) in issue for issue in issues)
    assert brief_postflight.categorize(issues) == 'fail'
    row['rationale'] = row['rationale'].replace(f'{weight}%', '21.19%')
    assert any('21.19%' in warning for warning in
               dashboard.compute_plan_timeline([], context=context)[0]['plan_warnings'])


def test_a_review_line_can_be_a_threshold_instead_of_a_weight_destination():
    from clawock.portfolio.guardrail import plan_trim_warnings

    ctx, plan = scenario()
    row = plan['decisions'][0]
    row['condition']['description'] = '这次卖完这一格回到 35% 的复核线以下。'
    assert plan_trim_warnings(row, plan_trim_projections(ctx, plan)[0])
    row['size']['shares'] = 60
    assert not plan_trim_warnings(row, plan_trim_projections(ctx, plan)[0])


def test_november_26_trim_already_reaches_review_line(tmp_path, monkeypatch):
    from clawock.harness.validation import _concentration_claim_issues
    from clawock.portfolio.guardrail import plan_trim_warnings
    from clawock.publish import dashboard

    root = Path(__file__).resolve().parents[1]
    frozen = json.loads((root / 'memory/2026-11-26-plan.json').read_text())
    row = next(d for d in frozen['decisions']
               if d['ticker'] == '00100' and d['action'] == 'trim_on_rebound')
    # Marks from the book packaged with the November 26 brief.
    _, reviews = _single_name_policy(
        'HK', [{'ticker': '00100', 'value': 13984, 'weight_pct': 38.51}],
        [{'ticker': '00100', 'shares': 160, 'lot_size': 20}], 36309.6, 'HKD')
    ctx = {'risk_guardrail': {'concentration_reviews': reviews}}
    plan = {'decisions': [row]}
    [projection] = ctx['plan_trim_projections'] = plan_trim_projections(ctx, plan)
    assert projection['post_trim_weight_pct'] == 34.42

    monkeypatch.setattr(dashboard.decision_v2, 'load_decisions', lambda: [row])
    [timeline] = dashboard.compute_plan_timeline([], context=ctx)
    assert any('34.42%' in warning and '35%' in warning
               for warning in timeline['plan_warnings'])
    issues = brief_postflight._brief_numeric_issues(tmp_path / 'missing.json', plan, ctx)
    assert brief_postflight.categorize(issues) == 'fail'
    assert _concentration_claim_issues(f"- **00100**\n{row['method']}", ctx)

    for prose in (
        '00100 目前仍高于 35% 复核线，减完这一格不高于 35% 复核线。',
        '00100 减完这一格不应声称仍略高于 35% 复核线。',
        '00100 减仓后约 34.42%，当前仍高于 35% 复核线。',
    ):
        assert not plan_trim_warnings({'rationale': prose}, projection)
        assert not _concentration_claim_issues(prose, ctx)

    assert plan_trim_warnings({'rationale': row['rationale']},
                              {**projection, 'post_trim_weight_pct': 35.0})
    assert not plan_trim_warnings({'rationale': row['rationale']},
                                  {**projection, 'post_trim_weight_pct': 35.01})


def test_review_line_sale_and_remainder_are_checked_against_the_stated_basis(tmp_path):
    from clawock.portfolio.guardrail import plan_trim_warnings

    ctx = {'risk_guardrail': {'concentration_reviews': [{
        'ticker': 'SPCH', 'leg': 'US', 'currency': 'USD', 'weight_pct': 80.47, 'review_pct': 35,
        'trim_inputs': {'shares': 320, 'value': 2057.6, 'total': 2556.97, 'price': 6.43,
                        'lot_size': 1, 'target_pct': 35},
    }]}}
    decision = {
        'ticker': 'SPCH', 'action': 'trim_on_rebound', 'size': {'shares': 100},
        'condition': {'type': 'price_above', 'price': 6.8},
        'rationale': '组合政策依据是美股腿这一格的单名占比远在复核线上方，风控算好的复核线数量是 279 股，也就是减 41 股',
    }
    plan = {'decisions': [decision]}
    trigger, = plan_trim_projections(ctx, plan)
    mark, = plan_trim_projections(ctx, plan, at_book_mark=True)
    assert (trigger['shares_to_review_line'], mark['shares_to_review_line']) == (281, 279)
    assert any('需卖 41 股' in warning for warning in plan_trim_warnings(decision, trigger, mark))
    issues = brief_postflight._brief_numeric_issues(tmp_path / 'missing.json', plan, ctx)
    assert brief_postflight.categorize(issues) == 'fail'

    decision['rationale'] = '按现价算，复核线数量是 279 股，减到 41 股；按触发价算，复核线数量是 281 股，减到 39 股。'
    assert not plan_trim_warnings(decision, trigger, mark)
    decision['rationale'] = '按账面价计算，复核线股数为 279 股，即卖 279 股。'
    assert not plan_trim_warnings(decision, trigger, mark)


@pytest.mark.parametrize('text', [
    '减 40 股便可回到复核线。',
    '为回到 35% 的复核线，得削掉 40 股。',
    '40 股即可压回复核线。',
    '复核线要求卖 40 股。',
    '复核线需卖 40 股（不是剩 80 股）。',
    '复核线数量为 60 股（也就意味着卖 40 股）。',
    '要达到复核线须卖 60 股（余 40 股）。',
])
def test_review_claims_bind_share_roles_to_the_line(tmp_path, monkeypatch, text):
    from clawock.publish import dashboard

    ctx, plan = scenario()
    row = plan['decisions'][0]
    row['rationale'] = text
    issues = brief_postflight._brief_numeric_issues(tmp_path / 'missing.json', plan, ctx)
    assert brief_postflight.categorize(issues) == 'fail'
    monkeypatch.setattr(dashboard.decision_v2, 'load_decisions', lambda: [row])
    [timeline] = dashboard.compute_plan_timeline([], context=ctx)
    assert timeline['plan_warnings']


@pytest.mark.parametrize('text', [
    '现在仍高于复核线，本档先卖 40 股。',
    '先卖 40 股也无法达到复核线。',
    '先卖 40 股，这样仍不能达到复核线。',
    '减 40 股到不了复核线。',
    '卖 80 股便可压回复核线，届时剩 60 股。',
    '卖 40 股后仍高于复核线，还需要卖 20 股才能达标。',
])
def test_review_line_context_does_not_turn_every_trade_into_the_minimum(text):
    from clawock.portfolio.trim_claims import trim_claim_warnings

    ctx, plan = scenario()
    [projection] = plan_trim_projections(ctx, plan)
    assert not trim_claim_warnings(text, projection)


def test_price_basis_can_change_inside_one_sentence():
    from clawock.portfolio.trim_claims import trim_claim_warnings

    book = {'price_basis': 'book_mark', 'price': 6.43, 'shares_to_review_line': 279,
            'remaining_shares_at_review_line': 41}
    trigger = {'price_basis': 'plan_trigger', 'price': 6.8, 'shares_to_review_line': 281,
               'remaining_shares_at_review_line': 39}
    text = ('按账面价 6.43 美元算，需卖 279 股达到复核线（余 41 股），'
            '按触发价 6.80 美元算，需卖 281 股达到复核线（余 39 股）。')
    assert not trim_claim_warnings(text, trigger, book)
    [warning] = trim_claim_warnings(text.replace('余 39 股', '余 41 股'), trigger, book)
    assert '应剩 41 股' in warning and '应剩 39 股' in warning


def test_named_position_keeps_a_price_basis_stated_before_its_name():
    from clawock.harness.validation import _concentration_claim_issues

    ctx, plan = scenario()
    ctx['plan_trim_projections'] = plan_trim_projections(ctx, plan)
    ctx['plan_book_trim_projections'] = plan_trim_projections(ctx, plan, at_book_mark=True)
    assert not _concentration_claim_issues('按账面价算，00100 卖 40 股后占比降至 38.63%。', ctx)


def test_two_decisions_for_one_ticker_each_use_their_own_sale_size(tmp_path):
    ctx, plan = scenario()
    first = plan['decisions'][0]
    second = {**first, 'size': {'shares': 60}}
    first['rationale'] = '卖 40 股后占比落到 39.53%。'
    second['rationale'] = '卖 60 股后占比落到 34.34%。'
    plan['decisions'].append(second)
    assert not brief_postflight._brief_numeric_issues(tmp_path / 'missing.json', plan, ctx)
    first['rationale'] = '卖 40 股后占比落到 34.34%。'
    assert brief_postflight.categorize(
        brief_postflight._brief_numeric_issues(tmp_path / 'missing.json', plan, ctx)) == 'fail'


def test_review_size_has_book_authority_even_without_a_planned_sale(tmp_path):
    ctx, _ = scenario()
    plan = {'decisions': [{'ticker': '00100', 'action': 'hold',
                          'rationale': '按账面价算，减 40 股即可回到复核线。'}]}
    assert brief_postflight.categorize(
        brief_postflight._brief_numeric_issues(tmp_path / 'missing.json', plan, ctx)) == 'fail'
    plan['decisions'][0]['rationale'] = '按账面价算，减 60 股即可回到复核线。'
    assert not brief_postflight._brief_numeric_issues(tmp_path / 'missing.json', plan, ctx)


def test_named_unreviewed_position_does_not_inherit_another_positions_numbers(
        tmp_path, monkeypatch):
    from clawock.publish import dashboard

    ctx, plan = scenario()
    ctx['portfolio'] = {'portfolios': {'hk': {'holdings': [
        {'ticker': '03033', 'name': '恒科 ETF'}]}}}
    row = plan['decisions'][0]
    row['rationale'] = '00100 仍高于复核线，恒科 ETF 卖 40 股便可回到复核线。'
    assert not brief_postflight._brief_numeric_issues(tmp_path / 'missing.json', plan, ctx)
    monkeypatch.setattr(dashboard.decision_v2, 'load_decisions', lambda: [row])
    [timeline] = dashboard.compute_plan_timeline([], context=ctx)
    assert not timeline['plan_warnings']
