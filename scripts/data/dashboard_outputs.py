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
import os
import subprocess
import tempfile
from pathlib import Path


from workspace import workspace_root  # noqa: E402

ROOT = workspace_root(Path(__file__).resolve().parents[2])

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


def write_generation(writes):
    """Publish the four outputs as ONE write set: stage every file, then swap.

    `writes` maps path -> already-serialized text. `safe_write_text` is atomic
    per file, so no single output can be torn — but four sequential calls are not
    atomic ACROSS files: a failure on the third leaves two files from the new
    generation beside two from the old, and every consumer of these payloads
    (the browser, the semantic diff, the publication pathspec) treats them as one
    generation.

    Staging every file first shrinks the window from "serialize + write + fsync,
    four times" down to the `os.replace` calls themselves, and converts the
    common failures — a full disk, a read-only mount, an unwritable directory —
    from "publish a mixed generation" into "publish nothing and raise".

    Targets are checked before anything is staged, because a target that cannot
    be replaced at all (one that is a directory) would otherwise fail in the swap
    loop, i.e. after earlier files had already been published — the exact outcome
    this exists to prevent.

    What remains is genuinely irreducible: the swap loop itself. If the directory
    is removed between staging and replacing, some files can land and others not.
    Four files cannot be swapped atomically without a transactional filesystem;
    this narrows the window to consecutive `os.replace` calls rather than closing
    it, and the payloads carry generation IDs so a reader can still tell.

    Returns the paths written, in the order given.
    """
    for path in map(Path, writes):
        if path.is_dir():
            raise IsADirectoryError(
                f"{path} is a directory; the write set cannot be swapped in")
    staged = []
    try:
        for path, text in writes.items():
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".staged-")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            staged.append((tmp, path))
    except BaseException:
        for tmp, _ in staged:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
        raise
    # Every byte is on disk; only the swaps remain.
    for tmp, path in staged:
        os.replace(tmp, path)
    return [str(path) for _, path in staged]


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


def _head_json(root: Path, path: str):
    raw = subprocess.check_output(
        ["git", "-C", str(root), "show", f"HEAD:{path}"],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    return json.loads(raw)


def _restore_head_worktree(root: Path, path: str):
    subprocess.run(
        ["git", "-C", str(root), "restore", "--source=HEAD", "--worktree", "--", path],
        check=True,
        capture_output=True,
        text=True,
    )


def semantic_changed_paths(root: Path | str = ROOT, *, restore_clock_only=True):
    """Return generated outputs whose public meaning differs from ``HEAD``.

    Clock-only rebuilds are restored to ``HEAD`` by default.  Missing/untracked
    outputs, invalid JSON, or a missing ``HEAD`` version are conservatively
    treated as real changes so they cannot disappear from publication.
    Generation-linked outputs are decided as a group, so a projection is never
    restored while the payload it is stamped from gets published.
    """
    root = Path(root)
    changed = set()
    clock_only = set()
    for path in DASHBOARD_OUTPUTS:
        try:
            current = json.loads((root / path).read_text(encoding="utf-8"))
            previous = _head_json(root, path)
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
                _restore_head_worktree(root, path)
    return [path for path in DASHBOARD_OUTPUTS if path in changed]


def main():
    parser = argparse.ArgumentParser(
        description="Print semantically changed build_dashboard output paths.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--keep-clock-only", action="store_true",
                        help="do not restore outputs changed only by build clocks")
    args = parser.parse_args()
    for path in semantic_changed_paths(
        args.root, restore_clock_only=not args.keep_clock_only
    ):
        print(path)


if __name__ == "__main__":
    main()
