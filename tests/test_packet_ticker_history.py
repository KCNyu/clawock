"""What this ticker's own past calls did, where the writer can read it (#1349).

`compute_reflections` has settled every episode for every held ticker each
morning — win rate, a per-bucket tally (`加×1 胜0; 持×15 胜9`), the last calls
and their realised benefit — and it went nowhere a decision could reach it.
SKILL.md Step 2 makes the packet summary the model's 唯一常驻输入; the packet
carried no per-ticker outcome history at all, so the process writing today's
call on CRCL could not see that its last 17 calls on CRCL won 59% and that the
one time it added, it lost.

Same shape as #1337: a signal that exists, is even on the dashboard, and has no
path into the process that writes decisions.

One of these tests exists because of a mistake made while writing the fix:
`summary_view` is a hand-written per-field projection. A field added to
`compile_packet` and not to it reaches nobody — the first version of this
change did exactly that and looked complete.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

from clawock.decision import packet as packet_mod

from test_brief_decision_packet import _context


REFLECTION = {
    "n": 17,
    "win_rate": 0.59,
    "bucket_history": "加×1 胜0; 持×15 胜9; watch×1 胜1",
    "recent": [{"date": "2026-09-01", "action": "hold_and_watch", "conf": 0.6,
                "outcome": "win", "benefit_pct": 2.2252}],
    "lesson": "LEVX: 过去 17 个策略 episode 胜率 59%（主动 call 多半没跑赢持有，本次谨慎）",
}


def _with_reflections(rows):
    ctx = copy.deepcopy(_context())
    ctx["reflections"] = rows
    return packet_mod.compile_packet(ctx, generation_id="test")


def _held(packet):
    return next(iter(packet["tickers"]))


def test_the_writer_can_see_how_its_past_calls_on_this_ticker_went():
    packet = _with_reflections({"LEVX": REFLECTION})
    history = packet["tickers"]["LEVX"]["history"]
    assert history["settled_episodes"] == 17
    assert history["win_rate"] == 0.59
    assert history["by_action"] == "加×1 胜0; 持×15 胜9; watch×1 胜1", (
        "the per-bucket tally is the part that answers 'what happened the times "
        "I added', which a single win rate cannot")


def test_history_reaches_the_summary_because_that_is_the_standing_input():
    """The regression that would make this whole change a no-op.

    `summary_view` names its per-ticker fields one by one. Wiring `history` into
    `compile_packet` alone leaves the model reading a summary without it.
    """
    packet = _with_reflections({"LEVX": REFLECTION})
    summary = packet_mod.summary_view(packet)
    rows = {row["ticker"]: row for row in summary["tickers"]}
    assert rows["LEVX"].get("history"), (
        "history is in the packet but not in summary_view — SKILL.md Step 2 calls "
        "the summary the model's 唯一常驻输入, so this reaches nobody")
    assert rows["LEVX"]["history"]["win_rate"] == 0.59


def test_the_pre_written_lesson_stays_out_of_the_model_facing_packet():
    """Code owns facts; the model owns the opinion overlay.

    `reflections[tk]['lesson']` is a finished sentence telling the reader what to
    conclude ("主动 call 多半没跑赢持有，本次谨慎"). Handing that to the model is the
    one thing this boundary exists to prevent — the numbers it came from are all
    projected, the conclusion is not.
    """
    packet = _with_reflections({"LEVX": REFLECTION})
    blob = json.dumps(packet, ensure_ascii=False)
    assert "本次谨慎" not in blob
    assert "lesson" not in packet["tickers"]["LEVX"]["history"]


def test_no_settled_history_is_stated_rather_than_omitted():
    """"Nothing to say yet" and "never wired in" must not look the same."""
    packet = _with_reflections({})
    history = packet["tickers"][_held(packet)]["history"]
    assert history == {"settled_episodes": 0}

def test_the_warning_stays_quiet_with_room_to_spare(capsys):
    ctx = copy.deepcopy(_context())
    packet_mod.compile_packet(ctx, generation_id="t")
    assert "ceiling" not in capsys.readouterr().err


def test_a_flat_episode_counts_in_the_ticker_win_rate_denominator(monkeypatch):
    """#3157: flat is a settled outcome, same as on the track-record card (#3154).

    Dropping it shrinks n and lifts the win rate the writer reads.
    """
    from clawock.harness import brief_preflight

    def row(day, outcome):
        return {"ticker": "LEVX", "plan_date": day, "action": "hold_and_watch",
                "evaluation": {"outcome": outcome}}

    rows = [row("2026-09-01", "win"), row("2026-09-02", "loss"), row("2026-09-03", "flat")]
    monkeypatch.setattr(brief_preflight.decision_v2, "load_decisions", lambda: rows)
    monkeypatch.setattr(brief_preflight.decision_v2, "episode_representatives", lambda rs, _h: rs)
    portfolio = {"portfolios": {
        "hk_stocks": {"holdings": []},
        "us_stocks": {"holdings": [{"ticker": "LEVX", "shares": 10}]},
    }}

    out = brief_preflight.compute_reflections(portfolio)["LEVX"]
    assert out["n"] == 3
    assert out["win_rate"] == 0.33
    assert out["bucket_history"] == "持×3 胜1"
    assert [r["outcome"] for r in out["recent"]] == ["win", "loss", "flat"]


def test_a_thin_ticker_bucket_sees_the_rest_of_the_books_base_rate(monkeypatch):
    """#3460: 07709's `cut` n=1 and SPCX's add n=2 cannot carry the base rate.

    The cross axis must exclude the ticker's own contribution and stay
    deterministic; it is context-only, not a new packet field.
    """
    from clawock.harness import brief_preflight

    def row(ticker, action, outcome, day):
        return {"ticker": ticker, "plan_date": day, "action": action,
                "evaluation": {"outcome": outcome}}

    rows = [
        # LEVX's own bucket: must not be counted in its cross row.
        row("LEVX", "add_only_on_trigger", "win", "2026-09-01"),
        # Other names: 3 wins / 2 losses on the same action.
        row("AAA", "add_only_on_trigger", "win", "2026-09-01"),
        row("BBB", "add_only_on_trigger", "win", "2026-09-02"),
        row("CCC", "add_only_on_trigger", "win", "2026-09-03"),
        row("DDD", "add_only_on_trigger", "loss", "2026-09-04"),
        row("EEE", "add_only_on_trigger", "loss", "2026-09-05"),
        # A different bucket with no cross sample is omitted.
        row("LEVX", "cut", "loss", "2026-09-06"),
    ]
    monkeypatch.setattr(brief_preflight.decision_v2, "load_decisions", lambda: rows)
    monkeypatch.setattr(brief_preflight.decision_v2, "episode_representatives",
                        lambda rs, _h: rs)
    portfolio = {"portfolios": {
        "hk_stocks": {"holdings": []},
        "us_stocks": {"holdings": [{"ticker": "LEVX", "shares": 10}]},
    }}

    out = brief_preflight.compute_reflections(portfolio)["LEVX"]
    assert out["cross_ticker"] == [{
        "action": "add_only_on_trigger", "n": 5, "win": 3, "win_rate": 0.6,
    }]
    assert "cut" not in {row["action"] for row in out["cross_ticker"]}


def test_a_sufficient_own_bucket_does_not_get_a_cross_row(monkeypatch):
    from clawock.harness import brief_preflight

    def row(ticker, action, outcome, day):
        return {"ticker": ticker, "plan_date": day, "action": action,
                "evaluation": {"outcome": outcome}}

    rows = [row("LEVX", "hold_and_watch", "win" if i % 2 else "loss",
                f"2026-09-{i + 1:02d}") for i in range(10)]
    rows += [row(t, "hold_and_watch", "win", "2026-10-01") for t in ("AAA", "BBB")]
    monkeypatch.setattr(brief_preflight.decision_v2, "load_decisions", lambda: rows)
    monkeypatch.setattr(brief_preflight.decision_v2, "episode_representatives",
                        lambda rs, _h: rs)
    portfolio = {"portfolios": {
        "hk_stocks": {"holdings": []},
        "us_stocks": {"holdings": [{"ticker": "LEVX", "shares": 10}]},
    }}
    assert "cross_ticker" not in brief_preflight.compute_reflections(portfolio)["LEVX"]
