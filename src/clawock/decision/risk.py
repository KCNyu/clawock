"""Durable governance ledger for portfolio-risk breaches.

The daily guardrail is a detector, not a workflow. This module gives each
breach a stable identity and persists acknowledgement, expiring overrides and
execution evidence until the portfolio is actually compliant. It never places
or simulates a trade.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from clawock.instruments import get as get_instrument
from clawock.instruments import one_x_swap_map
from clawock.workspace import workspace_root

WS = workspace_root()
LEDGER = WS / "memory" / "risk_breaches.json"
GUARDRAIL_HISTORY = WS / "assets" / "data" / "guardrail_history.jsonl"
SCHEMA_VERSION = 1

ADD_ACTIONS = {"add_only_on_trigger", "add_on_breakout"}

#: How long an open breach may stand with nobody having decided anything about
#: it before the ledger says so out loud.
#:
#: The worst state a risk system can be in is not "breached" — it is "breached,
#: told every day, never executed, and never declined either". Measured on
#: 2026-08-26: three `hard_stop / critical` records open **42 days**, every one
#: `acknowledgement: unacknowledged` / `override: none` / `execution: pending`,
#: while the plan re-issued the same three cuts 53 / 38 / 45 times with zero
#: executions. The ledger read "nobody has looked at this", when what had
#: actually happened is that somebody looked at it every single day and chose
#: not to act. `override` exists to record exactly that and had never been used.
#:
#: Ten calendar days: long enough that an ordinary execution delay (a weekend, a
#: holiday, waiting for a level) never trips it, short enough that six weeks is
#: unambiguous. Deliberately NOT derived from `not_followed` counts in
#: `decisions.jsonl` — that is a different file with a different write path, and
#: a gate that needs a cross-file join is a gate that breaks quietly.
STANDING_DECISION_DAYS = 10
# Imported, not re-typed: `actions.py` calls itself the vocabulary "shared by
# decision workflow components", and a second literal is a twin that agrees
# until the day somebody adds an action word to one of them (#1089).
from clawock.decision.actions import SELL_ACTIONS  # noqa: F401


def _now(value=None) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _stamp(value=None) -> str:
    return _now(value).astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_stamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _now(value)
    except (TypeError, ValueError):
        return None


def _stable_id(kind: str, leg: str | None, ticker: str | None) -> str:
    scope = ticker or leg or "book"
    digest = hashlib.sha1(f"{kind}|{leg}|{scope}".encode()).hexdigest()[:12]
    return f"risk-{digest}"


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def load_ledger(path: Path = LEDGER) -> dict:
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "updated_at": None,
            "records": [],
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"risk ledger schema {data.get('schema_version')} unsupported")
    if not isinstance(data.get("records"), list):
        raise ValueError("risk ledger records must be a list")
    return data


def _current_rows(guardrail: dict) -> list[dict]:
    rows = [copy.deepcopy(row) for row in guardrail.get("breaches") or []]
    for stop in guardrail.get("hard_stop_watch") or []:
        rows.append({
            **copy.deepcopy(stop),
            "type": "hard_stop",
            "severity": "critical",
        })
    for row in rows:
        row["breach_id"] = _stable_id(
            str(row.get("type")), row.get("leg"), row.get("ticker"))
    return rows


def _history_first_seen(row: dict, path: Path = GUARDRAIL_HISTORY) -> str | None:
    if not path.exists():
        return None
    wanted = (row.get("type"), row.get("leg"), row.get("ticker"))
    found = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            day = json.loads(line)
        except json.JSONDecodeError:
            continue
        candidates = list(day.get("breaches") or [])
        candidates += [
            {**stop, "type": "hard_stop"}
            for stop in day.get("hard_stop_watch") or []
        ]
        for candidate in candidates:
            key = (
                candidate.get("type"),
                candidate.get("leg"),
                candidate.get("ticker"),
            )
            if key == wanted and day.get("date"):
                found.append(str(day["date"]))
    return min(found) + "T00:00:00+00:00" if found else None


def _fingerprint(row: dict) -> str:
    body = {
        "severity": row.get("severity"),
        "detail": row.get("detail"),
        "action": row.get("action"),
        "required_reduction": row.get("required_reduction"),
    }
    return hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:16]


def _holding_map(portfolio: dict) -> dict[str, dict]:
    out = {}
    for book in (portfolio.get("portfolios") or {}).values():
        for holding in (book or {}).get("holdings") or []:
            ticker = str(holding.get("ticker") or holding.get("code") or "")
            if ticker:
                out[ticker] = holding
    return out


def _broker_evidence(record: dict, portfolio: dict) -> list[dict]:
    """Read-only reconciliation against user-recorded broker trades."""
    holdings = _holding_map(portfolio)
    required = record.get("required_reduction") or {}
    targets = list(required.get("target_tickers") or [])
    if record.get("ticker"):
        targets.append(record["ticker"])
    if not targets and record.get("type") in {
        "leveraged_exposure", "beta", "regime_delever",
    }:
        targets = list(one_x_swap_map())
    opened = (_parse_stamp(record.get("current_opened_at"))
              or _parse_stamp(record.get("first_seen_at")))
    opened_day = opened.date().isoformat() if opened else ""
    evidence = []
    for ticker in sorted(set(targets)):
        for trade in (holdings.get(ticker) or {}).get("trades") or []:
            if (str(trade.get("action") or "").lower() != "sell"
                    or str(trade.get("date") or "") < opened_day):
                continue
            evidence_id = hashlib.sha1(
                json.dumps(
                    [ticker, trade.get("date"), trade.get("shares"),
                     trade.get("price"), trade.get("action")],
                    sort_keys=True,
                ).encode()
            ).hexdigest()[:12]
            evidence.append({
                "evidence_id": f"trade-{evidence_id}",
                "source": "portfolio.trades",
                "ticker": ticker,
                "date": trade.get("date"),
                "action": "sell",
                "shares": trade.get("shares"),
                "price": trade.get("price"),
                "note": trade.get("note") or "",
            })
    return evidence


def _age_days(opened_at: str | None, now: datetime) -> int:
    opened = _parse_stamp(opened_at)
    return max(0, (now.date() - opened.date()).days) if opened else 0


def override_is_active(record: dict, now=None) -> bool:
    """Validate status, reason and TTL at the point an exception is consumed."""
    current_time = _now(now)
    override = record.get("override") or {}
    expires = _parse_stamp(override.get("expires_at"))
    return bool(
        record.get("status") == "overridden"
        and override.get("status") == "active"
        and str(override.get("reason") or "").strip()
        and expires is not None
        and expires > current_time
    )


def reconcile_guardrail(
    guardrail: dict,
    portfolio: dict,
    *,
    path: Path = LEDGER,
    now=None,
    history_path: Path = GUARDRAIL_HISTORY,
    write: bool = True,
) -> dict:
    """Merge today's detector output into the durable governance ledger."""
    current_time = _now(now)
    stamp = _stamp(current_time)
    ledger = load_ledger(path)
    by_id = {row["breach_id"]: row for row in ledger["records"]}
    current = {row["breach_id"]: row for row in _current_rows(guardrail)}

    for breach_id, row in current.items():
        previous = by_id.get(breach_id)
        fingerprint = _fingerprint(row)
        if previous is None:
            first = _history_first_seen(row, history_path) or stamp
            record = {
                "breach_id": breach_id,
                "type": row.get("type"),
                "leg": row.get("leg"),
                "ticker": row.get("ticker"),
                "status": "open",
                "severity": row.get("severity") or "high",
                "first_seen_at": first,
                "current_opened_at": first,
                "last_seen_at": stamp,
                "last_changed_at": stamp,
                "age_days": _age_days(first, current_time),
                "recurrence_count": 1,
                "detail": row.get("detail") or "",
                "required_action": row.get("action") or "",
                "required_reduction": row.get("required_reduction") or {},
                "acknowledgement": {
                    "status": "unacknowledged",
                    "acknowledged_at": None,
                    "note": "",
                },
                "override": {
                    "status": "none", "reason": "",
                    "created_at": None, "expires_at": None,
                },
                "execution": {
                    "status": "pending", "confirmed_at": None,
                    "evidence": [],
                },
                "fingerprint": fingerprint,
                "resolution": None,
                "pressure": _pressure(row),
            }
        else:
            record = previous
            if record.get("status") == "resolved":
                record["recurrence_count"] = int(
                    record.get("recurrence_count") or 1) + 1
                record["current_opened_at"] = stamp
                record["acknowledgement"] = {
                    "status": "unacknowledged",
                    "acknowledged_at": None,
                    "note": "",
                }
                record["override"] = {
                    "status": "none", "reason": "",
                    "created_at": None, "expires_at": None,
                }
                record["execution"] = {
                    "status": "pending", "confirmed_at": None,
                    "evidence": [],
                }
                record["resolution"] = None
            if record.get("fingerprint") != fingerprint:
                record["last_changed_at"] = stamp
            record.update({
                "status": "open",
                "pressure": _pressure(row),
                "severity": row.get("severity") or record.get("severity"),
                "last_seen_at": stamp,
                "detail": row.get("detail") or "",
                "required_action": row.get("action") or "",
                "required_reduction": row.get("required_reduction") or {},
                "fingerprint": fingerprint,
            })

        override = record.get("override") or {}
        expires = _parse_stamp(override.get("expires_at"))
        if override.get("status") == "active" and (
                expires is None or expires <= current_time
                or not str(override.get("reason") or "").strip()):
            override["status"] = (
                "expired" if expires and expires <= current_time else "invalid")
            override["expired_at"] = stamp
            record["last_changed_at"] = stamp
        if override.get("status") == "active":
            record["status"] = "overridden"

        existing_evidence = {
            item.get("evidence_id"): item
            for item in (record.get("execution") or {}).get("evidence") or []
        }
        for item in _broker_evidence(record, portfolio):
            existing_evidence[item["evidence_id"]] = item
        execution = record.setdefault("execution", {})
        execution["evidence"] = list(existing_evidence.values())
        if (execution.get("status") != "confirmed"
                and execution["evidence"]):
            execution["status"] = "evidence_present"
        record["age_days"] = _age_days(
            record.get("current_opened_at"), current_time)
        record["standing"] = _standing(record)
        record["adaptive"] = _adaptive(record, portfolio, current_time)
        by_id[breach_id] = record

    for breach_id, record in by_id.items():
        if breach_id in current or record.get("status") == "resolved":
            continue
        evidence = (record.get("execution") or {}).get("evidence") or []
        record["status"] = "resolved"
        record["last_changed_at"] = stamp
        record["resolution"] = {
            "resolved_at": stamp,
            "reason": (
                "state_compliant_after_execution"
                if evidence else "state_compliant"
            ),
        }

    records = sorted(
        by_id.values(),
        key=lambda r: (
            r.get("status") == "resolved",
            {"critical": 0, "high": 1, "medium": 2}.get(
                r.get("severity"), 3),
            -(r.get("age_days") or 0),
            r["breach_id"],
        ),
    )
    ledger = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": stamp,
        "records": records,
    }
    if write:
        _atomic_write(path, ledger)

    active = [r for r in records if r.get("status") in ("open", "overridden")]
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": stamp,
        "ledger_path": str(path.relative_to(WS) if path.is_relative_to(WS) else path),
        "open_count": sum(r.get("status") == "open" for r in active),
        "overridden_count": sum(
            r.get("status") == "overridden" for r in active),
        "unacknowledged_count": sum(
            (r.get("acknowledgement") or {}).get("status")
            != "acknowledged" for r in active
        ),
        "oldest_open_days": max(
            [r.get("age_days") or 0 for r in active] or [0]),
        "decision_overdue_count": sum(
            bool((r.get("standing") or {}).get("decision_overdue")) for r in active),
        "may_stand_count": sum(may_stand(r) for r in active),
        "must_reissue_count": sum(
            bool((r.get("adaptive") or {}).get("must_reissue")) for r in active),
        "records": active,
    }


