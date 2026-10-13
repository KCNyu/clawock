import collections
import json
import sys

rows = [json.loads(line) for line in open(sys.argv[1])]
total = sum(r["d"] for r in rows)
tests = collections.defaultdict(float)
files = collections.defaultdict(float)
phase = collections.defaultdict(float)
for r in rows:
    tests[r["id"]] += r["d"]
    files[r["id"].split("::")[0]] += r["d"]
    phase[r["when"]] += r["d"]
print(f"tests={len(tests)} files={len(files)} summed_seconds={total:.1f}")
print("by phase:", {k: round(v, 1) for k, v in phase.items()})
ranked = sorted(tests.values(), reverse=True)
for n in (10, 20, 50, 100, 200, 500, 1000):
    print(f"top {n:>4} tests: {sum(ranked[:n]):7.1f}s = {100 * sum(ranked[:n]) / total:5.1f}%")
print(f"tests over 1s: {sum(1 for v in ranked if v > 1)}, over 0.25s: {sum(1 for v in ranked if v > 0.25)}")
print("-- per worker")
workers = collections.defaultdict(list)
for r in rows:
    workers[r["w"]].append(r)
starts = [r["start"] for r in rows if r["start"]]
t0 = min(starts) if starts else 0
for name, items in sorted(workers.items()):
    busy = sum(r["d"] for r in items)
    first = min((r["start"] for r in items if r["start"]), default=0) - t0
    last = max((r["stop"] for r in items if r["stop"]), default=0) - t0
    print(f"{name}: reports={len(items)} busy={busy:.1f}s first_start=+{first:.1f}s last_stop=+{last:.1f}s")
print("-- slowest 40 files")
for name, value in sorted(files.items(), key=lambda kv: -kv[1])[:40]:
    print(f"{value:7.1f}s {name}")
print("-- slowest 40 tests")
for name, value in sorted(tests.items(), key=lambda kv: -kv[1])[:40]:
    print(f"{value:7.1f}s {name}")
failed = sorted({r["id"] for r in rows if r["outcome"] == "failed"})
print(f"-- failed ({len(failed)})")
for name in failed:
    print("FAILED-ID", name)
