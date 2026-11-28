"""The public brief archive carried within a pinned data-plane generation."""
import hashlib
import json
from pathlib import Path
import re

INDEX = "assets/data/brief-archive.json"
BRIEF_PATH = re.compile(r"memory/(?:\d{4}-\d{2}-\d{2}-pre-open\.md|weekly/\d{4}-W\d{2}\.md)")


def fingerprint(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def index_entries(index_text: str) -> dict[str, str]:
    index = json.loads(index_text)
    if not isinstance(index, dict) or index.get("schema_version") != 1:
        raise ValueError("unsupported brief archive index")
    files = index.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("brief archive index is empty")
    for path, digest in files.items():
        if not BRIEF_PATH.fullmatch(path) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"invalid brief archive entry: {path!r}")
    return files


def update_index(previous: str | None, files: dict[str, str]) -> str:
    if not files or any(not BRIEF_PATH.fullmatch(path) for path in files):
        raise ValueError("brief archive update requires public daily or weekly Markdown")
    indexed = index_entries(previous) if previous is not None else {}
    indexed.update({path: fingerprint(body) for path, body in files.items()})
    return json.dumps({"schema_version": 1, "files": indexed}, sort_keys=True, indent=2) + "\n"


def verify(files: dict[str, str]) -> None:
    if INDEX not in files:
        return
    for path, digest in index_entries(files[INDEX]).items():
        if path not in files or fingerprint(files[path]) != digest:
            raise ValueError(f"brief archive entry missing or corrupt: {path}")


def read_brief(root: Path, path: str) -> dict[str, str]:
    if not BRIEF_PATH.fullmatch(path):
        raise ValueError("expected a public daily or weekly Markdown path")
    source = root / path
    if source.is_symlink() or not source.resolve().is_relative_to(root.resolve()):
        raise ValueError("brief must resolve inside the workspace")
    return {path: source.read_bytes().decode("utf-8")}


def generation_index(store, previous: str | None, briefs: dict[str, str]) -> dict[str, str]:
    prior = None
    if previous and store._git("ls-tree", "--name-only", previous, INDEX):
        prior = store._git_blob(previous, INDEX)
    return {INDEX: update_index(prior, briefs)}
