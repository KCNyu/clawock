#!/usr/bin/env python3
"""Seed the public brief archive from tracked history or add a validated brief."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

_CHECKOUT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CHECKOUT))
sys.path.insert(0, str(_CHECKOUT / "src"))

from publish_data_branch import BOT_EMAIL, BOT_NAME, DATA_BRANCH, REPOSITORY, ROOT, credential_findings  # noqa: E402
from clawock.publish import GitBranchStore, GitHubDispatchDeployer, brief_archive  # noqa: E402


def pub_briefs(store: GitBranchStore, files: dict[str, str]):
    findings = credential_findings(files)
    if findings:
        raise ValueError("credential scan refused the public brief archive update")

    return store.publish(
        files, label="data: brief archive", overlay=True,
        expand=lambda previous: brief_archive.generation_index(store, previous, files),
    )


def tracked_briefs(store: GitBranchStore, ref: str) -> dict[str, str]:
    revision = store._git("rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
    paths = store._git("ls-tree", "-r", "--name-only", revision, "memory")
    return {path: store._git_blob(revision, path)
            for path in paths.splitlines() if brief_archive.BRIEF_PATH.fullmatch(path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--seed-ref")
    source.add_argument("--brief", metavar="PATH")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default=DATA_BRANCH)
    parser.add_argument("--deploy", action="store_true",
                        help="request a Pages rebuild from the published archive")
    args = parser.parse_args()
    store = GitBranchStore(args.root, args.branch, remote=args.remote,
                           author_name=BOT_NAME, author_email=BOT_EMAIL)
    if args.seed_ref:
        briefs = tracked_briefs(store, args.seed_ref)
    else:
        briefs = brief_archive.read_brief(args.root, args.brief)
    result = pub_briefs(store, briefs)
    print(f"brief archive: {len(briefs)} inputs, receipt {result.receipt}, changed={result.changed}")
    if args.deploy:
        # Retry the deploy request even when the previous attempt already pushed.
        request = GitHubDispatchDeployer(REPOSITORY).request(
            reason=f"brief archive {result.receipt[:12]}")
        print(f"brief archive: requested {request}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"brief archive: {exc}") from exc
