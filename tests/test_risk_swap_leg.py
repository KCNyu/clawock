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

def test_the_thesis_gate_is_a_kill_switch_and_says_so(monkeypatch, tmp_path):
    """The corrected version of a claim that shipped wrong for one evening.

    The first pass of #1075 said an empty `memory/theses/` held the add side
    shut. It does not. `_execution_view` only changes a number for
    `state ∈ {broken, damaged, weakening}` — it zeroes the tranche; `intact` and
    "no document" size identically, and the line that used to sit under
    `exploration_only` was `min(x, x)` under a comment claiming it stopped
    pyramiding (`max_tranches` does that). So an empty registry is not a closed
    door, it is an unarmed switch — and the gate has to say the true thing,
    because "0 valid · no open research work" said nothing at all.

    Entry gates stay out of the condition on purpose: governance requires one
    only for positions opened on/after `gate_required_from` (2026-07-27) and
    every current holding predates it, so zero gates is the policy working.
    """
    import importlib.util, json as _json, sys as _sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for path in (root, root / "src"):
        if str(path) not in _sys.path:
            _sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(
        "sc_research", root / "ops" / "system_check.py")
    sc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sc)

    book = tmp_path / "portfolio.json"
    book.write_text(_json.dumps({"portfolios": {"hk": {"holdings": [
        {"ticker": "00100", "shares": 120}, {"ticker": "07226", "shares": 6200},
        {"ticker": "SOLD", "shares": 0},
    ]}}}), encoding="utf-8")
    (tmp_path / "memory" / "theses").mkdir(parents=True)
    monkeypatch.setattr(sc, "WS", tmp_path)

    def run(counts, status="pass"):
        import clawock.evidence.research_surface as rs
        monkeypatch.setattr(rs, "check", lambda: {
            "status": status, "errors": [], "warnings": [], "counts": counts})
        r = sc.Result()
        sc.check_research_artifacts(r)
        return r.checks[0]

    _, severity, message = run(
        {"theses": 0, "earnings_artifacts": 0, "entry_gates": 0})
    assert severity == sc.WARNING
    assert "kill-switch is unarmed" in message
    assert "2 active holding" in message, "a cleared position is not a gap"
    assert "SOLD" not in message

    # Green half 1: a thesis for every active holding — nothing to report, even
    # with zero entry gates and zero earnings artifacts.
    _, severity, _ = run({"theses": 2, "earnings_artifacts": 0, "entry_gates": 0})
    assert severity == sc.OK, (
        "zero entry gates is the governance policy working, not a finding")

    # Green half 2: real open work still comes through the existing warn path.
    _, severity, message = run(
        {"theses": 2, "earnings_artifacts": 1, "entry_gates": 1}, status="warn")
    assert severity == sc.WARNING


def test_a_thesis_only_ever_subtracts(monkeypatch):
    """intact and unknown must size identically; only a broken story cuts.

    This is the assertion the removed `min(x, x)` pretended to be. If somebody
    later wants a thesis to ENABLE something, this test is the one that has to
    change on purpose.
    """
    holding = {"ticker": "T", "shares": 100, "current_price": 10.0}
    technical = {"setups": [{"setup_id": "alpha_confirmation", "campaign_id": "c",
                             "max_tranches": 1, "tranche_pct_of_position": 0.25}]}

    def size(state):
        view = packet._execution_view(
            holding, "US", 10_000.0, 10_000.0, technical,
            {"state": state}, False, authority_tier="exploration",
        )
        return view["max_add_shares"], view["thesis_gate"]

    unknown, unknown_gate = size("unknown")
    intact, intact_gate = size("intact")
    broken, broken_gate = size("broken")

    assert unknown == intact, (
        "a canonical thesis must not silently change sizing — that is what the "
        "no-op comment implied and the code never did")
    assert (unknown_gate, intact_gate, broken_gate) == (
        "exploration_only", "intact", "blocked")
    assert broken == 0, "a broken story is the one case that must cut the tranche"
