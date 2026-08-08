#!/usr/bin/env python3
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


# The checkout root, so `clawock` resolves from the tree this file ships
# in. Reached through the scripts/data/workspace shim until #267 step 3,
# whose only remaining job was inserting this path as a side effect.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from clawock.workspace import workspace_root  # noqa: E402

WS = workspace_root(Path(__file__).resolve().parents[2])
LEDGER = WS / "memory" / "risk_breaches.json"
GUARDRAIL_HISTORY = WS / "assets" / "data" / "guardrail_history.jsonl"
SCHEMA_VERSION = 1

LEVERAGED_TO_1X = {
    "07226": "03033",
    "PLTU": "PLTR",
    "ROBN": "HOOD",
    "MSFU": "MSFT",
    "TQQQ": "QQQ",
    "SOXL": "SOXX",
    "RKLX": "RKLB",
    "SPCH": "SPCX",
}
LEVERAGED_TICKERS = set(LEVERAGED_TO_1X)
ADD_ACTIONS = {"add_only_on_trigger", "add_on_breakout"}
SELL_ACTIONS = {"cut", "trim_on_rebound", "t_only"}


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
    for region in ("hk_stocks", "us_stocks"):
        for holding in (
            ((portfolio.get("portfolios") or {}).get(region) or {})
            .get("holdings") or []
        ):
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
        targets = list(LEVERAGED_TICKERS)
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
        "records": active,
    }


def attach_breach_ids(guardrail: dict) -> dict:
    """Return a context copy whose current detector rows carry stable IDs."""
    out = copy.deepcopy(guardrail)
    for row in out.get("breaches") or []:
        row["breach_id"] = _stable_id(
            str(row.get("type")), row.get("leg"), row.get("ticker"))
    for row in out.get("hard_stop_watch") or []:
        row["breach_id"] = _stable_id(
            "hard_stop", row.get("leg"), row.get("ticker"))
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
                        portfolio: dict) -> bool:
    target = str(decision.get("ticker") or "")
    holdings = _holding_map(portfolio)
    add_shares = (decision.get("size") or {}).get("shares")
    try:
        add_shares = float(add_shares)
    except (TypeError, ValueError):
        return False
    target_price = _holding_price(holdings.get(target) or {})
    for source, underlying in LEVERAGED_TO_1X.items():
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
                old_factor_notional = cut_shares * source_price * 2
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
    issues = []
    for decision in decisions:
        if decision.get("action") not in ADD_ACTIONS:
            continue
        ticker = str(decision.get("ticker") or "")
        leg = decision.get("leg") or ("HK" if ticker.isdigit() else "US")
        if _risk_reducing_swap(decision, decisions, portfolio):
            continue
        blockers = []
        for breach in open_records:
            if breach.get("leg") not in (None, leg):
                continue
            kind = breach.get("type")
            source = str(breach.get("ticker") or "")
            same_factor = {
                source, LEVERAGED_TO_1X.get(source, "")
            }
            reduction_sources = set(
                (breach.get("required_reduction") or {})
                .get("target_tickers") or []
            )
            same_risk_sleeve = reduction_sources | {
                LEVERAGED_TO_1X.get(item, "")
                for item in reduction_sources
            }
            if kind == "hard_stop" and ticker in same_factor:
                blockers.append(breach)
            elif kind == "factor_concentration":
                blockers.append(breach)
            elif kind in {"leveraged_exposure", "beta"} \
                    and ticker in (same_risk_sleeve or LEVERAGED_TICKERS):
                blockers.append(breach)
            elif kind == "regime_delever" and ticker in same_factor:
                blockers.append(breach)
            elif kind == "single_name" and breach.get("ticker") == ticker:
                blockers.append(breach)
        if blockers:
            ids = ", ".join(sorted({row["breach_id"] for row in blockers}))
            issues.append(
                f"{ticker} {decision.get('action')} frozen by open risk "
                f"breach(es) {ids}; only a proven risk-reducing 2x→1x pair "
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


def main() -> int:
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
    args = parser.parse_args()

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
