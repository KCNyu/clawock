"""Publication ownership and semantic diffs for generated JSON write sets.

The algorithm ships in the wheel. Output paths, clock-only fields and generation
groups are workspace configuration, so an installed package never inherits one
desk's artifact names or publication layout.
"""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
from pathlib import Path

from clawock.publish import write_generation  # noqa: F401
from clawock.workspace import workspace_root

ROOT = workspace_root()
CONTRACT_NAME = "dashboard-outputs.json"


def load_contract(root: Path | str = ROOT) -> dict:
    """Load and validate the workspace-owned output contract."""
    path = Path(root) / "config" / CONTRACT_NAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    outputs = payload.get("outputs") if isinstance(payload, dict) else None
    if (not isinstance(payload, dict) or payload.get("schema_version") != 1
            or not isinstance(outputs, dict) or not outputs):
        raise ValueError(f"{path} must declare schema_version 1 and non-empty outputs")
    for name, spec in outputs.items():
        if (not isinstance(name, str) or not name or Path(name).is_absolute()
                or ".." in Path(name).parts):
            raise ValueError(f"{path}: output paths must be non-empty and relative")
        if not isinstance(spec, dict):
            raise ValueError(f"{path}: outputs.{name} must be an object")
        for field in ("recursive_clock_fields", "top_level_clock_fields"):
            values = spec.get(field, [])
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value for value in values
            ):
                raise ValueError(f"{path}: outputs.{name}.{field} must be strings")
        group = spec.get("generation_group")
        if group is not None and (not isinstance(group, str) or not group):
            raise ValueError(f"{path}: outputs.{name}.generation_group is invalid")
    return payload


def output_paths(root: Path | str = ROOT) -> tuple[str, ...]:
    return tuple(load_contract(root)["outputs"])


# `write_generation` is re-exported from `clawock.publish`, not defined here.
# "Publish N files as one write set" stopped being specific to these four the
# moment the generation could go somewhere other than this worktree (#314), and
# `FilesystemStore` is the same operation with a directory in front of it. Two
# copies of a staging-then-swap loop is exactly the shape that drifts.


def _strip_recursive(value, fields):
    if isinstance(value, dict):
        for field in fields:
            value.pop(field, None)
        for child in value.values():
            _strip_recursive(child, fields)
    elif isinstance(value, list):
        for child in value:
            _strip_recursive(child, fields)
    return value


def semantic_value(path: str, value, *, contract=None, root: Path | str = ROOT):
    """Return a copy with build-clock-only metadata removed."""
    contract = contract or load_contract(root)
    spec = contract["outputs"].get(path, {})
    value = copy.deepcopy(value)
    recursive = set(spec.get("recursive_clock_fields", ()))
    if recursive:
        return _strip_recursive(value, recursive)
    if isinstance(value, dict):
        for field in spec.get("top_level_clock_fields", ()):
            value.pop(field, None)
    return value


class GitBaseline:
    """The generation currently committed at `rev`, and this repository's worktree.

    This is what the semantic diff has always compared against, now named so it
    can be replaced. `restore` is the part that is genuinely git-specific: it
    un-dirties the working tree after a rebuild that changed only build clocks,
    which only means anything where the outputs are tracked files.
    """

    name = "git"

    def __init__(self, root: Path | str = ROOT, rev: str = "HEAD") -> None:
        self.root = Path(root)
        self.rev = rev

    def load(self, path: str):
        raw = subprocess.check_output(
            ["git", "-C", str(self.root), "show", f"{self.rev}:{path}"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return json.loads(raw)

    def restore(self, root: Path, path: str) -> None:
        subprocess.run(
            ["git", "-C", str(root), "restore", f"--source={self.rev}",
             "--worktree", "--", path],
            check=True,
            capture_output=True,
            text=True,
        )


class DirectoryBaseline:
    """The generation as last published into a directory. No git, no worktree.

    What a filesystem publisher compares against once the outputs stop being
    repository history (#262). `restore` copies the previous bytes back over a
    clock-only rebuild, which is the same guarantee `git restore` gives — the
    publisher must not ship a file whose only change is when it was built.
    """

    name = "directory"

    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)

    def _file(self, path: str) -> Path:
        # Same layout `FilesystemStore` publishes and the same layout the data
        # branch holds: outputs keep their workspace-relative path. Flattening to
        # basename here would mean the baseline looked in one place and the store
        # wrote to another, which is only discoverable once they are wired to
        # each other.
        return self.directory / path

    def load(self, path: str):
        return json.loads(self._file(path).read_text(encoding="utf-8"))

    def restore(self, root: Path, path: str) -> None:
        (Path(root) / path).write_text(
            self._file(path).read_text(encoding="utf-8"), encoding="utf-8")


def semantic_changed_paths(root: Path | str = ROOT, *, restore_clock_only=True,
                           baseline=None):
    """Return generated outputs whose public meaning differs from the baseline.

    The baseline is what the last published generation was — `GitBaseline(root)`
    by default, which is this repository's ``HEAD`` and the behaviour every
    caller has today. It is a parameter because the outputs are on their way out
    of repository history (#262): once they are published to a directory or an
    object store, "what did we publish last time" stops being a git question,
    and this helper is the one place that assumed otherwise.

    Clock-only rebuilds are restored from the baseline by default. Missing
    outputs, invalid JSON, or a baseline that has no version of a file are
    conservatively treated as real changes so they cannot disappear from
    publication. Generation-linked outputs are decided as a group, so a
    projection is never restored while the payload it is stamped from gets
    published.
    """
    root = Path(root)
    contract = load_contract(root)
    outputs = tuple(contract["outputs"])
    baseline = baseline if baseline is not None else GitBaseline(root)
    changed = set()
    clock_only = set()
    for path in outputs:
        try:
            current = json.loads((root / path).read_text(encoding="utf-8"))
            previous = baseline.load(path)
        except (FileNotFoundError, json.JSONDecodeError, subprocess.SubprocessError):
            changed.add(path)
            continue

        if semantic_value(path, current, contract=contract) != semantic_value(
            path, previous, contract=contract
        ):
            changed.add(path)
        else:
            clock_only.add(path)

    groups: dict[str, set[str]] = {}
    for path, spec in contract["outputs"].items():
        if spec.get("generation_group"):
            groups.setdefault(spec["generation_group"], set()).add(path)
    for linked in groups.values():
        if changed & linked:
            changed |= clock_only & linked
            clock_only -= linked

    if restore_clock_only:
        for path in outputs:
            if path in clock_only:
                baseline.restore(root, path)
    return [path for path in outputs if path in changed]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Print semantically changed build_dashboard output paths.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--keep-clock-only", action="store_true",
                        help="do not restore outputs changed only by build clocks")
    parser.add_argument("--baseline-dir", type=Path, default=None,
                        help="compare against a directory holding the last "
                             "published generation instead of this repository's "
                             "HEAD (the outputs are no longer tracked, #314)")
    args = parser.parse_args(argv)
    baseline = DirectoryBaseline(args.baseline_dir) if args.baseline_dir else None
    for path in semantic_changed_paths(
        args.root, restore_clock_only=not args.keep_clock_only, baseline=baseline
    ):
        print(path)


if __name__ == "__main__":
    main()
