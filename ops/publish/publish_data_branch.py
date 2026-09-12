#!/usr/bin/env python3
"""Publish the current dashboard generation to the orphan data branch (#314).

The dashboard outputs are build products: nothing in the live loop reads them
back. They belong on a branch that holds the latest publication state rather
than in source history.

This is the instance wiring, not the mechanism — `clawock.publish.GitBranchStore`
is the mechanism, and its default sibling `FilesystemStore` is what a third party
gets without configuring a remote. What lives here is the choice of *these four
files, this branch, this repository*.

Reads the outputs from the worktree exactly as they stand, so whatever the
semantic diff selected (including clock-only files restored to their previous
bytes) is what the data branch receives as one generation.

Usage:
  python3 ops/publish/publish_data_branch.py                # publish HEAD-of-worktree
  python3 ops/publish/publish_data_branch.py --branch other --remote origin
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_CHECKOUT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CHECKOUT))
sys.path.insert(0, str(_CHECKOUT / "src"))
from clawock.workspace import workspace_root  # noqa: E402

ROOT = workspace_root(_CHECKOUT)

from clawock.publish import GitBranchStore, GitHubDispatchDeployer  # noqa: E402
from clawock.publish.outputs import output_paths  # noqa: E402

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

# One more file the browser DOES fetch, and the only member of this generation
# that is written on a different cadence from the rest: the weekly Search
# Console reading, committed by `seo-visibility.yml` once a week.
#
# It is kept out of `DATA_PLANE_FILES` deliberately. The branch is replaced
# wholesale, so the publisher refuses when a member cannot be read — correct for
# the files that share a tick, fatal for this one. A file that appears weekly, and
# that does not exist after a fresh checkout of the branch, would make every
# 20-minute tick refuse to publish the *entire* dashboard until the next Monday.
# Browser data that arrives on its own schedule is optional by construction: a
# missing one means the panel is absent, not that the generation is malformed.
DATA_PLANE_OPTIONAL = (
    "assets/data/crawl_visibility.json",
)

DATA_PLANE_FILES = output_paths(ROOT) + DATA_PLANE_EXTRA

# Failure classes, and the whole reason they are classes: `note_degradation`
# aggregates on (kind, detail), so a detail carrying this incident's text —
# a sha, a hostname, git's wording — writes a new row every time and the count
# that makes a rate readable never rises above 1. The incident's text is already
# on stderr, one line above.
PUBLISH_FAILED = "data_plane_publish_failed"


def note_failure(kind: str, reason: str) -> None:
    """Record a publisher failure where it can be counted, and never raise.

    The publisher runs every 20 minutes from host cron. Until now a failed tick
    left exactly one undated line in `logs/publish_dashboard.log`
    (`logs/dashboard_build_status.json` is a snapshot: the next tick overwrites
    it, so a failure that repaired itself is gone from every structured
    surface). That is the same state #1146 described for refused bars — "a
    source that fails once a quarter and one that fails every week look
    identical" — and the same answer applies: append it where it accrues a
    count and a first/last timestamp.

    Best-effort by construction. A publisher that crashed while recording that
    it had failed would be strictly worse than one that failed quietly.
    """
    try:
        from clawock.automation import workflow_outcomes

        workflow_outcomes.note_degradation(None, kind, reason)
    except Exception:
        pass


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
            note_failure(PUBLISH_FAILED, "an output file could not be read")
            return 1

    # Same whole-branch rule, opposite consequence, and the difference is the
    # cadence rather than the importance. See DATA_PLANE_OPTIONAL: refusing here
    # would let a file nobody wrote this week block the generation everybody
    # reads. An unreadable-but-present file is still refused, because that is a
    # real defect rather than a schedule.
    for path in DATA_PLANE_OPTIONAL:
        target = root / path
        if not target.is_file():
            print(f"· data-plane: {path} not written yet — publishing without it")
            continue
        try:
            files[path] = target.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"✗ data-plane: cannot read {path}: {exc}", file=sys.stderr)
            note_failure(PUBLISH_FAILED, "an output file could not be read")
            return 1

    store = GitBranchStore(
        args.repo or root, args.branch, remote=args.remote,
        author_name=BOT_NAME, author_email=BOT_EMAIL,
    )
    try:
        result = store.publish(files, label=generation_label(root))
    except subprocess.TimeoutExpired as exc:
        # A timeout is a diagnosis, not a crash. It is a SIBLING of
        # CalledProcessError, so before 2026-09-07 it fell through every handler
        # here and reached the caller as a raw traceback — the shape all 12 of
        # that day's publish failures took in logs/publish_dashboard.log.
        print(f"✗ data-plane: {' '.join(map(str, exc.cmd))!r} exceeded "
              f"{exc.timeout:g}s — the remote hung, the generation was not "
              f"published", file=sys.stderr)
        note_failure(PUBLISH_FAILED, "the remote hung past the git call timeout")
        return 1
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
        note_failure(PUBLISH_FAILED, "git refused the publish")
        return 1
    except ValueError as exc:
        print(f"✗ data-plane: {exc}", file=sys.stderr)
        note_failure(PUBLISH_FAILED, "the generation was rejected before publishing")
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
        # Its own class: the branch has the generation and the site does not,
        # which is the one failure here that does not repair itself on the next
        # tick — the next tick finds the branch unchanged and asks for nothing.
        note_failure("data_plane_deploy_not_requested",
                     "published to the branch, the site deploy was refused")
        return 1
    print(f"✓ data-plane: requested {receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