def _standing(record: dict) -> dict:
    """Has this breach been standing without anybody deciding anything?

    Three exits close it, and the ledger accepts any of them: execute the
    required action, acknowledge it (seen, accepted, still open), or override it
    (declined on purpose, with a reason and a revisit date). Only the absence of
    all three is overdue. See STANDING_DECISION_DAYS for the measurement that
    made this necessary.
    """
    age = int(record.get("age_days") or 0)
    acknowledged = (
        (record.get("acknowledgement") or {}).get("status") == "acknowledged")
    overridden = (record.get("override") or {}).get("status") == "active"
    executed = (
        (record.get("execution") or {}).get("status") == "confirmed")
    undecided = not (acknowledged or overridden or executed)
    return {
        "days_open": age,
        "threshold_days": STANDING_DECISION_DAYS,
        "undecided": undecided,
        "decision_overdue": bool(undecided and age >= STANDING_DECISION_DAYS),
        # Named so the reader does not have to infer what would clear it.
        "closes_with": ["execute", "acknowledge", "override"],
    }


#: Advice the book keeps declining (kcn 2026-09-12:「我们长期不听的模型建议可以考虑有一个
#: 自适应机制」). Measured the same day: 58 of the 61 active calls not followed in 30 days
#: were the same three risk_rule cuts (07226 / RKLX / SPCH), re-issued every morning for
#: 29 / 58 / 57 days, while the book showed what kcn had decided — shares unchanged, trades
#: in other names, and ten buys INTO SPCH (「无限子弹流继续摊本」) while it was told to cut.
#:
#: Split by who is good at what. The harness owns the evidence and the ledger: whether a
#: breach is ELIGIBLE to stand (`_revealed_stance`), the two rails that force it back
#: (`_worsened`, `REISSUE_CEILING_DAYS`), and the record of each day's choice
#: (`record_stances`). The brief model owns the judgment inside that envelope: whether
#: today is different enough to raise it again, and what to say instead. A model left to
#: itself shouts louder when ignored (09-11: 「今日第 5 次重发…三选一关闭」), and a model
#: that writes ledger state corrupts it (#1433) — so it gets the choice, not the pen.
REISSUE_CEILING_DAYS = 28
REARM_LOSS_PP = 10.0
REARM_REDUCTION_RATIO = 1.5
#: A trade elsewhere older than this says nothing about today: someone who has not
#: traded for a month may simply be away, and silence is not a decision.
RECENT_ACTIVITY_DAYS = 30
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2}


