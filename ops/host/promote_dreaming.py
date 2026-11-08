#!/usr/bin/env python3
"""Promote reviewed dreaming candidates into the shared store's public topics.

The 03:00 dreaming run writes private candidates. `review_dreaming.py` owns the
hash-bound review contract; this script applies its approved decisions to the
coding agents' store and then asks `publish.py` to regenerate the repository
`MEMORY.md` and its manifest.

One candidate becomes one new topic with `publish: public`, the next contiguous
`order`, `separator: true`, and the reviewed marker/source line in its body.
Existing public topics (including the 14 sections that predate this gate) are
never recreated. The marker is the idempotency key: a repeated run sees it in
the committed projection or in the store and writes nothing.

The store write is fail-closed:
  * snapshot before the first topic, then require `memctl verify` and
    `memctl doctor` to pass;
  * if `publish.py --write` or its post-check fails, restore the previous
    `MEMORY.md` and manifest before returning non-zero.

No candidate, no write, no projection. `--check` performs the review and reports
what would happen without touching the store or the repository.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HOST_DIR = Path(__file__).resolve().parent
SCRIPTS = HOST_DIR / "shared-memory" / "scripts"
sys.path.insert(0, str(HOST_DIR))
sys.path.insert(0, str(SCRIPTS))

import review_dreaming as gate  # noqa: E402  (the hash-bound review owner)
import memory as memory_tool  # noqa: E402  (the topic format owner)
import publish as projection  # noqa: E402  (the projection owner)

DEFAULT_STORE = Path(os.environ.get("SHARED_MEMORY_DIR", "~/.shared-memory")).expanduser()
DEFAULT_MEMCTL = Path.home() / ".agents/skills/shared-memory/scripts/memctl"
SOURCE_LINE = re.compile(r"^- Source: (memory/[\w./-]+):(\d+)-(\d+)", re.M)
SHA_LINE = re.compile(r"SHA256 ([0-9a-f]{64})")
SLUG_PART = re.compile(r"[^a-z0-9]+")


class PromotionError(Exception):
    pass


def line_range(entry: dict) -> tuple[str, str]:
    match = re.search(r":(\d+):(\d+)$", entry["key"])
    if not match:
        raise PromotionError(f"candidate key has no line range: {entry['key']}")
    return match.group(1), match.group(2)


def topic_slug(entry: dict) -> str:
    start, end = line_range(entry)
    stem = SLUG_PART.sub("-", Path(entry["source"]).stem.lower()).strip("-") or "source"
    return f"lessons-dreaming-{stem[:48].rstrip('-')}-{start}-{end}"


def topic_heading(entry: dict) -> str:
    start, end = line_range(entry)
    return f"## Dreaming 晋升 {Path(entry['source']).stem}（{start}-{end}）"


def topic_body(entry: dict, receipt: dict) -> str:
    start, end = line_range(entry)
    return (
        f"{topic_heading(entry)}\n\n"
        f"{entry['marker']}\n"
        f"- {receipt['conclusion']}\n"
        f"- Source: {entry['source']}:{start}-{end} "
        f"(reviewed {receipt['reviewed_on']}; SHA256 {entry['sha256']})\n"
    )


def body_with_metadata(entry: dict, body: str, order: int) -> str:
    return (
        "---\n"
        "metadata:\n"
        f"  order: {order}\n"
        "  separator: true\n"
        f"  dreaming_key: {json.dumps(entry['key'])}\n"
        f"  dreaming_sha256: {entry['sha256']}\n"
        "---\n\n"
        f"{body}"
    )


def read_topics(store: Path) -> list[tuple[Path, dict, dict, str]]:
    """Top-level topics with frontmatter, as (path, fields, metadata, body)."""
    if not store.is_dir():
        raise PromotionError(f"shared memory directory not found: {store}")
    rows = []
    for path in sorted(store.glob("*.md")):
        if path.name == "MEMORY.md":
            continue
        try:
            parsed = memory_tool.split_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PromotionError(f"{path.name}: {exc}") from exc
        if parsed is not None:
            fields, meta, body = parsed
            rows.append((path, fields, meta, body))
    return rows


def existing_promotions(store: Path) -> dict[str, dict]:
    """Reviewed candidates already written to a public topic, keyed by marker key."""
    found: dict[str, dict] = {}
    for path, fields, meta, body in read_topics(store):
        key = (meta.get("dreaming_key") or "").strip()
        marker = gate.MARKER.search(body)
        if not key:
            if not marker:
                continue
            key = marker.group(1)
        if marker and marker.group(1) != key:
            raise PromotionError(f"{path.name}: dreaming_key does not match its promotion marker")
        if not marker:
            raise PromotionError(f"{path.name}: dreaming_key has no promotion marker in the body")
        publish = (meta.get("publish") or fields.get("publish") or "").strip()
        if publish != "public":
            raise PromotionError(f"{path.name}: an already promoted candidate is not publish: public")
        order = (meta.get("order") or fields.get("order") or "").strip()
        if not order.isdigit():
            raise PromotionError(f"{path.name}: an already promoted candidate has no integer order")
        separator = (meta.get("separator") or fields.get("separator") or "").strip().lower()
        if separator not in ("true", "false"):
            raise PromotionError(f"{path.name}: an already promoted candidate has no separator")
        sha = (meta.get("dreaming_sha256") or "").strip()
        if not sha:
            source_match = SOURCE_LINE.search(body)
            sha_match = SHA_LINE.search(body)
            sha = sha_match.group(1) if sha_match else ""
        if not sha:
            raise PromotionError(f"{path.name}: cannot read the promoted candidate hash")
        if key in found:
            raise PromotionError(f"candidate {key} appears in both {found[key]['path'].name} and {path.name}")
        source_match = SOURCE_LINE.search(body)
        source_line = source_match.group(0) if source_match else ""
        found[key] = {
            "path": path,
            "slug": path.stem,
            "sha256": sha,
            "marker": marker.group(0),
            "source_line": source_line,
            "body": body,
        }
    return found


def archive_legacy_sections(workspace: Path, memory_text: str, legacy: str) -> str:
    """Keep old direct-to-MEMORY candidates private before the projection removes them."""
    if not gate.SECTION.search(memory_text):
        return legacy
    _, old_entries = gate.extract(memory_text)
    known = {entry["key"] for entry in gate.extract(legacy)[1]} if legacy else set()
    new_entries = [entry for entry in old_entries if entry["key"] not in known]
    if not new_entries:
        return legacy
    path = workspace / "memory/.dreams/legacy-promotion-candidates.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = legacy + "\n## Promoted From Short-Term Memory (2000-01-01)\n\n" + "".join(
        entry["marker"] + "\n- " + entry["text"] + "\n" for entry in new_entries)
    tmp = path.with_name(path.name + ".promote-tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)
    return text


def review_context(existing: dict[str, dict]) -> str:
    """Markers already promoted: review() skips them before receipt expiry."""
    return "\n".join(part for item in existing.values()
                     for part in (item["marker"], item["source_line"]) if part)


def load_inputs(workspace: Path) -> tuple[str, str, dict, str]:
    private = workspace / "memory/.dreams"
    memory_path = workspace / "MEMORY.md"
    memory_text = memory_path.read_text(encoding="utf-8")
    candidate_path = private / "promotion-candidates.md"
    candidates = candidate_path.read_text(encoding="utf-8") if candidate_path.exists() else ""
    legacy_path = private / "legacy-promotion-candidates.md"
    legacy = legacy_path.read_text(encoding="utf-8") if legacy_path.exists() else ""
    approvals_path = private / "promotion-approvals.json"
    approvals = json.loads(approvals_path.read_text(encoding="utf-8")) if approvals_path.exists() else {}
    if not isinstance(approvals, dict):
        raise PromotionError("promotion-approvals.json must be an object")
    return memory_text, candidates + "\n" + legacy, approvals, legacy


def next_order(store: Path) -> int:
    rows = projection.load_public_topics(store)
    return max(topic["order"] for topic in rows) + 1


def run(command: list[str], *, env: dict | None = None, what: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(command, text=True, capture_output=True, env=env)
    if proc.returncode:
        detail = (proc.stderr or proc.stdout).strip()
        raise PromotionError(f"{what} failed (exit {proc.returncode}): {detail[-1200:]}")
    return proc


def memctl_env(store: Path) -> dict:
    env = {**os.environ, "SHARED_MEMORY_DIR": str(store), "MEMCTL_AGENT": "rick"}
    state = os.environ.get("SHARED_MEMORY_STATE")
    if state:
        env["SHARED_MEMORY_STATE"] = state
    return env


def write_topic(store: Path, memory_py: Path, memctl: Path, entry: dict, receipt: dict,
                order: int) -> str:
    slug = topic_slug(entry)
    path = store / f"{slug}.md"
    if path.exists():
        raise PromotionError(f"topic already exists without this candidate's marker: {path.name}")
    body = body_with_metadata(entry, topic_body(entry, receipt), order)
    fd, name = tempfile.mkstemp(prefix=".promote-", suffix=".md", dir=str(store))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        env = memctl_env(store)
        env["SHARED_MEMORY_MEMCTL"] = str(memctl)
        run([sys.executable, str(memory_py), "add", slug,
             "--summary", memory_tool.one_line(receipt["conclusion"]),
             "--body-file", name, "--type", "project", "--scope", "memory",
             "--salience", "normal", "--status", "verified", "--publish", "public"],
            env=env, what=f"store write for {slug}")
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
    parsed = memory_tool.split_frontmatter(path.read_text(encoding="utf-8"))
    if parsed is None:
        raise PromotionError(f"{path.name}: store write produced no frontmatter")
    fields, meta, written = parsed
    if (meta.get("publish") or fields.get("publish")) != "public":
        raise PromotionError(f"{path.name}: store write did not keep publish: public")
    if (meta.get("order") or fields.get("order")) != str(order):
        raise PromotionError(f"{path.name}: store write did not keep order {order}")
    if (meta.get("separator") or fields.get("separator") or "").lower() != "true":
        raise PromotionError(f"{path.name}: store write did not keep separator: true")
    if entry["marker"] not in written:
        raise PromotionError(f"{path.name}: store write lost the promotion marker")
    return slug


def restore_bytes(path: Path, content: bytes | None) -> None:
    if content is None:
        path.unlink(missing_ok=True)
        return
    tmp = path.with_name(f".{path.name}.promote-restore")
    tmp.write_bytes(content)
    os.replace(tmp, path)


def regenerate(repo: Path, store: Path, publish_py: Path, manifest: Path) -> None:
    memory_path = repo / "MEMORY.md"
    before_memory = memory_path.read_bytes()
    before_manifest = manifest.read_bytes() if manifest.is_file() else None
    try:
        run([sys.executable, str(publish_py), "--write", "--repo", str(repo),
             "--store", str(store), "--manifest", str(manifest)],
            env=memctl_env(store), what="publish.py --write")
        run([sys.executable, str(publish_py), "--check", "--repo", str(repo),
             "--store", str(store), "--manifest", str(manifest)],
            env=memctl_env(store), what="publish.py --check --store")
    except (PromotionError, OSError) as exc:
        try:
            restore_bytes(memory_path, before_memory)
            restore_bytes(manifest, before_manifest)
        except OSError as restore_exc:
            raise PromotionError(
                f"{exc}; FURTHERMORE restoring the previous projection failed: {restore_exc}") from exc
        sha = hashlib.sha256(before_memory).hexdigest()
        raise PromotionError(
            f"{exc}; restored MEMORY.md (sha256 {sha}) and "
            f"{manifest.name} from the previous version") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", type=Path, required=True,
                        help="OpenClaw workspace holding MEMORY.md and memory/.dreams")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE,
                        help="shared-memory store (default: $SHARED_MEMORY_DIR or ~/.shared-memory)")
    parser.add_argument("--memctl", type=Path,
                        help="memctl used for snapshot/verify/doctor (default: installed skill)")
    parser.add_argument("--memory-py", type=Path,
                        help="memory.py used for the store write (default: this checkout)")
    parser.add_argument("--publish-script", type=Path,
                        help="publish.py used for regeneration (default: this checkout)")
    parser.add_argument("--check", action="store_true",
                        help="review and report only; never write the store or projection")
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    store = args.store.expanduser().resolve()
    memctl = (args.memctl or Path(os.environ.get("SHARED_MEMORY_MEMCTL") or DEFAULT_MEMCTL)).expanduser()
    memory_py = (args.memory_py or SCRIPTS / "memory.py").resolve()
    publish_py = (args.publish_script or SCRIPTS / "publish.py").resolve()
    manifest = workspace / projection.MANIFEST_REL

    try:
        memory_text, candidates, approvals, legacy = load_inputs(workspace)
        if gate.HEADING in memory_text:
            raise PromotionError(
                "MEMORY.md still carries the legacy '## Reviewed Dreaming Memory' section; "
                "move its reviewed entries to public store topics before promotion")
        existing = existing_promotions(store)
        base = memory_text.rstrip("\n") + "\n\n" + review_context(existing) + "\n"
        try:
            _, report = gate.review(base, candidates, approvals)
        except ValueError as exc:
            raise PromotionError(f"review failed: {exc}") from exc
        approved = [row for row in report if row["decision"] == "approved"]
        pending = [row for row in report if row["decision"] == "pending"]
        rejected = [row for row in report if row["decision"] == "rejected"]

        candidates_to_write = []
        for row in approved:
            old = existing.get(row["key"])
            if old:
                if old["sha256"] != row["sha256"]:
                    raise PromotionError(
                        f"candidate {row['key']} changed after promotion; refusing to rewrite {old['path'].name}")
                continue
            if (store / f"{topic_slug(row)}.md").exists():
                raise PromotionError(
                    f"topic slug collision for {row['key']}: {(store / f'{topic_slug(row)}.md').name}")
            candidates_to_write.append(row)
        candidates_to_write.sort(key=lambda row: row["key"])

        missing = [item for item in existing.values() if item["marker"] not in memory_text]
        legacy_sections = bool(gate.SECTION.search(memory_text))
        should_publish = bool(candidates_to_write or missing or legacy_sections)

        decisions = Counter(row["decision"] for row in report)
        summary = {"approved": decisions.get("approved", 0), "pending": decisions.get("pending", 0),
                   "rejected": decisions.get("rejected", 0),
                   "already_promoted": len(existing), "would_write": len(candidates_to_write),
                   "would_regenerate": should_publish}
        if args.check:
            print(json.dumps({"decisions": summary,
                              "pending_keys": [row["key"] for row in pending],
                              "rejected_keys": [row["key"] for row in rejected],
                              "write": [topic_slug(row) for row in candidates_to_write]},
                             ensure_ascii=False))
            return 0

        if not should_publish:
            print(f"promote_dreaming: no approved candidates; no store write, no projection generated "
                  f"(pending={summary['pending']}, rejected={summary['rejected']})")
            return 0

        if legacy_sections:
            legacy = archive_legacy_sections(workspace, memory_text, legacy)

        if candidates_to_write and not args.check:
            env = memctl_env(store)
            if os.environ.get("SHARED_MEMORY_STATE"):
                env["SHARED_MEMORY_STATE"] = os.environ["SHARED_MEMORY_STATE"]
            run([sys.executable, str(memctl), "snapshot", "--reason",
                 f"pre-dreaming-promotion {date.today().isoformat()}"],
                env=env, what="memctl snapshot before the store write")
            order = next_order(store)
            for row in candidates_to_write:
                write_topic(store, memory_py, memctl, row, approvals[row["key"]], order)
                order += 1
            run([sys.executable, str(memctl), "verify", "--quiet"], env=env,
                what="memctl verify after the store write")
            run([sys.executable, str(memctl), "doctor", "--quiet"], env=env,
                what="memctl doctor after the store write")

        if should_publish:
            regenerate(workspace, store, publish_py, manifest)
            run([sys.executable, str(memctl), "verify", "--quiet"], env=memctl_env(store),
                what="memctl verify after regeneration")
            run([sys.executable, str(memctl), "doctor", "--quiet"], env=memctl_env(store),
                what="memctl doctor after regeneration")

        sections = len(json.loads(manifest.read_text(encoding="utf-8"))["sections"]) if should_publish else 0
        print(json.dumps({"decisions": summary,
                          "wrote": [topic_slug(row) for row in candidates_to_write],
                          "regenerated": should_publish, "sections": sections},
                         ensure_ascii=False))
        return 0
    except (PromotionError, projection.ProjectionError, ValueError, OSError,
            json.JSONDecodeError) as exc:
        print(f"promote_dreaming: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
