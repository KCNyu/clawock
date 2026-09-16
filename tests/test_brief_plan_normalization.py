"""Regression coverage for brief plan normalization before validation."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
from clawock.harness import brief_postflight  # noqa: E402


def _authored_decision(**updates):
    decision = {
        "ticker": "AAA",
        "strategy_id": "risk_rebalance",
        "action": "cut",
        "condition": {
            "type": "manual",
            "price": None,
            "description": "risk rule",
        },
        "size": {"shares": 1, "pct": None, "note": ""},
        "confidence": 0.8,
        "driven_by": "risk_rule",
        "evidence_event_id": None,
        "regime": "neutral",
        "rationale": "reduce exposure",
    }
    decision.update(updates)
    return decision


def _write_authored_plan(tmp_path, decision):
    path = tmp_path / "2026-07-30-plan.json"
    path.write_text(json.dumps({
        "schema_version": 2,
        "date": "2026-07-30",
        "decisions": [decision],
    }))
    return path


def test_machine_owned_fields_are_normalized_before_validation(tmp_path):
    path = _write_authored_plan(tmp_path, _authored_decision())
    ledger = tmp_path / "decisions.jsonl"

    assert brief_postflight.normalize_plan_json(path, ledger) == []

    normalized = json.loads(path.read_text())
    decision = normalized["decisions"][0]
    assert decision["decision_id"].startswith("dec-")
    assert decision["episode_id"].startswith("ep-")
    assert decision["plan_date"] == "2026-07-30"
    assert decision["created_at"] == "2026-07-30T08:00:00+08:00"
    assert brief_postflight.validate_plan_json(path) == []


def test_packet_provenance_overwrites_authored_claim(tmp_path):
    path = _write_authored_plan(tmp_path, _authored_decision(
        signal_provenance={"information": {"signed_score": 999}},
    ))
    packet = {
        "_meta": {"generation_id": "gen-real"},
        "generated_at": "2026-07-30T08:00:00+08:00",
        "tickers": {"AAA": {
            "information": {"signed_score": -0.2},
            "quant": {"factor": {}, "peer_residual": {}},
            "execution": {"information_overlay": {
                "sizing_multiplier": 0.6,
                "contributors": ["information_negative_or_low_rank"],
            }},
            "constraints": {"max_add_shares": 0, "position_room_shares": 0},
        }},
    }

    assert brief_postflight.normalize_plan_json(
        path, tmp_path / "decisions.jsonl", decision_packet=packet
    ) == []
    provenance = json.loads(path.read_text())["decisions"][0]["signal_provenance"]
    assert provenance["context_generation_id"] == "gen-real"
    assert provenance["information"]["signed_score"] == -0.2


def test_semantic_authoring_error_is_not_rewritten_into_a_valid_default(tmp_path):
    path = _write_authored_plan(
        tmp_path,
        _authored_decision(condition={"type": "not-a-real-trigger"}),
    )

    issues = brief_postflight.normalize_plan_json(
        path, tmp_path / "decisions.jsonl"
    )

    assert any("bad condition.type" in issue for issue in issues)
    assert json.loads(path.read_text())["decisions"][0]["condition"] == {
        "type": "not-a-real-trigger"
    }


def test_harness_constraint_still_fails_after_normalization(tmp_path):
    path = _write_authored_plan(
        tmp_path,
        _authored_decision(action="add_only_on_trigger"),
    )
    packet = {
        "tickers": {
            "AAA": {
                "constraints": {
                    "allowed_actions": ["cut"],
                    "actionable_evidence_ids": [],
                    "max_sell_shares": 1,
                }
            }
        }
    }

    assert brief_postflight.normalize_plan_json(
        path, tmp_path / "decisions.jsonl"
    ) == []
    issues = brief_postflight.validate_plan_json(
        path, decision_packet=packet
    )
    assert any(
        "plan.json harness" in issue and "outside harness allowed_actions" in issue
        for issue in issues
    )
    assert brief_postflight.categorize(issues) == "fail"


def test_packet_approved_technical_tactical_add_passes_postflight(tmp_path):
    decision = _authored_decision(
        ticker="00100", strategy_id="tactical_entry",
        action="add_only_on_trigger", driven_by="technical",
        condition={"type": "price_above", "price": 11, "description": "reclaim"},
        size={"shares": 20, "pct": None, "note": "one board lot"},
        technical_setup_id="trend_pullback",
        technical_campaign_id="trend_pullback:2026-07-30",
        invalidation_price=9.5, tranche_number=1,
    )
    path = _write_authored_plan(tmp_path, decision)
    packet = {"tickers": {"00100": {
        "technical": {"setups": [{
            "setup_id": "trend_pullback",
            "campaign_id": "trend_pullback:2026-07-30",
            "entry_type": "price_above", "entry_price": 11,
            "invalidation_price": 9.5, "next_tranche_number": 1,
        }]},
        "constraints": {
            "allowed_actions": ["add_only_on_trigger"],
            "technical_setup_ids": ["trend_pullback"],
            "actionable_evidence_ids": [], "max_sell_shares": 100,
            "max_add_shares": 40, "lot_size": 20,
        },
    }}}

    assert brief_postflight.normalize_plan_json(
        path, tmp_path / "decisions.jsonl"
    ) == []
    assert brief_postflight.validate_plan_json(
        path, decision_packet=packet
    ) == []


def test_free_text_technical_add_without_packet_is_rejected(tmp_path):
    path = _write_authored_plan(tmp_path, _authored_decision(
        strategy_id="tactical_entry", action="add_only_on_trigger",
        driven_by="technical", technical_setup_id="trend_pullback",
        technical_campaign_id="trend_pullback:2026-07-30",
        invalidation_price=9.5, tranche_number=1,
    ))
    assert brief_postflight.normalize_plan_json(
        path, tmp_path / "decisions.jsonl"
    ) == []

    issues = brief_postflight.validate_plan_json(path)

    assert any("catalyst-gate" in issue for issue in issues)


def test_normalization_failure_is_fail_closed(tmp_path, monkeypatch):
    path = _write_authored_plan(tmp_path, _authored_decision())

    def fail_normalization(*_args, **_kwargs):
        raise ValueError("broken ledger")

    monkeypatch.setattr(
        brief_postflight.decision_v2,
        "normalize_authored_plan",
        fail_normalization,
    )
    issues = brief_postflight.normalize_plan_json(
        path, tmp_path / "decisions.jsonl"
    )

    assert issues == ["plan.json 标准化失败: broken ledger"]
    assert brief_postflight.categorize(issues) == "fail"


def _filled_judgment(generation_id="generation-fixture", tickers=()):
    """A judgment that passes validation, so postflight's gap check stays quiet.

    Since #1232 the report is rendered from the judgment, so an absent one is a
    reported issue (`_judgment_gap_issues`). These fixtures are about the plan
    and publication paths, not about that check, and they should not go quiet by
    accident.
    """
    from clawock.decision.packet import judgment_template

    overlay = judgment_template({
        "_meta": {"generation_id": generation_id},
        "tickers": {ticker: {} for ticker in tickers},
    })
    overlay["portfolio_assessment"] = "fixture assessment"
    overlay["portfolio_counterargument"] = "fixture counterargument"
    for field, value in list(overlay["narrative"].items()):
        if field == "risk_voice_first":
            continue
        overlay["narrative"][field] = (
            ["fixture step"] if isinstance(value, list) else "fixture text")
    for row in overlay["ticker_judgments"]:
        for field, value in list(row.items()):
            if value == "":
                row[field] = "fixture text"
    return overlay


def test_main_normalizes_before_calling_plan_validation(tmp_path, monkeypatch):
    # Freeze the HKT consumer and its fixture together, independent of host TZ.
    today = "2026-09-14"
    monkeypatch.setattr(brief_postflight.trading_calendar, "hkt_today",
                        lambda: date.fromisoformat(today))
    plan_path = tmp_path / "memory" / f"{today}-plan.json"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(json.dumps({
        "schema_version": 2,
        "date": today,
        "decisions": [_authored_decision()],
    }))
    # A present-but-minimal context: postflight fails closed without one, and
    # this test exercises plan normalization, not the context gate.
    ctx_dir = tmp_path / "memory" / ".tmp"
    ctx_dir.mkdir()
    (ctx_dir / f"brief-context-{today}.json").write_text("{}")
    (ctx_dir / f"brief-judgment-{today}.json").write_text(
        json.dumps(_filled_judgment(), ensure_ascii=False))
    observed = {}

    def assert_normalized(path, **_kwargs):
        decision = json.loads(path.read_text())["decisions"][0]
        observed["decision_id"] = decision["decision_id"]
        observed["episode_id"] = decision["episode_id"]
        return []

    monkeypatch.setattr(brief_postflight, "WS", tmp_path)
    # The degradation ledger resolves its path at call time, so the
    # module attribute above is not enough: without this a postflight
    # run from a test writes into the developer's own workspace (#816).
    monkeypatch.setenv("CLAWOCK_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(
        brief_postflight.trading_calendar, "closed_reason", lambda _market: None
    )
    monkeypatch.setattr(
        brief_postflight.workflow_outcomes, "slot_for_job", lambda _job: "slot"
    )
    monkeypatch.setattr(
        brief_postflight.workflow_outcomes, "record_stage", lambda *_a, **_k: None
    )
    monkeypatch.setattr(brief_postflight, "validate_markdown", lambda *_a, **_k: [])
    monkeypatch.setattr(brief_postflight, "validate_plan_json", assert_normalized)
    monkeypatch.setattr(brief_postflight, "already_delivered", lambda _path: True)
    monkeypatch.setattr(sys, "argv", ["brief_postflight.py", "--dry-run"])

    assert brief_postflight.main() == 0
    assert observed["decision_id"].startswith("dec-")
    assert observed["episode_id"].startswith("ep-")


def test_dry_run_validates_normalized_plan_without_rewriting_source(
    tmp_path, monkeypatch
):
    # Freeze the HKT consumer and its fixture together, independent of host TZ.
    today = "2026-09-14"
    monkeypatch.setattr(brief_postflight.trading_calendar, "hkt_today",
                        lambda: date.fromisoformat(today))
    plan_path = tmp_path / "memory" / f"{today}-plan.json"
    plan_path.parent.mkdir(parents=True)
    authored = json.dumps({
        "schema_version": 2,
        "date": today,
        "decisions": [_authored_decision()],
    })
    plan_path.write_text(authored)
    # Present-but-minimal context: postflight fails closed without one.
    ctx_dir = tmp_path / "memory" / ".tmp"
    ctx_dir.mkdir(parents=True, exist_ok=True)
    (ctx_dir / f"brief-context-{today}.json").write_text("{}")
    (ctx_dir / f"brief-judgment-{today}.json").write_text(
        json.dumps(_filled_judgment(), ensure_ascii=False))
    before_mtime = plan_path.stat().st_mtime_ns
    observed = {}
    validate = brief_postflight.validate_plan_json

    def capture_validation(path, **kwargs):
        decision = json.loads(path.read_text())["decisions"][0]
        observed["decision_id"] = decision["decision_id"]
        observed["issues"] = validate(path, **kwargs)
        return observed["issues"]

    monkeypatch.setattr(brief_postflight, "WS", tmp_path)
    # The degradation ledger resolves its path at call time, so the
    # module attribute above is not enough: without this a postflight
    # run from a test writes into the developer's own workspace (#816).
    monkeypatch.setenv("CLAWOCK_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(
        brief_postflight.trading_calendar, "closed_reason", lambda _market: None
    )
    monkeypatch.setattr(
        brief_postflight.workflow_outcomes, "slot_for_job", lambda _job: "slot"
    )
    monkeypatch.setattr(
        brief_postflight.workflow_outcomes, "record_stage", lambda *_a, **_k: None
    )
    monkeypatch.setattr(brief_postflight, "validate_markdown", lambda *_a, **_k: [])
    monkeypatch.setattr(
        brief_postflight, "validate_plan_json", capture_validation
    )
    monkeypatch.setattr(brief_postflight, "already_delivered", lambda _path: True)
    monkeypatch.setattr(sys, "argv", ["brief_postflight.py", "--dry-run"])

    assert brief_postflight.main() == 0
    assert observed["decision_id"].startswith("dec-")
    assert observed["issues"] == []
    assert plan_path.read_text() == authored
    assert plan_path.stat().st_mtime_ns == before_mtime


def _ledger_row(plan_date, decision_id, episode_id, ticker="AAA"):
    return {
        "schema_version": 2, "decision_id": decision_id,
        "episode_id": episode_id, "plan_date": plan_date,
        "created_at": f"{plan_date}T08:00:00+08:00", "ticker": ticker,
        "strategy_id": "risk_rebalance", "action": "cut",
        "condition": {"type": "manual", "price": None},
    }


def test_model_typed_ids_do_not_split_a_running_episode(tmp_path):
    # 2026-09-11: after a failed first postflight listed "missing
    # decision_id / episode_id", the model typed `ep-20260911-07226-cut` and
    # the ledger kept it — a cut thesis running since 09-04 became a new,
    # independently scored episode. Continuity is the ledger's call.
    ledger = tmp_path / "decisions.jsonl"
    ledger.write_text(json.dumps(
        _ledger_row("2026-07-29", "dec-aaaaaaaaaaaa", "ep-bbbbbbbbbbbb")) + "\n")
    path = _write_authored_plan(tmp_path, _authored_decision(
        decision_id="dec-pending-aaa-20260730",
        episode_id="ep-20260730-aaa-cut",
    ))

    assert brief_postflight.normalize_plan_json(path, ledger) == []

    decision = json.loads(path.read_text())["decisions"][0]
    assert decision["episode_id"] == "ep-bbbbbbbbbbbb"
    assert decision["decision_id"] != "dec-pending-aaa-20260730"
    assert decision["decision_id"].startswith("dec-")


def test_copied_decision_id_cannot_overwrite_yesterdays_row(tmp_path):
    # The upsert is keyed on decision_id: yesterday's id, copied forward,
    # would rewrite yesterday's row with today's plan_date.
    ledger = tmp_path / "decisions.jsonl"
    ledger.write_text(json.dumps(
        _ledger_row("2026-07-29", "dec-aaaaaaaaaaaa", "ep-bbbbbbbbbbbb")) + "\n")
    path = _write_authored_plan(
        tmp_path, _authored_decision(decision_id="dec-aaaaaaaaaaaa"))

    assert brief_postflight.normalize_plan_json(path, ledger) == []

    assert json.loads(path.read_text())["decisions"][0]["decision_id"] \
        != "dec-aaaaaaaaaaaa"


def test_rerun_over_own_output_keeps_its_decision_id(tmp_path):
    # A second postflight on the same day reads the plan the first one wrote
    # back and committed; keeping that id is what makes the upsert an update.
    ledger = tmp_path / "decisions.jsonl"
    path = _write_authored_plan(tmp_path, _authored_decision())
    assert brief_postflight.normalize_plan_json(path, ledger) == []
    first = json.loads(path.read_text())
    brief_postflight.decision_v2.upsert_plan_decisions(first, path=ledger)

    # The model edits the condition after the first run; the id stays.
    first["decisions"][0]["condition"]["description"] = "edited"
    path.write_text(json.dumps(first))
    assert brief_postflight.normalize_plan_json(path, ledger) == []

    again = json.loads(path.read_text())["decisions"][0]
    assert again["decision_id"] == first["decisions"][0]["decision_id"]
    assert again["episode_id"] == first["decisions"][0]["episode_id"]


def test_skipped_normalization_does_not_ask_the_model_for_ids(tmp_path):
    # With a semantic error, normalization is skipped and the file lacks every
    # machine-owned field. Listing those (48 of 62 issues on 2026-09-11) is
    # what sent the model off to invent ids.
    path = _write_authored_plan(tmp_path, _authored_decision(action="bogus"))
    ledger = tmp_path / "decisions.jsonl"

    semantic = brief_postflight.normalize_plan_json(path, ledger)
    assert semantic and all("plan.json authored" in i for i in semantic)

    issues = brief_postflight.validate_plan_json(path, normalized=False)
    assert not any(
        field in issue
        for issue in issues
        for field in ("decision_id", "episode_id", "plan_date",
                      "created_at", "schema_version must be 2")
    ), issues
    # Normalized plans still report them: there they would be a harness bug.
    assert any("decision_id" in issue
               for issue in brief_postflight.validate_plan_json(path))


def test_an_unnormalized_plan_is_not_booked_into_the_ledger(tmp_path, capsys,
                                                            monkeypatch):
    """The 2026-09-16 postflight: one authored semantic error skipped
    normalization, and `log_decisions` then booked the raw plan anyway. Nine
    id-less decisions collapsed onto a single ledger row, which failed the
    pre-push ledger check and stranded every commit on the host — the brief's
    own and the next job's — with origin four hours stale.

    That day's trigger was `debate.frames`, which no longer skips normalization
    (see `_normalization_owned_plan_error`). This backstop is not about which
    error it was, so it uses one that still does: the collapse is what must stay
    impossible for *any* plan that reaches here un-normalized."""
    ledger = tmp_path / "memory" / "decisions.jsonl"
    ledger.parent.mkdir(parents=True)
    # LEDGER reaches load/upsert/write as a definition-time default argument.
    monkeypatch.setattr(brief_postflight, "WS", tmp_path)
    for fn, defaults in (
            (brief_postflight.decision_v2.load_decisions, (ledger,)),
            (brief_postflight.decision_v2.write_decisions, (ledger,)),
            (brief_postflight.decision_v2.upsert_plan_decisions,
             (ledger, None, True))):
        monkeypatch.setattr(fn, "__defaults__", defaults)

    plan_path = tmp_path / "memory" / "2026-07-30-plan.json"
    plan_path.write_text(json.dumps({
        "schema_version": 2,
        "date": "2026-07-30",
        "decisions": [
            _authored_decision(ticker="AAA"),
            _authored_decision(ticker="BBB", action="bogus"),
        ],
    }))

    # Normalization declines: the second decision carries a semantic error.
    assert brief_postflight.normalize_plan_json(plan_path, ledger)
    assert all("decision_id" not in d
               for d in json.loads(plan_path.read_text())["decisions"])

    assert brief_postflight.log_decisions("2026-07-30") is False

    assert not ledger.exists(), "an un-normalized plan must not reach the ledger"
    assert "not normalized" in capsys.readouterr().err


def test_an_unnormalized_plan_blocks_the_commit_path(monkeypatch):
    """Delivery has already happened when maybe_commit runs. An unsafe ledger
    skip must therefore fail publication loudly, without rebuilding or creating
    a successful commit that leaves the day's decisions permanently unbooked."""
    monkeypatch.setattr(brief_postflight, "log_decisions", lambda _today: False)

    def must_not_continue(*_args, **_kwargs):
        raise AssertionError("an unbooked plan must stop before commit work")

    monkeypatch.setattr(brief_postflight, "record_risk_stances", must_not_continue)
    monkeypatch.setattr(brief_postflight, "rebuild_dashboard", must_not_continue)
    monkeypatch.setattr(brief_postflight, "_git", must_not_continue)

    committed, message = brief_postflight.maybe_commit(
        "warn", "2026-07-30"
    )

    assert committed is False
    assert message.startswith("ledger booking blocked:")
    assert brief_postflight.classify_commit_outcome(committed, message) == "failed"


