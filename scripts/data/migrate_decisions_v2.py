#!/usr/bin/env python3
"""One-way migration from plan.actions + calibration.csv to decision ledger v2.

The migration is deterministic and idempotent. It rewrites every historical
``memory/*-plan.json`` to schema v2, rebuilds ``memory/decisions.jsonl`` from the
plans, recomputes trigger/outcome fields from committed snapshots, and removes
the v1 CSV when ``--apply`` is supplied. Git history remains the audit trail.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict, deque
from pathlib import Path

from decision_v2 import (
    LEDGER, WS, assign_episode_ids, legacy_action_to_decision, load_decisions, settle_decisions,
    validate_decision, write_decisions,
)

V1 = WS / "memory" / "calibration.csv"


def _legacy_rows():
    if not V1.exists():
        return []
    with V1.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _row_key(row):
    return (
        (row.get("plan_date") or "")[:10], str(row.get("ticker") or "").strip(),
        row.get("bucket") or row.get("action") or "",
        row.get("trigger_type") or (row.get("condition") or {}).get("type") or "",
    )


def _apply_legacy_ground_truth(decision, row):
    if not row:
        return
    followed = (row.get("followed") or "unknown").strip().lower().split(" ", 1)[0]
    decision["execution"] = {
        "status": "followed" if followed == "true" else "not_followed" if followed == "false" else "unknown",
        "detected_at": row.get("followed_at") or None,
        "source": "calibration_v1_migration",
    }
    if decision.get("simulated_entry_price") is None:
        try:
            decision["simulated_entry_price"] = float(row.get("sim_entry_price") or 0) or None
        except (TypeError, ValueError):
            pass
    decision["migration"] = {
        "source": "calibration_v1",
        "legacy_outcome": row.get("outcome"),
        "legacy_benefit_t1_pct": row.get("pnl_5d"),
        "legacy_benefit_t5_pct": row.get("pnl_30d"),
        "legacy_updated_at": row.get("updated_at"),
    }


def migrate(apply=False):
    rows = _legacy_rows()
    # After the one-way cutover, the ledger—not plans alone—is authoritative:
    # it also contains legacy rows whose source plan no longer exists. Auditing
    # must therefore retain those orphans and be idempotent on every later run.
    if not rows and LEDGER.exists():
        existing = load_decisions(LEDGER)
        unique = []
        seen = set()
        duplicate_ids = []
        for d in existing:
            did = d.get("decision_id")
            if did in seen:
                duplicate_ids.append(did)
                continue
            seen.add(did)
            unique.append(d)
        assign_episode_ids(unique)
        settle_decisions(unique)
        errors = [f"{d.get('decision_id')}: {e}" for d in unique for e in validate_decision(d)]
        if errors:
            raise SystemExit("ledger validation failed:\n" + "\n".join(errors[:30]))
        if apply:
            write_decisions(unique, LEDGER)
        report = {
            "plans": len(list((WS / "memory").glob("*-plan.json"))),
            "decisions": len(unique),
            "episodes": len({d.get("episode_id") for d in unique}),
            "legacy_rows": 0,
            "retained_orphan_rows": sum((d.get("rationale") or "").startswith("migrated calibration row") for d in unique),
            "duplicate_ids_removed": len(duplicate_ids),
            "apply": apply,
            "idempotent_ledger_audit": True,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return report
    plans = []
    all_decisions = []
    authored_at = defaultdict(list)  # (plan_date, ticker) -> authored decisions
    date_lies = []
    for path in sorted((WS / "memory").glob("*-plan.json")):
        plan = json.loads(path.read_text())
        # The filename is the only trustworthy date: 2026-06-01-plan.json shipped
        # with date="2026-06-02", which silently collapsed two plan-days onto one
        # set of decision_ids and dropped the six decisions authored that day.
        plan_date = path.name[:10]
        if plan.get("date") and plan["date"] != plan_date:
            date_lies.append(f"{path.name} declares date={plan['date']!r}")
        source = plan.get("decisions") if plan.get("schema_version") == 2 else plan.get("actions") or []
        decisions = []
        for i, item in enumerate(source):
            # Ids are pure functions of (plan_date, ticker, strategy, action,
            # condition, ordinal), but legacy_action_to_decision reuses a stored
            # one when present. A re-run over already-migrated plans would then
            # keep ids minted from a wrong plan_date, so re-derive them here.
            item = {k: v for k, v in item.items() if k not in ("decision_id", "episode_id")}
            d = legacy_action_to_decision(item, plan_date, i)
            if item.get("user_override"):
                d["override"] = {
                    "status": "active", "reason": str(item.get("user_override")),
                    "expires_on": None, "revisit_condition": "material thesis/risk change",
                }
            decisions.append(d)
            all_decisions.append(d)
            authored_at[(plan_date, d["ticker"])].append(d)
        migrated = {k: v for k, v in plan.items() if k != "actions"}
        migrated["schema_version"] = 2
        migrated["date"] = plan_date
        migrated["decisions"] = decisions
        plans.append((path, migrated))

    # Attach v1 ground truth to the decision each row describes. The two stores
    # were written independently and disagree on bucket/trigger_type for ~4% of
    # rows (v1 also used retired names: watch, add_on_breakout, conditional), and
    # the plan side is normalized while the CSV side is raw. Keying on exact
    # 4-tuple equality therefore fails for rows whose decision plainly exists, so
    # match strictly first, then fall back to date+ticker.
    def _normalized(row):
        return legacy_action_to_decision({
            "ticker": row.get("ticker"), "bucket": row.get("bucket"),
            "trigger_type": row.get("trigger_type"), "trigger_price": row.get("trigger_price"),
        }, (row.get("plan_date") or "")[:10], 0)

    strict = defaultdict(deque)
    for d in all_decisions:
        strict[(d["plan_date"], d["ticker"], d["action"], d["condition"]["type"])].append(d)

    claimed, loose_n, dropped = set(), 0, []
    deferred = []
    for row in rows:
        norm = _normalized(row)
        pick = None
        queue = strict[(norm["plan_date"], norm["ticker"], norm["action"], norm["condition"]["type"])]
        while queue:
            cand = queue.popleft()
            if id(cand) not in claimed:
                pick = cand
                break
        if pick is None:
            deferred.append(row)
            continue
        claimed.add(id(pick))
        _apply_legacy_ground_truth(pick, row)

    orphan_n = 0
    for row in deferred:
        key = ((row.get("plan_date") or "")[:10], str(row.get("ticker") or "").strip())
        free = [d for d in authored_at.get(key, []) if id(d) not in claimed]
        if free:
            # Prefer a candidate whose action agrees; where v1 logged two
            # contradictory rows against one authored decision, attaching the
            # disagreeing row's followed/outcome would rewrite the track record.
            norm = _normalized(row)
            pick = next((d for d in free if d["action"] == norm["action"]), free[0])
            claimed.add(id(pick))
            _apply_legacy_ground_truth(pick, row)
            loose_n += 1
            continue
        if key in authored_at:
            # Every decision authored that day/ticker already carries ground truth;
            # this row is a stale duplicate. Fabricating a decision nobody authored
            # would inflate the episode count, so drop it and report the count.
            dropped.append(row)
            continue
        item = {
            "ticker": row.get("ticker"), "bucket": row.get("bucket"),
            "trigger_type": row.get("trigger_type"), "trigger_price": row.get("trigger_price"),
            "confidence": row.get("confidence"), "driven_by": row.get("driven_by") or "technical",
            "simulated_entry_price": row.get("sim_entry_price"),
            "rationale": "migrated calibration row; source plan unavailable",
        }
        d = legacy_action_to_decision(item, row.get("plan_date"), 10000 + orphan_n)
        _apply_legacy_ground_truth(d, row)
        d["migration"] = {"source": "calibration_v1_orphan"}  # after: _apply overwrites migration
        all_decisions.append(d)
        orphan_n += 1

    assign_episode_ids(all_decisions)
    # The plan and ledger share object references; episode ids now exist in both.
    settle_decisions(all_decisions)
    errors = []
    for d in all_decisions:
        errors.extend(f"{d.get('decision_id')}: {e}" for e in validate_decision(d))
    if errors:
        raise SystemExit("migration validation failed:\n" + "\n".join(errors[:30]))

    report = {
        "plans": len(plans), "decisions": len(all_decisions),
        "episodes": len({d.get("episode_id") for d in all_decisions}),
        "legacy_rows": len(rows),
        "matched_strict": len(claimed) - loose_n,
        "matched_by_date_ticker": loose_n,
        "migrated_orphan_rows": orphan_n,
        "dropped_stale_duplicate_rows": len(dropped),
        "plans_with_wrong_date_field": date_lies,
        "apply": apply,
    }
    if apply:
        for path, plan in plans:
            path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
        write_decisions(all_decisions, LEDGER)
        if V1.exists():
            V1.unlink()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="rewrite plans/ledger and remove calibration.csv")
    args = ap.parse_args()
    migrate(apply=args.apply)


if __name__ == "__main__":
    main()
