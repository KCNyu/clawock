"""#964：昨日计划的判词只有一份，来自 decision_v2 的结算。

原来 compute_retrospective 自己拿 portfolio 快照的 current_price / day_open /
day_high / day_low 判「触发了没有」，而同一批 decision 的正式结算走 memory/bars。
两套判词可以互相矛盾，且被同时喂进同一条 context 让 LLM 校准 confidence。
"""
import json

from clawock.harness import brief_preflight


PORTFOLIO = {
    'portfolios': {
        'us_stocks': {'holdings': [{
            'ticker': 'ABC',
            # 快照口径：这一天「看起来」冲到过 12，旧实现会据此判 price_above 10 已触发。
            'current_price': 11.0, 'day_open': 9.0, 'day_high': 12.0,
            'day_low': 8.5, 'prev_close': 9.5,
        }]},
        'hk_stocks': {'holdings': []},
    },
}


def _plan(tmp_path, **overrides):
    decision = {
        'decision_id': 'dec-1',
        'ticker': 'ABC',
        'action': 'add_only_on_trigger',
        'condition': {'type': 'price_above', 'price': 10.0},
        'size': {'shares': 100},
        'confidence': 0.9,
        'rationale': 'breakout',
    }
    decision.update(overrides)
    path = tmp_path / 'plan-2026-08-24.json'
    path.write_text(json.dumps({'date': '2026-08-24', 'decisions': [decision]}))
    return path


def _ledger_row(**evaluation):
    return {
        'decision_id': 'dec-1',
        'plan_date': '2026-08-24',
        'ticker': 'ABC',
        'leg': 'US',
        'action': 'add_only_on_trigger',
        'condition': {'type': 'price_above', 'price': 10.0},
        'evaluation': evaluation,
    }


def test_the_ledger_verdict_wins_over_what_the_snapshot_would_have_said(tmp_path):
    """快照说 day_high=12 ≥ 10（旧实现判 fired），canonical bars 说没触发。

    留下的必须是后者 —— 这条测试的整个意义就是：两者矛盾时，输出里不能出现
    快照那一份。
    """
    retro = brief_preflight.compute_retrospective(
        _plan(tmp_path), PORTFOLIO,
        [_ledger_row(triggered=False, status='not_triggered', outcome='not_triggered',
                     fill_reason='high_below_trigger', trigger_session='2026-08-25')],
    )

    row = retro['decisions'][0]
    assert row['trigger_fired'] is False
    assert row['settlement_status'] == 'not_triggered'
    assert row['verdict_source'] == 'decision_ledger'
    assert row['verdict_basis'].startswith('memory/bars')
    # 快照价格字段不许再出现在输出里：它们是另一套 vintage 的数字。
    for gone in ('actual_open', 'actual_close', 'actual_day_high',
                 'actual_day_low', 'actual_prev_close', 'simulated_pnl',
                 'simulated_execution_price'):
        assert gone not in row, gone


def test_every_row_reconciles_with_the_ledger_row_it_joined(tmp_path):
    ledger = [_ledger_row(triggered=True, status='settled', outcome='win',
                          execution_price=10.0, benefit_t1_pct=1.25,
                          trigger_session='2026-08-25')]

    retro = brief_preflight.compute_retrospective(_plan(tmp_path), PORTFOLIO, ledger)

    row = retro['decisions'][0]
    settled = ledger[0]['evaluation']
    assert (row['trigger_fired'], row['outcome'], row['execution_price'],
            row['benefit_t1_pct'], row['trigger_session']) == (
        settled['triggered'], settled['outcome'], settled['execution_price'],
        settled['benefit_t1_pct'], settled['trigger_session'])
    assert retro['confidence_calibration']['conf_80_100'] == '1/1'


def test_an_unsettled_decision_is_reported_as_unsettled_not_scored(tmp_path):
    """台账里没有这条 ⇒ 说「没有判词」，不许本函数自己补一个。"""
    retro = brief_preflight.compute_retrospective(_plan(tmp_path), PORTFOLIO, [])

    row = retro['decisions'][0]
    assert row['trigger_fired'] is None
    assert row['verdict_source'] == 'unsettled_no_ledger_row'
    # 计划侧的事实照常带着（判词缺失不等于这条 decision 不存在）。
    assert row['plan_trigger_price'] == 10.0
    assert row['plan_confidence'] == 0.9
    assert retro['confidence_calibration']['conf_80_100'] == 'n/a'


def test_a_ticker_that_left_the_portfolio_still_gets_its_verdict(tmp_path):
    """旧实现遇到「已不在持仓」直接 error 掉整行 —— 卖掉的票照样有判词要对账。"""
    empty = {'portfolios': {'us_stocks': {'holdings': []}, 'hk_stocks': {'holdings': []}}}

    retro = brief_preflight.compute_retrospective(
        _plan(tmp_path), empty,
        [_ledger_row(triggered=True, status='settled', outcome='loss',
                     execution_price=10.0, benefit_t1_pct=-2.0,
                     trigger_session='2026-08-25')],
    )

    row = retro['decisions'][0]
    assert row['still_held'] is False
    assert row['trigger_fired'] is True
    assert row['outcome'] == 'loss'
