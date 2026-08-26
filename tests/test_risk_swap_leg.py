"""A hard stop prescribes two legs; only one of them was expressible (#1075).

Measured on 2026-08-26 in `memory/risk_breaches.json`: three `hard_stop /
critical` records open **42 days**, each `acknowledgement: unacknowledged`,
`override: none`, `execution: pending`. Over the same period the plan re-issued
the same three cuts 53 (07226) / 38 (RKLX) / 45 (SPCH) times with **zero**
executions, and the last `add_only_on_trigger` of any kind was 2026-07-20.

The plan writer said why, in its own 2026-08-26 rationale for 03033:

    07226 砍完 swap 03033 路径被 packet add 限制阻挡
    (allowed=[hold_and_watch, watch])

The breach's own text is 「换仓 1x 同因子 03033（敞口保留、停 decay,**规则非择时**）」
— and `_constraints` gated its buy leg on `bool(setup_ids)`, i.e. on timing.
"""
from __future__ import annotations

import pytest

packet = pytest.importorskip("clawock.decision.packet")


def _risks(**by_ticker):
    return {t: list(rows) for t, rows in by_ticker.items()}


def _hard_stop(swap_to, value=1000.0, currency="HKD", severity="critical"):
    return {
        "kind": "hard_stop", "scope": "ticker", "breach_id": "risk-abc",
        "type": "leveraged_hard_stop", "severity": severity,
        "detail": "浮亏 -26% ≤ 硬止损线 -18%",
        "action_text": f"换仓 1x 同因子 {swap_to}（敞口保留、停 decay，规则非择时）",
        "required_reduction": {
            "kind": "full_leveraged_position", "swap_to": swap_to,
            "minimum_value": value, "currency": currency,
        },
    }


def _constraints(risks_for_ticker, mandates, *, setups=()):
    """The add side with no technical setup — the permanent live condition."""
    return packet._constraints(
        shares=0,
        risks=list(risks_for_ticker),
        actionable_ids=[],
        technical={"setups": [{"setup_id": s, "remaining_tranches": 1} for s in setups]},
        execution={"blockers": ["no_approved_setup"], "thesis_gate": "exploration_only",
                   "max_add_shares": 0, "position_room_shares": 0},
        swap_mandates=mandates,
    )


def test_the_buy_leg_of_a_rule_does_not_wait_for_a_setup():
    mandates = packet._swap_mandates(_risks(**{"07226": [_hard_stop("03033", 20001.2)]}))
    assert set(mandates) == {"03033"}

    c = _constraints([], mandates["03033"])
    assert "add_only_on_trigger" in c["allowed_actions"], (
        "the swap target could not be bought, so the prescription could only "
        "ever be executed half-way")
    mandate = c["swap_mandate"]
    assert mandate["from_ticker"] == "07226"
    assert mandate["authorised_by"] == "risk_rule"
    assert mandate["max_value"] == 20001.2
    assert mandate["requires_transaction_group_id"] is True


def test_without_a_mandate_the_timing_gate_still_applies():
    """The red half: nothing here loosens the ordinary add campaign."""
    c = _constraints([], [])
    assert c["swap_mandate"] is None
    assert "add_only_on_trigger" not in c["allowed_actions"]
    assert c["allowed_actions"] == ["hold_and_watch", "watch"]


def test_a_target_that_is_itself_breaching_is_refused():
    """Moving exposure into a second broken leg satisfies the letter, not the rule."""
    mandates = packet._swap_mandates(_risks(**{"07226": [_hard_stop("03033")]}))
    c = _constraints([_hard_stop("03032")], mandates["03033"])
    assert c["swap_mandate"] is None
    assert "add_only_on_trigger" not in c["allowed_actions"]


def test_the_mandate_names_one_ticker_and_only_that_ticker():
    mandates = packet._swap_mandates(_risks(**{
        "07226": [_hard_stop("03033")],
        "SPCH": [_hard_stop("SPCX", 2604.0, "USD")],
    }))
    assert sorted(mandates) == ["03033", "SPCX"]
    assert mandates["03033"][0]["from_ticker"] == "07226"
    assert mandates["SPCX"][0]["from_ticker"] == "SPCH"
    # An unrelated holding gets nothing.
    assert _constraints([], mandates.get("00100") or [])["swap_mandate"] is None


def test_a_self_referential_swap_is_ignored():
    assert packet._swap_mandates(_risks(**{"07226": [_hard_stop("07226")]})) == {}


def test_the_critical_mandate_wins_when_a_target_carries_several():
    mandates = packet._swap_mandates(_risks(**{
        "A": [_hard_stop("T", 1.0, severity="high")],
        "B": [_hard_stop("T", 2.0, severity="critical")],
    }))
    view = _constraints([], mandates["T"])["swap_mandate"]
    assert view["severity"] == "critical" and view["from_ticker"] == "B"
    assert len(view["all_mandates"]) == 2, "the others must stay visible"


# ── The layer the timing gate waits on has never filled (#1075) ──────────────

def test_an_empty_research_layer_is_reported_not_blessed(monkeypatch, tmp_path):
    """"0 valid" and "no open work" are one sentence to a validator and
    opposite facts to a reader.

    `memory/theses/`, `memory/entry-gates/` and `memory/earnings/` hold nothing
    but READMEs; `clawock thesis` is a manual CLI and no cron writes them. The
    gate said OK on every push while `_execution_view` blocked every add on
    `no_approved_setup` — the add side held shut by a layer that never fills.
    """
    import importlib.util, sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for path in (root, root / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(
        "sc_research", root / "ops" / "system_check.py")
    sc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sc)

    def result_with(counts, status="pass"):
        return {"status": status, "errors": [], "warnings": [], "counts": counts}

    def run(counts, status="pass"):
        import clawock.evidence.research_surface as rs
        monkeypatch.setattr(rs, "check", lambda: result_with(counts, status))
        r = sc.Result()
        sc.check_research_artifacts(r)
        return r.checks[0]

    _, severity, message = run(
        {"theses": 0, "earnings_artifacts": 0, "entry_gates": 0})
    assert severity == sc.WARNING, "an empty layer read as 'no open research work'"
    assert "never" in message

    # Green half: a layer that HAS produced something and has nothing pending
    # is genuinely fine, and must not start warning.
    _, severity, _ = run({"theses": 2, "earnings_artifacts": 0, "entry_gates": 1})
    assert severity == sc.OK


def test_the_skill_tells_the_writer_the_mandate_exists():
    """A capability the plan writer is never told about is an inert fix.

    The skill already said 「同一份 plan 中可证明净降 factor exposure 的 2x→1x 配对
    换仓不受阻」 while `_constraints` forbade exactly that — the instruction and
    the packet contradicted each other and the packet won, silently, for 42
    days. Now that they agree, the writer still has to be told which field
    carries the authorisation and that a mandated target needs no setup.
    """
    from pathlib import Path
    skill = (Path(__file__).resolve().parents[1] / "skills" / "daily-deep-brief"
             / "SKILL.md").read_text(encoding="utf-8")
    for token in ("swap_mandate", "transaction_group_id", "target_held",
                  "decision_overdue"):
        assert token in skill, (
            f"the packet publishes {token} and nothing tells the writer to read it")