def test_off_menu_debate_frames_do_not_block_the_whole_plan(tmp_path, monkeypatch):
    """2026-09-16, decision[7]: one out-of-menu `debate.frames` value on one
    decision left all nine that day without machine-owned ids.

    `normalize_debate` discards unknown frames by design and SKILL.md promises
    the model exactly that, but the whole-plan gate in `normalize_plan_json` ran
    first and bailed, so the per-field leniency never executed. The frame must be
    dropped and every other decision normalized.
    """
    monkeypatch.setenv("CLAWOCK_WORKSPACE", str(tmp_path))
    path = tmp_path / "2026-07-30-plan.json"
    path.write_text(json.dumps({
        "schema_version": 2,
        "date": "2026-07-30",
        "decisions": [
            _authored_decision(ticker="AAA"),
            _authored_decision(ticker="BBB", debate={
                "bull": "still cheap",
                "bear": "lost the 200MA",
                # `regime_shift` is invented; `risk_rule` is a `driven_by` value.
                "frames": ["technical_breakdown", "regime_shift", "risk_rule"],
            }),
        ],
    }))

    assert brief_postflight.normalize_plan_json(
        path, tmp_path / "decisions.jsonl") == []

    decisions = json.loads(path.read_text())["decisions"]
    assert all(d["decision_id"].startswith("dec-") for d in decisions)
    assert all(d["episode_id"].startswith("ep-") for d in decisions)
    # The menu value survives; the two off-menu ones are gone, not defaulted.
    assert decisions[1]["debate"]["frames"] == ["technical_breakdown"]
    assert decisions[1]["debate"]["bear"] == "lost the 200MA"
    assert brief_postflight.validate_plan_json(path) == []