def _pressure(row: dict) -> dict | None:
    """The one number that says how bad this breach is, in its own units."""
    if row.get("type") in ("hard_stop", "leveraged_hard_stop") and isinstance(
            row.get("pnl_pct"), (int, float)):
        return {"kind": "pnl_pct", "value": float(row["pnl_pct"])}
    reduction = row.get("required_reduction") or {}
    value = reduction.get("minimum_value")
    if isinstance(value, (int, float)):
        return {"kind": "minimum_value", "value": float(value),
                "currency": reduction.get("currency")}
    return None


def _targets(record: dict) -> set[str]:
    targets = {str(t) for t in (record.get("required_reduction") or {}).get(
        "target_tickers") or []}
    if record.get("ticker"):
        targets.add(str(record["ticker"]))
    return targets


def _trades(portfolio: dict) -> list[dict]:
    out = []
    for ticker, holding in _holding_map(portfolio).items():
        for trade in holding.get("trades") or []:
            if isinstance(trade, dict) and isinstance(trade.get("date"), str):
                out.append({"ticker": ticker, "date": trade["date"][:10],
                            "action": str(trade.get("action") or "").lower()})
    return out


def _revealed_stance(record: dict, portfolio: dict, now: datetime) -> dict:
    """What the book shows the user did about this breach while it stood.

    `acting`   — sold one of the names it targets since it opened;
    `contrary` — bought one of them instead;
    `declined` — traded other names recently, never these;
    `silent`   — no recent trading at all: maybe away. Not a decision, never inferred as one.

    Read from trades on the CURRENT target tickers, not from `execution.status`: that
    field keeps whatever evidence it ever collected, and the US leverage breach carries
    `evidence_present` from July sells of MSFU/PLTU while its targets today are RKLX/SPCH.
    """
    opened = (_parse_stamp(record.get("current_opened_at"))
              or _parse_stamp(record.get("first_seen_at")))
    since = opened.date().isoformat() if opened else ""
    recent = (now.date() - timedelta(days=RECENT_ACTIVITY_DAYS)).isoformat()
    targets = _targets(record)
    today = now.date().isoformat()
    window = [t for t in _trades(portfolio) if since <= t["date"] <= today]
    on_target = [t for t in window if t["ticker"] in targets]
    sells = [t for t in on_target if t["action"] == "sell"]
    buys = [t for t in on_target if t["action"] == "buy"]
    elsewhere = [t for t in window if t["ticker"] not in targets and t["date"] >= recent]
    if sells:
        stance = "acting"
    elif buys:
        stance = "contrary"
    elif elsewhere:
        stance = "declined"
    else:
        stance = "silent"
    return {
        "stance": stance,
        "since": since,
        "target_tickers": sorted(targets),
        "sells_on_target": len(sells),
        "buys_on_target": len(buys),
        "last_buy_on_target": max((t["date"] for t in buys), default=None),
        "trades_elsewhere_recent": len(elsewhere),
        "last_trade_elsewhere": max((t["date"] for t in elsewhere), default=None),
    }


