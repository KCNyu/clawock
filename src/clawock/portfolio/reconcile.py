"""Recompute every derived money field, then run the integrity gate.

This is the single command to run after editing trades, cash adjustments, or
broker-truth leaves in ``portfolio.json``.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from clawock.portfolio import aggregates, cash, integrity, realized
from clawock.workspace import workspace_root


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='clawock reconcile', description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--path", type=Path)
    args = parser.parse_args(argv)

    workspace = workspace_root()
    portfolio = args.path or workspace / "portfolio.json"
    derivation_policy = workspace / "config" / "portfolio-derivations.json"
    dry = ["--dry-run"] if args.dry_run else []

    # `realized` does raw arithmetic on each fill, so a quoted fill number
    # would crash it before the gate below could name the row (#2186).
    malformed = [f for f in integrity.check(portfolio)['findings']
                 if f['code'] == 'TRADE_NUMERIC_INVALID']
    if malformed:
        for f in malformed:
            print(f"🔴 {f['code']} [{f.get('region') or '-'}] {f['msg']}")
        print("\n成交行有非数字字段，先修正再重算 → ❌ 未重算")
        return 2

    print("▸ recompute aggregates")
    aggregates.main(["--path", str(portfolio), "--config", str(derivation_policy), *dry])
    print("▸ recompute cash")
    cash.main(["--path", str(portfolio), "--config", str(derivation_policy), *dry])
    print("▸ recompute realized P&L")
    realized.main(["--path", str(portfolio), *dry])
    print("▸ verify money conservation")
    return integrity.main([str(portfolio)])


if __name__ == "__main__":
    raise SystemExit(main())