def test_discarded_frames_are_counted_rather_than_silenced(tmp_path, monkeypatch):
    """Leniency must not become invisibility: the model drifted off this menu on
    four separate days in two weeks, and a dropped value that nothing counts is
    how that goes unnoticed."""
    monkeypatch.setenv("CLAWOCK_WORKSPACE", str(tmp_path))
    noted = []
    monkeypatch.setattr(brief_postflight.workflow_outcomes, "note_degradation",
                        lambda ledger, kind, detail, **kw: noted.append((kind, detail)))
    path = _write_authored_plan(tmp_path, _authored_decision(
        debate={"bear": "lost the 200MA", "frames": ["risk_rule"]}))

    assert brief_postflight.normalize_plan_json(
        path, tmp_path / "decisions.jsonl") == []

    assert [k for k, _ in noted] == ["debate_frames_off_menu"]
    assert "risk_rule" in noted[0][1]


def test_action_and_condition_errors_still_refuse_normalization(tmp_path):
    """The refusal exists so a bad *tradeable* field is never laundered into a
    valid default. Narrowing it for `debate` must not reach these: unlike a
    discarded frame, every one of these has a default that would substitute a
    meaning the model never wrote.
    """
    ledger = tmp_path / "decisions.jsonl"
    for label, updates in (
            ("action", {"action": "yolo"}),
            ("condition.type", {"condition": {"type": "vibes"}}),
            ("condition.price", {"condition": {"type": "price_above",
                                               "price": None}}),
            ("strategy_id", {"strategy_id": "nope"}),
    ):
        path = _write_authored_plan(tmp_path, _authored_decision(**updates))
        issues = brief_postflight.normalize_plan_json(path, ledger)
        assert issues, f"{label} must still block normalization"
        assert all("plan.json authored" in i for i in issues), issues
        assert "decision_id" not in json.loads(path.read_text())["decisions"][0]


