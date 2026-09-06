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

Two of these tests exist because of mistakes made while writing the fix:

* `summary_view` is a hand-written per-field projection. A field added to
  `compile_packet` and not to it reaches nobody — the first version of this
  change did exactly that and looked complete.
* the packet was already at 95.7% of its hard ceiling with nothing warning,
  because the 2026-08-17 budget lesson had been applied to `MAX_SUMMARY_BYTES`
  and not to `MAX_PACKET_BYTES`.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

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


def test_the_packet_ceiling_warns_before_the_wall_like_the_summary_does(capsys):
    """#1349's own finding: the 2026-08-17 lesson stopped at the smaller budget.

    Overrunning `MAX_PACKET_BYTES` raises, and that raise is preflight failing —
    the morning brief with no packet at all. A warning that only arrives at the
    wall is the failure the summary already learned to precede.
    """
    assert packet_mod.PACKET_BUDGET_WARN_RATIO < 1.0
    ctx = copy.deepcopy(_context())
    real = packet_mod.MAX_PACKET_BYTES
    try:
        packet_mod.MAX_PACKET_BYTES = int(
            len(packet_mod._compact(packet_mod.compile_packet(ctx, generation_id="t"))
                .encode("utf-8")) / 0.9)
        packet_mod.compile_packet(ctx, generation_id="t")
    finally:
        packet_mod.MAX_PACKET_BYTES = real
    err = capsys.readouterr().err
    assert "of the" in err and "ceiling" in err, (
        f"a packet at 90% of its ceiling said nothing: {err!r}")


def test_the_warning_stays_quiet_with_room_to_spare(capsys):
    ctx = copy.deepcopy(_context())
    packet_mod.compile_packet(ctx, generation_id="t")
    assert "ceiling" not in capsys.readouterr().err