def _worsened(anchor, current, anchor_severity, severity) -> str:
    """Why this breach is materially worse than when it was last raised, or ''."""
    if _SEVERITY_RANK.get(severity, 3) < _SEVERITY_RANK.get(anchor_severity, 3):
        return f"严重度 {anchor_severity} → {severity}"
    if not anchor or not current or anchor.get("kind") != current.get("kind"):
        return ""
    before, now_value = float(anchor["value"]), float(current["value"])
    if anchor["kind"] == "pnl_pct" and now_value <= before - REARM_LOSS_PP:
        return (f"浮亏 {before:.1f}% → {now_value:.1f}%"
                f"（比上次重提时再深 ≥{REARM_LOSS_PP:g}pp）")
    if (anchor["kind"] == "minimum_value" and before > 0
            and now_value >= before * REARM_REDUCTION_RATIO):
        return (f"需减额 {before:,.0f} → {now_value:,.0f} {current.get('currency') or ''}"
                f"（≥{REARM_REDUCTION_RATIO:g}×）").replace(" （", "（")
    return ""


def _rearm_at(anchor) -> str:
    # A breach with no number of its own (the US β row carries its value only in
    # prose) has only the severity rail and the ceiling; say so rather than print "—".
    if not anchor:
        return "严重度升级"
    if anchor.get("kind") == "pnl_pct":
        return f"浮亏 ≤ {float(anchor['value']) - REARM_LOSS_PP:.1f}%"
    return (f"需减额 ≥ {float(anchor['value']) * REARM_REDUCTION_RATIO:,.0f} "
            f"{anchor.get('currency') or ''}").rstrip()


