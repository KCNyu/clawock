"""`evaluate` is recomputed every intraday slot from inputs that move once a day.

`rebuild_dashboard` runs `clawock decision-map` on every dashboard rebuild, and
`decision_map.panel_scores` calls `signal_panel.evaluate` — 20.663s of
`timings_s.decision_map` on the live host (2026-09-04), inside the half of the
postflight that the cron payloads had to forbid a `timeout` around, because a
kill there delivers the report and loses the commit (#765).

It does not need recomputing that often. A panel row needs its t20 forward
returns, so the panel's leading edge lags the calendar: on 2026-09-06 its newest
session was 2026-09-01. And `evaluate` is pure with every draw seeded, so the
same panel through the same code gives the same dict — verified byte for byte
before the memo was written.

These tests pin the two halves of that claim: a hit returns exactly what a
recomputation returns, and it really is a hit (the recomputation is *denied*,
not counted). The third pins the part that is easy to get wrong — a memo keyed
only on data serves pre-edit numbers after the scoring code changes.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clawock.evaluation import signal_panel  # noqa: E402


def _panel():
    """Three sessions of a two-name cross-section — enough for `_cluster_ci`."""
    rows = []
    for index, day in enumerate(("2026-08-03", "2026-08-04", "2026-08-05")):
        for ticker, value in (("AAA", 1.0 + index), ("BBB", -1.0 - index)):
            rows.append({
                "as_of": day, "ticker": ticker, "leg": "us",
                "signal": "quant.demo", "value": value,
                "t1": value / 100, "t5": value / 50, "t20": value / 25,
            })
    return rows


def test_the_memo_returns_what_a_recomputation_returns(tmp_path):
    panel = _panel()
    memo = tmp_path / "memo.json"

    fresh = signal_panel.evaluate(panel)
    first = signal_panel.evaluate_cached(panel, path=memo)
    second = signal_panel.evaluate_cached(panel, path=memo)

    dump = lambda value: json.dumps(value, sort_keys=True, default=str)  # noqa: E731
    assert dump(first) == dump(fresh)
    assert dump(second) == dump(fresh)
    assert memo.exists(), "the memo was never written, so every call recomputes"


def test_a_hit_does_not_recompute(tmp_path, monkeypatch):
    """Denied, not counted — and a memo that recursed into itself would fail
    here too, which is how that draft was caught."""
    panel = _panel()
    memo = tmp_path / "memo.json"
    warm = signal_panel.evaluate_cached(panel, path=memo)

    monkeypatch.setattr(signal_panel, "evaluate", lambda _panel: pytest.fail(
        "the memo recomputed an answer it already had"))
    again = signal_panel.evaluate_cached(panel, path=memo)

    assert json.dumps(again, sort_keys=True) == json.dumps(warm, sort_keys=True)


def test_a_different_panel_is_a_miss(tmp_path):
    panel = _panel()
    memo = tmp_path / "memo.json"
    signal_panel.evaluate_cached(panel, path=memo)

    moved = [dict(row) for row in panel]
    moved[0]["value"] += 5.0
    result = signal_panel.evaluate_cached(moved, path=memo)

    assert json.dumps(result, sort_keys=True, default=str) == json.dumps(
        signal_panel.evaluate(moved), sort_keys=True, default=str)


def test_editing_the_scoring_code_invalidates_the_memo(tmp_path, monkeypatch):
    """A memo keyed only on data would answer with pre-edit numbers."""
    panel = _panel()
    memo = tmp_path / "memo.json"
    signal_panel.evaluate_cached(panel, path=memo)
    before = json.loads(memo.read_text(encoding="utf-8"))["key"]

    monkeypatch.setattr(signal_panel, "_source_fingerprint",
                        lambda: "pretend the scoring code changed")
    signal_panel.evaluate_cached(panel, path=memo)
    after = json.loads(memo.read_text(encoding="utf-8"))["key"]

    assert before != after, (
        "the key ignores the code, so an edit to score_signal would be served "
        "the answer from before it")


def test_an_unreadable_memo_costs_a_recomputation_and_nothing_else(tmp_path):
    memo = tmp_path / "memo.json"
    memo.write_text("{not json", encoding="utf-8")
    panel = _panel()

    result = signal_panel.evaluate_cached(panel, path=memo)

    assert json.dumps(result, sort_keys=True, default=str) == json.dumps(
        signal_panel.evaluate(panel), sort_keys=True, default=str)
    assert json.loads(memo.read_text(encoding="utf-8"))["key"]


def test_every_first_party_import_is_classified():
    """Either it decides what `evaluate` returns — and is fingerprinted — or it
    provably cannot. An import in neither tuple is an unanswered question about
    whether the memo can go stale."""
    source = (ROOT / "src" / "clawock" / "evaluation" / "signal_panel.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("clawock"):
            for alias in node.names:
                imported.add(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names if a.name.startswith("clawock"))

    package = ROOT / "src" / "clawock"
    fingerprinted = {path.relative_to(package).with_suffix("")
                     for pattern in signal_panel.EVALUATION_SOURCES
                     for path in package.glob(pattern)}
    fingerprinted = {"clawock." + str(rel).replace("/", ".") for rel in fingerprinted}

    unclassified = []
    for name in sorted(imported):
        module = name
        # `from clawock.x import y` — y may be a symbol, not a module.
        candidates = {module, module.rsplit(".", 1)[0]}
        if candidates & fingerprinted:
            continue
        if any(candidate in signal_panel.MEMO_NEUTRAL_IMPORTS
               for candidate in candidates):
            continue
        unclassified.append(name)

    assert not unclassified, (
        f"neither fingerprinted nor declared panel-build-only: {unclassified}. "
        f"If it can change what evaluate() returns it belongs in "
        f"EVALUATION_SOURCES; if it cannot, say so in MEMO_NEUTRAL_IMPORTS.")
