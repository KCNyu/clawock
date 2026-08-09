#!/usr/bin/env python3
"""
``clawock audit-resettle`` — dry-run the bar-based re-settle and report every
state transition.

A re-settlement moves the public scorecard. "The win rate after the fix" is not a
reportable number on its own: the fix removes some rows and adds others, and if the
removed ones happened to be losers the record improves for no honest reason. This
prints the whole transition matrix so the direction of every change is attributable,
and it never writes the ledger.

  clawock audit-resettle                 # dry-run + full report
  clawock audit-resettle --write         # apply to memory/decisions.jsonl
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter, defaultdict

from clawock import decision_v2 as dv2


def snap(decisions: list[dict]) -> dict:
    return {d["decision_id"]: copy.deepcopy(d.get("evaluation") or {}) for d in decisions}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="persist the re-settled ledger")
    args = ap.parse_args(argv)

    decisions = dv2.load_decisions()
    before = snap(decisions)
    before_eps = {d["decision_id"]: d.get("episode_id") for d in decisions}
    before_exec = {d["decision_id"]: (d.get("execution") or {}).get("status") for d in decisions}

    changed = dv2.settle_decisions(decisions)
    after = snap(decisions)

    print(f"decisions: {len(decisions)} | evaluations changed: {changed}\n")

    # --- invariants: this pass must not touch identity, execution, or grouping ---
    ep_moved = [k for k, v in before_eps.items() if v != {d["decision_id"]: d.get("episode_id") for d in decisions}[k]]
    ex_moved = [k for k, v in before_exec.items()
                if v != {d["decision_id"]: (d.get("execution") or {}).get("status") for d in decisions}[k]]
    print(f"episode_id changed : {len(ep_moved)}  (must be 0 — episode rules were not touched)")
    print(f"execution changed  : {len(ex_moved)}  (must be 0 — execution is ground truth)\n")

    def dist(m, key):
        return Counter(v.get(key) for v in m.values())

    for key in ("status", "outcome", "triggered"):
        b, a = dist(before, key), dist(after, key)
        keys = sorted(set(b) | set(a), key=lambda x: str(x))
        print(f"--- {key}")
        for k in keys:
            d = a[k] - b[k]
            print(f"   {str(k):22} {b[k]:4} → {a[k]:4}  ({d:+d})")
        print()

    # --- transition matrices ---
    print("--- triggered transitions (old → new)")
    tr = Counter((before[k].get("triggered"), after[k].get("triggered")) for k in before)
    for (o, n), c in sorted(tr.items(), key=lambda x: -x[1]):
        mark = "" if o == n else "   <== CHANGED"
        print(f"   {str(o):6} → {str(n):6}  {c:4}{mark}")
    print()

    print("--- outcome transitions (old → new)")
    oc = Counter((before[k].get("outcome"), after[k].get("outcome")) for k in before)
    for (o, n), c in sorted(oc.items(), key=lambda x: -x[1]):
        mark = "" if o == n else "   <== CHANGED"
        print(f"   {str(o):14} → {str(n):14}  {c:4}{mark}")
    print()

    print("--- why decisions became not_evaluable")
    reasons = Counter(v.get("not_evaluable_reason") for v in after.values()
                      if v.get("status") == "not_evaluable")
    for r, c in reasons.most_common():
        print(f"   {str(r):34} {c:4}")
    print()

    print("--- fill model (how triggered calls were priced)")
    fr = Counter(v.get("fill_reason") for v in after.values() if v.get("triggered") is True)
    for r, c in fr.most_common():
        print(f"   {str(r):34} {c:4}")
    print()

    print("--- session mapping")
    sr = Counter(v.get("session_reason") for v in after.values())
    for r, c in sr.most_common():
        print(f"   {str(r):34} {c:4}")
    print()

    # --- the headline, with the unresolved bound that makes it honest ---
    m = dv2.compute_metrics(decisions)
    act = m["active"]
    print("--- 30d active (the number that must not be flattered)")
    print(f"   win_rate {act['win_rate']} | n={act['n_episodes']} | avg {act['avg_benefit_pct']}%")
    print(f"   CI {act['cluster_ci95']}")
    print(f"   settled episodes {m['settled_episodes']} | brier {m['brier']} vs baseline {m['brier_baseline_loo']}")
    print()

    # Coverage must be episode-level: the win rate's denominator is episodes, so
    # counting unresolved *decisions* against it compares two different units.
    by_ep = defaultdict(list)
    for d in decisions:
        if d.get("action") in dv2.ACTIVE_ACTIONS and d.get("episode_id"):
            by_ep[d["episode_id"]].append(d)
    graded = partial = fully_unresolved = 0
    for rows in by_ep.values():
        ok = [r for r in rows if (r.get("evaluation") or {}).get("benefit_t1_pct") is not None]
        bad = [r for r in rows if (r.get("evaluation") or {}).get("status") == "not_evaluable"]
        if not ok:
            fully_unresolved += 1
        elif bad:
            partial += 1
        else:
            graded += 1
    total_ep = len(by_ep)
    print("--- active episode coverage (the win rate's own denominator)")
    print(f"   fully graded            {graded:4}")
    print(f"   partially graded        {partial:4}  (some members dropped → episode mean shifts)")
    print(f"   fully unresolved        {fully_unresolved:4}  (excluded from the rate entirely)")
    print(f"   total active episodes   {total_ep:4}")
    unresolved_d = [d for d in decisions
                    if d.get("action") in dv2.ACTIVE_ACTIONS
                    and (d.get("evaluation") or {}).get("status") == "not_evaluable"]
    reasons = Counter((d.get("evaluation") or {}).get("not_evaluable_reason") for d in unresolved_d)
    print(f"   ({len(unresolved_d)} active decisions unresolved: {dict(reasons)})")
    print("   Excluding hard cases is exactly how a record gets prettier for free, so")
    print("   the coverage is published next to the rate rather than rounded away.")

    if args.write:
        dv2.write_decisions(decisions)
        print(f"\n✓ wrote {dv2.LEDGER}")
    else:
        print("\n(dry-run — ledger untouched; pass --write to apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