def _adaptive(record: dict, portfolio: dict, now: datetime) -> dict:
    """May today's brief let this breach stand, or must it raise it again?"""
    prev = record.get("adaptive") or {}
    today = now.date()
    stance = _revealed_stance(record, portfolio, now)
    blockers = []
    if record.get("status") != "open":
        blockers.append(f"status={record.get('status')}")
    if (record.get("execution") or {}).get("status") == "confirmed":
        blockers.append("execution confirmed")
    if int(record.get("age_days") or 0) < STANDING_DECISION_DAYS:
        blockers.append(f"open {record.get('age_days') or 0}d < {STANDING_DECISION_DAYS}d")
    if stance["stance"] not in ("declined", "contrary"):
        blockers.append(f"stance={stance['stance']}")
    stances = list(prev.get("stances") or [])[-10:]
    if blockers:
        return {"eligible": False, "may_stand": False, "must_reissue": False,
                "not_eligible_because": blockers, "stance": stance,
                "stances": stances}

    entering = not prev.get("eligible")
    anchor = record.get("pressure") if entering else prev.get("anchor")
    anchor_severity = record.get("severity") if entering else prev.get("anchor_severity")
    last = prev.get("last_reissued_on") if not entering else None
    # Entering: until today the plan re-issued it every morning, so today is the
    # last reissue the ceiling counts from.
    last = last or today.isoformat()
    try:
        since_last = (today - datetime.fromisoformat(last).date()).days
    except ValueError:
        since_last, last = 0, today.isoformat()
    worse = _worsened(anchor, record.get("pressure"), anchor_severity,
                      record.get("severity"))
    ceiling = since_last >= REISSUE_CEILING_DAYS
    must = bool(worse or ceiling)
    reason = worse or (f"距上次重提 {since_last} 天（上限 {REISSUE_CEILING_DAYS} 天）"
                       if ceiling else "")
    return {
        "eligible": True,
        "may_stand": not must,
        "must_reissue": must,
        "must_reason": reason,
        "stance": stance,
        "anchor": anchor,
        "anchor_severity": anchor_severity,
        "last_reissued_on": last,
        "days_since_reissue": since_last,
        "forced_on": (datetime.fromisoformat(last).date()
                      + timedelta(days=REISSUE_CEILING_DAYS)).isoformat(),
        "rearm_at": _rearm_at(anchor),
        "stances": stances,
    }


def may_stand(row: dict) -> bool:
    """True when today's plan may hold this breach instead of re-issuing its cut."""
    return bool((row.get("adaptive") or {}).get("may_stand"))


