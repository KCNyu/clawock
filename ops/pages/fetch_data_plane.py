#!/usr/bin/env python3
"""Put the published generation where Jekyll will pick it up (#314).

The dashboard generation lives on an orphan data branch, while the browser
keeps fetching it from `assets/data/…` on the site. Jekyll
builds `_site` from the checkout, so the generation has to be in the checkout
before `jekyll-build-pages` runs. This is the step that puts it there.

Deliberately not `git checkout <ref> -- <paths>`: that writes the index as well,
and this runs inside a checkout whose state other steps depend on. The files are
read out of the fetched tree and written as one write set, the same way they were
published.

**Failure is loud on purpose.** Falling back to files from the source checkout
would quietly freeze the site on whichever generation happened to be present.
`prepare_pages_artifact`
already refuses to build an artifact with pages missing; this refuses one built
from a data plane it could not read.

Usage (see .github/workflows/pages.yml):
  python3 ops/pages/fetch_data_plane.py
  python3 ops/pages/fetch_data_plane.py --branch other --into .
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Source-tree execution must resolve both the product and the repository-owned
# publisher without depending on whichever module a caller imported first.
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ops" / "publish"))

from clawock.publish import GitBranchStore  # noqa: E402
from publish_data_branch import DATA_BRANCH, DATA_PLANE_FILES  # noqa: E402


READ_FAILED = "data_plane_read_failed"


def note_failure(reason: str) -> None:
    """Count a failed read where a rate is readable. Never raises — same rule as
    the writer's (`ops/publish/publish_data_branch.py`): the reason is a class,
    not this incident's text, because the sink aggregates on it."""
    try:
        from clawock.automation import workflow_outcomes

        workflow_outcomes.note_degradation(None, READ_FAILED, reason)
    except Exception:
        pass


def pre_split_members(store, error) -> list[str]:
    """Outputs the published generation may lack because it was built before them.

    A new output split out of an existing one (`split_from` in
    config/dashboard-outputs.json) cannot be on the data branch until the host
    publisher runs the code that writes it — and that code cannot merge while this
    step refuses every generation without it. The generation says which side of
    the split it is on: if the parent file still carries the sections, it predates
    the split and the missing member is expected. Anything else stays a failure.
    """
    missing = [name for name in DATA_PLANE_FILES if name in str(error)]
    if not missing:
        return []
    try:
        outputs = json.loads((ROOT / "config" / "dashboard-outputs.json")
                             .read_text(encoding="utf-8"))["outputs"]
    except (OSError, ValueError, KeyError):
        return []
    for name in missing:
        split = (outputs.get(name) or {}).get("split_from") or {}
        try:
            parent = json.loads(store._git_blob("FETCH_HEAD", split["file"]))
        except Exception:
            return []
        if not all(key in parent for key in split.get("keys") or ["\0"]):
            return []
    return missing


def _split_specs() -> dict:
    outputs = json.loads((ROOT / "config" / "dashboard-outputs.json")
                         .read_text(encoding="utf-8"))["outputs"]
    return {name: spec["split_from"] for name, spec in outputs.items()
            if spec.get("split_from")}


def materialize_split_members(into: Path, names) -> list[str]:
    """Write a pre-split generation's missing members from the parent's sections.

    The page and the browser contract then see the post-split shape — the new file
    is there, carrying exactly what the parent carried — instead of a 404 during the
    one publisher cycle it takes the host to start writing the file itself.
    """
    specs, written = _split_specs(), []
    for name in names:
        spec = specs[name]
        parent = json.loads((into / spec["file"]).read_text(encoding="utf-8"))
        body = {"as_of": parent.get("generated_at"),
                **{key: parent[key] for key in spec["keys"] if key in parent}}
        (into / name).write_text(json.dumps(body, ensure_ascii=False, separators=(",", ":")),
                                 encoding="utf-8")
        written.append(name)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--into", type=Path, default=None,
                        help="directory to materialise into (default: --repo)")
    parser.add_argument("--branch", default=DATA_BRANCH)
    parser.add_argument("--remote", default="origin")
    args = parser.parse_args()

    store = GitBranchStore(args.repo, args.branch, remote=args.remote)
    names = list(DATA_PLANE_FILES)
    try:
        try:
            written = store.fetch(args.into or args.repo, names=names)
        except FileNotFoundError as exc:
            excused = pre_split_members(store, exc)
            if not excused:
                raise
            print(f"· data-plane: the published generation predates {excused} "
                  "(its parent still carries the sections) — fetching the rest and "
                  "deriving them from it")
            written = store.fetch(args.into or args.repo,
                                  names=[n for n in names if n not in excused])
            written += materialize_split_members(Path(args.into or args.repo), excused)
    except subprocess.TimeoutExpired as exc:
        # Same sibling-not-subclass trap as publish_data_branch: a hung remote
        # reached the caller as a traceback instead of a diagnosis (2026-09-07).
        print(f"✗ data-plane: reading {args.remote}/{args.branch} exceeded "
              f"{exc.timeout:g}s — the remote hung", file=sys.stderr)
        note_failure("the remote hung past the git call timeout")
        return 1
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"")
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", "replace")
        print(f"✗ data-plane: cannot read {args.remote}/{args.branch}: "
              f"{detail.strip() or exc}", file=sys.stderr)
        note_failure("git could not read the branch")
        return 1
    except FileNotFoundError as exc:
        print(f"✗ data-plane: {exc}", file=sys.stderr)
        note_failure("the branch does not carry every file of a generation")
        return 1
    print(f"✓ data-plane: {len(written)} outputs from {args.remote}/{args.branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
