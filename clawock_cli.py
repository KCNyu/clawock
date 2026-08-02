#!/usr/bin/env python3
"""`clawock` — the entry point a stranger reaches for first.

Today the only honest thing it can do is answer "could this run against my
book?", which is precisely the question nobody could previously ask: without
package metadata or a workspace override, the code only ever operated on the
tree it lived in.

    clawock doctor                      # this checkout
    clawock doctor --workspace ~/mybook # someone else's
    CLAWOCK_WORKSPACE=~/mybook clawock doctor
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts" / "data"))

from workspace import ENV_VAR, describe, workspace_root  # noqa: E402


def _doctor(args) -> int:
    default = args.workspace or Path(__file__).resolve().parent
    root = workspace_root(default)
    report = describe(root)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report["problems"] else 1

    print(f"workspace: {report['workspace']}")
    if report["holdings"] is not None:
        print(f"holdings:  {report['holdings']}")
    if not report["problems"]:
        print("✅ runnable")
        return 0
    print(f"❌ not runnable — {len(report['problems'])} problem(s):")
    for problem in report["problems"]:
        print(f"   · {problem}")
    print(f"\nPoint at another workspace with --workspace or ${ENV_VAR}.")
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="clawock", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="can this workspace run the loop?")
    doctor.add_argument("--workspace", type=Path, default=None)
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=_doctor)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
