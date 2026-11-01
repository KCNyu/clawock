"""Read-only session recap: current plan version, execution records and observed triggers.

No new history store. HK dates use HKT and US dates use ET, including a close
report after HKT midnight. Unknown evidence is never an unfilled order or a
claim that a trigger never fired during the session.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from clawock import sessions
from clawock.decision.actions import ACTIVE_ACTIONS
from clawock.decision.ledger import load_decisions


def _identity(row):
    return tuple(row.get(k) for k in ("plan_date", "ticker", "leg", "action")), row.get("condition"), row.get("size")


def build(workspace, market, *, now, plan_triggers=(), unrefreshed=(), limit=12):
    """Bounded projection, with independent availability for each source."""
    market = market.lower()
    if market not in {"hk", "us"}:
        raise ValueError("market must be hk or us")
    if now.tzinfo is None:
        now = now.replace(tzinfo=sessions.HKT)
    day = now.astimezone(sessions.ET if market == "us" else sessions.HKT).date().isoformat()
    memory = Path(workspace) / "memory"
    path = memory / f"{day}-plan.json"
    out = {"session": f"{market}:{day}", "as_of": now.isoformat(),
           "plan_status": "unavailable", "plan_source": f"memory/{path.name}",
           "plan_sha256": None, "execution_status": "unavailable",
           "counts": {}, "rows": [], "omitted": 0,
           "current_triggers": [], "trigger_omitted": 0,
           "intraday_status": "unavailable", "observed_signals": [], "signal_omitted": 0}
    try:
        raw = path.read_bytes()
        plan = json.loads(raw)
        if plan.get("date") != day or not isinstance(plan.get("decisions"), list):
            raise ValueError("plan is not for this session")
        if any(not isinstance(r, dict) for r in plan["decisions"]):
            raise ValueError("invalid plan row")
        baseline = [r for r in plan["decisions"] if r.get("leg") == market.upper()]
        ids = [r.get("decision_id") for r in baseline]
        if any(not i for i in ids) or len(set(ids)) != len(ids):
            raise ValueError("plan identities missing or duplicated")
        out.update(plan_status="ok", plan_sha256=hashlib.sha256(raw).hexdigest())
        entries = {}
        try:
            ledger_path = memory / "decisions.jsonl"
            if not ledger_path.is_file():
                raise ValueError("missing execution ledger")
            for row in load_decisions(ledger_path):
                if not isinstance(row, dict):
                    raise ValueError("invalid execution row")
                if row.get("decision_id") in ids:
                    if row["decision_id"] in entries:
                        raise ValueError("duplicate execution identity")
                    entries[row["decision_id"]] = row
            out["execution_status"] = "ok"
        except (OSError, ValueError, TypeError):
            entries = {}
        rows = []
        counts = {"followed": 0, "not_followed": 0, "unknown": 0, "passive": 0}
        for original in baseline:
            if original.get("action") not in ACTIVE_ACTIONS:
                counts["passive"] += 1
                continue
            current = entries.get(original["decision_id"], {})
            status = (current.get("execution") or {}).get("status")
            if _identity(current) != _identity(original) or status not in {"followed", "not_followed"}:
                status = "unknown"
            counts[status] += 1
            rows.append({"decision_id": original["decision_id"], "ticker": original.get("ticker"),
                         "action": original.get("action"), "execution": status})
        out.update(counts=counts, rows=rows[:limit], omitted=max(0, len(rows) - limit))
        # Use the existing plan trigger evaluator's result, not another price policy.
        # A hit can represent an older restatement of the same condition.
        keys = {(r.get("ticker"), r.get("action"), (r.get("condition") or {}).get("type"),
                 (r.get("condition") or {}).get("price")) for r in baseline}
        hits = sorted({str(r["ticker"]) for r in plan_triggers
                       if r.get("ticker") and r.get("ticker") not in unrefreshed
                       and r.get("quote_fresh") is not False
                       and (r.get("ticker"), r.get("action"), r.get("condition"), r.get("condition_price")) in keys})
        out.update(current_triggers=hits[:limit], trigger_omitted=max(0, len(hits) - limit))
    except (OSError, ValueError, TypeError, AttributeError):
        out.update(plan_status="unavailable", counts={}, rows=[], current_triggers=[])

    # Only previously delivered observations from this session, never yesterday
    # or a future slot. Their disappearance does not establish risk resolution.
    try:
        delivered = json.loads((memory / ".tmp" / f"intraday-delivered-state-{market}.json").read_text())
        state = delivered["state"]
        slot = datetime.fromisoformat(delivered["slot"])
        if slot.tzinfo is None:
            slot = slot.replace(tzinfo=sessions.HKT)
        if (state.get("session") != out["session"] or slot > now
                or slot.astimezone(sessions.ET if market == "us" else sessions.HKT).date().isoformat() != day):
            raise ValueError("not a prior observation of this session")
        seen = state.get("breaches_seen") or state.get("breaches") or []
        signals = sorted({(str(r["ticker"]), str(r["level"])) for r in seen
                          if r.get("kind") == "signal" and r.get("ticker") and r.get("level")})
        out.update(intraday_status="ok", intraday_slot=delivered["slot"],
                   observed_signals=[{"ticker": t, "level": level} for t, level in signals[:limit]],
                   signal_omitted=max(0, len(signals) - limit))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    return out
