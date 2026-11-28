#!/usr/bin/env python3
"""Audit the legacy recall corpus without modifying it."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "shared-memory" / "scripts"))

import replay  # noqa: E402
import review_dreaming as gate  # noqa: E402
import review_dreams  # noqa: E402

TRANSIENT = re.compile(
    r"\b(?:nothing to report|no (?:significant|notable|substantive))\b"
    r"|没有值得|暂无|未发现.{0,8}(?:变化|结论)|无重要更新",
    re.I,
)


def paragraphs(text: str):
    """Drop structural lines and fenced snippets before counting prose units."""
    text = re.sub(r"\A---\n[\s\S]*?\n---(?:\n|\Z)", "", text)
    text = re.sub(r"^```[^\n]*\n[\s\S]*?^```[^\S\n]*$", "", text, flags=re.M)
    for paragraph in re.split(r"\n[ \t]*\n", text):
        body = "\n".join(
            line for line in paragraph.splitlines()
            if line.strip() and not re.match(r"^\s*(?:#|<!--|---+$)", line)
        ).strip()
        if body:
            yield body


def sources(workspace: Path):
    memory = workspace / "memory"
    legacy = (p for p in sorted(memory.glob("*.md")) if not p.name.endswith("-pre-open.md"))
    for source, files in (("legacy", legacy), ("light", sorted((memory / "dreaming/light").rglob("*.md")))):
        for path in files:
            if path.is_file() and not path.is_symlink():
                yield source, path, paragraphs(path.read_text(encoding="utf-8"))
    for name in ("promotion-candidates.md", "legacy-promotion-candidates.md"):
        path = memory / ".dreams" / name
        if path.is_file() and not path.is_symlink():
            _, entries = gate.extract(path.read_text(encoding="utf-8"), strict=False)
            yield "ranking", path, (entry["text"] for entry in entries)
    path = workspace / "DREAMS.md"
    if path.is_file() and not path.is_symlink():
        diary = review_dreams.parse(path.read_text(encoding="utf-8"))
        if diary is None:
            raise ValueError("DREAMS.md has no diary markers")
        yield "narrative", path, (entry["body"] for entry in diary["entries"])


def classify(candidate: str, normalized: str, seen: set[str]) -> tuple[str, str]:
    if gate.reasons(candidate):
        return "discard", "protected_or_transient"
    if normalized in seen:
        return "duplicate", "normalized_text_match"
    if re.search(r"\d", candidate):
        return "discard", "no_ledger_binding"
    if len(normalized) < 24 or TRANSIENT.search(candidate):
        return "discard", "insufficient_durable_content"
    return "extractable", "screened_for_review"


def build_report(workspace: Path, store: Path) -> dict:
    if not store.is_dir() or not (workspace / "memory").is_dir():
        raise ValueError("both store and workspace memory must exist")
    seen = set()
    for topic in replay.load_topics(store).values():
        seen.add(replay.normalized_body(topic["body"]))
        seen.update(replay.normalized_body(text) for text in paragraphs(topic["body"]))

    rows = []
    files = Counter()
    for source, path, candidates in sources(workspace):
        files[source] += 1
        for candidate in candidates:
            normalized = replay.normalized_body(candidate)
            decision, reason = classify(candidate, normalized, seen)
            if decision == "extractable":
                seen.add(normalized)
            rows.append({
                "source": source,
                "path": path.relative_to(workspace).as_posix(),
                "sha256": gate.digest(normalized),
                "decision": decision,
                "reason": reason,
            })

    totals = Counter(row["decision"] for row in rows)
    return {
        "files": dict(files),
        "counts": {field: totals[field] for field in ("extractable", "duplicate", "discard")},
        "candidates": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--store", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build_report(args.workspace, args.store), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
