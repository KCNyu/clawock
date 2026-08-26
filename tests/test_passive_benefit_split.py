"""`followed` was measuring the market, not the advice (#1087).

`assets/data/decision_audit.json` on 2026-08-26, T+1:

    followed   n=107  win 32.7%  avg −1.86%  CI [−3.25, −0.62]

Read plainly: acting on the advice loses money, significantly. Read correctly:
`_benefit` gives a `hold_and_watch` the underlying's own move —

    advantage = -underlying if action in SELL_ACTIONS else underlying

— so a hold in a falling market scores a loss however right the hold was, and
103 of August's 166 decisions were holds on a book down 28–66%. Splitting the
column apart on the same data:

    passive          n=105  win 32.4%  avg −1.84%  CI [−3.23, −0.64]
    followed         n=107  win 32.7%  avg −1.86%  CI [−3.25, −0.62]
    followed_active  n=  6  win 33.3%  avg −6.42%  CI [−18.14, +2.20]

`followed` is `passive` plus six episodes. The significant negative was beta.
The question it looked like it answered has n=6 and a CI straddling zero.

A benchmark-relative benefit for the passive legs would be the richer fix and is
not available: `benchmark.json` keeps a 60-day window (from 2026-06-29) while the
episodes start 2026-05-17.
"""
from __future__ import annotations

import pytest

ledger = pytest.importorskip("clawock.decision.ledger")
actions = pytest.importorskip("clawock.decision.actions")


def _decision(idx, action, benefit, *, executed="followed"):
    return {
        "decision_id": f"dec-{idx}", "episode_id": f"ep-{idx}",
        "ticker": "AAA", "leg": "US", "strategy_id": "core_position",
        "action": action, "plan_date": f"2026-07-{(idx % 28) + 1:02d}",
        "created_at": f"2026-07-{(idx % 28) + 1:02d}T00:00:00+08:00",
        "size": {"shares": 1}, "confidence": 0.6,
        "execution": {"status": executed},
        # `triggered` is what `_episode_settled` filters on — a call that never
        # fired has no number to average.
        "evaluation": {"status": "settled", "triggered": True,
                       "outcome": "win" if benefit > 0 else "loss",
                       "benefit_t1_pct": benefit, "benefit_t5_pct": benefit},
    }


def _t1(decisions):
    return ledger.compute_backtest(decisions)["horizons"]["t1"]


def test_a_falling_market_no_longer_reads_as_bad_advice():
    """Ten holds in a −5% tape and two profitable cuts.

    Before the split the only executed-episode column mixed them and came out
    negative. `followed_active` asks the question the reader thought they were
    reading.
    """
    decisions = (
        [_decision(i, "hold_and_watch", -5.0) for i in range(10)]
        + [_decision(100 + i, "cut", +3.0) for i in range(2)]
    )
    t1 = _t1(decisions)

    assert t1["passive"]["n_episodes"] == 10
    assert t1["passive"]["avg_benefit_pct"] == pytest.approx(-5.0)
    assert t1["followed"]["n_episodes"] == 12, "unchanged: continuity for readers"
    assert t1["followed_active"]["n_episodes"] == 2
    assert t1["followed_active"]["avg_benefit_pct"] == pytest.approx(3.0), (
        "the cuts were right; the old column buried them under the tape")


def test_passive_and_active_partition_the_whole_record():
    decisions = (
        [_decision(i, "hold_and_watch", -1.0) for i in range(7)]
        + [_decision(50 + i, "cut", 1.0) for i in range(3)]
    )
    t1 = _t1(decisions)
    assert (t1["passive"]["n_episodes"] + t1["active"]["n_episodes"]
            == t1["all"]["n_episodes"])


def test_followed_active_is_a_subset_of_both_its_parents():
    decisions = (
        [_decision(i, "cut", 1.0) for i in range(4)]
        + [_decision(50 + i, "cut", 1.0, executed="not_followed") for i in range(3)]
        + [_decision(80 + i, "hold_and_watch", -1.0) for i in range(5)]
    )
    t1 = _t1(decisions)
    assert t1["followed_active"]["n_episodes"] == 4
    assert t1["followed_active"]["n_episodes"] <= t1["active"]["n_episodes"]
    assert t1["followed_active"]["n_episodes"] <= t1["followed"]["n_episodes"]


def test_every_column_says_what_it_measures():
    """The columns do not answer the same question and nothing said so.

    This is the half of the fix that is not arithmetic: a reader taking
    `followed` for "does the advice work" was not being careless, they were
    reading a name with no stated meaning.
    """
    t1 = _t1([_decision(0, "cut", 1.0)])
    measures = t1["measures"]
    assert set(measures) == {
        "all", "active", "passive", "followed", "followed_active"}
    assert "beta" in measures["passive"]
    assert "alpha" in measures["active"]
    for column in measures:
        assert column in t1, f"{column} is described but not published"


def test_the_passive_vocabulary_is_the_shared_one():
    """A local copy of the action set is the twin that drifts (#1089)."""
    import inspect
    source = inspect.getsource(ledger.compute_backtest)
    assert "PASSIVE_ACTIONS" in source
    assert actions.PASSIVE_ACTIONS == {"hold_and_watch", "watch"}
