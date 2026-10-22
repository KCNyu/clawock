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
import contextlib
import copy
import sys
from collections import Counter

from clawock.decision import ledger as dv2


def snap(decisions: list[dict]) -> dict:
    return {d["decision_id"]: copy.deepcopy(d.get("evaluation") or {}) for d in decisions}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="clawock audit-resettle")
    ap.add_argument("--write", action="store_true", help="persist the re-settled ledger")
    args = ap.parse_args(argv)
    # `--write` rewrites the ledger from the copy loaded below, so the lock has to
    # cover the whole report, not just the final write (#1482).
    with (dv2.ledger_lock() if args.write else contextlib.nullcontext()):
        return _resettle(args)


def _resettle(args) -> int:
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

    # Use the headline's window and episode owner, including pending reasons.
    coverage = m["coverage_active"]
    print("--- active episode coverage, last 30d (the win rate's own denominator)")
    print(f"   fully graded            {coverage['episodes_graded']:4}")
    print(f"   partially graded        {coverage['episodes_partial']:4}  (some members dropped → episode mean shifts)")
    print(f"   fully unresolved        {coverage['episodes_unresolved']:4}  (excluded from the rate entirely)")
    print(f"   never triggered         {coverage['episodes_not_triggered']:4}  (no member fired; not a call to grade)")
    print(f"   total active episodes   {coverage['episodes_total']:4}")
    print(f"   graded coverage         {coverage['graded_pct']}%")
    # Reasons are per distinct reason per ungraded episode (#3151), so they
    # overlap and need not sum to the unresolved + never-triggered rows.
    print(f"   ungraded episode reasons (overlapping): {coverage['unresolved_reasons']}")
    print("   Excluding hard cases is exactly how a record gets prettier for free, so")
    print("   the coverage is published next to the rate rather than rounded away.")

    coverage = m["coverage_passive"]
    print("--- passive episode coverage, last 30d")
    print(f"   total {coverage['episodes_total']} | fully graded {coverage['episodes_graded']} | partially graded {coverage['episodes_partial']} | unresolved {coverage['episodes_unresolved']} | never triggered {coverage['episodes_not_triggered']}")
    print(f"   graded coverage {coverage['graded_pct']}% | reasons (overlapping) {coverage['unresolved_reasons']}")

    if args.write:
        dv2.write_decisions(decisions)
        print(f"\n✓ wrote {dv2.LEDGER}")
    else:
        print("\n(dry-run — ledger untouched; pass --write to apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
