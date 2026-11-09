#!/usr/bin/env python3
"""Nightly consolidation candidates from the shared store and recent agent work.

Reads the store, `memctl`'s ledger and recent task/session text, then writes **candidates
only** to `<workspace>/memory/.replay/` (a sibling of `memory/.dreams/`, gitignored). It
never edits the store, `MEMORY.md`, `DREAMS.md` or any public file, and it is not called
from `commit_dreaming.sh`.

Candidate kinds:
  duplicate-merge       two topics carry the same or near-identical body
  contradiction         overlapping topics disagree (stale/superseded/opposite markers)
  unused-high-salience  a high-salience topic has no recall and no recent mention

The report is a review queue, not a promotion: a person decides what to merge or rewrite.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recall  # noqa: E402
from memory import split_frontmatter  # noqa: E402

DEFAULT_STATE = Path(os.environ.get("SHARED_MEMORY_STATE", "~/.local/state/shared-memory")).expanduser()
MAX_PER_KIND = 20
MIN_BODY_CHARS = 80
NEAR_DUPLICATE = 0.85
CONTRADICTION_OVERLAP = 0.35
MAX_SESSION_FILES = 25
MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024

POSITIVE_EN = {"must", "always", "enable", "enabled", "on", "allow", "allowed", "required"}
NEGATIVE_EN = {"never", "off", "disable", "disabled", "forbid", "forbidden", "prohibited"}
POSITIVE_HAN = {"必须", "一律", "启用", "开启", "允许", "只能"}
NEGATIVE_HAN = {"不要", "禁止", "禁用", "关闭", "不能", "不再", "已删", "退役"}
HAN = "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"


def now_from(value: str | None) -> dt.datetime:
    if not value:
        return dt.datetime.now(dt.timezone.utc).astimezone()
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def parse_day(value: str | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_topics(store: Path) -> dict[str, dict]:
    topics: dict[str, dict] = {}
    for path in sorted(store.glob("*.md")):
        if path.name == "MEMORY.md":
            continue
        text = path.read_text(encoding="utf-8")
        try:
            parsed = split_frontmatter(text)
        except ValueError:
            continue
        if parsed is None:
            continue
        fields, meta, body = parsed
        topics[path.stem] = {"slug": path.stem, "text": text, "meta": meta, "fields": fields, "body": body}
    return topics


def normalized_body(body: str) -> str:
    text = re.sub(r"\A\s*#\s+[^\n]*\n+", "", body)
    return re.sub(r"\s+", " ", text.lower()).strip()


def tokens(text: str) -> set[str]:
    lower = text.lower()
    out = set(re.findall(r"[a-z0-9][a-z0-9_+.-]{2,}", lower))
    for run in re.findall(f"[{HAN}]+", lower):
        out.update(run[i:i + 2] for i in range(len(run) - 1))
    return out


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def polarity(text: str) -> tuple[bool, bool]:
    low = text.lower()
    pos = any(marker in low for marker in POSITIVE_HAN) or any(
        re.search(rf"\b{re.escape(marker)}\b", low) for marker in POSITIVE_EN)
    neg = any(marker in low for marker in NEGATIVE_HAN) or any(
        re.search(rf"\b{re.escape(marker)}\b", low) for marker in NEGATIVE_EN)
    return pos, neg


def read_head(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return handle.read(MAX_FILE_BYTES)
    except OSError:
        return ""


def recent_files(root: Path, suffix: str, now: dt.datetime, days: int, limit: int) -> list[Path]:
    if not root.is_dir():
        return []
    cutoff = now.timestamp() - days * 86400
    found = []
    for path in root.rglob(f"*{suffix}"):
        try:
            if path.is_file() and path.stat().st_mtime >= cutoff:
                found.append(path)
        except OSError:
            continue
    found.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return found[:limit]


def collect_text(state: Path, now: dt.datetime, days: int) -> dict:
    """Recent task results and agent session text, bounded by count and bytes."""
    log_dir = Path(os.environ.get("AGENT_DISPATCH_LOG_DIR", Path.home() / "logs" / "agent-dispatch"))
    roots = [(log_dir, "result.env"), (log_dir, "runner-summary.txt")]
    if os.environ.get("SHARED_MEMORY_REPLAY_SESSIONS", "1").lower() not in ("0", "off", "false"):
        roots += [
            (Path.home() / ".codex" / "sessions", ".jsonl"),
            (Path.home() / ".claude" / "projects" / ("-" + str(Path.home()).replace("/", "-").lstrip("-")), ".jsonl"),
        ]
    texts: list[tuple[str, str]] = []
    used = 0
    for root, suffix in roots:
        for path in recent_files(root, suffix, now, days, MAX_SESSION_FILES):
            if used >= MAX_TOTAL_BYTES:
                break
            text = read_head(path)
            if not text:
                continue
            used += len(text.encode("utf-8"))
            texts.append((str(path), text))
    ledger = state / "ledger.jsonl"
    entries = []
    if ledger.is_file():
        for line in ledger.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
    return {
        "texts": texts,
        "ledger": entries,
        "sources": {
            "task_or_session_files": len(texts),
            "ledger_entries": len(entries),
            "bytes_read": used,
        },
    }


def mentions(topics: dict[str, dict], texts: list[tuple[str, str]]) -> dict[str, int]:
    counts = {slug: 0 for slug in topics}
    for _, text in texts:
        low = text.lower()
        for slug in topics:
            counts[slug] += low.count(slug.lower())
    return counts


def guarded(topic: dict) -> list[str]:
    reasons = []
    meta = topic["meta"]
    if (meta.get("status") or "") == "verified":
        reasons.append("verified")
    if (meta.get("publish") or "") == "public":
        reasons.append("publish:public")
    if (meta.get("scope") or "") in ("persona", "memory"):
        reasons.append(f"scope:{meta.get('scope')}")
    return reasons


def build_candidates(store: Path, state: Path, now: dt.datetime, days: int,
                     max_per_kind: int = MAX_PER_KIND) -> dict:
    topics = load_topics(store)
    collected = collect_text(state, now, days)
    recent_mentions = mentions(topics, collected["texts"])
    rows = recall.events()
    stats = recall.build_stats(rows, now=now)
    window_start = now - dt.timedelta(days=30)
    window_counts: dict[str, int] = {}
    for event in rows:
        stamp = recall._parse(event["ts"])
        if stamp is None or stamp < window_start:
            continue
        for slug in event["topics"]:
            window_counts[slug] = window_counts.get(slug, 0) + 1

    duplicates: list[dict] = []
    bodies = {slug: normalized_body(topic["body"]) for slug, topic in topics.items()}
    tokens_by = {slug: tokens(body) for slug, body in bodies.items()}
    exact: dict[str, list[str]] = {}
    for slug, body in bodies.items():
        if len(body) >= MIN_BODY_CHARS:
            exact.setdefault(body, []).append(slug)
    for group in exact.values():
        if len(group) < 2:
            continue
        group.sort()
        duplicates.append({
            "kind": "duplicate-merge",
            "slugs": group,
            "reason": f"identical normalized body ({len(bodies[group[0]])} chars)",
            "similarity": 1.0,
            "manual_only": any(guarded(topics[slug]) for slug in group),
        })
    seen = {frozenset(item["slugs"]) for item in duplicates}
    slugs = sorted(topics)
    for i, left in enumerate(slugs):
        for right in slugs[i + 1:]:
            pair = frozenset((left, right))
            if pair in seen or not bodies[left] or not bodies[right]:
                continue
            score = jaccard(tokens_by[left], tokens_by[right])
            if score >= NEAR_DUPLICATE:
                duplicates.append({
                    "kind": "duplicate-merge",
                    "slugs": [left, right],
                    "reason": f"near-identical body (Jaccard {score:.2f})",
                    "similarity": round(score, 3),
                    "manual_only": guarded(topics[left]) + guarded(topics[right]) != [],
                })
                seen.add(pair)

    contradictions: list[dict] = []
    for i, left in enumerate(slugs):
        for right in slugs[i + 1:]:
            a, b = topics[left], topics[right]
            score = jaccard(tokens_by[left], tokens_by[right])
            if score < CONTRADICTION_OVERLAP:
                continue
            apos, aneg = polarity(a["body"])
            bpos, bneg = polarity(b["body"])
            superseded = ((a["meta"].get("superseded_by") or "").removesuffix(".md") == right
                          or (b["meta"].get("superseded_by") or "").removesuffix(".md") == left)
            stale_pair = ((a["meta"].get("status") == "stale") != (b["meta"].get("status") == "stale"))
            opposite = (apos and bneg) or (aneg and bpos)
            if not (superseded or stale_pair or opposite):
                continue
            reason = ("superseded_by link" if superseded else
                      "one side is stale and the bodies overlap" if stale_pair else
                      "opposite policy markers in overlapping bodies")
            contradictions.append({
                "kind": "contradiction",
                "slugs": [left, right],
                "reason": f"{reason} (Jaccard {score:.2f})",
                "similarity": round(score, 3),
                "manual_only": guarded(a) + guarded(b) != [],
            })

    unused: list[dict] = []
    # Missing observations are not evidence of thirty days without use. Match
    # the retirement report's conservative history floor before nominating.
    usage_observed = stats["coverage"]["days"] >= 30
    for slug, topic in sorted(topics.items()):
        if not usage_observed:
            continue
        if (topic["meta"].get("salience") or "") != "high":
            continue
        updated = parse_day(topic["meta"].get("updated"))
        age = (now.date() - updated).days if updated else None
        if age is None or age < 30:
            continue
        if window_counts.get(slug, 0) or recent_mentions.get(slug, 0):
            continue
        item = stats["topics"].get(slug, {})
        unused.append({
            "kind": "unused-high-salience",
            "slugs": [slug],
            "reason": f"salience=high, {age}d old, zero recalls in 30d, no recent task/session mention",
            "last_recalled": item.get("last_recalled"),
            "count": item.get("count", 0),
            "manual_only": bool(guarded(topic)),
        })

    def capped(rows_: list[dict]) -> list[dict]:
        return rows_[:max_per_kind]

    all_candidates = capped(duplicates) + capped(contradictions) + capped(unused)
    counts = {
        "duplicate-merge": len(duplicates),
        "contradiction": len(contradictions),
        "unused-high-salience": len(unused),
    }
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "store": str(store),
        "window_days": days,
        "sources": collected["sources"],
        "counts": counts,
        "shown": {kind: len(capped([row for row in all_candidates if row["kind"] == kind]))
                  for kind in counts},
        "candidates": all_candidates,
        "notes": [
            "Review queue only; nothing here is promoted or written to the store.",
            "duplicate-merge and contradiction rows need a human decision; manual_only marks public/verified/persona/memory topics.",
        ],
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Shared-memory replay candidates",
        "",
        f"Generated {report['generated_at']} from `{report['store']}`.",
        "Review only: this report never edits the store, `MEMORY.md` or `DREAMS.md`.",
        "",
        f"- recent task/session files read: {report['sources']['task_or_session_files']}",
        f"- `memctl` ledger entries read: {report['sources']['ledger_entries']}",
        "",
    ]
    for kind in ("duplicate-merge", "contradiction", "unused-high-salience"):
        rows = [row for row in report["candidates"] if row["kind"] == kind]
        total = report["counts"][kind]
        lines += [f"## {kind}: {total}", ""]
        if not rows:
            lines += ["None.", ""]
            continue
        for row in rows:
            slugs = " + ".join(f"`{slug}`" for slug in row["slugs"])
            note = " (manual-only)" if row.get("manual_only") else ""
            lines.append(f"- {slugs} — {row['reason']}{note}")
        if total > len(rows):
            lines.append(f"- … {total - len(rows)} more; raise `--max-per-kind` for the full set")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_report(report: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    for path, text in ((out / "candidates.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n"),
                       (out / "report.md", render_markdown(report))):
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", type=Path,
                        default=Path(os.environ.get("SHARED_MEMORY_DIR", "~/.shared-memory")).expanduser())
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--workspace", type=Path,
                        default=Path(os.environ["CLAWOCK_WORKSPACE"]).expanduser()
                        if os.environ.get("CLAWOCK_WORKSPACE") else None)
    parser.add_argument("--out", type=Path, help="default: <workspace>/memory/.replay")
    parser.add_argument("--days", type=int, default=14, help="task/session lookback")
    parser.add_argument("--now", help="ISO timestamp for a reproducible report")
    parser.add_argument("--max-per-kind", type=int, default=MAX_PER_KIND)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.workspace is None:
        parser.error("--workspace (or CLAWOCK_WORKSPACE) is required")
    now = now_from(args.now)
    old_state = os.environ.get("SHARED_MEMORY_STATE")
    os.environ["SHARED_MEMORY_STATE"] = str(args.state)
    try:
        report = build_candidates(args.store, args.state, now, args.days, args.max_per_kind)
        report["workspace"] = str(args.workspace)
    finally:
        if old_state is None:
            os.environ.pop("SHARED_MEMORY_STATE", None)
        else:
            os.environ["SHARED_MEMORY_STATE"] = old_state
    out = args.out or (args.workspace / "memory" / ".replay")
    write_report(report, out)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report), end="")
        print(f"# wrote {out / 'candidates.json'} and {out / 'report.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
