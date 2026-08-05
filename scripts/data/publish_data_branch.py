#!/usr/bin/env python3
"""Publish the current dashboard generation to the orphan data branch (#314).

The four outputs `build_dashboard.py` writes are build products: nothing in the
live loop reads them back, and they account for 71% of the commits on `master`.
They belong on a branch that holds state rather than history.

This is the instance wiring, not the mechanism — `clawock.publish.GitBranchStore`
is the mechanism, and its default sibling `FilesystemStore` is what a third party
gets without configuring a remote. What lives here is the choice of *these four
files, this branch, this repository*.

Reads the outputs from the worktree exactly as they stand, so whatever the
semantic diff decided to publish (including clock-only files it restored to their
previous bytes) is what the data branch receives — byte-identical to what the
same generation puts on `master`. That equality is the acceptance criterion while
both destinations are written.

Usage:
  python3 scripts/data/publish_data_branch.py                # publish HEAD-of-worktree
  python3 scripts/data/publish_data_branch.py --branch other --remote origin
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from workspace import workspace_root  # noqa: E402

ROOT = workspace_root(Path(__file__).resolve().parents[2])
# The checkout root, so `clawock` is importable regardless of where WS points
# (#265, #313).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from clawock.publish import GitBranchStore  # noqa: E402
from dashboard_outputs import DASHBOARD_OUTPUTS  # noqa: E402

# The one place this name is decided. The reader imports it from here rather
# than restating it (`scripts/build/fetch_data_plane.py`), because a rename that
# updated only the writer would serve a stale generation with every gate green.
DATA_BRANCH = "data-plane"

# Same bot identity the scheduled publisher commits under. Injected per
# invocation by the store (`git -c`), never written to git config — a persistent
# identity would clobber kcn's interactive one.
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


def generation_label(root: Path) -> str:
    """Describe the generation being published, for the commit subject.

    Falls back to a bare label rather than failing: the branch is state, and the
    payloads carry their own generation IDs, so an unreadable subject line is not
    a reason to withhold a publish.
    """
    try:
        payload = json.loads(
            (root / "assets/data/dashboard.json").read_text(encoding="utf-8"))
        stamp = payload.get("generated_at")
    except (OSError, ValueError):
        stamp = None
    return f"data: dashboard generation {stamp}" if stamp else "data: dashboard generation"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT,
                        help="workspace holding the outputs to publish")
    parser.add_argument("--repo", type=Path, default=None,
                        help="repository to publish from (default: --root)")
    parser.add_argument("--branch", default=DATA_BRANCH)
    parser.add_argument("--remote", default="origin",
                        help="an ssh URL when a deploy key was selected; "
                             "publish_identity.sh exports the matching GIT_SSH_COMMAND")
    args = parser.parse_args()

    root = Path(args.root)
    files = {}
    for path in DASHBOARD_OUTPUTS:
        try:
            files[path] = (root / path).read_text(encoding="utf-8")
        except OSError as exc:
            # Refuse rather than publish a partial generation: the branch is
            # replaced wholesale, so a missing member is not "unchanged", it is
            # deleted from the data plane.
            print(f"✗ data-plane: cannot read {path}: {exc}", file=sys.stderr)
            return 1

    store = GitBranchStore(
        args.repo or root, args.branch, remote=args.remote,
        author_name=BOT_NAME, author_email=BOT_EMAIL,
    )
    try:
        result = store.publish(files, label=generation_label(root))
    except subprocess.CalledProcessError as exc:
        print(f"✗ data-plane: git failed: {exc.stderr or exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"✗ data-plane: {exc}", file=sys.stderr)
        return 1
    if not result.changed:
        print(f"· data-plane: {args.remote}/{args.branch} already holds this "
              f"generation ({result.receipt[:12]})")
        return 0
    print(f"✓ data-plane: published {len(files)} outputs as "
          f"{result.receipt[:12]} → {args.remote} {args.branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
