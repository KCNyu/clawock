"""The model asks for a number; the code computes it and says what it read (#2843).

Two things are pinned. The calculator is closed: an expression reaches only the
whitelisted functions over stored bars, never the host, never a session after
`as_of`. And its result is usable: a receipt replays, and prose quoting a
computed value is not reported as a number the context never states.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from clawock.context import intraday_layers as layers
from clawock.harness import validation
from clawock.market_data import compute
from clawock.tools import ToolError, build_registry

ROOT = Path(__file__).resolve().parents[1]


def _bars(closes, start_day=1, **extra):
    return {"source": "fixture", "adjustment": "raw", "bars": {
        f"2026-01-{start_day + i:02d}": {"open": c, "high": c + 1, "low": c - 1, "close": c,
                                        **extra}
        for i, c in enumerate(closes)}}


STORE = {
    "AAA": _bars([10, 11, 12, 13, 14, 15, 16, 17, 18, 20]),
    "BBB": _bars([20, 20, 21, 21, 22, 22, 23, 23, 24, 25]),
    "SHORT": _bars([5, 6]),
}


def load(ticker):
    return STORE.get(ticker, {})


def value(expression, **kwargs):
    return compute.receipt_value(compute.evaluate(expression, load=load, **kwargs))


# ── the arithmetic is the stated arithmetic ─────────────────────────────────

def test_a_return_is_the_two_closes_it_names():
    receipt = compute.evaluate('ret(close("AAA"), 5)', load=load)
    assert receipt["unit"] == "percent"
    assert receipt["value_pct"] == round((20 / 14 - 1) * 100, 6)
    assert receipt["as_of"] == "2026-01-10"
    assert receipt["inputs"] == [{
        "ticker": "AAA", "fields": ["close"], "first_session": "2026-01-01",
        "last_session": "2026-01-10", "sessions": 10, "source": "fixture",
        "adjustment": "raw", "sha256": receipt["inputs"][0]["sha256"]}]


def test_the_model_can_define_a_relation_no_config_names():
    ratio = [a / b for a, b in zip([10, 11, 12, 13, 14, 15, 16, 17, 18, 20],
                                   [20, 20, 21, 21, 22, 22, 23, 23, 24, 25])]
    window = ratio[-5:]
    mean = sum(window) / 5
    spread = (sum((v - mean) ** 2 for v in window) / 4) ** 0.5
    receipt = compute.evaluate('zscore(close("AAA") / close("BBB"), 5)', load=load)
    assert receipt["unit"] == "sigma"
    assert receipt["value_sigma"] == round((window[-1] - mean) / spread, 6)
    assert [row["ticker"] for row in receipt["inputs"]] == ["AAA", "BBB"]


def test_units_follow_the_arithmetic_or_the_author():
    spread = compute.evaluate('ret(close("AAA"), 5) - ret(close("BBB"), 5)', load=load)
    assert spread["unit"] == "pp" and "value_pp" in spread
    assert compute.evaluate('sma(close("AAA"), 3) * 1.05', load=load)["unit"] == "price"
    ratio = compute.evaluate('last(close("AAA")) / sma(close("AAA"), 5) - 1', load=load)
    assert ratio["unit"] == "plain" and ratio["value"] == round(20 / 17.2 - 1, 6)
    named = compute.evaluate('last(close("AAA")) / last(close("BBB"))', unit="multiple",
                             load=load)
    assert named["value_multiple"] == 0.8


def test_atr_reads_the_true_range():
    # Every bar is close±1 and closes rise by 1 (2 on the last): TR is 2, then 3.
    assert value('atr("AAA", 3)') == round((2 + 2 + 3) / 3, 6)
    assert value('range_pos("AAA", 5)') == round((20 - 14) / (21 - 14) * 100, 6)


# ── nothing later than the cut is read ──────────────────────────────────────

def test_as_of_cuts_every_series():
    early = compute.evaluate('last(close("AAA"))', as_of="2026-01-05", load=load)
    assert early["value"] == 14 and early["as_of"] == "2026-01-05"
    assert early["inputs"][0]["last_session"] == "2026-01-05"
    assert early["inputs"][0]["sessions"] == 5
    with pytest.raises(compute.ComputeError, match="at or before 2025-12-31"):
        compute.evaluate('last(close("AAA"))', as_of="2025-12-31", load=load)


def test_a_window_longer_than_the_history_is_refused_not_shortened():
    with pytest.raises(compute.ComputeError,
                       match="insufficient history: sma needs 5 sessions, 2 available"):
        value('sma(close("SHORT"), 5)')
    with pytest.raises(compute.ComputeError, match="no stored daily bars for NOPE"):
        value('last(close("NOPE"))')


# ── the language cannot reach the host ──────────────────────────────────────

@pytest.mark.parametrize("expression", [
    '__import__("os").system("true")',
    'close("AAA").__class__',
    'close("AAA")[0]',
    '[c for c in close("AAA")]',
    'lambda: 1',
    'open("/etc/passwd")',
    'close("../../portfolio")',
    'sma(close("AAA"), n=3)',
    'close("AAA") if 1 else 2',
    'sma(close("AAA"), 100000)',
    'close("AAA")',
    '"AAA"',
    '1 / 0',
    'x + 1',
])
def test_anything_outside_the_whitelist_is_refused(expression):
    with pytest.raises(compute.ComputeError):
        value(expression)


def test_the_size_limits_are_enforced():
    with pytest.raises(compute.ComputeError, match="exceeds 400 characters"):
        value("1" + " + 1" * 200)
    with pytest.raises(compute.ComputeError, match="syntax nodes"):
        value("+".join(["1"] * 60))


# ── a receipt replays, and a changed input is noticed ───────────────────────

def test_a_receipt_replays_on_the_same_bars():
    receipt = compute.evaluate('ret(close("AAA"), 5)', load=load)
    assert compute.verify(receipt, load=load) == []
    # Later sessions arriving does not change what the receipt was cut at.
    later = {**STORE, "AAA": _bars([10, 11, 12, 13, 14, 15, 16, 17, 18, 20, 30, 40])}
    assert compute.verify(receipt, load=later.get) == []


def test_a_repaired_bar_or_an_edited_value_does_not_replay():
    receipt = compute.evaluate('ret(close("AAA"), 5)', load=load)
    repaired = {**STORE, "AAA": _bars([10, 11, 12, 13, 99, 15, 16, 17, 18, 20])}
    issues = compute.verify(receipt, load=repaired.get)
    assert any("recomputes as" in issue for issue in issues)
    assert any("input bars differ" in issue for issue in issues)
    forged = {**receipt, "value_pct": 99.0}
    assert any("recomputes as" in issue for issue in compute.verify(forged, load=load))
    relabelled = {**receipt, "receipt_id": "cr-0000000000000000"}
    assert compute.verify(relabelled, load=load) == ["receipt_id does not match its content"]
    assert compute.verify({"kind": "other"}, load=load) == ["not a compute receipt"]


# ── the tools, through the registry the CLI uses ────────────────────────────

@pytest.fixture
def workspace(tmp_path, monkeypatch):
    bars = tmp_path / "memory" / "bars"
    bars.mkdir(parents=True)
    for ticker, doc in STORE.items():
        (bars / f"{ticker}.json").write_text(json.dumps({**doc, "ticker": ticker}))
    data = tmp_path / "assets" / "data"
    data.mkdir(parents=True)
    (data / "cross_sectional_factor.json").write_text(json.dumps({
        "as_of": "2026-01-10",
        "activation": {"usable_for_decisions": False, "blockers": ["min_prospective_dates"]},
        "methodology": {"momentum": "residual", "weights": {"residual_mom_1m": 0.2}},
        "live_rankings": {"AAA": {
            "feature_as_of": "2026-01-10", "mom_1m": 0.08, "low_volatility": -0.5,
            "composite_score": 0.35, "market_percentile": 1.0,
            "sector_neutral_ranks": {"residual_mom_1m": 0.5}}}}))
    (data / "news_evidence_graph.json").write_text(json.dumps({
        "as_of": "2026-01-10", "source_status": {"sec": "ok"},
        "events": [
            {"event_id": "evt_1", "ticker": "AAA", "title": "Form 4", "source_reliability": 0.9,
             "impact_direction": "unknown", "actionable_escalation": False,
             "publication_time": {"iso": "2026-01-09T12:00:00+00:00"}},
            {"event_id": "evt_2", "ticker": "BBB", "title": "other"}]}))
    from clawock.market_data import bars as bars_store
    monkeypatch.setattr(bars_store, "BARS_DIR", bars)
    return tmp_path


def test_compute_tool_returns_and_keeps_the_receipt(workspace):
    registry = build_registry(workspace)
    assert {"compute", "observations"} <= set(registry.names())
    receipt = json.loads(registry.call("compute", expression='ret(close("AAA"), 5)'))
    assert compute.load_receipt(workspace, receipt["receipt_id"]) == receipt
    assert compute.load_receipt(workspace, "../../etc/passwd") is None
    with pytest.raises(ToolError, match="unknown function"):
        registry.call("compute", expression='shell("ls")')
    described = next(tool for tool in registry.schemas()
                     if tool["function"]["name"] == "compute")
    assert "zscore" in described["function"]["description"]


def test_observations_separate_the_measurement_from_the_opinion(workspace):
    registry = build_registry(workspace)
    factors = json.loads(registry.call("observations", ticker="aaa", kind="factors"))
    assert factors["measurements"] == {
        "feature_as_of": "2026-01-10", "mom_1m": 0.08, "low_volatility": -0.5}
    opinion = factors["policy_opinion"]
    assert opinion["composite_score"] == 0.35 and opinion["validated"] is False
    assert opinion["validation_blockers"] == ["min_prospective_dates"]

    events = json.loads(registry.call("observations", ticker="AAA", kind="events"))
    assert [row["observed"]["event_id"] for row in events["events"]] == ["evt_1"]
    # An event the escalation rule passed over is still an observation.
    assert events["events"][0]["policy_opinion"] == {
        "source_reliability": 0.9, "impact_direction": "unknown",
        "actionable_escalation": False}
    quiet = json.loads(registry.call("observations", ticker="SHORT", kind="events"))
    assert quiet["events"] == [] and "not the same as no news" in quiet["missing"]

    bars = json.loads(registry.call("observations", ticker="AAA", kind="bars", n="3",
                                    as_of="2026-01-08"))
    assert [row["session"] for row in bars["rows"]] == [
        "2026-01-06", "2026-01-07", "2026-01-08"]
    assert bars["observed_through"] == "2026-01-08" and bars["adjustment"] == "raw"
    for bad in ({"ticker": "NOPE", "kind": "bars"}, {"ticker": "AAA", "kind": "bars", "n": "0"},
                {"ticker": "../x", "kind": "bars"}, {"ticker": "NOPE", "kind": "factors"},
                {"ticker": "AAA", "kind": "secrets"}):
        with pytest.raises(ToolError):
            registry.call("observations", **bad)


# ── a computed number may be quoted ─────────────────────────────────────────

def test_prose_may_quote_a_value_computed_during_the_run(workspace):
    context = {"generated_at": "2026-01-10T08:00:00+08:00", "anomalies": []}
    prose = "AAA 近 5 日涨 42.86%，比值的 z 值 1.2σ。"
    before = validation.check_numeric_claims(prose, context)
    assert before and "42.86%" in before[0]

    receipt = json.loads(build_registry(workspace).call(
        "compute", expression='ret(close("AAA"), 5)'))
    assert receipt["value_pct"] == 42.857143
    enriched = validation.with_compute_receipts(context, workspace)
    after = validation.check_numeric_claims(prose, enriched)
    # The return is now sourced; the z value nobody computed still is not.
    assert after and "42.86%" not in after[0] and "1.2σ" in after[0]


def test_a_receipt_from_before_this_run_is_not_a_source(workspace):
    receipt = compute.evaluate('ret(close("AAA"), 5)', load=load)
    path = compute.save_receipt(workspace, receipt)
    os.utime(path, (1_000_000_000, 1_000_000_000))
    context = {"generated_at": "2026-01-10T08:00:00+08:00"}
    assert validation.with_compute_receipts(context, workspace) is context
    # Computing it again in this run makes it one.
    compute.save_receipt(workspace, receipt)
    assert validation.with_compute_receipts(context, workspace)["compute_receipts"][0][
        "receipt_id"] == receipt["receipt_id"]


# ── which fields are a rule's conclusion ────────────────────────────────────

def test_every_context_field_declares_its_semantics():
    known = {*layers.CORE_FIELDS, *layers.REFERENCE_ENTRIES, *layers.CONTROL_ENTRIES}
    labelled = [*layers.POLICY_FIELDS, *layers.MIXED_FIELDS]
    assert len(labelled) == len(set(labelled)), "a field is in both tables"
    assert set(labelled) <= known, "a semantics table names a field no layer has"
    assert not set(labelled) & set(layers.CONTROL_ENTRIES)
    counts = {}
    for field in known:
        counts[layers.field_semantics(field)] = counts.get(
            layers.field_semantics(field), 0) + 1
    assert counts == {"observation": len(known) - 22, "policy": 11, "mixed": 9, "control": 2}


def test_the_intraday_index_names_the_rule_outputs_present():
    from clawock.harness import intraday_preflight as pre

    packet = pre.judgment_packet({"context_id": "c1", "add_side_reads": {"rows": []},
                                  "analyzer_block": "x", "full_holdings": []})
    assert packet["index"]["rule_outputs"] == {
        "policy": ["add_side_reads"], "mixed": ["analyzer_block"]}


def test_the_brief_contract_names_rule_outputs_that_exist_in_a_row():
    from tests.test_brief_decision_packet import _compiled

    compiled = _compiled()
    rule_outputs = compiled["judgment_contract"]["rule_outputs"]
    row = compiled["tickers"]["00100"]
    for section, fields in rule_outputs.items():
        if section == "how_to_read":
            continue
        node = row
        for key in section.split("."):
            node = node[key]
        # `left_side` is present only when the bars are usable for it.
        missing = [field for field in fields if field not in node and field != "left_side"]
        assert not missing, f"{section}: {missing} are not fields of a compiled row"


def test_the_documented_parameter_counts_match_the_configs():
    """The table in decision-architecture.md is a count of what is in config/."""
    def leaves(node, path=""):
        if isinstance(node, dict):
            for key, child in node.items():
                yield from leaves(child, f"{path}/{key}")
        elif isinstance(node, list):
            for child in node:
                yield from leaves(child, f"{path}/[]")
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            yield path

    doc = (ROOT / "docs/architecture/decision-architecture.md").read_text()
    rows = re.findall(r"^\| `([a-z-]+\.json)` \| (\d+) \|", doc, re.M)
    assert len(rows) == 8
    total = 0
    for name, stated in rows:
        config = json.loads((ROOT / "config" / name).read_text())
        counted = [path for path in leaves(config)
                   if "schema_version" not in path and not path.endswith("/leverage")]
        assert len(counted) == int(stated), f"{name}: {len(counted)} numeric leaves"
        total += len(counted)
    assert f"hold {total} numeric leaves" in doc


@pytest.mark.parametrize("expression", [
    'ret(close("AAA"))', 'sma(close("AAA"), 2, 3)', 'last()', 'atr("AAA")',
    'min()', 'max()',
])
def test_bad_function_arity_is_a_readable_refusal(expression):
    with pytest.raises(compute.ComputeError, match="argument"):
        compute.evaluate(expression, load=load)


def test_compute_uses_the_requested_workspace_not_an_import_time_root(workspace, monkeypatch):
    def wrong_root(_ticker):
        raise AssertionError("must not read the process-global store")
    monkeypatch.setattr(compute, "_default_loader", wrong_root)
    receipt = json.loads(build_registry(workspace).call("compute", expression='last(close("AAA"))'))
    assert receipt["value"] == 20
    assert compute.verify(receipt, load=compute.workspace_loader(workspace)) == []
    from clawock.harness.brief_postflight import tool_receipt_issues
    assert tool_receipt_issues([{"ticker": "AAA", "tool_receipts": [receipt["receipt_id"]]}],
                               "2026-01-10", workspace=workspace) == []


def test_bad_arity_reaches_the_model_as_a_tool_error(workspace):
    with pytest.raises(ToolError, match="invalid arguments"):
        build_registry(workspace).call("compute", expression='sma(close("AAA"))')
