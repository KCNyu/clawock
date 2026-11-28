#!/usr/bin/env python3
"""Replay offline behavior cases through the existing deterministic graders."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def trial(nodes, output, scratch):
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--junitxml", str(output),
         "--basetemp", str(scratch), *nodes],
        cwd=ROOT, check=False, stdout=sys.stderr,
    )
    if completed.returncode not in (0, 1) or not output.is_file():
        raise RuntimeError(f"eval collection or execution failed (pytest exit {completed.returncode})")
    reports = defaultdict(list)
    for test in ET.parse(output).iter("testcase"):
        path = test.attrib["classname"].replace(".", "/") + ".py"
        name = test.attrib["name"].split("[", 1)[0]
        passed = all(test.find(state) is None for state in ("failure", "error", "skipped"))
        reports[f"{path}::{name}"].append(passed)
    if set(reports) != set(nodes):
        raise RuntimeError("the evaluated nodes do not match the case registry")
    return {node: all(reports[node]) for node in nodes}


def summarize(rows):
    return {
        "cases": len(rows),
        "pass@k": sum(any(row["trials"]) for row in rows) / len(rows),
        "pass^k": sum(all(row["trials"]) for row in rows) / len(rows),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", default=3, type=int)
    parser.add_argument("--track", default="all", choices=("all", "regression", "capability"))
    args = parser.parse_args()
    if not 1 <= args.trials <= 10:
        parser.error("--trials must be between 1 and 10")
    cases = json.loads((ROOT / "evals/cases.json").read_text())
    cases = [case for case in cases if args.track in ("all", case["track"])]
    nodes = [case["node"] for case in cases]
    if not nodes or len(set(nodes)) != len(nodes):
        raise ValueError("the selected case registry is empty or contains duplicate tests")
    runs = []
    with TemporaryDirectory(prefix="brief-eval-") as directory:
        root = Path(directory)
        for i in range(args.trials):
            runs.append(trial(nodes, root / f"{i}.xml", root / f"trial-{i}"))

    rows = [{**case, "trials": [run[case["node"]] for run in runs]} for case in cases]
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["track"]].append(row)
        if row["dimension"] == "citation_accuracy":
            grouped["citation_accuracy"].append(row)
    summary = {name: summarize(group) for name, group in grouped.items()}
    print(json.dumps({"k": args.trials, "summaries": summary, "cases": rows}, indent=2))
    return 0 if all(all(row["trials"]) for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