def record_stances(path: Path, plan_date: str, decisions: list[dict]) -> list[dict]:
    """File what today's plan did with each eligible breach. Harness-written.

    `reissue` when the plan carries a cut/trim on one of the breach's targets, which
    also re-anchors both rails; otherwise `stand`, with the call's own rationale as the
    reason. Keyed on `plan_date`, so a postflight re-run replaces its own entry.
    """
    ledger = load_ledger(path)
    by_ticker: dict[str, list[dict]] = {}
    for decision in decisions or []:
        by_ticker.setdefault(str(decision.get("ticker") or ""), []).append(decision)
    filed = []
    for record in ledger["records"]:
        adaptive = record.get("adaptive") or {}
        if record.get("status") != "open" or not adaptive.get("eligible"):
            continue
        mine = [d for t in sorted(_targets(record)) for d in by_ticker.get(t, [])]
        cuts = [d for d in mine if d.get("action") in ("cut", "trim_on_rebound")]
        choice = "reissue" if cuts else "stand"
        why = ((cuts or mine or [{}])[0].get("rationale") or "")[:240]
        entry = {"date": plan_date, "choice": choice, "why": why}
        stances = [row for row in adaptive.get("stances") or []
                   if row.get("date") != plan_date]
        adaptive["stances"] = (stances + [entry])[-10:]
        if choice == "reissue":
            adaptive["last_reissued_on"] = plan_date
            adaptive["anchor"] = record.get("pressure")
            adaptive["anchor_severity"] = record.get("severity")
        record["adaptive"] = adaptive
        filed.append({"breach_id": record.get("breach_id"), **entry})
    if filed:
        ledger["updated_at"] = _stamp()
        _atomic_write(path, ledger)
    return filed


#: The three lists a guardrail context carries, in the order the brief reads them.
GUARDRAIL_ROW_KEYS = ("breaches", "hard_stop_watch", "concentration_reviews")


def evidence_ref(row: dict) -> str:
    """The debate citation that resolves to this exact row.

    Composed here, once, so the model that cites it and the postflight that
    resolves it are reading the same string rather than two descriptions of one
    (#1141). The SKILL used to spell the grammar out — namespace, the full list
    of legal `type` values, ticker form vs leg form, "do not invent a name" —
    and the model still spent 2026-09-08 citing `risk:single_name:00100` at a
    row whose own type is `single_name_review`: right row, wrong half of a name
    that another row legitimately carries. A rule the model will not follow is
    a wish, not a rule; the fix is to stop asking it to compose an identifier
    and hand it one to copy.

    Ticker first, then leg: a cap on a name is about the name, and a leg-level
    breach (`leveraged_exposure`, `beta`) has no ticker to be about.
    """
    kind = str(row.get("type") or "").strip()
    if not kind:
        return ""
    for scope in (row.get("ticker"), row.get("leg")):
        scoped = str(scope or "").strip()
        if scoped:
            return f"risk:{kind}:{scoped}"
    return f"risk:{kind}"


def news_evidence_ref(event: dict) -> str:
    """The debate citation that resolves to this exact news event.

    Same reason as `evidence_ref` above, one namespace over. A real event id is
    `evt_3ffdc891b1dd9eb52b84` — opaque, and nothing in it says which story it
    is. On 2026-09-10 the model cited `news:00100-humain-m3-2026-09-04` and
    `news:02208-h1-report-2026-09-08`: `<ticker>-<topic>-<date>`, a format it
    invented because it is the one a human would have chosen. Both resolved to
    nothing. Asking a model to carry an opaque token it cannot check is asking
    it to prefer a plausible one; hand it the finished string instead.
    """
    event_id = str((event or {}).get("event_id") or "").strip()
    return f"news:{event_id}" if event_id else ""


def attach_event_ids(events: list) -> list:
    """Return a copy of the projected events, each advertising its citation."""
    out = []
    for event in events or []:
        if not isinstance(event, dict):
            out.append(event)
            continue
        row = dict(event)
        ref = news_evidence_ref(row)
        if ref:
            row["evidence_id"] = ref
        out.append(row)
    return out


def attach_breach_ids(guardrail: dict) -> dict:
    """Return a context copy whose current detector rows carry stable IDs."""
    out = copy.deepcopy(guardrail)
    for row in out.get("breaches") or []:
        row["breach_id"] = _stable_id(
            str(row.get("type")), row.get("leg"), row.get("ticker"))
    for row in out.get("hard_stop_watch") or []:
        row["breach_id"] = _stable_id(
            "hard_stop", row.get("leg"), row.get("ticker"))
    # Every row, including the concentration reviews `breach_id` skips: a review
    # is not a breach, but it is just as citable, and it was the one the model
    # got wrong.
    for key in GUARDRAIL_ROW_KEYS:
        for row in out.get(key) or []:
            ref = evidence_ref(row)
            if ref:
                row["evidence_id"] = ref
    return out


