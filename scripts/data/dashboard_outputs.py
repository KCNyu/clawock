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
    """
    root = Path(root)
    changed = []
    for path in DASHBOARD_OUTPUTS:
        try:
            current = json.loads((root / path).read_text(encoding="utf-8"))
            previous = _head_json(root, path)
        except (FileNotFoundError, json.JSONDecodeError, subprocess.SubprocessError):
            changed.append(path)
            continue

        if semantic_value(path, current) != semantic_value(path, previous):
            changed.append(path)
        elif restore_clock_only:
            _restore_head_worktree(root, path)
    return changed


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
