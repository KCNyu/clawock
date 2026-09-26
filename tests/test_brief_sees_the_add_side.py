"""The process that writes decisions must be able to see an add.

Between 2026-07-20 and 2026-09-05 the bar store held 48 close-confirmed
breakouts across 18 names and the ledger recorded zero `add_only_on_trigger`
decisions. Nothing was broken in the usual sense: every test passed, the cron
was green, the intraday slot even printed `candidate` rows. The brief context —
the only input the model that writes decisions ever reads — carried 34 fields,
and every one of them described risk or state. `risk_rule`, which gets an
explicit "cut N shares" input, wrote 135 cuts at mean confidence 0.81;
`catalyst`/`macro`/`sentiment`/`peer` wrote `hold_and_watch` 145 times out of
148, because there was no shape in that context for anything else.

So the assertions here are not about arithmetic. They are: the brief can see a
breakout, it says why when it sees none, and the two readers of "where is this
name against its 20-day high" cannot drift apart.
"""
from __future__ import annotations

import json

import pytest

from clawock.decision import add_side


NEAR, NOCHASE = 5.0, 2.0


def _signals(close, prior, z=0.0):
    return {"close": close, "prior_20d_high": prior, "zscore20": z}


def test_a_settled_breakout_is_a_candidate_the_brief_can_act_on():
    radar = add_side.daily_radar({"CRCL": _signals(103.23, 96.40, z=0.9)},
                                 near_pct=NEAR, no_chase_z=NOCHASE)
    reads = add_side.read_rows(radar=radar, levels=radar["levels"],
                               close_confirmed=True)

    assert reads["candidate_count"] == 1, (
        "a close above the prior 20-day high is the one add shape #819 measured "
        "an edge on; if it cannot reach a candidate the add side is unreachable")
    row = reads["rows"][0]
    assert row["ticker"] == "CRCL" and row["verdict"] == "candidate"
    assert "收盘确认" in row["why"], (
        "the brief reads settled closes; quoting the intraday wording would "
        "claim a confirmation the intraday slot explicitly does not have")


def test_the_intraday_wording_still_says_the_close_is_pending():
    radar = add_side.daily_radar({"CRCL": _signals(103.23, 96.40, z=0.9)},
                                 near_pct=NEAR, no_chase_z=NOCHASE)
    reads = add_side.read_rows(radar=radar, levels=radar["levels"])
    assert "收盘未确认" in reads["rows"][0]["why"]


def test_an_unexecuted_discipline_action_still_blocks_the_add():
    """The rule that made the sell-only stream self-reinforcing, kept on purpose.

    Since kcn 2026-09-25 it blocks by downgrading (wait, with the reason), not
    by rejecting; a candidate still cannot come out of it."""
    radar = add_side.daily_radar({"CRCL": _signals(103.23, 96.40, z=0.9)},
                                 near_pct=NEAR, no_chase_z=NOCHASE)
    plan = {"open": [{"ticker": "CRCL", "driven_by": "risk_rule",
                      "action": "cut", "shares": 300}]}
    reads = add_side.read_rows(radar=radar, levels=radar["levels"],
                               plan_context=plan, close_confirmed=True)
    assert reads["rows"][0]["verdict"] == "wait" and reads["candidate_count"] == 0
    assert reads["discipline_downgraded_count"] == 1
    assert "纪律动作未了结" in reads["rows"][0]["why"]


@pytest.mark.parametrize("z,state", [(0.5, "breakout"), (2.96, "wait_rebreak")])
def test_the_no_chase_filter_is_what_separates_a_breakout_from_a_chase(z, state):
    """ROBN on 2026-09-03: 40.82 over a 34.20 high, demoted by z=2.96.

    Pinned because it is the second gate, and the one that produced zero
    candidates on a day with three real breakouts. Whether 2.0 is the right
    number is kcn's call; that the answer turns on this comparison is not.
    """
    radar = add_side.daily_radar({"ROBN": _signals(40.82, 34.20, z=z)},
                                 near_pct=NEAR, no_chase_z=NOCHASE)
    assert radar["rows"][0]["state"] == state


def test_both_readers_build_the_same_radar_from_the_same_signals(tmp_path, monkeypatch):
    """The intraday slot and the brief must not disagree about the same name.

    Behavioural parity, not a source search: hand the intraday collector a
    universe whose bars resolve to fixed signals, hand the brief's builder the
    same signals, and the rows and levels must be identical. A second copy of
    the comparisons is how a slot and a brief end up telling kcn different
    things about CRCL on the same afternoon.
    """
    from clawock.harness import intraday_preflight as P

    sigs = {
        "BO": {"close": 110.0, "prior_20d_high": 100.0, "zscore20": 1.0, "prior_5d_low": 101.0},
        "WB": {"close": 110.0, "prior_20d_high": 100.0, "zscore20": 2.5, "prior_5d_low": 99.0},
        "NEAR": {"close": 98.0, "prior_20d_high": 100.0, "zscore20": 0.5, "prior_5d_low": 95.0},
        "FAR": {"close": 80.0, "prior_20d_high": 100.0, "zscore20": -1.0, "prior_5d_low": 79.0},
    }
    holdings = {"BO": ["BO", "BO2X"], "WB": ["WB"], "NEAR": ["NEAR"], "FAR": ["FAR"]}
    monkeypatch.setattr(P, "WS", tmp_path)
    monkeypatch.setattr(P.quant_signals, "universe_details", lambda errors=None: [
        {"label": label, "code": label, "region": "HK", "source_holdings": holdings[label]}
        for label in sigs])
    monkeypatch.setattr(P, "_fetch_bars_cached", lambda code, cnt: code)
    monkeypatch.setattr(P.quant_signals, "compute_signals", lambda code: sigs[code])

    slot = P.collect_opportunity_radar("hk")
    brief = add_side.radar(sigs, holdings_of=holdings, near_pct=NEAR, no_chase_z=NOCHASE,
                           confirmed_at_close=True)

    assert slot["rows"] == brief["rows"]
    assert slot["levels"] == brief["levels"]
    assert [row["state"] for row in slot["rows"]] == ["breakout", "wait_rebreak", "near_breakout"]


