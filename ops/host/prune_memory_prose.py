#!/usr/bin/env python3
"""Retention for the workspace's untracked memory prose (#1069).

kcn's rule, 2026-08-26: 「这些 memory 可以有但要定时清理而且不能进 repo」 —— the
same shape as the interactive agents' own durable memory: a curated index that
is kept, and raw per-session prose that ages out on a schedule.

`.gitignore` owns the second half (nothing here can enter the repository). This
job owns the first: the prose classes below are deleted once they pass their
retention window. Nothing curated is in scope — `MEMORY.md`, the daily briefs
(`memory/*-pre-open.md`), the plans, bars, snapshots and the decision ledger are
all tracked repository data and are structurally out of reach here.

**The safety invariant is tracking, not the glob.** A file is deleted only when
git both ignores it AND does not track it. A wrong pattern can therefore delete
nothing that matters: every artifact the dashboards, the ledger or the site read
is tracked, so it fails the check no matter what a glob says.

Run daily from the host crontab; `--dry-run` prints the same report without
deleting. The counts go to logs/memory_prune.log, which
`ops/system_check.py::check_host_cron_logs` already watches for crash tails
(it derives its targets from the crontab, so no registration is needed).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

# Suffixes that share the dated prefix but are tracked repository data: the
# daily brief and its plan. The tracked guard below would protect them anyway —
# this keeps them out of the report so a real "protected" line stays a signal.
KEEP_SUFFIXES = ("-pre-open.md", "-plan.json")

# (label, glob relative to the workspace, retention days)
#
# Windows are deliberately different: session prose is re-read only while the
# work it describes is still in flight, dreaming output is promoted into
# MEMORY.md within a night and kept longer only for the memory index's recall,
# and `.tmp` is same-day scratch that several harness phases hand to each other.
CLASSES = (
    ("session prose (dated)", "memory/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*.md", 14),
    ("dreaming notes", "memory/dreaming/*/*.md", 30),
    ("dream scratch", "memory/.dreams/**/*", 30),
    ("harness scratch", "memory/.tmp/**/*", 7),
)


def _git(root: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], input=stdin,
                          capture_output=True, text=True)


def _deletable(root: Path, candidates: list[Path]) -> list[Path]:
    """The subset git ignores AND does not track.

    Both halves are load-bearing. `check-ignore` answers about patterns, not
    about tracking — a tracked file matching an ignore rule still reports as
    ignored — so the tracked set is what actually protects repository data.
    """
    if not candidates:
        return []
    rel = [p.relative_to(root).as_posix() for p in candidates]
    ignored = _git(root, "check-ignore", "--stdin", stdin="\n".join(rel) + "\n")
    ignored_set = {line.strip() for line in ignored.stdout.splitlines() if line.strip()}
    tracked = _git(root, "ls-files", "--", "memory")
    tracked_set = {line.strip() for line in tracked.stdout.splitlines() if line.strip()}
    return [p for p, name in zip(candidates, rel)
            if name in ignored_set and name not in tracked_set]


def prune(root: Path, *, now: float | None = None, dry_run: bool = False) -> list[dict]:
    now = time.time() if now is None else now
    report = []
    for label, pattern, days in CLASSES:
        cutoff = now - days * 86400
        matched = [p for p in root.glob(pattern)
                   if p.is_file() and not p.name.endswith(KEEP_SUFFIXES)]
        old = [p for p in matched if p.stat().st_mtime < cutoff]
        removable = _deletable(root, old)
        freed = sum(p.stat().st_size for p in removable)
        if not dry_run:
            for path in removable:
                try:
                    path.unlink()
                except OSError as exc:  # a writer holding it is not our problem
                    print(f"  ! {path.name}: {exc}", file=sys.stderr)
        report.append({
            "label": label, "days": days, "matched": len(matched),
            "removed": len(removable), "kept": len(matched) - len(removable),
            "bytes": freed,
            # A file that is old but neither ignored nor untracked is the
            # interesting case: it means a pattern reaches repository data.
            "protected": len(old) - len(removable),
        })
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workspace", type=Path,
                    default=Path(__file__).resolve().parents[2])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    root = args.workspace.resolve()
    if not (root / ".git").exists():
        print(f"not a git checkout: {root}", file=sys.stderr)
        return 2

    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    verb = "would remove" if args.dry_run else "removed"
    total = 0
    print(f"{stamp} memory-prune{' (dry run)' if args.dry_run else ''}")
    for row in prune(root, dry_run=args.dry_run):
        total += row["bytes"]
        note = f" · {row['protected']} protected (tracked)" if row["protected"] else ""
        print(f"  {row['label']:<22} >{row['days']}d: {verb} {row['removed']}, "
              f"kept {row['kept']}, {row['bytes'] / 1024:.0f}K{note}")
    print(f"  total {verb}: {total / 1024:.0f}K")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
