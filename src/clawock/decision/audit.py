"""Read-only absolute and benchmark-relative episode direction scores."""
from __future__ import annotations

import argparse
import json

from clawock.decision import ledger


def main(argv=None):
    parser = argparse.ArgumentParser(prog="clawock decision-audit", description=__doc__)
    parser.add_argument("--json", action="store_true", help="print full metrics and benchmark provenance")
    args = parser.parse_args(argv)
    result = ledger.compute_backtest(ledger.load_decisions())
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print("大盘相对方向分：US→SPY / HK→HSI；不调杠杆，非组合 alpha 或决策增益。")
    for horizon, buckets in result["horizons"].items():
        for name in ("all", "active", "passive", "followed", "followed_active"):
            row = buckets[name]
            print(f"{horizon} {name}: 绝对 {row['avg_benefit_pct']}% | "
                  f"相对 {row['excess_benefit_pct']}pp | "
                  f"episode覆盖 {row['benchmark_coverage_pct']}% "
                  f"({row['benchmark_n_episodes']}/{row['n_episodes']}) | "
                  f"call覆盖 {row['benchmark_call_coverage_pct']}% "
                  f"({row['benchmark_paired_calls']}/{row['benchmark_settled_calls']})")
    return 0
