#!/usr/bin/env python3
"""Fail-closed source check for public artifacts built from the shared store.

`MEMORY.md`, `DREAMS.md` and the published pre-open brief may quote a topic only
when that topic says `publish: public`, or quote runtime data (portfolio, plan,
brief context) that never came from the store. A paragraph or long line copied
from a topic that is not public is a hard error: it means the private body
reached a public file by transcription rather than by a reviewed public topic.

The check is deliberately textual. A paraphrase passes; an exact copy of a
private topic line/paragraph does not. Runtime data the caller names explicitly
(`--allow`) is an allowed source and passes. A private line duplicated into a
public topic is still a private body leak: the public topic is what needs
fixing, so the projection fails rather than laundering it.

CLI:
    provenance.py --artifact memory/2026-11-08-pre-open.md [--store DIR]
Exit 0: no private copy. Exit 2: private copy found (message names the topic).
Exit 1: usage/store/read error. It never writes.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from memory import split_frontmatter  # noqa: E402  (the topic format owner)

DEFAULT_STORE = Path(os.environ.get("SHARED_MEMORY_DIR", "~/.shared-memory")).expanduser()
MIN_LINE_CHARS = 24
MIN_PARAGRAPH_CHARS = 48


class ProvenanceError(Exception):
    pass


def _published(fields: dict[str, str], meta: dict[str, str]) -> bool:
    return (meta.get("publish") or fields.get("publish") or "").strip().lower() == "public"


def _strip_markdown(line: str) -> str:
    line = line.strip()
    while True:
        before = line
        line = line.removeprefix(">").lstrip()
        line = line.removeprefix("#").lstrip()
        if line[:2] in ("- ", "* ", "+ "):
            line = line[2:].lstrip()
        else:
            head, dot, rest = line.partition(". ")
            if dot and head.isdigit():
                line = rest.lstrip()
        if line == before:
            return line


def _normalise(text: str) -> str:
    return " ".join(text.split()).casefold()


def _lines(body: str) -> list[str]:
    rows = []
    for raw in body.splitlines():
        line = _normalise(_strip_markdown(raw))
        if line:
            rows.append(line)
    return rows


def _paragraphs(body: str) -> list[str]:
    rows = []
    for block in body.split("\n\n"):
        lines = [_strip_markdown(line) for line in block.splitlines()]
        line = _normalise(" ".join(part for part in lines if part))
        if line:
            rows.append(line)
    return rows


def _topic_rows(store: Path) -> list[tuple[str, bool, str]]:
    if not store.is_dir():
        raise ProvenanceError(f"shared memory directory not found: {store}")
    rows: list[tuple[str, bool, str]] = []
    paths = sorted(store.glob("*.md")) + sorted((store / "archive").glob("*.md"))
    for path in paths:
        if path.name == "MEMORY.md":
            continue
        try:
            parsed = split_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ProvenanceError(f"{path.name}: {exc}") from exc
        if parsed is None:
            continue
        fields, meta, body = parsed
        rows.append((path.stem, _published(fields, meta), body))
    return rows


def _private_units(store: Path, allowed_texts: list[str]) -> list[tuple[str, str, str]]:
    """(kind, topic, unit) for long private lines/paragraphs outside runtime data."""
    allowed_blob = _normalise(" ".join(allowed_texts))
    units: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for slug, public, body in _topic_rows(store):
        if public:
            continue
        for kind, values, floor in (("line", _lines(body), MIN_LINE_CHARS),
                                    ("paragraph", _paragraphs(body), MIN_PARAGRAPH_CHARS)):
            for value in values:
                if len(value) < floor or value in allowed_blob:
                    continue
                key = (slug, value)
                if key in seen:
                    continue
                seen.add(key)
                units.append((kind, slug, value))
    return units


def find_copies(text: str, store: Path, allowed_texts: list[str] | None = None) -> list[dict[str, str]]:
    """Exact private-topic lines/paragraphs present in `text` (empty when clean)."""
    units = _private_units(Path(store).expanduser(), allowed_texts or [])
    blob = _normalise(text)
    return [{"topic": slug, "kind": kind, "text": value}
            for kind, slug, value in units if value in blob]


def assert_public_sources(label: str, text: str, store: Path,
                          allowed_texts: list[str] | None = None) -> None:
    """Raise ProvenanceError naming every private topic copied into `label`."""
    copies = find_copies(text, store, allowed_texts)
    if not copies:
        return
    details = "; ".join(
        f"{item['topic']} ({item['kind']}): {item['text'][:120]!r}" for item in copies[:5])
    more = "" if len(copies) <= 5 else f" (+{len(copies) - 5} more)"
    raise ProvenanceError(
        f"{label} copies a private topic body, which may not be published: {details}{more}. "
        "Quote a publish: public topic or runtime data instead.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--artifact", type=Path, required=True,
                        help="public file to check (brief, DREAMS.md or MEMORY.md)")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE,
                        help="shared-memory store (default: $SHARED_MEMORY_DIR or ~/.shared-memory)")
    parser.add_argument("--allow", type=Path, action="append", default=[],
                        help="runtime-data file whose text is an allowed source (repeatable)")
    args = parser.parse_args()
    try:
        text = args.artifact.read_text(encoding="utf-8")
        allowed = [path.read_text(encoding="utf-8") for path in args.allow]
        assert_public_sources(str(args.artifact), text, args.store, allowed)
    except ProvenanceError as exc:
        print(f"provenance: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"provenance: {exc}", file=sys.stderr)
        return 1
    print(f"provenance: {args.artifact} has no private-topic copy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
