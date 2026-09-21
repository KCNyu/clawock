"""Every JSONL line this repository writes has to survive a strict parser.

`json.dumps` emits bare `NaN` / `Infinity` / `-Infinity` for non-finite floats.
Python reads those back happily, which is exactly why it went unnoticed: the
browser's `JSON.parse`, Go's `encoding/json` and `json.loads(..., allow_nan=
False)` all reject the file outright, so a single degenerate evaluation takes
the whole ledger with it (#1733).

The two JSONL writers went straight to `json.dumps` while every document
writer in `safe_io` already sanitized first. They share that path now, and the
test below is written against the two writers rather than the helper, because
the helper being correct was never the thing in doubt.
"""
from __future__ import annotations

import json

import pytest

from clawock.decision import ledger
from clawock.market_data import bars


def _strict(text: str):
    """Parse the way a parser that is not Python's default would."""
    def refuse(token):
        raise ValueError(f"non-finite token in JSONL: {token}")

    return [json.loads(line, parse_constant=refuse)
            for line in text.splitlines() if line.strip()]


def test_the_decision_ledger_survives_a_non_finite_evaluation(tmp_path):
    path = tmp_path / "decisions.jsonl"
    decision = {
        "decision_id": "d-nan", "ticker": "TEST", "action": "hold_and_watch",
        "evaluation": {"benefit_t1_pct": float("nan"),
                       "r_multiple": float("inf"),
                       "drawdown": float("-inf"),
                       "status": "settled"},
    }

    ledger.write_decisions([decision], path)

    rows = _strict(path.read_text(encoding="utf-8"))
    assert rows[0]["evaluation"] == {
        "benefit_t1_pct": None, "r_multiple": None, "drawdown": None,
        "status": "settled",
    }, "a non-finite evaluation must land as null, not as a NaN token"
    # And the ledger's own reader still gets the record back.
    assert ledger.load_decisions(path)[0]["decision_id"] == "d-nan"


def test_the_bar_conflict_log_survives_a_non_finite_ratio(tmp_path):
    path = tmp_path / "bar-conflicts.jsonl"

    written = bars.record_conflicts(
        "0700.HK", [{"kind": "rescale", "ratio": float("nan"), "tencent": 1.0}],
        path)

    assert written == 1
    rows = _strict(path.read_text(encoding="utf-8"))
    assert rows[0]["ratio"] is None
    assert rows[0]["ticker"] == "0700.HK"


def test_a_finite_ledger_is_byte_for_byte_what_it_always_was(tmp_path):
    """The sanitizer is a floor, not a reformatter: ordinary rows must not move."""
    path = tmp_path / "decisions.jsonl"
    rows = [{"decision_id": "d1", "confidence": 0.5, "ticker": "中芯国际"},
            {"decision_id": "d2", "confidence": 0.25, "ticker": "AAPL"}]

    ledger.write_decisions(rows, path)

    assert path.read_text(encoding="utf-8") == "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)


def test_strict_mode_is_available_for_a_producer_that_would_rather_abort():
    from clawock.safe_io import jsonl_line

    with pytest.raises(ValueError, match="non-finite"):
        jsonl_line({"x": float("nan")}, label="probe", strict=True)
