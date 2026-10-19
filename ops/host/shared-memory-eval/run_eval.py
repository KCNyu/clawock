#!/usr/bin/env python3
"""Score `memory.py search` (or any engine's ranked lists) against the held-out queries.

    run_eval.py                               # the checkout's memory.py on ~/.shared-memory
    run_eval.py --memory-py PATH              # another memory.py (e.g. the installed copy)
    run_eval.py --hits ranked.json            # lists another engine produced: {"query": ["topic.md", ...]}
    run_eval.py --json out.json               # also write every row's result
    run_eval.py --compare before.json         # show the rows whose verdict changed

A row passes when one of its expected topics is among the first --top results (default 3), or,
for a row expecting `-`, when the search lists nothing. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUERIES = HERE / "queries.tsv"
MEMORY_PY = HERE.parent / "shared-memory" / "scripts" / "memory.py"


def load(path: Path) -> list[dict[str, str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            qid, kind, query, expect, source, why = (line.split("\t") + [""] * 6)[:6]
            rows.append({"id": qid, "kind": kind, "query": query, "expect": expect.split(), "source": source, "why": why})
    return rows


def search(memory_py: str, query: str) -> list[str]:
    out = subprocess.run([sys.executable, memory_py, "search", query, "--limit", "50", "--lines", "0"],
                         capture_output=True, text=True).stdout
    return [line.split(" — ")[0].split(" [")[0] for line in out.splitlines() if line and not line.startswith(" ")]


def score(row: dict, hits: list[str], top: int) -> dict:
    if row["expect"] == ["-"]:
        return {**row, "pass": not hits, "rank": None, "n": len(hits), "top": hits[:top]}
    rank = next((i for i, hit in enumerate(hits, 1) if hit in row["expect"]), None)
    return {**row, "pass": rank is not None and rank <= top, "rank": rank, "n": len(hits), "top": hits[:top]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--memory-py", default=str(MEMORY_PY))
    parser.add_argument("--hits", help="JSON {query: [topic, ...]} from another engine")
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--json", help="write every row's result here")
    parser.add_argument("--compare", help="a previous --json output")
    args = parser.parse_args()

    rows = load(QUERIES)
    lists = json.loads(Path(args.hits).read_text(encoding="utf-8")) if args.hits else None
    results = [score(row, lists.get(row["query"], []) if lists is not None else search(args.memory_py, row["query"]), args.top)
               for row in rows]

    for r in results:
        rank = "-" if r["rank"] is None else r["rank"]
        print(f"{'ok  ' if r['pass'] else 'FAIL'} {r['id']} {r['kind']:<11} rank={rank:<3} n={r['n']:<3} "
              f"{r['query'][:40]!r} -> {' '.join(r['top']) or '(nothing)'}")
    passed = Counter(r["kind"] for r in results if r["pass"])
    total = Counter(r["kind"] for r in results)
    print("\n" + "  ".join(f"{kind} {passed[kind]}/{total[kind]}" for kind in sorted(total)))
    print(f"passed {sum(passed.values())}/{len(results)} (top {args.top})")

    if args.compare:
        before = {r["id"]: r for r in json.loads(Path(args.compare).read_text(encoding="utf-8"))}
        for r in results:
            b = before.get(r["id"])
            if b and b["pass"] != r["pass"]:
                print(f"{'fixed ' if r['pass'] else 'BROKEN'} {r['id']} {r['query'][:50]!r}: rank {b['rank']} -> {r['rank']}")
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
