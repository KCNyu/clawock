#!/usr/bin/env python3
"""Small, dependency-free CLI for a Markdown memory shared by several coding agents.

Topic format (compatible with Claude Code auto-memory):

    ---
    name: <slug, same as the filename>
    description: "<one-line hook used for recall>"
    metadata:
      type: user | feedback | project | reference
      updated: YYYY-MM-DD
    ---

    <body>
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import os
from pathlib import Path
import fnmatch
import re
import stat
import subprocess
import sys
import tempfile


DEFAULT_ROOT = Path(os.environ.get("SHARED_MEMORY_DIR", "~/.shared-memory")).expanduser()
NEW_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
ROUTE_RE = r"(?:(?:archive|indexes)/)?[a-zA-Z0-9][a-zA-Z0-9_.-]*\.md"
TYPES = ("user", "feedback", "project", "reference")
MAIN_INDEX = "MEMORY.md"
REDIRECTS = "indexes/redirects.tsv"
# Topic names say what kind of memory they hold; the prefix also picks the index a new topic lands in.
PREFIXES = ("feedback-", "lessons-", "decision-", "project-", "incident-", "reference-")


ROUTES = "indexes/routes.tsv"


def default_index(slug: str, root: Path | None = None) -> str:
    """Index a new topic is routed from: the first `<glob>\t<index>` line of indexes/routes.tsv
    whose glob matches the slug; MEMORY.md when the store has no routing table or nothing matches."""
    path = (root or memory_root()) / ROUTES
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#") and "\t" in line:
                pattern, index = (part.strip() for part in line.split("\t", 1))
                if fnmatch.fnmatchcase(slug, pattern):
                    return index
    return MAIN_INDEX


def redirects(root: Path) -> dict[str, str]:
    """old slug -> current slug, from indexes/redirects.tsv (renames and merges)."""
    path = root / REDIRECTS
    if not path.is_file():
        return {}
    pairs = (line.split("\t") for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#"))
    return {old.strip(): new.strip() for old, new in pairs}
MAIN_INDEX_BUDGET = 8_000
SUB_INDEX_BUDGET = 16_000
TOPIC_BUDGET = 16_000
DESCRIPTION_LIMIT = 300
# Header written by the previous `add` helper in front of the real body.
LEGACY_WRAPPER_RE = re.compile(r"\A# [^\n]*\n\n- Updated: (\d{4}-\d{2}-\d{2})\n\n+")


def memory_root() -> Path:
    root = DEFAULT_ROOT
    if not root.is_dir():
        raise SystemExit(f"shared memory directory not found: {root}")
    return root


def topic_path(root: Path, topic: str) -> Path:
    name = topic.removesuffix(".md")
    if not re.fullmatch(r"(?:(?:archive|indexes)/)?[a-zA-Z0-9][a-zA-Z0-9_.-]*", name) or ".." in name:
        raise SystemExit("topic must be a filename, indexes/filename or archive/filename")
    path = root / f"{name}.md"
    if not path.resolve().is_relative_to(root.resolve()):
        raise SystemExit("topic must stay inside the shared memory directory")
    return path


def atomic_write(path: Path, content: str) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def locked(root: Path):
    lock = (root / ".shared-memory.lock").open("a+", encoding="utf-8")
    fcntl.flock(lock, fcntl.LOCK_EX)
    return lock


# --- frontmatter -----------------------------------------------------------

def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return re.sub(r'\\(["\\])', r"\1", value[1:-1])
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def _quote(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_.:+-]+", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def split_frontmatter(text: str) -> tuple[dict[str, str], dict[str, str], str] | None:
    """Parse the flat subset of YAML used by memory topics.

    Returns (top-level fields, metadata fields, body), or None when the text has
    no frontmatter. Raises ValueError for frontmatter this parser cannot round-trip.
    """
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 3)
    if end < 0:
        if not text.rstrip().endswith("\n---"):
            raise ValueError("unterminated frontmatter")
        end = len(text.rstrip()) - 4
    head, body = text[4:end], text[end + 5:]
    fields: dict[str, str] = {}
    meta: dict[str, str] = {}
    in_meta = False
    for line in head.splitlines():
        if not line.strip():
            continue
        top = re.fullmatch(r"([A-Za-z_][\w-]*):[ \t]*(.*)", line)
        if top:
            key, value = top[1], top[2].strip()
            in_meta = key == "metadata" and not value
            if not in_meta:
                if value in (">", "|", ">-", "|-"):
                    raise ValueError(f"block scalar in {key}")
                fields[key] = _unquote(value)
            continue
        nested = re.fullmatch(r"[ \t]+([A-Za-z_][\w-]*):[ \t]*(.*)", line)
        if nested and in_meta:
            meta[nested[1]] = _unquote(nested[2].strip())
            continue
        raise ValueError(f"unsupported frontmatter line: {line[:60]}")
    return fields, meta, body


def render_topic(slug: str, description: str, meta: dict[str, str], body: str) -> str:
    ordered = {key: meta[key] for key in ("type", "updated") if meta.get(key)}
    ordered.update((key, value) for key, value in meta.items() if key not in ordered and value)
    lines = ["---", f"name: {slug}", f"description: {_quote(description)}", "metadata:"]
    lines += [f"  {key}: {_quote(value)}" for key, value in ordered.items()]
    return "\n".join(lines) + "\n---\n\n" + body.strip("\n") + "\n"


def infer_type(slug: str) -> str:
    for prefix, kind in (("feedback-", "feedback"), ("user-", "user"), ("profile-", "user"), ("reference-", "reference")):
        if slug.startswith(prefix):
            return kind
    return "project"


def one_line(text: str) -> str:
    text = " ".join(text.replace("**", "").split())
    return text if len(text) <= DESCRIPTION_LIMIT else text[: DESCRIPTION_LIMIT - 1] + "…"


# --- indexes ---------------------------------------------------------------

def index_refs(text: str) -> list[str]:
    """Read bullet hooks, including dotted filenames and one-level brace groups.

    All routes are relative to the memory root, including in archive indexes.
    """
    refs: list[str] = []
    for line in text.splitlines():
        if not line.startswith("- "):
            continue
        for token in re.findall(r"`([^`]+)`", line):
            brace = re.fullmatch(r"([^{}]*)\{([^{}]+)\}([^{}]*)", token)
            names = ([brace[1] + part.strip() + brace[3] for part in brace[2].split(",")]
                     if brace else [token])
            refs.extend(name for name in names if re.fullmatch(ROUTE_RE, name))
        # Claude Code auto-memory writes `- [Title](file.md) — hook`.
        refs.extend(name for name in re.findall(r"\]\(([^)\s]+)\)", line) if re.fullmatch(ROUTE_RE, name))
    return refs


def index_files(root: Path) -> list[str]:
    return [MAIN_INDEX] + sorted(str(p.relative_to(root)) for p in (root / "indexes").glob("MEMORY*.md"))


def index_hooks(root: Path) -> dict[str, str]:
    """Map each routed topic to the text of the index line that routes it."""
    hooks: dict[str, str] = {}
    for name in index_files(root):
        for line in (root / name).read_text(encoding="utf-8").splitlines():
            refs = index_refs(line)
            if not refs:
                continue
            text = re.sub(r"`([^`]+)`", lambda m: "" if index_refs(f"- {m[0]}") else m[1], line[2:])
            text = re.sub(r"^[\s+—–-]+", "", text)
            for ref in refs:
                hooks.setdefault(ref, text)
    return hooks


def topics(root: Path) -> list[Path]:
    skip = {root / name for name in index_files(root)}
    return sorted(p for p in root.rglob("*.md") if p not in skip and not p.name.startswith("."))


# --- commands --------------------------------------------------------------

def cmd_index(args: argparse.Namespace) -> int:
    lines = (memory_root() / MAIN_INDEX).read_text(encoding="utf-8").splitlines()
    print("\n".join(lines[: args.lines]))
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    root = memory_root()
    path = topic_path(root, args.topic)
    moved = redirects(root).get(path.stem)
    if not path.is_file() and path.parent == root and moved and (root / f"{moved}.md").is_file():
        print(f"# renamed: {path.stem} -> {moved}", file=sys.stderr)
        path = root / f"{moved}.md"
    if not path.is_file() and path.parent == root and (root / "archive" / path.name).is_file():
        path = root / "archive" / path.name
        print(f"# archived: archive/{path.name}", file=sys.stderr)
    if not path.is_file():
        raise SystemExit(f"memory topic not found: {path.name}")
    print(path.read_text(encoding="utf-8"), end="")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    root = memory_root()
    moved = redirects(root)
    terms = [args.query.lower()] if args.exact else list(dict.fromkeys(args.query.lower().split()))
    if not terms:
        raise SystemExit("query cannot be empty")
    docs = []
    for path in sorted(root.rglob("*.md")):
        rel = str(path.relative_to(root))
        text = path.read_text(encoding="utf-8")
        try:
            parsed = split_frontmatter(text)
        except ValueError:
            parsed = None
        description = parsed[0].get("description", "") if parsed else ""
        docs.append((rel, text, description))

    def rank(require_all: bool):
        results = []
        for rel, text, description in docs:
            lower = text.lower()
            present = [t for t in terms if t in lower or t in rel.lower()]
            if not present or (require_all and len(present) < len(terms)):
                continue
            lines = []
            header_end = text.find("\n---\n", 3) if text.startswith("---\n") else -1
            header_lines = text[:header_end].count("\n") + 2 if header_end >= 0 else 0
            for number, line in enumerate(text.splitlines(), 1):
                hit = sum(t in line.lower() for t in terms)
                if hit:
                    # Frontmatter is already shown as the description; prefer body snippets.
                    lines.append((hit - (0.5 if number <= header_lines else 0), number, line))
            score = (10 * len(present)
                     + 6 * sum(t in rel.lower() for t in terms)
                     + 4 * sum(t in description.lower() for t in terms)
                     + min(sum(hit for hit, _, _ in lines), 15)
                     - (8 if rel.startswith("archive/") else 0))
            results.append((score, rel, description, lines))
        # An archived full text whose name redirects to an active digest ranks just below that
        # digest, so the reader lands on the current conclusions first.
        by_rel = {rel: [score, rel, description, lines] for score, rel, description, lines in results}
        descriptions = {rel: description for rel, _, description in docs}
        for score, rel, description, lines in results:
            target = moved.get(Path(rel).stem) if rel.startswith("archive/") else None
            if target and f"{target}.md" in descriptions:
                digest = by_rel.setdefault(f"{target}.md", [score, f"{target}.md", descriptions[f"{target}.md"], []])
                digest[0] = max(digest[0], score + 1)
                by_rel[rel][2] = f"(full text behind {target}.md) {description}"
        return sorted((tuple(v) for v in by_rel.values()), key=lambda item: (-item[0], item[1]))

    results = rank(require_all=True)
    if not results and len(terms) > 1:
        results = rank(require_all=False)
        if results:
            print("# no topic contains every term; showing topics matching some terms", file=sys.stderr)
    for score, rel, description, lines in results[: args.limit]:
        suffix = f" — {one_line(description)[:160]}" if description else ""
        print(f"{rel}{suffix}")
        for _, number, line in sorted(lines, key=lambda item: (-item[0], item[1]))[: args.lines]:
            print(f"  {number}: {line.strip()[:200]}")
    if len(results) > args.limit:
        print(f"# {len(results) - args.limit} more topics; refine the query or raise --limit", file=sys.stderr)
    return 0 if results else 1


def _format_entry(name: str, summary: str) -> str:
    # Summaries often open with their own date, e.g. "(09-14) ..."; don't stack a second one.
    if re.match(r"\((\d{4}-)?\d{2}-\d{2}[)，,]", summary):
        return f"- `{name}` — {summary}"
    return f"- `{name}` — ({dt.date.today().isoformat()}) {summary}"


def _read_body(body_file: str | None) -> tuple[dict[str, str], dict[str, str], str] | None:
    if body_file is None:
        return None
    raw = sys.stdin.read() if body_file == "-" else Path(body_file).read_text(encoding="utf-8")
    try:
        parsed = split_frontmatter(raw.strip() + "\n")
    except ValueError as exc:
        raise SystemExit(f"body frontmatter: {exc}")
    fields, meta, body = parsed or ({}, {}, raw)
    if not body.strip():
        raise SystemExit("memory body cannot be empty")
    return fields, meta, body


def path_slug(topic: str) -> str:
    return Path(topic.removesuffix(".md")).name


def cmd_add(args: argparse.Namespace) -> int:
    root = memory_root()
    if not NEW_SLUG_RE.fullmatch(args.slug):
        raise SystemExit("new topic must use a lowercase hyphenated slug")
    if not one_line(args.summary):
        raise SystemExit("summary cannot be empty")
    if not args.slug.startswith(PREFIXES):
        raise SystemExit(f"new topic names start with one of: {', '.join(PREFIXES)}")
    return write_topic(root, topic_path(root, args.slug), args.summary, _read_body(args.body_file),
                       args.type, MAIN_INDEX if args.pin else (args.index or default_index(args.slug, root)),
                       create=True, replace=args.replace)


def cmd_update(args: argparse.Namespace) -> int:
    root = memory_root()
    if args.summary is None and args.body_file is None and args.type is None:
        raise SystemExit("nothing to update: pass --summary, --body-file and/or --type")
    if args.summary is not None and not one_line(args.summary):
        raise SystemExit("summary cannot be empty")
    return write_topic(root, topic_path(root, args.slug), args.summary, _read_body(args.body_file),
                       args.type, default_index(path_slug(args.slug), root), create=False, replace=True)


def write_topic(root: Path, path: Path, summary: str | None, new_body, kind: str | None,
                target: str, *, create: bool, replace: bool) -> int:
    if target not in index_files(root):
        raise SystemExit(f"unknown index: {target}")
    body_fields, body_meta, body = new_body or ({}, {}, None)

    with locked(root):
        old_fields: dict[str, str] = {}
        old_meta: dict[str, str] = {}
        old_body = None
        if path.exists():
            if not replace:
                raise SystemExit(f"topic exists; inspect it and use --replace: {path.name}")
            old_text = LEGACY_WRAPPER_RE.sub("", path.read_text(encoding="utf-8"), count=1)
            try:
                old_fields, old_meta, old_body = split_frontmatter(old_text) or ({}, {}, old_text)
            except ValueError as exc:
                if body is None or summary is None:
                    raise SystemExit(f"cannot parse {path.name}: {exc}; pass both --summary and --body-file")
        elif not create:
            raise SystemExit(f"memory topic not found: {path.name}")
        summary = one_line(summary if summary is not None else old_fields.get("description", ""))
        body = body if body is not None else old_body
        if not summary or not body or not body.strip():
            raise SystemExit("topic needs a non-empty summary and body")
        meta = {**old_meta, **body_meta}
        kind = kind or body_meta.get("type") or body_fields.get("type") or old_meta.get("type") or infer_type(path.stem)
        if kind not in TYPES:
            raise SystemExit(f"type must be one of {', '.join(TYPES)}")
        meta.update(type=kind, updated=dt.date.today().isoformat())
        topic = render_topic(path.stem, summary, meta, body)

        # Update an existing single-route hook in place; grouped hooks keep their other routes.
        entry = _format_entry(str(path.relative_to(root)), summary)
        route = str(path.relative_to(root))
        writes: dict[str, list[str]] = {}
        routed = False
        for name in index_files(root):
            lines = (root / name).read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines):
                refs = index_refs(line)
                if route in refs:
                    routed = True
                    if refs == [route]:
                        lines[i] = entry
                        writes[name] = lines
                    else:
                        print(f"note: {route} is in a grouped hook in {name}; update its summary manually", file=sys.stderr)
        if not routed and not route.startswith("archive/"):
            lines = writes.get(target) or (root / target).read_text(encoding="utf-8").splitlines()
            insert_at = next((i for i, line in enumerate(lines) if line.startswith("- `")), len(lines))
            lines.insert(insert_at, entry)
            writes[target] = lines

        atomic_write(path, topic)
        for name, lines in writes.items():
            atomic_write(root / name, "\n".join(lines).rstrip() + "\n")
    print(path)
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    """Move active topics into archive/ (never delete) and repoint index routes."""
    root = memory_root()
    with locked(root):
        plan = []
        for slug in args.slugs:
            src = topic_path(root, slug)
            if src.parent != root:
                raise SystemExit(f"only active top-level topics can be archived: {slug}")
            dst = root / "archive" / src.name
            if not src.is_file():
                raise SystemExit(f"memory topic not found: {src.name}")
            if dst.exists():
                raise SystemExit(f"archive target already exists: archive/{src.name}")
            plan.append((src, dst))
        names = {src.name for src, _ in plan}
        writes: dict[str, list[str]] = {}
        for index_name in index_files(root):
            lines = (root / index_name).read_text(encoding="utf-8").splitlines()
            kept: list[str] = []
            for line in lines:
                refs = index_refs(line)
                if refs and set(refs) <= names and args.drop_hooks:
                    print(f"drop hook from {index_name}: {line[:100]}")
                    continue
                if names & set(refs):
                    line = re.sub(r"`([a-zA-Z0-9][a-zA-Z0-9_.-]*\.md)`",
                                  lambda m: f"`archive/{m[1]}`" if m[1] in names else m[0], line)
                    line = re.sub(r"\]\(([a-zA-Z0-9][a-zA-Z0-9_.-]*\.md)\)",
                                  lambda m: f"](archive/{m[1]})" if m[1] in names else m[0], line)
                kept.append(line)
            if kept != lines:
                writes[index_name] = kept
        mentions = {name: [str(p.relative_to(root)) for p in topics(root)
                           if p.name not in names and name in p.read_text(encoding="utf-8")]
                    for name in names}
        for src, dst in plan:
            print(f"{'WOULD archive' if args.dry_run else 'archive'} {src.name} -> archive/{src.name}"
                  f" ({len(mentions[src.name])} topic bodies mention it; `read` falls back to archive/)")
        if args.dry_run:
            return 0
        (root / "archive").mkdir(exist_ok=True)
        for src, dst in plan:
            os.replace(src, dst)
        for index_name, lines in writes.items():
            atomic_write(root / index_name, "\n".join(lines).rstrip() + "\n")
    return 0


def normalize_text(slug: str, text: str, hook: str | None) -> tuple[str, list[str]]:
    changes: list[str] = []
    updated = None
    wrapper = LEGACY_WRAPPER_RE.match(text)
    if wrapper:
        updated, text = wrapper[1], text[wrapper.end():]
        changes.append("strip legacy add header")
    parsed = split_frontmatter(text)
    if parsed is None:
        fields, meta, body = {}, {}, text
        changes.append("add frontmatter")
    else:
        fields, meta, body = parsed
    meta = dict(meta)
    for key, value in fields.items():
        if key not in ("name", "description") and key not in meta:
            meta[key] = value
            changes.append(f"move {key} into metadata")
    kind = meta.get("type")
    if kind not in TYPES:
        meta["type"] = "project" if kind == "decision" else infer_type(slug)
        if parsed is not None:
            changes.append(f"type {kind or '(none)'} -> {meta['type']}")
    if updated and not meta.get("updated"):
        meta["updated"] = updated
    old_name = fields.get("name", "")
    if parsed is not None and old_name != slug:
        changes.append("name -> slug")
        if old_name and not re.search(r"^# ", body, re.M):
            body = f"# {old_name}\n\n{body.lstrip()}"
    description = fields.get("description", "").strip()
    if not description:
        heading = re.search(r"^# (.+)$", body, re.M)
        description = hook or (heading[1] if heading else slug)
        if parsed is not None:
            changes.append("fill description")
    new_text = render_topic(slug, one_line(description), meta, body)
    if new_text != text and not changes:
        changes.append("reformat frontmatter")
    return new_text, changes


def cmd_normalize(args: argparse.Namespace) -> int:
    root = memory_root()
    hooks = index_hooks(root)
    changed = skipped = 0
    with locked(root):
        for path in topics(root):
            rel = str(path.relative_to(root))
            text = path.read_text(encoding="utf-8")
            try:
                new_text, changes = normalize_text(path.stem, text, one_line(hooks[rel]) if rel in hooks else None)
            except ValueError as exc:
                print(f"SKIP {rel}: {exc}", file=sys.stderr)
                skipped += 1
                continue
            mode_fix = stat.S_IMODE(path.stat().st_mode) != 0o644
            if new_text == text and not mode_fix:
                continue
            changed += 1
            print(f"{'FIX ' if args.apply else 'WOULD'} {rel}: {', '.join(changes + (['chmod 644'] if mode_fix else [])) or 'reformat'}")
            if args.apply:
                if new_text != text:
                    atomic_write(path, new_text)
                else:
                    os.chmod(path, 0o644)
    verb = "normalized" if args.apply else "would normalize (dry run; pass --apply)"
    print(f"{verb} {changed} topics; skipped {skipped}")
    return 1 if skipped else 0


def cmd_doctor(args: argparse.Namespace) -> int:
    root = memory_root()
    if not (root / MAIN_INDEX).is_file():
        print(f"ERROR missing {MAIN_INDEX}", file=sys.stderr)
        return 1

    errors: list[str] = []
    warnings: dict[str, list[str]] = {}

    def warn(kind: str, item: str) -> None:
        warnings.setdefault(kind, []).append(item)

    listed: set[str] = set()
    routed_in: dict[str, list[str]] = {}
    indexes: set[str] = set()
    pending = [MAIN_INDEX]
    while pending:
        index_name = pending.pop()
        if index_name in indexes:
            continue
        indexes.add(index_name)
        index_text = (root / index_name).read_text(encoding="utf-8")
        budget = MAIN_INDEX_BUDGET if index_name == MAIN_INDEX else SUB_INDEX_BUDGET
        size = len(index_text.encode("utf-8"))
        if size > budget:
            warn("index over budget", f"{index_name} {size}B > {budget}B")
        seen: set[str] = set()
        for name in index_refs(index_text):
            if name in seen:
                errors.append(f"duplicate index entry in {index_name}: {name}")
            seen.add(name)
            listed.add(name)
            routed_in.setdefault(name, []).append(index_name)
            path = root / name
            if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
                errors.append(f"indexed topic missing or outside store: {name}")
            elif path.name.startswith("MEMORY"):
                pending.append(name)
    # One route per topic: a second hook in another index drifts out of date on its own.
    for name, where in sorted(routed_in.items()):
        if len(where) > 1 and not name.startswith("indexes/"):
            warn("topic routed from several indexes", f"{name} ({', '.join(sorted(where))})")
    all_topics = {str(p.relative_to(root)) for p in root.rglob("*.md")} - indexes
    # archive/ is search-only: routes into it are allowed but not required.
    for name in sorted(all_topics - listed):
        if not name.startswith("archive/"):
            errors.append(f"topic not indexed: {name}")

    for name in sorted(all_topics):
        path = root / name
        text = path.read_text(encoding="utf-8")
        if LEGACY_WRAPPER_RE.match(text):
            warn("legacy add header", name)
        try:
            parsed = split_frontmatter(LEGACY_WRAPPER_RE.sub("", text, count=1))
        except ValueError as exc:
            warn("unparseable frontmatter", f"{name} ({exc})")
            parsed = None
        else:
            if parsed is None:
                warn("missing frontmatter", name)
        if parsed:
            fields, meta, _ = parsed
            if fields.get("name") != path.stem:
                warn("name differs from filename", name)
            if not fields.get("description"):
                warn("missing description", name)
            if meta.get("type") not in TYPES:
                warn("missing or invalid metadata.type", name)
        size = len(text.encode("utf-8"))
        if size > TOPIC_BUDGET and not name.startswith("archive/"):
            warn("topic over size budget", f"{name} {size // 1000}KB")
        if stat.S_IMODE(path.stat().st_mode) != 0o644:
            warn("permission not 644", name)

    # Links between topics: [[slug]] and `slug.md` must resolve to an active topic, an archived
    # file or a redirect; a rename that left old links behind shows up here.
    moved = redirects(root)
    active = {str(p.relative_to(root))[:-3] for p in root.glob("*.md")}
    archived = {p.stem for p in (root / "archive").glob("*.md")}
    for old, new in sorted(moved.items()):
        if new not in active:
            errors.append(f"redirect target missing: {old} -> {new}")
        if old in active:
            warn("redirected name is still an active topic", old)
    for name in sorted([MAIN_INDEX, *indexes, *(n for n in all_topics if not n.startswith("archive/"))]):
        text = (root / name).read_text(encoding="utf-8")
        wiki = set(re.findall(r"\[\[([^\]]+)\]\]", text))
        for link in [*wiki, *re.findall(r"`((?:archive/|indexes/)?[a-z0-9][\w.-]*)\.md`", text)]:
            slug = link.removesuffix(".md")
            if slug.startswith("archive/"):
                ok = slug[8:] in archived
            elif slug.startswith("indexes/"):
                ok = (root / f"{slug}.md").is_file()
            else:
                ok = slug in active or slug in archived or slug in moved or slug in {"MEMORY", "AGENTS", "CLAUDE", "SKILL", "README"}
            memoryish = link in wiki or slug.startswith(PREFIXES + ("archive/", "indexes/"))
            if not ok and memoryish:
                warn("dead topic link", f"{name}: {link}")
    for name in sorted(n for n in all_topics if not n.startswith("archive/")):
        if not Path(name).stem.startswith(PREFIXES):
            warn("topic name without a type prefix", name)

    for error in errors:
        print(f"ERROR {error}", file=sys.stderr)
    for kind, items in warnings.items():
        shown = items if args.verbose else items[:5]
        more = "" if len(shown) == len(items) else f" (+{len(items) - len(shown)} more, --verbose)"
        print(f"WARN {kind}: {len(items)}{more}", file=sys.stderr)
        for item in shown:
            print(f"  {item}", file=sys.stderr)
    status = "OK" if not errors else "FAIL"
    total = sum(len(items) for items in warnings.values())
    print(f"{status} {len(all_topics)} topics, {len(indexes)} indexes, {len(listed)} distinct routes, {total} warnings")
    return 1 if errors or (args.strict and warnings) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    index = sub.add_parser("index", help="print the compact memory index")
    index.add_argument("--lines", type=int, default=200)
    index.set_defaults(func=cmd_index)

    read = sub.add_parser("read", help="read one topic")
    read.add_argument("topic")
    read.set_defaults(func=cmd_read)

    search = sub.add_parser("search", help="rank topics containing every whitespace-separated term (archives included, ranked lower)")
    search.add_argument("query")
    search.add_argument("--exact", action="store_true", help="match the query as one literal phrase")
    search.add_argument("--limit", type=int, default=10, help="topics to show")
    search.add_argument("--lines", type=int, default=3, help="matching lines per topic")
    search.set_defaults(func=cmd_search)

    add = sub.add_parser("add", help="create or replace a topic and route it from an index")
    add.add_argument("slug")
    add.add_argument("--summary", required=True, help="one-line hook; becomes description and index text")
    add.add_argument("--body-file", required=True, help="Markdown file or - for stdin")
    add.add_argument("--type", choices=TYPES)
    add.add_argument("--index", help="index for new routes (default: the area index for the slug's prefix)")
    add.add_argument("--pin", action="store_true", help=f"route a new topic from {MAIN_INDEX} (durable conventions only)")
    add.add_argument("--replace", action="store_true")
    add.set_defaults(func=cmd_add)

    update = sub.add_parser("update", help="change an existing topic's summary, body and/or type, keeping the rest")
    update.add_argument("slug")
    update.add_argument("--summary")
    update.add_argument("--body-file", help="Markdown file or - for stdin")
    update.add_argument("--type", choices=TYPES)
    update.set_defaults(func=cmd_update)

    archive = sub.add_parser("archive", help="move topics into archive/ (no deletion) and repoint index routes")
    archive.add_argument("slugs", nargs="+")
    archive.add_argument("--drop-hooks", action="store_true", help="remove index lines that only route archived topics")
    archive.add_argument("--dry-run", action="store_true")
    archive.set_defaults(func=cmd_archive)

    normalize = sub.add_parser("normalize", help="migrate topics to the shared frontmatter format (dry run by default)")
    normalize.add_argument("--apply", action="store_true")
    normalize.set_defaults(func=cmd_normalize)

    doctor = sub.add_parser("doctor", help="check index/topic consistency and format health")
    doctor.add_argument("--verbose", action="store_true")
    doctor.add_argument("--strict", action="store_true", help="exit non-zero on warnings")
    doctor.set_defaults(func=cmd_doctor)
    return parser


def wrote(args: argparse.Namespace) -> list[str] | None:
    """Topics a successful command changed, or None when it changed nothing."""
    if args.command in ("add", "update"):
        return [args.slug]
    if args.command == "archive" and not args.dry_run:
        return list(args.slugs)
    if args.command == "normalize" and args.apply:
        return []
    return None


def record_history(args: argparse.Namespace) -> None:
    """Hand a finished write to memctl (when installed next to this script) so the change is
    committed to the store's history attributed to the agent that ran us. Best effort: the
    write already happened; without memctl, or before `memctl init`, history simply skips it."""
    targets = wrote(args)
    memctl = Path(os.environ.get("SHARED_MEMORY_MEMCTL") or Path(__file__).with_name("memctl"))
    if targets is None or os.environ.get("SHARED_MEMORY_HISTORY") == "0" or not memctl.is_file():
        return
    reason = " ".join([args.command, *targets])[:200]
    try:
        proc = subprocess.run([sys.executable, str(memctl), "snapshot", "--if-ready", "--quiet",
                               "--op", args.command, "--reason", reason],
                              env={**os.environ, "SHARED_MEMORY_DIR": str(memory_root())},
                              capture_output=True, text=True, timeout=60)
        if proc.returncode:
            print(f"note: history not recorded ({proc.stderr.strip()[:200]})", file=sys.stderr)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"note: history not recorded ({exc})", file=sys.stderr)


def main() -> int:
    args = build_parser().parse_args()
    code = args.func(args)
    if code == 0:
        record_history(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
