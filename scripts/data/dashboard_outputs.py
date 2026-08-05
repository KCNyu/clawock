#!/usr/bin/env python3
"""Ownership and semantic-diff contract for build_dashboard.py outputs.

``build_dashboard.py`` writes four public files as one logical build.  Every
committer that invokes it must publish the same semantic write set:

* overview.json
* dashboard.json
* decision_audit.json
* shadow_portfolio.json

The files also contain build-clock metadata.  A rebuild that changes only those
fields must restore the tracked copy instead of leaving a dirty tree or creating
a no-op commit.
"""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path


from workspace import workspace_root  # noqa: E402

ROOT = workspace_root(Path(__file__).resolve().parents[2])
# The checkout root, so `clawock` is importable regardless of where WS points:
# WS is a data directory and can be redirected with CLAWOCK_WORKSPACE, while the
# package lives in the checkout (#265, #313).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from clawock.publish import write_generation  # noqa: E402,F401

# Keep this tuple explicit and ordered: callers use it as the exact publication
# pathspec, and the contract test fails when build_dashboard gains a new sidecar
# without adding an owner here.
DASHBOARD_OUTPUTS = (
    "assets/data/overview.json",
    "assets/data/dashboard.json",
    "assets/data/decision_audit.json",
    "assets/data/shadow_portfolio.json",
)

_RECURSIVE_CLOCK_FIELDS = {
    "assets/data/overview.json": {
        "generated_at", "generation_id", "age_hours", "days_behind",
    },
    "assets/data/dashboard.json": {"generated_at", "age_hours", "days_behind"},
}
_TOP_LEVEL_CLOCK_FIELDS = {
    "assets/data/decision_audit.json": {"as_of"},
    "assets/data/shadow_portfolio.json": {"as_of"},
}

# overview.json is a projection of dashboard.json and pins
# ``overview.generation_id == dashboard.generated_at``.  Per-file clock-only
# restores break that parity whenever the full payload changes in a field the
# projection does not carry: the projection is byte-identical, gets restored to
# HEAD, and stays one generation behind the payload published beside it.  These
# two publish together or not at all.
_GENERATION_LINKED = frozenset({
    "assets/data/overview.json",
    "assets/data/dashboard.json",
})


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


def semantic_value(path: str, value):
    """Return a copy with build-clock-only metadata removed."""
    value = copy.deepcopy(value)
    recursive = _RECURSIVE_CLOCK_FIELDS.get(path)
    if recursive:
        return _strip_recursive(value, recursive)
    if isinstance(value, dict):
        for field in _TOP_LEVEL_CLOCK_FIELDS.get(path, ()):
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
    baseline = baseline if baseline is not None else GitBaseline(root)
    changed = set()
    clock_only = set()
    for path in DASHBOARD_OUTPUTS:
        try:
            current = json.loads((root / path).read_text(encoding="utf-8"))
            previous = baseline.load(path)
        except (FileNotFoundError, json.JSONDecodeError, subprocess.SubprocessError):
            changed.add(path)
            continue

        if semantic_value(path, current) != semantic_value(path, previous):
            changed.add(path)
        else:
            clock_only.add(path)

    if changed & _GENERATION_LINKED:
        changed |= clock_only & _GENERATION_LINKED
        clock_only -= _GENERATION_LINKED

    if restore_clock_only:
        for path in DASHBOARD_OUTPUTS:
            if path in clock_only:
                baseline.restore(root, path)
    return [path for path in DASHBOARD_OUTPUTS if path in changed]


def main():
    parser = argparse.ArgumentParser(
        description="Print semantically changed build_dashboard output paths.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--keep-clock-only", action="store_true",
                        help="do not restore outputs changed only by build clocks")
    parser.add_argument("--baseline-dir", type=Path, default=None,
                        help="compare against a directory holding the last "
                             "published generation instead of this repository's "
                             "HEAD (the outputs are no longer tracked, #314)")
    args = parser.parse_args()
    baseline = DirectoryBaseline(args.baseline_dir) if args.baseline_dir else None
    for path in semantic_changed_paths(
        args.root, restore_clock_only=not args.keep_clock_only, baseline=baseline
    ):
        print(path)


if __name__ == "__main__":
    main()
