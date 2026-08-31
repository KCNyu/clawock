"""A decision must be able to carry the debate that produced it (#1117).

The brief runs Bull, Bear, a named devil's-advocate attack and a Judge that has
to pick strategy frames — and then publishes a summary in which none of that is
separable. Measured before this change: every decision in a plan carried exactly
one prose `rationale`, so "we argued both sides" was an assertion about a
process, checkable by nobody outside the desk.

This is the first step of that issue and it is deliberately optional: the field
is written by a model inside the cron that must produce a brief every morning,
so a strict schema would buy structure by adding a new way for 08:00 to go red.
What these tests hold is that leniency does not become silence — the block is
normalized rather than rejected, and how often it is actually emitted is
published as a number.
"""
import json

from clawock.decision import ledger as dv2
from clawock.decision.actions import STRATEGY_FRAMES
from clawock.publish import dashboard


def authored(**over):
    row = {
        "ticker": "AAA", "action": "cut", "strategy_id": "core_position",
        "condition": {"type": "open"}, "confidence": 0.6,
        "driven_by": "technical", "size": {"shares": 1},
    }
    row.update(over)
    return row


def normalized(**over):
    row = dv2.legacy_action_to_decision(authored(**over), "2026-08-28")
    row["episode_id"] = "ep-test"
    return row


def test_a_decision_carries_the_debate_the_brief_already_ran():
    row = normalized(debate={
        "bull": "the position still has a catalyst ahead",
        "bear": "leverage decay eats the thesis before the catalyst lands",
        "attacked_consensus": "attacked the 'AI has another leg' consensus",
        "frames": ["technical_breakdown", "relative_strength"],
        "judge": "discipline first: policy trim does not wait for a prediction",
    })

    assert row["debate"]["bear"].startswith("leverage decay")
    assert row["debate"]["frames"] == ["technical_breakdown", "relative_strength"]
    assert dv2.validate_decision(row) == []


def test_a_plan_without_a_debate_block_is_still_valid_and_says_so():
    """Optional means optional — and absent must not read as an empty debate."""
    row = normalized()

    assert row["debate"] is None
    assert dv2.validate_decision(row) == []


def test_a_malformed_block_is_normalized_rather_than_failing_the_morning():
    """The one property that decides whether this is safe to ship at all.

    This field is model-written inside the 08:00 cron. Unknown keys, an
    over-long case, a frame that is not on the menu and a bare string where a
    list belongs must all normalize, because the alternative is a brief that
    does not go out.
    """
    row = normalized(debate={
        "bull": "  padded  ",
        "bear": "x" * 5000,
        "frames": "momentum",
        "judge": 42,
        "invented_field": "ignored",
        "attacked_consensus": "",
    })

    debate = row["debate"]
    assert debate["bull"] == "padded"
    assert len(debate["bear"]) == dv2.DEBATE_TEXT_CHARS
    assert debate["frames"] == ["momentum"], "a single frame may arrive unwrapped"
    assert "judge" not in debate, "a non-string value is dropped, not coerced"
    assert "invented_field" not in debate
    assert "attacked_consensus" not in debate, "an empty string is not a case"
    assert dv2.validate_decision(row) == []


def test_frames_outside_the_judges_menu_are_discarded():
    row = normalized(debate={"bear": "b", "frames": ["momentum", "vibes", "breakout"]})

    assert row["debate"]["frames"] == ["momentum", "breakout"]
    assert "vibes" not in STRATEGY_FRAMES


def test_a_debate_block_with_nothing_in_it_is_recorded_as_absent():
    """Otherwise an empty object inflates the coverage number it is measured by."""
    for empty in ({}, {"bull": "   "}, {"frames": ["nonsense"]}, "not a dict", None):
        assert dv2.normalize_debate(empty) is None


def test_a_hand_written_plan_with_an_unreadable_block_is_refused():
    """Leniency covers the model's output, which the normalizer has already seen.

    Anything reaching validation unnormalized came from a hand-edited or foreign
    plan, and there the right answer is to refuse rather than store a block no
    consumer can read.
    """
    row = normalized()

    row["debate"] = {"bear": ["not", "text"]}
    assert "debate.bear must be text" in dv2.validate_decision(row)

    row["debate"] = {"bear": "b", "smuggled": "x"}
    assert any("unknown debate field" in e for e in dv2.validate_decision(row))

    row["debate"] = {"bear": "b", "frames": ["vibes"]}
    assert any("strategy frames" in e for e in dv2.validate_decision(row))

    row["debate"] = {}
    assert "debate must be null or a non-empty object" in dv2.validate_decision(row)


def _plan(tmp_path, decisions):
    (tmp_path / "memory").mkdir(exist_ok=True)
    (tmp_path / "memory" / "2026-08-28-plan.json").write_text(
        json.dumps({"schema_version": 2, "date": "2026-08-28",
                    "decisions": decisions}), encoding="utf-8")


def test_the_dashboard_publishes_how_often_the_debate_was_actually_recorded(
        tmp_path, monkeypatch):
    """The number that keeps stage 1 honest.

    An optional field with no series behind it decays quietly. This one is
    counted per published plan, and the bear case is counted separately from
    "some block exists" — the losing side is the half a reader cannot otherwise
    check.
    """
    monkeypatch.setattr(dashboard, "WS_ROOT", tmp_path)
    _plan(tmp_path, [
        {"action": "cut", "debate": {"bear": "b", "attacked_consensus": "c",
                                     "frames": ["momentum"],
                                     "evidence_ids": ["news:evt_1"]}},
        {"action": "hold_and_watch", "debate": {"bull": "only one side"}},
        {"action": "watch"},
    ])

    coverage = dashboard.compute_debate_metrics()["debate_coverage"]

    # `with_evidence_ids` is the second-stage series (#1141): a debate that
    # cites nothing is counted apart from one that stands on named context,
    # the same way a missing bear case is counted apart from a missing block.
    assert coverage == {
        "decisions": 3, "with_debate": 2, "with_bear_case": 1,
        "with_attacked_consensus": 1, "with_frames": 1,
        "with_evidence_ids": 1,
        "bear_case_pct": 33.3,
    }


def test_the_page_prints_the_coverage_rather_than_only_the_verdict():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    js = (root / "site" / "assets" / "js" / "dashboard.render.js").read_text(
        encoding="utf-8")

    assert "debate_coverage" in js and "bear_case_pct" in js, (
        "decisiveness says what the debate concluded; nothing said whether the "
        "debate left anything to check")


def test_the_skill_documents_the_field_it_asks_the_model_to_emit():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    skill = (root / "skills" / "daily-deep-brief" / "SKILL.md").read_text(
        encoding="utf-8")

    assert '"debate"' in skill, "an undocumented field is never emitted"
    assert "attacked_consensus" in skill and "frames" in skill
    assert "debate_coverage" in skill, (
        "the model has to be told the omission is counted, not merely allowed")