def test_the_entries_differ_only_in_how_sure_the_close_is():
    """Same radar, same plans, same policy: identical verdicts from both entries.

    `add_policy.ENTRY_PROFILES` is the only place the two entries are allowed to
    differ; for `read_rows` that is `close_confirmed`, which changes wording and
    nothing else.
    """
    from clawock.decision import add_policy

    radar = add_side.radar({"CRCL": _signals(110.0, 100.0, z=1.0),
                            "RKLB": _signals(97.0, 100.0, z=0.2)},
                           holdings_of={"RKLB": ["RKLB", "RKLX"]},
                           near_pct=NEAR, no_chase_z=NOCHASE)
    policy = json.loads(open("config/add-alpha-policy.json").read())
    out = {}
    for entry in ("brief", "intraday"):
        profile = add_policy.entry_profile(entry)
        out[entry] = add_side.read_rows(
            radar=radar, levels=radar["levels"], plan_context={"open": []},
            close_confirmed=profile["close_confirmed"], leveraged={"RKLX"},
            policy=policy)

    def verdicts(read):
        return [(r["ticker"], r["verdict"], r["kind"], r["needs"], r["evidence"])
                for r in read["rows"]]

    assert verdicts(out["brief"]) == verdicts(out["intraday"])
    assert out["brief"]["confirmed_at_close"] and not out["intraday"]["confirmed_at_close"]
    assert "收盘确认" in out["brief"]["rows"][0]["why"]
    assert "收盘未确认" in out["intraday"]["rows"][0]["why"]


def test_the_brief_context_carries_the_add_side_and_explains_an_empty_one(tmp_path, monkeypatch):
    """An empty add side must be an answer, not an absence.

    The silent version of this is what "为什么建议都是卖出" actually was.
    """
    from clawock.harness import brief_preflight

    bars = tmp_path / "memory" / "bars"
    bars.mkdir(parents=True)
    # Deep inside its range: no read at all, so the reason must fall through to
    # the level report rather than claiming discipline or overheating.
    # compute_signals needs 30 closes before it answers at all.
    day_rows = {f"2026-07-{d:02d}": {"open": 10.0, "high": 10.0, "low": 9.0, "close": 9.0}
                for d in range(1, 32)}
    day_rows.update({f"2026-08-{d:02d}": {"open": 10.0, "high": 10.0, "low": 9.0, "close": 9.0}
                     for d in range(1, 29)})
    day_rows["2026-08-29"] = {"open": 5.0, "high": 5.1, "low": 4.9, "close": 5.0}
    (bars / "SLEEPY.json").write_text(json.dumps({"ticker": "SLEEPY", "bars": day_rows}))
    monkeypatch.setattr(brief_preflight, "WS", tmp_path)

    read = brief_preflight._opportunity_reads({"open": []})

    assert read["counts"] == {"candidate": 0, "wait": 0, "reject": 0}
    assert read["why_no_candidate"], "a zero add side with no stated reason is the bug"
    assert "前 20 日高" in read["why_no_candidate"]
    assert read["levels"], "the level that would settle the question must be quotable"


def test_a_breakout_in_the_bar_store_reaches_the_brief_context(tmp_path, monkeypatch):
    """The 48-breakouts-zero-adds failure, reproduced end to end.

    The series oscillates rather than sitting flat on purpose: a flat run with
    one jump has a tiny standard deviation, so the jump scores z>4 and the
    no-chase filter correctly calls it a chase. A breakout that is *not* a
    chase needs the range to be real — which is also why the fixture is the
    honest one to pin.
    """
    from clawock.harness import brief_preflight

    bars = tmp_path / "memory" / "bars"
    bars.mkdir(parents=True)
    rows = {}
    for i in range(40):
        close = 9.5 + (1.0 if i % 2 else 0.0)
        rows[f"2026-{7 + i // 31:02d}-{i % 31 + 1:02d}"] = {
            "open": close, "high": close + 0.1, "low": close - 0.1, "close": close}
    rows["2026-09-01"] = {"open": 10.7, "high": 11.0, "low": 10.6, "close": 10.9}
    (bars / "BREAK.json").write_text(json.dumps({"ticker": "BREAK", "bars": rows}))
    monkeypatch.setattr(brief_preflight, "WS", tmp_path)

    read = brief_preflight._opportunity_reads({"open": []})

    assert read["counts"]["candidate"] == 1, (
        "the brief cannot see a breakout its own bar store holds — this is the "
        "48-breakouts-zero-adds failure, reproduced")
    assert read["why_no_candidate"] is None
    assert read["rows"][0]["ticker"] == "BREAK"
