"""The 08:00 plan has to survive into the crons that execute it.

Before `plan_surface` existed, every later cron rebuilt the day from prices alone,
and on 2026-07-27 the 09:30 report told kcn to wait for a -1% pullback on a name
the brief had already ruled a non-timed discipline swap (issue #119).

Two properties matter more than the rest and are asserted directly:

* the ledger, not the plan file, decides what is still open — `clawock mark-followed`
  writes execution status only to `decisions.jsonl`, so a plan-file reader would
  keep re-proposing a filled order;
* nothing here may raise. A malformed brief artifact taking down the 30-minute
  reporting crons would be a strictly worse failure than having no plan context.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


WS = Path(__file__).resolve().parents[1]
DATA_SCRIPTS = str(WS / "scripts" / "data")
HARNESS = str(WS / "scripts" / "harness")
TODAY = "2026-07-27"


@pytest.fixture(scope="module")
def ps():
    return pytest.importorskip("clawock.decision.plans")


def decision(**over):
    """A row shaped like the real ledger: open unless a test says otherwise."""
    row = {
        "decision_id": "dec-test-0001",
        "plan_date": TODAY,
        "ticker": "07226",
        "leg": "HK",
        "action": "cut",
        "condition": {"type": "open", "description": ""},
        "size": {"shares": 1000, "pct": 16.1},
        "confidence": 0.85,
        "driven_by": "risk_rule",
        "rationale": "4 重 breach — 纪律 swap 不是择时",
        "execution": {"status": "unknown"},
        "evaluation": {"status": "pending"},
    }
    for key, value in over.items():
        row[key] = value
    return row


@pytest.fixture
def ledger(tmp_path):
    def write(rows):
        path = tmp_path / "decisions.jsonl"
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        return path
    return write


@pytest.fixture
def call(ps, tmp_path):
    def run(path, *, leg="HK", today=TODAY, memory_dir=None):
        return ps.open_decisions_context(
            leg=leg, today=today, ledger=path,
            memory_dir=memory_dir or tmp_path,
        )
    return run


def test_open_decision_reaches_the_context(ledger, call):
    ctx = call(ledger([decision()]))
    assert [d["ticker"] for d in ctx["open"]] == ["07226"]
    assert ctx["carried_over"] == 0


def test_size_is_carried_verbatim(ledger, call):
    # The 2026-07-27 10:05 slot quoted "6200 股" for a swap the plan sized at 1000
    # and "各 1000 股" for a 6200-share holding in the same sentence (issue #120).
    # Prose can only quote what the context states, so the context must state the
    # plan's own number and never a derived one.
    ctx = call(ledger([decision(size={"shares": 1000, "pct": 16.1})]))
    assert ctx["open"][0]["shares"] == 1000
    assert ctx["open"][0]["pct"] == 16.1


def test_filled_order_is_not_re_proposed(ledger, call):
    # `clawock mark-followed` writes execution status to the ledger only. Reading the
    # plan file instead would keep proposing this order all day.
    ctx = call(ledger([decision(execution={"status": "followed"})]))
    assert ctx == {}


def test_declined_order_is_not_re_proposed(ledger, call):
    ctx = call(ledger([decision(execution={"status": "not_followed"})]))
    assert ctx == {}


def test_settled_decision_is_not_open(ledger, call):
    ctx = call(ledger([decision(evaluation={"status": "settled"})]))
    assert ctx == {}


def test_leg_scopes_the_context(ledger, call):
    rows = [decision(), decision(decision_id="d2", ticker="SPCH", leg="US")]
    assert [d["ticker"] for d in call(ledger(rows), leg="HK")["open"]] == ["07226"]
    assert [d["ticker"] for d in call(ledger(rows), leg="US")["open"]] == ["SPCH"]


def test_carried_over_orders_are_kept_and_counted(ledger, call):
    # A swap hanging since Friday is the single most useful thing a Monday slot
    # can say; dropping it would hide exactly the case the brief flags as 悬挂.
    rows = [decision(), decision(decision_id="d2", plan_date="2026-07-24")]
    ctx = call(ledger(rows))
    assert ctx["carried_over"] == 1
    assert [d["plan_date"] for d in ctx["open"]] == [TODAY, "2026-07-24"]


def test_exec_mode_comes_from_the_plan_file(ledger, call, tmp_path):
    (tmp_path / f"{TODAY}-plan.json").write_text(json.dumps(
        {"exec_mode": {"today_override": "ALL SWAPS USE MARKET-ON-OPEN (MOO)"}},
    ), encoding="utf-8")
    ctx = call(ledger([decision()]), memory_dir=tmp_path)
    assert "MARKET-ON-OPEN" in ctx["exec_mode"]


def test_missing_plan_file_still_yields_the_open_decisions(ledger, call):
    ctx = call(ledger([decision()]))
    assert ctx["open"]
    assert "exec_mode" not in ctx


def test_unparseable_plan_file_does_not_lose_the_decisions(ledger, call, tmp_path):
    (tmp_path / f"{TODAY}-plan.json").write_text("{not json", encoding="utf-8")
    ctx = call(ledger([decision()]), memory_dir=tmp_path)
    assert ctx["open"]
    assert "exec_mode" not in ctx


def test_missing_ledger_is_empty_not_an_error(call, tmp_path):
    assert call(tmp_path / "nope.jsonl") == {}


def test_corrupt_line_does_not_blind_the_rest(ledger, call, tmp_path):
    path = ledger([decision()])
    # Append-only file caught mid-write: the tail is garbage, the head is not.
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"decision_id": "half-writ')
    assert [d["ticker"] for d in call(path)["open"]] == ["07226"]


def test_a_raising_loader_degrades_to_an_error_not_to_silence(ps, monkeypatch,
                                                              ledger, call):
    """Still fail-soft — never raise into a market cron — but say so (#136).

    This asserted `== {}` when it was written. That made a failed read identical
    to the legitimate "no open decisions today", so the prose would state there
    was no plan and the #119 contradiction could return unannounced.
    """
    def boom(_path):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(ps, "_load_ledger", boom)
    context = call(ledger([decision()]))
    assert context["error"].startswith("RuntimeError: disk on fire")
    assert "open" not in context, "a failed read must not imply an empty plan"


def test_context_is_bounded(ps, ledger, call):
    # Past ~12 rows the context stops being a checklist and starts being a
    # document the slot has to read instead of act on.
    rows = [decision(decision_id=f"d{i}", ticker=f"T{i}") for i in range(20)]
    ctx = call(ledger(rows))
    assert len(ctx["open"]) == ps.MAX_DECISIONS < 20
    assert ctx["truncated"] == 20 - ps.MAX_DECISIONS


def test_duplicate_add_safety_view_is_not_truncated(ps, ledger, call):
    rows = [decision(decision_id=f"d{i}", ticker=f"T{i}") for i in range(20)]
    rows[-1] = decision(
        decision_id="open-add", ticker="ADD", action="add_only_on_trigger"
    )

    ctx = call(ledger(rows))

    assert len(ctx["open"]) == ps.MAX_DECISIONS
    assert ctx["open_add_tickers"] == ["ADD"]


def test_rationale_is_trimmed(ledger, call):
    ctx = call(ledger([decision(rationale="很长的理由 " * 200)]))
    assert len(ctx["open"][0]["rationale"]) <= 181


# --- wiring: the context has to reach the two preflights, offline ------------

def _stub_preflight(module, monkeypatch, tmp_path):
    """Replace every network/subprocess seam so main() runs on synthetic data.

    `subprocess.run` is stubbed because the intraday path shells out to
    compute_t0_setups.py, which writes `assets/data/t0_setups.json` for real — an
    unstubbed test run left two generated files dirty in the working tree.
    """
    monkeypatch.setattr(module, "TMP", tmp_path)
    monkeypatch.setattr(
        module.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(module, "run_analyze", lambda market: (0, "🇭🇰 港股盯盘 | data", ""))
    monkeypatch.setattr(module, "collect_peers", lambda market: {})
    monkeypatch.setattr(module.research_surface, "movers_thesis_context", lambda *a, **k: {})
    monkeypatch.setattr(module.mover_news, "probe", lambda *a, **k: {})
    if hasattr(module, "known_catalysts"):
        monkeypatch.setattr(module.known_catalysts, "for_movers", lambda *a, **k: {})
    monkeypatch.setattr(
        module.plan_surface, "open_decisions_context",
        lambda **kwargs: {"plan_date": TODAY, "open": [{"ticker": "07226"}],
                          "carried_over": 0, "_leg": kwargs.get("leg")},
    )


@pytest.fixture(scope="module")
def report_preflight():
    for path in (DATA_SCRIPTS, HARNESS):
        if path not in sys.path:
            sys.path.insert(0, path)
    return pytest.importorskip("report_preflight")


@pytest.fixture(scope="module")
def intraday_preflight():
    for path in (DATA_SCRIPTS, HARNESS):
        if path not in sys.path:
            sys.path.insert(0, path)
    return pytest.importorskip("intraday_preflight")


def test_report_preflight_publishes_plan_context(report_preflight, monkeypatch, tmp_path):
    module = report_preflight
    _stub_preflight(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "_market_closed_reason", lambda *a: None)
    monkeypatch.setattr(module.workflow_outcomes, "record_stage", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["report_preflight.py", "--market", "hk", "--phase", "open"])

    assert module.main() == 0
    written = json.loads(next(tmp_path.glob("report-context-hk-open-*.json")).read_text())
    assert written["plan_context"]["open"][0]["ticker"] == "07226"
    # HK phase must not be handed the US leg's swaps.
    assert written["plan_context"]["_leg"] == "HK"


def test_intraday_preflight_publishes_plan_context(intraday_preflight, monkeypatch, tmp_path):
    module = intraday_preflight
    _stub_preflight(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module.trading_calendar, "closed_reason", lambda market: None)
    monkeypatch.setattr(module.cron_heartbeat, "record",
                        lambda *a, **k: {"job": "盘中盯盘", "slot": "slot"})
    monkeypatch.setattr(module, "collect_peers", lambda market: {})
    monkeypatch.setattr(sys, "argv", ["intraday_preflight.py", "--market", "us"])

    assert module.main() == 0
    written = json.loads((tmp_path / "intraday-context-us-latest.json").read_text())
    assert written["plan_context"]["open"][0]["ticker"] == "07226"
    assert written["plan_context"]["_leg"] == "US"


# --- wiring: the prose templates have to reference it ------------------------

@pytest.mark.parametrize("skill", ["hk-stock-analysis", "us-stock-analysis"])
def test_skill_instructs_the_turn_to_reconcile(skill):
    # A bare `"plan_context" in text` check passes on a passing mention in a
    # changelog line. What has to exist is the instruction: the key, the ban on
    # contradicting a risk_rule decision, and the order to quote the size.
    text = (WS / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    assert text.count("`plan_context`") >= 2, "context key not named in both modes"
    assert "driven_by=risk_rule" in text, "no rule against re-timing a discipline action"
    assert "照抄" in text, "no instruction to quote the plan's own size"


@pytest.mark.parametrize("skill", ["hk-stock-analysis", "us-stock-analysis"])
def test_the_two_share_rules_do_not_read_as_contradictory(skill):
    """Two rules land in the same file: quote `plan_context.shares`, and never
    restate a position's share count. On 2026-07-27 those were the same ticker on
    the same day with different numbers (07226: 6200 held, 1000 swapped), so the
    prompt has to say which is which or the model picks one at random."""
    text = (WS / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    assert "禁止重述持仓股数" in text
    assert "例外且仅此一个" in text, "the exception for plan sizes is not stated"
    assert "6200" in text and "1000" in text, "the concrete pair is not shown"


# ── the condition's own price (2026-09-07) ────────────────────────────────
# The 08:00 plan hung `00100 trim_on_rebound price_above 365`. The projection
# carried the TYPE and the (empty) description and dropped `condition.price`,
# so every downstream slot saw "price_above" with no price. 00100 traded to 393
# that morning — 7.7% through the line — and all eight intraday slots could only
# report a generic 异动. It closed at 350.8 and the trim never happened, for the
# second session running.


def priced(**over):
    row = decision(
        ticker="00100", action="trim_on_rebound",
        condition={"type": "price_above", "description": "", "price": 365.0},
        size={"shares": 20, "pct": 16.7},
    )
    for key, value in over.items():
        row[key] = value
    return row


def test_the_conditions_price_reaches_the_context(ledger, call):
    ctx = call(ledger([priced()]))
    assert ctx["open"][0]["condition"] == "price_above"
    assert ctx["open"][0]["condition_price"] == 365.0


def test_a_condition_without_a_price_says_none_not_zero(ledger, call):
    ctx = call(ledger([decision()]))
    assert ctx["open"][0]["condition_price"] is None


def test_a_met_condition_is_reported_with_how_far_through(ps, ledger, call):
    ctx = call(ledger([priced()]))
    rows = ps.triggered_conditions(ctx, {"00100": 393.0})
    assert len(rows) == 1
    assert rows[0]["ticker"] == "00100"
    assert rows[0]["condition_price"] == 365.0
    assert rows[0]["last"] == 393.0
    assert rows[0]["through_pct"] == 7.67
    assert rows[0]["execution_status"] == "unknown"


def test_an_unmet_condition_is_silent(ps, ledger, call):
    ctx = call(ledger([priced()]))
    assert ps.triggered_conditions(ctx, {"00100": 350.8}) == []


def test_price_below_compares_the_other_way(ps, ledger, call):
    ctx = call(ledger([priced(
        condition={"type": "price_below", "description": "", "price": 4.0})]))
    assert ps.triggered_conditions(ctx, {"00100": 3.9})
    assert ps.triggered_conditions(ctx, {"00100": 4.1}) == []


def test_the_boundary_counts_as_met(ps, ledger, call):
    """`price_above 365` is the price the plan named; 365.0 IS the trigger."""
    ctx = call(ledger([priced()]))
    assert ps.triggered_conditions(ctx, {"00100": 365.0})


def test_a_missing_quote_is_not_the_same_as_not_met(ps, ledger, call):
    """"I could not check" must not render as "the condition is not met" —
    that conflation is the 2026-09-07 defect one layer down."""
    ctx = call(ledger([priced()]))
    assert ps.triggered_conditions(ctx, {}) == []
    assert ps.triggered_conditions(ctx, {"00100": None}) == []


def test_a_condition_with_no_price_is_never_triggered(ps, ledger, call):
    ctx = call(ledger([decision()]))          # condition type "open", no price
    assert ps.triggered_conditions(ctx, {"07226": 3.12}) == []


def test_an_index_condition_is_left_alone(ps, ledger, call):
    """`index_breakdown` prices an INDEX. A holding's last is not an answer to
    it, and guessing would be worse than staying quiet."""
    ctx = call(ledger([priced(
        condition={"type": "index_breakdown", "description": "", "price": 4400})]))
    assert ps.triggered_conditions(ctx, {"00100": 5000.0}) == []


def test_a_restated_order_is_one_line_that_dates_itself(ps, ledger, call):
    """The 08:00 brief re-hangs an unfilled order under a fresh decision_id, so
    on 2026-09-07 the same 00100 trim at ≥365 was open twice: today's and the
    9/4 one it had already failed to execute. One line, and it says since when."""
    ctx = call(ledger([
        priced(decision_id="dec-earlier", plan_date="2026-07-24"),
        priced(decision_id="dec-today", plan_date=TODAY),
    ]))
    rows = ps.triggered_conditions(ctx, {"00100": 393.0})
    assert len(rows) == 1
    assert rows[0]["restated_count"] == 2
    assert rows[0]["open_since"] == "2026-07-24"


def _plan_with_levels(tmp_path, levels):
    memory = tmp_path / 'memory'
    memory.mkdir(parents=True, exist_ok=True)
    (memory / '2026-09-08-plan.json').write_text(
        json.dumps({'date': '2026-09-08', 'decisions': [],
                    'watch_levels': levels}, ensure_ascii=False),
        encoding='utf-8')
    return memory


def test_the_levels_the_morning_set_reach_the_slots_that_watch_the_tape(tmp_path):
    """2026-09-08: the plan named `hstech_breakdown: 4500`, HSTECH traded around
    4460–4530 all day, and not one intraday slot could quote the number.

    `watch_levels` lived in the morning card and the plan file only. This is the
    same shape as #1337 one level down — the context that decides is full of
    risk and state and carries none of the day's own lines.
    """
    from clawock.decision import plans

    levels = plans.watch_levels(
        today='2026-09-08',
        memory_dir=_plan_with_levels(tmp_path, {
            'hstech_breakdown': 4500,
            'book_force_derisk_usd': -3500,
            'cpi_2026-09-11_soft_boost': '若 CPI <= 2.8% 软数据, 加仓窗口开',
        }))

    assert levels['hstech_breakdown'] == 4500
    # Verbatim, including the prose ones: these keys are free text the model
    # writes each morning, so coercing them would be inventing a schema.
    assert levels['cpi_2026-09-11_soft_boost'].startswith('若 CPI')


def test_a_missing_or_broken_plan_is_no_levels_not_an_exception(tmp_path):
    """Same rule as the rest of this surface: a malformed brief artifact must
    never take down a 30-minute cron."""
    from clawock.decision import plans

    assert plans.watch_levels(today='2026-09-08', memory_dir=tmp_path) == {}

    memory = tmp_path / 'broken'
    memory.mkdir()
    (memory / '2026-09-08-plan.json').write_text('{not json', encoding='utf-8')
    assert plans.watch_levels(today='2026-09-08', memory_dir=memory) == {}

    # A plan with no levels block, and one whose block is the wrong type.
    for payload in ({'date': '2026-09-08'}, {'watch_levels': ['4500']}):
        (memory / '2026-09-08-plan.json').write_text(
            json.dumps(payload), encoding='utf-8')
        assert plans.watch_levels(today='2026-09-08', memory_dir=memory) == {}


def test_the_intraday_context_carries_them():
    """The projection is the point: a reader of the context can name the line."""
    import inspect
    import re

    from clawock.harness import intraday_preflight

    source = inspect.getsource(intraday_preflight)
    # Static, like the data-plane timeout gate next door: the context dict is
    # assembled inline in `main()` behind a live market fetch, so the readable
    # assertion is that the key is wired at all — the two tests above own what
    # it resolves to. Whitespace-tolerant on purpose; alignment is not contract.
    assert re.search(r"'watch_levels'\s*:\s*plan_surface\.watch_levels\(", source), (
        'the intraday context must carry the levels the plan set')
