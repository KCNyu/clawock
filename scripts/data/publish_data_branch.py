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

# The checkout root, so `clawock` resolves from the tree this file ships
# in. Reached through the scripts/data/workspace shim until #267 step 3,
# whose only remaining job was inserting this path as a side effect.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from clawock.workspace import workspace_root  # noqa: E402

ROOT = workspace_root(Path(__file__).resolve().parents[2])
# The checkout root, so `clawock` is importable regardless of where WS points
# (#265, #313).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from clawock.publish import GitBranchStore, GitHubDispatchDeployer  # noqa: E402
from dashboard_outputs import DASHBOARD_OUTPUTS  # noqa: E402

# The one place this name is decided. The reader imports it from here rather
# than restating it (`ops/pages/fetch_data_plane.py`), because a rename that
# updated only the writer would serve a stale generation with every gate green.
DATA_BRANCH = "data-plane"

# The generation is six files, not four. `cron-heartbeats.json` and
# `workflow-outcomes.json` are written by the same tick as the four payloads and
# were the ONLY two entries left in the publisher's commit pathspec — which is
# why moving the four barely changed the commit count (#325). Nothing in the
# browser fetches them; `build_dashboard` embeds their content into the payload.
DATA_PLANE_EXTRA = (
    "assets/data/cron-heartbeats.json",
    "assets/data/workflow-outcomes.json",
)
DATA_PLANE_FILES = tuple(DASHBOARD_OUTPUTS) + DATA_PLANE_EXTRA

# Same bot identity the scheduled publisher commits under. Injected per
# invocation by the store (`git -c`), never written to git config — a persistent
# identity would clobber kcn's interactive one.
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"

# This instance's site. A third party publishing to a filesystem asks nobody for
# a deploy, which is why `--deploy` is opt-in rather than the default.
REPOSITORY = "KCNyu/clawock"


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
    parser.add_argument("--deploy", action="store_true",
                        help="ask GitHub to rebuild the site when this publish "
                             "changed the branch")
    args = parser.parse_args()

    root = Path(args.root)
    files = {}
    for path in DATA_PLANE_FILES:
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
        # Hooks commonly explain a refusal on stdout while git writes only its
        # generic final line to stderr. Keeping just stderr hid the actual
        # COST_BASIS gate behind "failed to push some refs" for an entire US
        # session (#370). Preserve both streams; callers can still bound how
        # much they persist, but the useful end must reach them first.
        detail = "\n".join(
            part.strip() for part in (exc.stdout, exc.stderr) if part and part.strip()
        ) or str(exc)
        print(f"✗ data-plane: git failed:\n{detail}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"✗ data-plane: {exc}", file=sys.stderr)
        return 1
    if not result.changed:
        # No deploy request either: the site already serves this generation, and
        # asking on every quiet tick would rebuild it 72 times a day for nothing.
        print(f"· data-plane: {args.remote}/{args.branch} already holds this "
              f"generation ({result.receipt[:12]})")
        return 0
    print(f"✓ data-plane: published {len(files)} outputs as "
          f"{result.receipt[:12]} → {args.remote} {args.branch}")

    if not args.deploy:
        return 0
    try:
        receipt = GitHubDispatchDeployer(REPOSITORY).request(
            reason=f"data-plane {result.receipt[:12]}")
    except (subprocess.CalledProcessError, OSError) as exc:
        # Loud, and non-zero. A generation that reached the branch but never
        # reached the site is the failure this whole seam exists to make
        # visible: nothing else in the system notices a site frozen on an old
        # generation.
        detail = getattr(exc, "stderr", "") or exc
        print(f"✗ data-plane: published, but the site deploy was not requested: "
              f"{detail}", file=sys.stderr)
        return 1
    print(f"✓ data-plane: requested {receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