def attach_discipline(guardrail: dict, discipline: dict) -> dict:
    """Copy each breach's durable `standing` and `adaptive` onto today's detector rows.

    The packet reads `risk[].standing` off these rows (#1075) — and nothing had ever
    put it there: `reconcile_guardrail` computed it into the ledger and the context's
    `risk_discipline`, never into `risk_guardrail`, so every packet risk row carried
    `standing: {}` and the "stood N days undecided" verdict reached the model only if
    it went looking in a different part of the context. Joined by `breach_id`.
    """
    by_id = {row.get("breach_id"): row for row in (discipline or {}).get("records") or []}
    out = copy.deepcopy(guardrail)
    for key in ("breaches", "hard_stop_watch"):
        for row in out.get(key) or []:
            record = by_id.get(row.get("breach_id"))
            if record:
                row["standing"] = record.get("standing") or {}
                row["adaptive"] = record.get("adaptive") or {}
    return out


def _holding_price(holding: dict) -> float | None:
    for key in ("current_price", "price"):
        try:
            if holding.get(key) is not None:
                return float(holding[key])
        except (TypeError, ValueError):
            pass
    value = holding.get("current_value")
    shares = holding.get("shares")
    try:
        return float(value) / float(shares) if value and shares else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _risk_reducing_swap(decision: dict, decisions: list[dict],
                        portfolio: dict, leverage_pairs: dict[str, str]) -> bool:
    target = str(decision.get("ticker") or "")
    holdings = _holding_map(portfolio)
    add_shares = (decision.get("size") or {}).get("shares")
    try:
        add_shares = float(add_shares)
    except (TypeError, ValueError):
        return False
    target_price = _holding_price(holdings.get(target) or {})
    for source, underlying in leverage_pairs.items():
        if underlying != target:
            continue
        reductions = [
            row for row in decisions
            if row.get("ticker") == source
            and row.get("action") in SELL_ACTIONS
            and row.get("strategy_id") == "risk_rebalance"
        ]
        for reduction in reductions:
            try:
                cut_shares = float(
                    (reduction.get("size") or {}).get("shares"))
            except (TypeError, ValueError):
                continue
            source_price = _holding_price(holdings.get(source) or {})
            if source_price and target_price:
                source_meta = get_instrument(source) or {}
                leverage = float(source_meta.get("leverage_multiple") or 1)
                old_factor_notional = cut_shares * source_price * leverage
                new_factor_notional = add_shares * target_price
                if new_factor_notional <= old_factor_notional * 1.05:
                    return True
    return False


def validate_exposure_increases(
    decisions: list[dict],
    discipline: dict,
    portfolio: dict,
) -> list[str]:
    """Freeze same-risk adds while a non-overridden hard breach is open."""
    open_records = [
        row for row in discipline.get("records") or []
        if row.get("status") != "resolved"
        and not override_is_active(row)
        and row.get("severity") in ("critical", "high")
    ]
    if not open_records:
        return []
    leverage_pairs = one_x_swap_map()
    leveraged_tickers = set(leverage_pairs)
    issues = []
    for decision in decisions:
        if decision.get("action") not in ADD_ACTIONS:
            continue
        ticker = str(decision.get("ticker") or "")
        instrument = get_instrument(ticker) or {}
        leg = decision.get("leg") or instrument.get("region")
        if _risk_reducing_swap(
            decision, decisions, portfolio, leverage_pairs
        ):
            continue
        blockers = []
        for breach in open_records:
            # BOOK is the cross-market correlation scope. It applies only to
            # target_tickers inside that measured cluster, not indiscriminately
            # to every add on either leg.
            if breach.get("leg") not in (None, "BOOK", leg):
                continue
            kind = breach.get("type")
            source = str(breach.get("ticker") or "")
            same_factor = {
                source, leverage_pairs.get(source, "")
            }
            reduction_sources = set(
                (breach.get("required_reduction") or {})
                .get("target_tickers") or []
            )
            same_risk_sleeve = reduction_sources | {
                leverage_pairs.get(item, "")
                for item in reduction_sources
            }
            if kind == "hard_stop" and ticker in same_factor:
                blockers.append(breach)
            elif kind == "factor_concentration" and ticker in reduction_sources:
                blockers.append(breach)
            elif kind in {"leveraged_exposure", "beta"} \
                    and ticker in (same_risk_sleeve or leveraged_tickers):
                blockers.append(breach)
            elif kind == "regime_delever" and ticker in same_factor:
                blockers.append(breach)
            elif kind == "single_name" and breach.get("ticker") == ticker:
                blockers.append(breach)
        if blockers:
            ids = ", ".join(sorted({row["breach_id"] for row in blockers}))
            issues.append(
                f"{ticker} {decision.get('action')} frozen by open risk "
                f"breach(es) {ids}; only a proven risk-reducing leveraged→1x pair "
                "or a durable unexpired override may proceed"
            )
    return issues


