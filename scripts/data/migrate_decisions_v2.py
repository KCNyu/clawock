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
    row_queues = defaultdict(deque)
    for row in rows:
        row_queues[_row_key(row)].append(row)

    plans = []
    all_decisions = []
    for path in sorted((WS / "memory").glob("*-plan.json")):
        plan = json.loads(path.read_text())
        plan_date = plan.get("date") or path.name[:10]
        source = plan.get("decisions") if plan.get("schema_version") == 2 else plan.get("actions") or []
        decisions = []
        for i, item in enumerate(source):
            d = legacy_action_to_decision(item, plan_date, i)
            if item.get("user_override"):
                d["override"] = {
                    "status": "active", "reason": str(item.get("user_override")),
                    "expires_on": None, "revisit_condition": "material thesis/risk change",
                }
            key = (plan_date, d["ticker"], d["action"], d["condition"]["type"])
            row = row_queues[key].popleft() if row_queues[key] else None
            _apply_legacy_ground_truth(d, row)
            decisions.append(d)
            all_decisions.append(d)
        migrated = {k: v for k, v in plan.items() if k != "actions"}
        migrated["schema_version"] = 2
        migrated["decisions"] = decisions
        plans.append((path, migrated))

    # Some early calibration rows outlived their plan file or used a legacy key
    # that no longer matches it. They are still raw evidence and must migrate too.
    orphan_n = 0
    for queue in row_queues.values():
        while queue:
            row = queue.popleft()
            item = {
                "ticker": row.get("ticker"), "bucket": row.get("bucket"),
                "trigger_type": row.get("trigger_type"), "trigger_price": row.get("trigger_price"),
                "confidence": row.get("confidence"), "driven_by": row.get("driven_by") or "technical",
                "simulated_entry_price": row.get("sim_entry_price"),
                "rationale": "migrated calibration row; source plan unavailable",
            }
            d = legacy_action_to_decision(item, row.get("plan_date"), 10000 + orphan_n)
            d["migration"] = {"source": "calibration_v1_orphan"}
            _apply_legacy_ground_truth(d, row)
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
        "legacy_rows": len(rows), "migrated_orphan_rows": orphan_n,
        "unmatched_legacy_rows": sum(len(q) for q in row_queues.values()),
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
