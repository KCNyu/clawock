#!/usr/bin/env python3
"""Nominate retirement candidates from the shared memory store — never execute one.

The report is private (`~/.local/state/shared-memory/`), runs after dreaming, and only
lists topics a person may archive. It never edits, moves or deletes a topic, and it is
not part of `commit_dreaming.sh`'s `set -e` chain.

Rules:
  stale      status=stale and updated older than STALE_DAYS
  unused     zero recalls over USAGE_DAYS, only when explicitly enabled and the counter
             already covers at least MIN_COVERAGE_DAYS (the rule ships disabled)
  superseded metadata.superseded_by points at another active topic
  duplicate  two active topics carry the same normalized body

Every topic that is verified, linked/cited by another topic or an index, public, in
`persona`/`memory`, or missing a write-time field is `manual_only` and never appears in
`candidates`.
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
from memory import index_refs, split_frontmatter  # noqa: E402
from replay import now_from  # noqa: E402

STALE_DAYS = int(os.environ.get("SHARED_MEMORY_STALE_DAYS", "90"))
USAGE_DAYS = int(os.environ.get("SHARED_MEMORY_USAGE_DAYS", "30"))
MIN_COVERAGE_DAYS = 30
# The usage rule is written here and deliberately off until the counter has a history.
USAGE_RULE_ENABLED = os.environ.get("SHARED_MEMORY_USAGE_RULE", "0").lower() in ("1", "on", "true")
REQUIRED = ("scope", "salience", "status", "publish", "agent")
VALID = {
    "salience": {"high", "normal", "low"},
    "status": {"verified", "hypothesis", "stale"},
    "publish": {"public", "private"},
}
SCOPE_RE = re.compile(r"[a-z][a-z0-9_-]*")
LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
ROUTE_RE = re.compile(r"`([a-zA-Z0-9][\w.-]*)\.md`")


def parse_day(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def normalize_body(body: str) -> str:
    # The topic heading names the file, not the fact; two copies of one paragraph under
    # different headings are still duplicates.
    text = re.sub(r"\A\s*#\s+[^\n]*\n+", "", body)
    return re.sub(r"\s+", " ", text.lower()).strip()


def topic_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_topics(store: Path) -> dict[str, dict]:
    topics: dict[str, dict] = {}
    for path in sorted(store.glob("*.md")):
        if path.name == "MEMORY.md":
            continue
        text = path.read_text(encoding="utf-8")
        try:
            parsed = split_frontmatter(text)
        except ValueError as exc:
            topics[path.stem] = {"slug": path.stem, "path": path, "text": text, "error": str(exc),
                                 "meta": {}, "fields": {}, "body": ""}
            continue
        if parsed is None:
            topics[path.stem] = {"slug": path.stem, "path": path, "text": text, "error": "no frontmatter",
                                 "meta": {}, "fields": {}, "body": text}
            continue
        fields, meta, body = parsed
        topics[path.stem] = {"slug": path.stem, "path": path, "text": text, "error": None,
                             "meta": meta, "fields": fields, "body": body}
    return topics


def reference_index(store: Path, topics: dict[str, dict]) -> dict[str, list[str]]:
    """slug -> evidence strings from other topics, index hooks and redirects."""
    refs: dict[str, list[str]] = {}
    for slug, topic in topics.items():
        for link in LINK_RE.findall(topic["body"]):
            target = link.strip().removesuffix(".md")
            if target and target != slug:
                refs.setdefault(target, []).append(f"{slug}: [[{target}]]")
        for link in ROUTE_RE.findall(topic["body"]):
            if link != slug:
                refs.setdefault(link, []).append(f"{slug}: `{link}.md`")
    for index in sorted((store / "indexes").glob("*.md")):
        for line in index.read_text(encoding="utf-8").splitlines():
            routes = index_refs(line)
            for route in routes:
                slug = Path(route).stem
                # The topic's own single-route hook is not evidence of use; a grouped hook
                # or a second index line is.
                if len(routes) > 1 or slug not in topics:
                    refs.setdefault(slug, []).append(f"{index.name}: {line.strip()[:120]}")
    for name in ("routes.tsv", "redirects.tsv"):
        path = store / "indexes" / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            for part in parts:
                for slug in topics:
                    if re.fullmatch(rf".*{re.escape(slug)}.*", part):
                        refs.setdefault(slug, []).append(f"indexes/{name}: {line.strip()[:120]}")
    return refs


def guard_reasons(topic: dict, refs: list[str]) -> list[str]:
    reasons: list[str] = []
    if topic["error"]:
        reasons.append(f"unparseable: {topic['error']}")
    fields, meta = topic["fields"], topic["meta"]
    for key in REQUIRED:
        if not (meta.get(key) or fields.get(key)):
            reasons.append(f"missing {key}")
        elif key in VALID and (meta.get(key) or fields.get(key)) not in VALID[key]:
            reasons.append(f"invalid {key}")
    scope = meta.get("scope") or fields.get("scope")
    if scope and not SCOPE_RE.fullmatch(scope):
        reasons.append("invalid scope")
    if (meta.get("status") or fields.get("status")) == "verified":
        reasons.append("status=verified")
    if (meta.get("publish") or fields.get("publish")) == "public":
        reasons.append("publish=public")
    if scope in ("persona", "memory"):
        reasons.append(f"scope={scope}")
    if refs:
        reasons.append("referenced: " + "; ".join(refs[:3]))
    return reasons


def candidate_report(store: Path, *, now: dt.datetime, usage_enabled: bool = USAGE_RULE_ENABLED,
                     stale_days: int = STALE_DAYS, usage_days: int = USAGE_DAYS) -> dict:
    topics = load_topics(store)
    refs = reference_index(store, topics)
    rows = recall.events()
    stats = recall.build_stats(rows, now=now)
    recall.write_stats(now=now, stats=stats)
    window_start = now - dt.timedelta(days=usage_days)
    window_counts: dict[str, int] = {}
    for event in rows:
        stamp = recall._parse(event["ts"])
        if stamp is None or stamp < window_start:
            continue
        for slug in event["topics"]:
            window_counts[slug] = window_counts.get(slug, 0) + 1

    candidates: list[dict] = []
    guarded: list[dict] = []
    seen_duplicates: set[tuple[str, str]] = set()

    def base(topic: dict) -> dict:
        meta = topic["meta"]
        age = None
        updated = parse_day(meta.get("updated") or topic["fields"].get("updated"))
        if updated:
            age = (now.date() - updated).days
        item = stats["topics"].get(topic["slug"], {})
        return {
            "slug": topic["slug"],
            "reason": None,
            "evidence": "",
            "proposed_action": "archive",
            "age_days": age,
            "last_recalled": item.get("last_recalled"),
            "count": item.get("count", 0),
            "window_count": window_counts.get(topic["slug"], 0),
            "source_hash": topic_hash(topic["text"]),
            "manual_only": False,
        }

    for slug, topic in sorted(topics.items()):
        reasons = guard_reasons(topic, refs.get(slug, []))
        item = base(topic)
        if reasons:
            item.update(manual_only=True, reason="guarded", evidence="; ".join(reasons))
            guarded.append(item)
            continue
        status = topic["meta"].get("status")
        updated = parse_day(topic["meta"].get("updated"))
        if status == "stale" and item["age_days"] is not None and item["age_days"] >= stale_days:
            item.update(reason="stale", proposed_action="archive",
                        evidence=f"status=stale, updated {updated} ({item['age_days']}d >= {stale_days}d)")
            candidates.append(item)
            continue
        superseded = (topic["meta"].get("superseded_by") or "").strip().removesuffix(".md")
        if superseded and superseded in topics and superseded != slug:
            item.update(reason="superseded", proposed_action="archive",
                        evidence=f"superseded_by={superseded}")
            candidates.append(item)
            continue
        if usage_enabled and stats["coverage"]["days"] >= MIN_COVERAGE_DAYS:
            fresh_enough = item["age_days"] is not None and item["age_days"] >= usage_days
            if fresh_enough and item["window_count"] == 0:
                item.update(reason="unused", proposed_action="archive",
                            evidence=f"zero recalls in {usage_days}d; counter covers "
                                     f"{stats['coverage']['days']}d; updated {updated}")
                candidates.append(item)
                continue

    # Duplicates are proposed as one merge row, not two archive rows.
    duplicate_candidates: list[dict] = []
    duplicate_slugs: set[str] = set()
    by_body: dict[str, list[dict]] = {}
    for slug, topic in topics.items():
        if guard_reasons(topic, refs.get(slug, [])):
            continue
        normalized = normalize_body(topic["body"])
        if len(normalized) >= 80:
            by_body.setdefault(normalized, []).append(topic)
    for group in by_body.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda topic: ({"low": 0, "normal": 1, "high": 2}.get(topic["meta"].get("salience"), 1),
                                      topic["slug"]))
        keep = group[0]
        for other in group[1:]:
            pair = tuple(sorted((keep["slug"], other["slug"])))
            if pair in seen_duplicates:
                continue
            seen_duplicates.add(pair)
            item = base(other)
            item.update(reason="duplicate", proposed_action="merge", slug=keep["slug"],
                        evidence=f"same normalized body as {other['slug']} ({len(normalized)} chars)")
            item["related"] = [keep["slug"], other["slug"]]
            duplicate_candidates.append(item)
            duplicate_slugs.update((keep["slug"], other["slug"]))
    if duplicate_slugs:
        candidates = [item for item in candidates if item["slug"] not in duplicate_slugs]
        candidates.extend(duplicate_candidates)

    counts: dict[str, int] = {}
    for item in candidates:
        counts[item["reason"]] = counts.get(item["reason"], 0) + 1
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "store": str(store),
        "rules": {
            "stale_days": stale_days,
            "usage_days": usage_days,
            "usage_rule_enabled": usage_enabled,
            "min_coverage_days": MIN_COVERAGE_DAYS,
            "coverage_days": stats["coverage"]["days"],
            "action": "nominate only; no store writes",
        },
        "counts": counts,
        "total_candidates": len(candidates),
        "total_guarded": len(guarded),
        "candidates": candidates,
        "guarded": guarded,
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Shared-memory retirement candidates",
        "",
        f"Generated {report['generated_at']} from `{report['store']}`.",
        "Nomination only: this report never edits, archives or deletes a topic.",
        "",
        f"- candidates: **{report['total_candidates']}**",
        f"- guarded (never automatic): **{report['total_guarded']}**",
        f"- counter coverage: {report['rules']['coverage_days']} day(s)",
        f"- usage rule: {'on' if report['rules']['usage_rule_enabled'] else 'off'} "
        f"(zero recall over {report['rules']['usage_days']}d, needs {report['rules']['min_coverage_days']}d coverage)",
        "",
    ]
    if not report["candidates"]:
        lines.append("No candidate meets an enabled rule.")
    for kind in ("stale", "unused", "superseded", "duplicate"):
        rows = [item for item in report["candidates"] if item["reason"] == kind]
        if not rows:
            continue
        lines += [f"## {kind} ({len(rows)})", ""]
        for item in rows:
            lines.append(f"- `{item['slug']}` — {item['evidence']} → {item['proposed_action']}")
        lines.append("")
    guarded = report["guarded"]
    if guarded:
        lines += [f"## Guarded ({len(guarded)})", ""]
        for item in guarded[:20]:
            lines.append(f"- `{item['slug']}` — {item['evidence']}")
        if len(guarded) > 20:
            lines.append(f"- … {len(guarded) - 20} more in the JSON report")
    return "\n".join(lines).rstrip() + "\n"


def write_report(report: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    for path, text in ((output, json.dumps(report, ensure_ascii=False, indent=2) + "\n"),
                       (output.with_suffix(".md"), render_markdown(report))):
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", type=Path,
                        default=Path(os.environ.get("SHARED_MEMORY_DIR", "~/.shared-memory")).expanduser())
    parser.add_argument("--output", type=Path,
                        default=Path(os.environ.get("SHARED_MEMORY_STATE", "~/.local/state/shared-memory")).expanduser()
                        / "retirement-candidates.json")
    parser.add_argument("--now", help="ISO timestamp for a reproducible report")
    parser.add_argument("--enable-usage-rule", action="store_true",
                        help="enable the zero-recall rule (default: off until the counter has history)")
    parser.add_argument("--stale-days", type=int, default=STALE_DAYS)
    parser.add_argument("--usage-days", type=int, default=USAGE_DAYS)
    parser.add_argument("--json", action="store_true", help="print the JSON report")
    args = parser.parse_args()
    now = now_from(args.now)
    report = candidate_report(args.store, now=now, usage_enabled=args.enable_usage_rule or USAGE_RULE_ENABLED,
                              stale_days=args.stale_days, usage_days=args.usage_days)
    write_report(report, args.output)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report), end="")
        print(f"# wrote {args.output} and {args.output.with_suffix('.md')}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
