#!/usr/bin/env python3
"""What the 08:00 brief already decided, for the crons that run after it.

The daily deep brief writes `memory/{date}-plan.json` and appends its decisions to
`memory/decisions.jsonl`. Until this module existed, nothing downstream read either
one: the 09:30 report and every 30-minute intraday slot rebuilt their view of the
day from prices alone.

That gap is not cosmetic. On 2026-07-27 the 09:30 report attached a "wait for a
-1% pullback" condition to 07226 — a name the 08:00 plan had already ruled a
discipline swap on four simultaneous risk breaches, i.e. explicitly not a timing
decision (issue #119). The 10:05 slot reached the right answer only by shelling out
six times to read the plan by hand, and misquoted the size while doing it.

The ledger is the source of truth, not the plan file: `mark_followed.py` writes
execution status back to `decisions.jsonl` only. Reading the plan file alone would
keep proposing an order that already filled.

Nothing here may raise. A brief artifact must never be able to red a
market-reporting cron, so every failure path degrades to "no plan context" and the
report is written from prices, exactly as it was before this module.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

# The checkout root, so `clawock` resolves from the tree this file ships
# in. Reached through the scripts/data/workspace shim until #267 step 3,
# whose only remaining job was inserting this path as a side effect.
import sys  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from clawock.workspace import workspace_root  # noqa: E402

WS = workspace_root(Path(__file__).resolve().parents[2])
MEMORY = WS / "memory"
LEDGER = MEMORY / "decisions.jsonl"

# A day's plan is 7 decisions; a backlog of hanging swaps has run to 5 on top of
# that. Past ~12 the context stops being a checklist and starts being a document.
MAX_DECISIONS = 12
RATIONALE_CHARS = 180
EXEC_MODE_CHARS = 240

# An order still waiting on the market. `followed`/`not_followed` are terminal:
# mark_followed.py has already recorded what happened, so re-proposing the action
# would be arguing with the ledger.
OPEN_EXECUTION = "unknown"


def _trim(text, limit):
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _load_ledger(path):
    """Every decision row, newest last. A corrupt line is skipped, not fatal —
    the ledger is append-only and a half-written tail must not blind the day."""
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _is_open(row):
    execution = (row.get("execution") or {}).get("status")
    evaluation = (row.get("evaluation") or {}).get("status")
    return execution == OPEN_EXECUTION and evaluation == "pending"


def _entry(row):
    size = row.get("size") or {}
    condition = row.get("condition") or {}
    return {
        "decision_id":      row.get("decision_id"),
        "plan_date":        row.get("plan_date"),
        "ticker":           row.get("ticker"),
        "leg":              row.get("leg"),
        "action":           row.get("action"),
        "condition":        condition.get("type"),
        "condition_detail": _trim(condition.get("description"), 80),
        # Sizes are quoted, never restated from memory: the 2026-07-27 slot said
        # "6200 股" for a swap the plan sized at 1000 (issue #120).
        "shares":           size.get("shares"),
        "pct":              size.get("pct"),
        "confidence":       row.get("confidence"),
        "driven_by":        row.get("driven_by"),
        "execution_status": (row.get("execution") or {}).get("status"),
        "rationale":        _trim(row.get("rationale"), RATIONALE_CHARS),
    }


def _plan_extras(plan_date, memory_dir):
    """exec_mode from the plan file — the one field the ledger does not carry.

    2026-07-27's was 'ALL SWAPS USE MARKET-ON-OPEN (MOO), NOT LIMIT ORDERS', which
    is exactly the instruction a later slot must not contradict with a limit-style
    'wait for a pullback' suggestion.
    """
    path = memory_dir / f"{plan_date}-plan.json"
    if not path.exists():
        return None
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    override = (plan.get("exec_mode") or {}).get("today_override")
    return _trim(override, EXEC_MODE_CHARS) or None


def open_decisions_context(*, leg=None, today=None, ledger=None, memory_dir=None):
    """Open decisions the report/intraday prose has to reconcile against.

    `leg` scopes to 'HK' or 'US' so a港股 slot is not handed five US swaps. Rows
    carried over from an earlier plan date are kept — a swap that never filled is
    the single most important thing a later slot can tell kcn about.
    """
    try:
        ledger_path = Path(ledger) if ledger else LEDGER
        memory = Path(memory_dir) if memory_dir else MEMORY
        today = today or datetime.now().strftime("%Y-%m-%d")

        rows = [row for row in _load_ledger(ledger_path) if _is_open(row)]
        if leg:
            rows = [row for row in rows if str(row.get("leg", "")).upper() == leg.upper()]
        if not rows:
            return {}

        # Today's plan first, then the oldest carried-over orders: a swap hanging
        # since Friday is more urgent than one written this morning, but the
        # morning's plan is what the prose is being asked to execute.
        rows.sort(
            key=lambda row: (
                row.get("plan_date") != today,
                str(row.get("plan_date") or ""),
                -float(row.get("confidence") or 0),
            )
        )
        selected = rows[:MAX_DECISIONS]
        carried = [row for row in selected if row.get("plan_date") != today]

        context = {
            "plan_date":    today,
            "open":         [_entry(row) for row in selected],
            "carried_over": len(carried),
        }
        if len(rows) > MAX_DECISIONS:
            context["truncated"] = len(rows) - MAX_DECISIONS
        exec_mode = _plan_extras(today, memory)
        if exec_mode:
            context["exec_mode"] = exec_mode
        return context
    except Exception as exc:  # noqa: BLE001 — a plan artifact must never red a report cron
        # Fail soft, but as a VALUE, not as silence (#136). `{}` is also the
        # legitimate "no open decisions today" answer, so a read that throws used
        # to be indistinguishable from a clean day — and the report would write
        # prose accordingly. That is exactly the #119 defect coming back with no
        # signal: on 2026-07-27 the 09:30 report advised waiting for a pullback
        # while the day's plan held the same position as a risk_rule swap.
        return {"error": f"{type(exc).__name__}: {exc}"[:200]}


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--leg", choices=["HK", "US"])
    parser.add_argument("--date")
    args = parser.parse_args()
    print(json.dumps(
        open_decisions_context(leg=args.leg, today=args.date),
        ensure_ascii=False, indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