def test_unresolvable_debate_evidence_ids_do_not_block_the_plan(tmp_path,
                                                                monkeypatch):
    """Same discard-only contract as `frames`: `normalize_debate_evidence` drops
    refs in no resolvable namespace, so the error is normalization's to fix.
    SKILL.md makes the model the same promise here ("核不上的直接丢掉")."""
    monkeypatch.setenv("CLAWOCK_WORKSPACE", str(tmp_path))
    noted = []
    monkeypatch.setattr(brief_postflight.workflow_outcomes, "note_degradation",
                        lambda ledger, kind, detail, **kw: noted.append((kind, detail)))
    path = _write_authored_plan(tmp_path, _authored_decision(debate={
        "bear": "lost the 200MA",
        "evidence_ids": ["risk:hard_stop:AAA", "made-up-ref",
                         "risk:hard_stop:AAA"],
    }))

    assert brief_postflight.normalize_plan_json(
        path, tmp_path / "decisions.jsonl") == []

    decision = json.loads(path.read_text())["decisions"][0]
    assert decision["decision_id"].startswith("dec-")
    assert decision["debate"]["evidence_ids"] == ["risk:hard_stop:AAA"]
    assert [kind for kind, _ in noted] == ["debate_citation_unresolved"]
    assert "2 debate evidence ref(s)" in noted[0][1]
    assert "made-up-ref" in noted[0][1]


def test_evidence_cap_discards_are_counted(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWOCK_WORKSPACE", str(tmp_path))
    noted = []
    monkeypatch.setattr(brief_postflight.workflow_outcomes, "note_degradation",
                        lambda ledger, kind, detail, **kw: noted.append((kind, detail)))
    refs = [f"news:evt_{i}" for i in range(8)]
    path = _write_authored_plan(tmp_path, _authored_decision(debate={
        "bear": "crowded", "evidence_ids": refs,
    }))

    assert brief_postflight.normalize_plan_json(
        path, tmp_path / "decisions.jsonl") == []

    decision = json.loads(path.read_text())["decisions"][0]
    assert decision["debate"]["evidence_ids"] == refs[:6]
    assert [kind for kind, _ in noted] == ["debate_citation_unresolved"]
    assert "2 debate evidence ref(s)" in noted[0][1]
    assert "above the 6-ref cap" in noted[0][1]
