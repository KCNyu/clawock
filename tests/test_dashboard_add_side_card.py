"""The dashboard has to be able to answer "why is there no add today".

For 47 days the book produced sell-only advice and the dashboard showed it
without any way to ask why. The answer was never missing — it was in three
places nobody looked: the evidence families' activation counters, the add-side
read in the brief context, and #856's shape study, which had no durable artifact
at all until `evaluate-add-shapes` (#1341).

This card projects all three. The assertions are about that word: every number
is copied from the brief context or an `add_shapes` run card, because a second
computation of the same quantity in the publish layer is how a dashboard and a
brief end up telling kcn different things on the same morning.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from clawock.publish import dashboard

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
RENDER = (ROOT / "site" / "assets" / "js" / "dashboard.render.js").read_text(encoding="utf-8")
CSS = (ROOT / "site" / "assets" / "css" / "dashboard.css").read_text(encoding="utf-8")


CONTEXT = {
    "date": "2026-09-05",
    "opportunity": {
        "counts": {"candidate": 0, "wait": 9, "reject": 1},
        "why_no_candidate": "3 只已收盘站上前 20 日高，但 z≥2 判为追高",
        "policy": "技术突破…",
        "rows": [
            {"ticker": "CRCL", "verdict": "wait", "why": "窗口内无一手公告",
             "needs": "站上 96.4", "evidence": {"prior_20d_high": 96.4,
                                                "pct_from_high": -7.09}},
            {"ticker": "SPCH", "verdict": "reject", "why": "纪律动作未了结",
             "needs": "先把纪律动作走完", "evidence": {}},
        ],
    },
    "add_alpha_activation": {
        "cold_start": True,
        "families": {
            "price_relative_factor": {
                "active": False,
                "progress": {"prospective_dates": [8, 24],
                             "membership_history": [False, True]},
                "blockers": ["prospective_dates", "clustered_edge"]},
            "point_in_time_information": {
                "active": False, "progress": {"history_dates": [16, 24]},
                "blockers": ["history_dates"]},
        },
    },
    "action_track_record": {"by_action": {
        "cut": {"win": 112, "loss": 101, "settled": 213, "hit_rate": 0.5258},
        "hold_and_watch": {"win": 158, "loss": 216, "settled": 376, "hit_rate": 0.42},
    }},
}

CARD = {
    "run_id": "add_shapes-20260905-deadbeef",
    "metrics": {
        "names": 25,
        "shapes": {
            "breakout": {"t20": {"n": 84, "hit_rate": 0.655, "mean_pct": 20.06}},
            "pullback_in_uptrend": {"t20": {"n": 313, "hit_rate": 0.383, "mean_pct": 3.99}},
        },
        "baseline": {"t20": {"n": 2660, "hit_rate": 0.501, "mean_pct": 5.24}},
    },
}


@pytest.fixture()
def projected(tmp_path, monkeypatch):
    cards = tmp_path / "backtests"
    cards.mkdir()
    (cards / "add_shapes-20260905-deadbeef.json").write_text(json.dumps(CARD))
    monkeypatch.setattr(dashboard, "_latest_brief_context",
                        lambda: ("brief-context-2026-09-05.json", CONTEXT))
    return dashboard.compute_add_side(shape_cards_dir=cards)


def test_it_projects_the_brief_context_rather_than_recomputing_it(projected):
    assert projected["counts"] == {"candidate": 0, "wait": 9, "reject": 1}
    assert projected["why_no_candidate"] == CONTEXT["opportunity"]["why_no_candidate"], (
        "the reason is the whole point of the card and must arrive verbatim")
    assert projected["cold_start"] is True
    assert projected["pending"] is False


def test_a_family_carries_the_counter_it_is_waiting_on_and_never_a_flag(projected):
    """`membership_history: [False, True]` is a pass/fail, not a countdown.

    `isinstance(False, int)` is True, so a naive filter renders it as
    "membership_history 0/1" — a progress bar for something that cannot progress.
    """
    factor = next(row for row in projected["families"]
                  if row["name"] == "price_relative_factor")
    assert factor["progress"] == {"counter": "prospective_dates", "have": 8, "need": 24}
    assert factor["active"] is False


def test_the_shape_study_comes_from_a_run_card_so_it_stays_re_derivable(projected):
    study = projected["shapes"]
    assert study["run_id"] == "add_shapes-20260905-deadbeef", (
        "without the run id the numbers on the page cannot be traced to the run "
        "that produced them — the exact failure #1341 exists to prevent")
    assert study["shapes"]["breakout"]["t20"] == [84, 0.655, 20.06]
    assert study["baseline"]["t20"] == [2660, 0.501, 5.24], (
        "the baseline row is what makes every other row mean anything")


def test_only_the_action_kinds_this_card_is_about_are_carried(projected):
    """Payload budget: the card shows the add side, not the whole ledger."""
    assert set(projected["track_record"]) <= {
        "cut", "trim_on_rebound", "add_only_on_trigger"}
    assert "hold_and_watch" not in projected["track_record"]


def test_a_context_from_before_the_add_side_shipped_says_so(monkeypatch, tmp_path):
    """An empty card that looks broken is worse than one that says "not yet"."""
    monkeypatch.setattr(dashboard, "_latest_brief_context", lambda: (None, {"date": "2026-09-04"}))
    projected = dashboard.compute_add_side(shape_cards_dir=tmp_path)

    assert projected["pending"] is True
    assert projected["counts"] == {}


def test_the_projection_stays_small_enough_for_the_payload(projected):
    """186KB of a 200KB cap was already spent when this card was added."""
    size = len(json.dumps(projected, ensure_ascii=False).encode("utf-8"))
    assert size < 4000, f"the add-side projection grew to {size} bytes"


def test_the_card_is_wired_from_markup_to_renderer_to_stylesheet():
    assert 'id="add-side-card"' in INDEX and 'id="add-side-body"' in INDEX
    assert re.search(r"plan:\s*\[\s*renderAddSide", RENDER), (
        "the renderer exists but the plan tab never calls it")
    assert '.add-family-bar' in CSS and '.add-baseline' in CSS


def test_the_card_never_computes_the_numbers_it_shows():
    """A browser-side recomputation is a second answer to the same question."""
    body = RENDER[RENDER.index("function renderAddSide"):
                  RENDER.index("function renderWatchLevels")]
    for forbidden in ("prior_20d_high >", "Math.max(", "reduce("):
        assert forbidden not in body, (
            f"renderAddSide grew its own arithmetic ({forbidden}); the numbers "
            "belong to the brief context and the run card")
