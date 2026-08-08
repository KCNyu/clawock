#!/usr/bin/env python3
"""Record execution ground truth in the v2 decision ledger.

Usage:
  mark_followed.py DECISION_ID [--no]
  mark_followed.py --list
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from clawock import decision_v2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("decision_id", nargs="?")
    ap.add_argument("--no", action="store_true", help="mark not_followed")
    ap.add_argument("--list", action="store_true", help="list unknown triggered decisions")
    args = ap.parse_args()
    rows = decision_v2.load_decisions()
    if args.list:
        for d in rows:
            if (d.get("execution") or {}).get("status") == "unknown" and (d.get("evaluation") or {}).get("triggered") is True:
                print(d["decision_id"], d["plan_date"], d["ticker"], d["strategy_id"], d["action"])
        return
    if not args.decision_id:
        ap.error("DECISION_ID is required unless --list is used")
    found = False
    for d in rows:
        if d.get("decision_id") == args.decision_id:
            d["execution"] = {"status": "not_followed" if args.no else "followed",
                              "source": "manual", "detected_at": None}
            found = True
            break
    if not found:
        raise SystemExit(f"decision not found: {args.decision_id}")
    decision_v2.write_decisions(rows)
    print(f"{args.decision_id}: {'not_followed' if args.no else 'followed'}")


if __name__ == "__main__":
    main()
