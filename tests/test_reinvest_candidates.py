"""A cut's ammunition gets a same-leg destination (#555).

The 08:00 plan used to end at "sell SPCH": the risk_rule cut never said what
the money was for. With the opportunity radar (#551) in place, the plan context
can carry up to two same-leg, un-flagged candidates so the prose can pair
"砍 X 的弹药 → 候选:Y". Candidates stay observations, never orders.
"""
from clawock.harness import intraday_preflight as P


def _radar_row(label, state="breakout", prior=100.0):
    return {'label': label, 'setup_id': f'opportunity:{state}', 'state': state,
            'state_zh': '机会·突破', 'holdings': [label],
            'close': 110.0, 'prior_20d_high': prior,
            'pct_from_high': 10.0, 'zscore20': 1.0}


def test_attach_pairs_up_to_two_unflagged_candidates():
    plan_ctx = {'open': [{'decision_id': 'd1', 'action': 'cut'}]}
    radar = {'rows': [_radar_row('00100', 'breakout', 374.4),
                      _radar_row('SKHY', 'near_breakout', 177.93),
                      _radar_row('CRCL', 'breakout', 75.89)]}

    out = P.attach_reinvest_candidates(plan_ctx, radar, [])

    assert out['reinvest_candidates'] == [
        {'ticker': '00100', 'state': 'breakout', 'trigger': '已突破'},
        {'ticker': 'SKHY', 'state': 'near_breakout', 'trigger': '突破前高 177.93'},
    ]
    assert len(out['reinvest_candidates']) == 2


def test_flagged_candidates_are_excluded():
    radar = {'rows': [_radar_row('SPCH'), _radar_row('SKHY')]}
    signals = [{'ticker': 'SPCH', 'level': 'STOP'}]

    out = P.attach_reinvest_candidates(
        {'open': [{'decision_id': 'd1', 'action': 'cut'}]}, radar, signals)

    tickers = [c['ticker'] for c in out['reinvest_candidates']]
    assert 'SPCH' not in tickers
    assert tickers == ['SKHY']


def test_clean_day_without_cut_returns_context_untouched():
    """#605: no open cut/trim decision → no ammunition to pair. Attaching
    candidates on a clean day would invite the model to invent a cut for the
    money (the pre-#605 test pinned the ungated behavior as correct)."""
    radar = {'rows': [_radar_row('00100', 'breakout', 374.4),
                      _radar_row('SKHY', 'near_breakout', 177.93)]}

    plan_ctx = {'open': [{'decision_id': 'd1', 'action': 'hold_and_watch'}]}
    assert P.attach_reinvest_candidates(plan_ctx, radar, []) is plan_ctx

    empty = {'open': []}
    assert P.attach_reinvest_candidates(empty, radar, []) is empty


def test_no_candidates_returns_context_untouched():
    plan_ctx = {'open': []}

    assert P.attach_reinvest_candidates(plan_ctx, {'rows': []}, []) is plan_ctx
    assert P.attach_reinvest_candidates(plan_ctx, None, []) is plan_ctx


def test_all_flagged_returns_context_untouched():
    radar = {'rows': [_radar_row('SPCH')]}
    signals = [{'ticker': 'SPCH', 'level': 'ALERT'}]

    assert P.attach_reinvest_candidates({'open': []}, radar, signals) == {'open': []}
