#!/usr/bin/env python3
"""Measure what the memory layers add over the injected index.

Three modes run the same question set:

  none    no memory at all (the stateless floor);
  index   only MEMORY.md, the layer a session receives without searching;
  search  the note layer reached through `memory.py search` (default top 3).

A positive row is a hit only when the named topic is retrieved *and* the expected
fact is in that topic. A negative row is a false positive when any topic is
retrieved. The fixture store is synthetic so the numbers are repeatable and contain
no private memory; `--store` and `--cases` accept a private pair for a live run.

    run_benefit.py
    run_benefit.py --json after.json
    run_benefit.py --store ~/.shared-memory --cases /path/to/private-cases.tsv

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases.tsv"
FIXTURES = HERE / "fixtures"
MEMORY_PY = HERE.parent.parent / "shared-memory" / "scripts" / "memory.py"


def load(path: Path) -> list[dict[str, str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        qid, question, topic, fact, kind = (line.split("\t") + [""] * 5)[:5]
        rows.append({"id": qid, "question": question, "topic": topic, "fact": fact, "kind": kind})
    return rows


def search(memory_py: str, store: Path, query: str, top: int) -> list[str]:
    proc = subprocess.run([sys.executable, str(memory_py), "search", query, "--limit", str(top), "--lines", "0"],
                          env={"SHARED_MEMORY_DIR": str(store), "PATH": "/usr/bin:/bin"},
                          capture_output=True, text=True, timeout=60)
    if proc.returncode not in (0, 1):
        raise SystemExit(f"search failed for {query!r}: {proc.stderr.strip()[:300]}")
    return [line.split(" — ")[0].split(" [")[0] for line in proc.stdout.splitlines()
            if line and not line.startswith(" ")]


def evaluate(rows: list[dict[str, str]], store: Path, memory_py: str, top: int) -> dict[str, dict]:
    index = (store / "MEMORY.md").read_text(encoding="utf-8")
    modes = {name: {"positives": 0, "hits": 0, "ranks": [], "negatives": 0, "false_positives": 0,
                    "misses": [], "rows": []}
             for name in ("none", "index", "search")}
    for row in rows:
        positive = row["kind"] == "positive"
        expected = row["topic"]
        fact = row["fact"].lower()
        for mode in modes:
            modes[mode]["positives" if positive else "negatives"] += 1
        # The stateless floor cannot answer a store-only fact and cannot retrieve a wrong topic.
        modes["none"]["rows"].append({"id": row["id"], "mode": "none", "hit": False, "rank": None})
        # The injected index can answer only if the fact itself was promoted into it.
        index_hit = positive and fact and fact in index.lower()
        modes["index"]["rows"].append({"id": row["id"], "mode": "index", "hit": index_hit, "rank": None})
        if index_hit:
            modes["index"]["hits"] += 1
            modes["index"]["ranks"].append(1)
        # The note layer needs the expected topic and the fact in that topic.
        hits = search(memory_py, store, row["question"], top)
        rank = next((i for i, hit in enumerate(hits, 1) if hit == expected), None)
        fact_present = rank is not None and fact and fact in (store / expected).read_text(encoding="utf-8").lower()
        search_hit = bool(positive and rank is not None and fact_present)
        modes["search"]["rows"].append({"id": row["id"], "mode": "search", "hit": search_hit, "rank": rank,
                                        "retrieved": hits})
        if positive:
            if search_hit:
                modes["search"]["hits"] += 1
                modes["search"]["ranks"].append(rank)
            else:
                modes["search"]["misses"].append({"id": row["id"], "rank": rank, "retrieved": hits})
        elif hits:
            modes["search"]["false_positives"] += 1
    for mode in modes.values():
        mode["hit_rate"] = round(mode["hits"] / mode["positives"], 3) if mode["positives"] else 0.0
        mode["fp_rate"] = round(mode["false_positives"] / mode["negatives"], 3) if mode["negatives"] else 0.0
        mode["avg_rank"] = round(sum(mode["ranks"]) / len(mode["ranks"]), 2) if mode["ranks"] else None
    return modes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", default=str(FIXTURES), help="memory store (default: synthetic fixtures)")
    parser.add_argument("--cases", default=str(CASES), help="TSV cases (default: synthetic fixtures)")
    parser.add_argument("--memory-py", default=str(MEMORY_PY))
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--json", help="write the per-mode and per-row results here")
    args = parser.parse_args()

    rows = load(Path(args.cases))
    store = Path(args.store).expanduser()
    modes = evaluate(rows, store, args.memory_py, args.top)

    print(f"{'mode':<8} {'positive':>8} {'hits':>5} {'hit%':>6} {'avg rank':>8} {'negative':>8} {'false+':>6} {'fp%':>5}")
    for name in ("none", "index", "search"):
        mode = modes[name]
        rank = "-" if mode["avg_rank"] is None else f"{mode['avg_rank']:.2f}"
        print(f"{name:<8} {mode['positives']:>8} {mode['hits']:>5} {mode['hit_rate']:>6.2f} {rank:>8} "
              f"{mode['negatives']:>8} {mode['false_positives']:>6} {mode['fp_rate']:>5.2f}")
    for miss in modes["search"]["misses"]:
        print(f"miss {miss['id']}: rank={miss['rank']} retrieved={' '.join(miss['retrieved']) or '(nothing)'}")
    if args.json:
        Path(args.json).write_text(json.dumps(modes, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
