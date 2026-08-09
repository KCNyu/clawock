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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--path", type=Path)
    args = parser.parse_args(argv)

    workspace = workspace_root(Path.cwd())
    portfolio = args.path or workspace / "portfolio.json"
    derivation_policy = workspace / "config" / "portfolio-derivations.json"
    dry = ["--dry-run"] if args.dry_run else []

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
