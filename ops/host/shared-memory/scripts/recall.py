#!/usr/bin/env python3
"""Private recall counter for the shared memory store.

Every reader appends one line per recall to
`${SHARED_MEMORY_STATE:-~/.local/state/shared-memory}/recall.jsonl`:

    {"ts":"2026-11-08T18:00:00+08:00","source":"python-search","topics":["feedback-x"]}

No query text, no snippets, no user id. The file is 0600 and lives outside the store and
the repository. `stats` derives `recall-stats.json` (`count`, `last_recalled`, `sources`
per topic), which is what the nightly retirement report reads.

Appends are best-effort: a failed counter write must never fail a search or a read.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

STATE_DIR = Path(os.environ.get("SHARED_MEMORY_STATE", "~/.local/state/shared-memory")).expanduser()
LOG_NAME = "recall.jsonl"
STATS_NAME = "recall-stats.json"
SOURCES = ("openclaw-supplement", "openclaw-get", "python-search", "python-read",
           "cron-brief", "inject-direct", "inject-worker", "inject-investment-cron")


def state_dir() -> Path:
    return Path(os.environ.get("SHARED_MEMORY_STATE", str(STATE_DIR))).expanduser()


def log_path() -> Path:
    override = os.environ.get("SHARED_MEMORY_RECALL_LOG")
    return Path(override).expanduser() if override else state_dir() / LOG_NAME


def _clean_topics(topics) -> list[str]:
    seen: list[str] = []
    for topic in topics or ():
        slug = str(topic).strip().removesuffix(".md")
        if not slug or ".." in slug or not all(ch.isalnum() or ch in "-_./" for ch in slug):
            continue
        if slug not in seen:
            seen.append(slug)
    return seen


def record(source: str, topics, *, when: dt.datetime | None = None) -> bool:
    """Append one recall event. Returns True when it was written.

    Never raises: a memory read must not fail because the counter is unavailable.
    """
    if os.environ.get("SHARED_MEMORY_RECALL", "").lower() in ("0", "off", "false"):
        return False
    slugs = _clean_topics(topics)
    if not source or not slugs:
        return False
    stamp = (when or dt.datetime.now(dt.timezone.utc).astimezone()).isoformat(timespec="seconds")
    line = json.dumps({"ts": stamp, "source": source, "topics": slugs},
                      ensure_ascii=False, separators=(",", ":")) + "\n"
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
        os.chmod(path, 0o600)
        return True
    except OSError:
        return False


def events(path: Path | None = None):
    path = path or log_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        source = event.get("source")
        topics = event.get("topics")
        stamp = event.get("ts")
        if not isinstance(source, str) or not isinstance(stamp, str) or not isinstance(topics, list):
            continue
        topics = _clean_topics(topics)
        if topics:
            out.append({"ts": stamp, "source": source, "topics": topics})
    return out


def _parse(ts: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def build_stats(rows, *, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc).astimezone()
    topics: dict[str, dict] = {}
    sources: dict[str, dict] = {}
    first = last = None
    for row in rows:
        stamp = _parse(row["ts"])
        if stamp is None:
            continue
        if first is None or stamp < first:
            first = stamp
        if last is None or stamp > last:
            last = stamp
        source = row["source"]
        bucket = sources.setdefault(source, {"events": 0, "topics": 0, "_topics": set()})
        bucket["events"] += 1
        for slug in row["topics"]:
            item = topics.setdefault(slug, {"count": 0, "last_recalled": None, "sources": {}})
            item["count"] += 1
            item["sources"][source] = item["sources"].get(source, 0) + 1
            if item["last_recalled"] is None or stamp > _parse(item["last_recalled"]):
                item["last_recalled"] = stamp.isoformat(timespec="seconds")
            bucket["_topics"].add(slug)
    for bucket in sources.values():
        bucket["topics"] = len(bucket.pop("_topics"))
    coverage_days = 0.0
    if first and last:
        coverage_days = round((last - first).total_seconds() / 86400, 2)
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "coverage": {
            "first": first.isoformat(timespec="seconds") if first else None,
            "last": last.isoformat(timespec="seconds") if last else None,
            "days": coverage_days,
            "events": len(rows),
        },
        "sources": dict(sorted(sources.items())),
        "topics": dict(sorted(topics.items())),
    }


def write_stats(path: Path | None = None, *, now: dt.datetime | None = None,
                stats: dict | None = None) -> dict:
    stats = stats or build_stats(events(), now=now)
    path = path or state_dir() / STATS_NAME
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record", help="append one recall event")
    rec.add_argument("--source", required=True)
    rec.add_argument("topics", nargs="+")
    stats = sub.add_parser("stats", help="print or write the derived per-topic counters")
    stats.add_argument("--write", action="store_true")
    stats.add_argument("--json", action="store_true")
    log = sub.add_parser("log", help="print recent recall events")
    log.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    if args.command == "record":
        return 0 if record(args.source, args.topics) else 1
    if args.command == "log":
        for row in events()[-args.limit:]:
            print(json.dumps(row, ensure_ascii=False))
        return 0
    if args.write:
        stats_data = write_stats()
    else:
        stats_data = build_stats(events())
    if args.json:
        print(json.dumps(stats_data, ensure_ascii=False, indent=2))
    else:
        coverage = stats_data["coverage"]
        print(f"coverage: {coverage['days']} day(s), {coverage['events']} event(s), "
              f"{len(stats_data['topics'])} topic(s)")
        for slug, item in stats_data["topics"].items():
            print(f"{slug}\t{item['count']}\t{item['last_recalled']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
