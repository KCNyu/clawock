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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--into", type=Path, default=None,
                        help="directory to materialise into (default: --repo)")
    parser.add_argument("--branch", default=DATA_BRANCH)
    parser.add_argument("--remote", default="origin")
    args = parser.parse_args()

    store = GitBranchStore(args.repo, args.branch, remote=args.remote)
    try:
        written = store.fetch(args.into or args.repo, names=DATA_PLANE_FILES)
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