def _mutate_record(path: Path, breach_id: str, mutate) -> dict:
    ledger = load_ledger(path)
    record = next(
        (row for row in ledger["records"]
         if row.get("breach_id") == breach_id),
        None,
    )
    if record is None:
        raise ValueError(f"breach not found: {breach_id}")
    mutate(record)
    ledger["updated_at"] = _stamp()
    _atomic_write(path, ledger)
    return record


def acknowledge(path: Path, breach_id: str, note: str) -> dict:
    if not note.strip():
        raise ValueError("acknowledgement note is required")
    return _mutate_record(path, breach_id, lambda row: row.update({
        "acknowledgement": {
            "status": "acknowledged",
            "acknowledged_at": _stamp(),
            "note": note.strip(),
        },
        "last_changed_at": _stamp(),
    }))


def grant_override(path: Path, breach_id: str, reason: str,
                   ttl_hours: int) -> dict:
    if not reason.strip():
        raise ValueError("override reason is required")
    if not 1 <= ttl_hours <= 168:
        raise ValueError("override TTL must be between 1 and 168 hours")
    now = _now()
    expires = now + timedelta(hours=ttl_hours)

    def mutate(row):
        if row.get("status") == "resolved":
            raise ValueError("cannot override a resolved breach")
        row["override"] = {
            "status": "active",
            "reason": reason.strip(),
            "created_at": _stamp(now),
            "expires_at": _stamp(expires),
        }
        row["status"] = "overridden"
        row["last_changed_at"] = _stamp(now)

    return _mutate_record(path, breach_id, mutate)


def confirm_execution(path: Path, breach_id: str, evidence: str) -> dict:
    if not evidence.strip():
        raise ValueError("execution evidence is required")

    def mutate(row):
        execution = row.setdefault("execution", {})
        entries = execution.setdefault("evidence", [])
        evidence_id = "manual-" + hashlib.sha1(
            evidence.strip().encode()).hexdigest()[:12]
        item = {
            "evidence_id": evidence_id,
            "source": "manual_confirmation",
            "recorded_at": _stamp(),
            "note": evidence.strip(),
        }
        if not any(entry.get("evidence_id") == evidence_id for entry in entries):
            entries.append(item)
        execution["status"] = "confirmed"
        execution["confirmed_at"] = _stamp()
        row["last_changed_at"] = _stamp()

    return _mutate_record(path, breach_id, mutate)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Maintain the durable risk-breach governance ledger")
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    ack = sub.add_parser("ack")
    ack.add_argument("breach_id")
    ack.add_argument("--note", required=True)
    override = sub.add_parser("override")
    override.add_argument("breach_id")
    override.add_argument("--reason", required=True)
    override.add_argument("--ttl-hours", type=int, required=True)
    confirm = sub.add_parser("confirm")
    confirm.add_argument("breach_id")
    confirm.add_argument("--evidence", required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "list":
            ledger = load_ledger(args.ledger)
            for row in ledger["records"]:
                if row.get("status") != "resolved":
                    print(
                        row["breach_id"], row["status"], row["severity"],
                        f"age={row.get('age_days', 0)}d",
                        row.get("ticker") or row.get("leg") or "book",
                        row.get("detail") or "",
                    )
            return 0
        if args.command == "ack":
            row = acknowledge(args.ledger, args.breach_id, args.note)
        elif args.command == "override":
            row = grant_override(
                args.ledger, args.breach_id, args.reason, args.ttl_hours)
        else:
            row = confirm_execution(
                args.ledger, args.breach_id, args.evidence)
        print(json.dumps(row, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
