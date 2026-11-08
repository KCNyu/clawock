#!/usr/bin/env python3
"""Generate the public MEMORY.md projection from `publish: public` topics.

The store is the source of truth for the projection. A topic is included only when
its metadata says `publish: public`; every included topic must carry an integer
`order` and a boolean `separator`. The output is deterministic: topics are sorted by
`order`, the header is fixed, and a section that needs the legacy horizontal rule
sets `separator: true`.

`--check` (the default) validates the committed projection and its manifest without
reading the store, so CI can run it from a clean checkout. `--write` regenerates both
from the live store; run it only from a checkout that was just reviewed.
"""
from __future__ import annotations

import argparse
from difflib import unified_diff
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from memory import split_frontmatter  # noqa: E402  (the format owner sits next to us)

HEADER = (
    "# MEMORY.md - Rick's Long-Term Memory\n"
    "\n"
    "直聊主会话注入本文件；isolated cron 不注入。只放规则、偏好和长期结论。持仓、ticker 列表、\n"
    "金额只在 `portfolio.json`，这里不留副本。"
)
MANIFEST_VERSION = 1
MANIFEST_REL = "ops/host/shared-memory/publish-manifest.json"
DEFAULT_STORE = Path(os.environ.get("SHARED_MEMORY_DIR", "~/.shared-memory")).expanduser()


class ProjectionError(Exception):
    pass


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists():
            return parent
    return Path.cwd()


def _truth(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def load_public_topics(store: Path) -> list[dict]:
    """Read every active public topic, require an explicit order, and sort it."""
    if not store.is_dir():
        raise ProjectionError(f"shared memory directory not found: {store}")
    topics: list[dict] = []
    for path in sorted(store.glob("*.md")):
        if path.name == "MEMORY.md":
            continue
        try:
            parsed = split_frontmatter(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ProjectionError(f"{path.name}: {exc}") from exc
        if parsed is None:
            continue
        fields, meta, body = parsed
        if (meta.get("publish") or fields.get("publish")) != "public":
            continue
        raw_order = (meta.get("order") or fields.get("order") or "").strip()
        if not raw_order.isdigit() or int(raw_order) < 1:
            raise ProjectionError(f"{path.name}: publish: public needs an integer metadata.order")
        raw_separator = (meta.get("separator") or fields.get("separator") or "").strip()
        if raw_separator.lower() not in ("true", "false"):
            raise ProjectionError(f"{path.name}: publish: public needs metadata.separator true|false")
        clean = body.strip("\n")
        if not clean.lstrip().startswith("#"):
            raise ProjectionError(f"{path.name}: the body must start with its Markdown heading")
        topics.append({
            "slug": path.stem,
            "order": int(raw_order),
            "separator": _truth(raw_separator),
            "body": clean,
            "heading": clean.splitlines()[0],
        })
    if not topics:
        raise ProjectionError("no topic carries publish: public")
    orders = sorted(topic["order"] for topic in topics)
    if orders != list(range(1, len(topics) + 1)):
        raise ProjectionError(f"public projection orders must be contiguous 1..{len(topics)} (got {orders})")
    topics.sort(key=lambda topic: topic["order"])
    return topics


def render(topics: list[dict], header: str = HEADER) -> str:
    blocks = [header.rstrip("\n")]
    for topic in topics:
        if topic["separator"]:
            blocks.append("---")
        blocks.append(topic["body"].rstrip("\n"))
    return "\n\n".join(blocks) + "\n"


def build_manifest(text: str, topics: list[dict], header: str = HEADER) -> dict:
    header_text = header.rstrip("\n")
    return {
        "version": MANIFEST_VERSION,
        "generated_by": "ops/host/shared-memory/scripts/publish.py",
        "header_lines": len(header_text.splitlines()),
        "header_sha256": sha256(header_text),
        "content_sha256": sha256(text),
        "bytes": len(text.encode("utf-8")),
        "sections": [
            {
                "slug": topic["slug"],
                "order": topic["order"],
                "publish": "public",
                "separator": topic["separator"],
                "heading": topic["heading"],
                "lines": len(topic["body"].splitlines()),
                "sha256": sha256(topic["body"].rstrip("\n")),
            }
            for topic in topics
        ],
    }


def validate(text: str, manifest: dict) -> list[str]:
    """Validate a committed projection against its manifest, without the store.

    The manifest holds line counts and hashes, not bodies: a hand-added line, a
    removed section, an edited paragraph or a private section all fail here.
    """
    errors: list[str] = []
    if manifest.get("version") != MANIFEST_VERSION:
        errors.append(f"manifest version {manifest.get('version')!r} is not {MANIFEST_VERSION}")
    if sha256(text) != manifest.get("content_sha256"):
        errors.append("MEMORY.md content hash does not match the manifest")
    lines = text.splitlines()
    header_lines = int(manifest.get("header_lines") or 0)
    if header_lines <= 0 or header_lines > len(lines):
        return errors + ["manifest header_lines is missing or out of range"]
    header = "\n".join(lines[:header_lines])
    if sha256(header) != manifest.get("header_sha256"):
        errors.append("MEMORY.md header does not match the manifest")
    cursor = header_lines
    # The header is followed by one blank line before the first section.
    if lines[cursor:cursor + 1] != [""]:
        errors.append("MEMORY.md is missing the blank line after the header")
        return errors
    cursor += 1
    sections = manifest.get("sections") or []
    for index, section in enumerate(sections, 1):
        if section.get("publish") != "public":
            errors.append(f"section {section.get('slug')!r} is not publish: public")
        if section.get("separator"):
            if lines[cursor:cursor + 2] != ["---", ""]:
                errors.append(f"section {section.get('slug')!r}: missing the --- separator")
                return errors
            cursor += 2
        count = int(section.get("lines") or 0)
        block = lines[cursor:cursor + count]
        if len(block) != count:
            errors.append(f"section {section.get('slug')!r}: expected {count} lines, found {len(block)}")
            return errors
        body = "\n".join(block)
        if sha256(body) != section.get("sha256"):
            errors.append(f"section {section.get('slug')!r}: body hash does not match the manifest")
        if block and block[0] != section.get("heading"):
            errors.append(f"section {section.get('slug')!r}: heading does not match the manifest")
        cursor += count
        if index < len(sections):
            if lines[cursor:cursor + 1] != [""]:
                errors.append(f"section {section.get('slug')!r}: missing the blank line before the next section")
                return errors
            cursor += 1
    if cursor != len(lines):
        errors.append(f"MEMORY.md has {len(lines) - cursor} unexpected line(s) after the last section")
    return errors


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProjectionError(f"cannot read manifest {path}: {exc}") from exc


def check(repo: Path, store: Path | None, manifest_path: Path) -> int:
    memory_path = repo / "MEMORY.md"
    try:
        text = memory_path.read_text(encoding="utf-8")
        manifest = _read_json(manifest_path)
    except OSError as exc:
        print(f"publish: {exc}", file=sys.stderr)
        return 1
    errors = validate(text, manifest)
    if store is not None:
        try:
            topics = load_public_topics(store)
        except ProjectionError as exc:
            print(f"publish: {exc}", file=sys.stderr)
            return 1
        expected = render(topics)
        expected_manifest = build_manifest(expected, topics)
        if expected != text:
            print("publish: MEMORY.md differs from the store projection:", file=sys.stderr)
            sys.stderr.writelines(unified_diff(
                text.splitlines(True), expected.splitlines(True),
                fromfile="MEMORY.md", tofile="generated", n=2))
            errors.append("MEMORY.md is stale")
        if expected_manifest != manifest:
            errors.append(f"{manifest_path.name} is stale")
    for error in errors:
        print(f"publish: {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"publish: {len(manifest['sections'])} public section(s), "
          f"{manifest['bytes']} bytes, manifest matches MEMORY.md")
    return 0


def write(repo: Path, store: Path, manifest_path: Path) -> int:
    topics = load_public_topics(store)
    text = render(topics)
    manifest = build_manifest(text, topics)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    for path, content in ((repo / "MEMORY.md", text),
                          (manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")):
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    print(f"publish: wrote {repo / 'MEMORY.md'} ({len(manifest['sections'])} sections, "
          f"{manifest['bytes']} bytes) and {manifest_path}")
    return check(repo, store, manifest_path)


def main() -> int:
    repo_default = _repo_root()
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=repo_default, help="checkout holding MEMORY.md")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE,
                        help="shared-memory store (only needed with --write or --check-store)")
    parser.add_argument("--manifest", type=Path, help=f"default: <repo>/{MANIFEST_REL}")
    parser.add_argument("--write", action="store_true", help="regenerate MEMORY.md and the manifest")
    parser.add_argument("--check-store", action="store_true",
                        help="also compare the committed projection with the live store")
    args = parser.parse_args()
    manifest = args.manifest or (args.repo / MANIFEST_REL)
    try:
        if args.write:
            return write(args.repo, args.store, manifest)
        return check(args.repo, args.store if args.check_store else None, manifest)
    except ProjectionError as exc:
        print(f"publish: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
