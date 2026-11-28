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

from publish_data_branch import BOT_EMAIL, BOT_NAME, DATA_BRANCH, ROOT, credential_findings  # noqa: E402
from clawock.publish import GitBranchStore, brief_archive  # noqa: E402


def pub_briefs(store: GitBranchStore, files: dict[str, str]):
    findings = credential_findings(files)
    if findings:
        raise ValueError("credential scan refused the public brief archive update")

    def expand(previous):
        index = None
        if previous and store._git("ls-tree", "--name-only", previous, brief_archive.INDEX):
            index = store._git_blob(previous, brief_archive.INDEX)
        return {brief_archive.INDEX: brief_archive.update_index(index, files)}

    return store.publish_updates(files, label="data: brief archive", expand=expand)


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
    args = parser.parse_args()
    store = GitBranchStore(args.root, args.branch, remote=args.remote,
                           author_name=BOT_NAME, author_email=BOT_EMAIL)
    if args.seed_ref:
        briefs = tracked_briefs(store, args.seed_ref)
    else:
        if not brief_archive.BRIEF_PATH.fullmatch(args.brief):
            parser.error("--brief must name a public daily or weekly Markdown file")
        path = args.root / args.brief
        if path.is_symlink() or not path.resolve().is_relative_to(args.root.resolve()):
            parser.error("--brief must resolve inside the workspace")
        briefs = {args.brief: path.read_bytes().decode("utf-8")}
    result = pub_briefs(store, briefs)
    print(f"brief archive: {len(briefs)} inputs, receipt {result.receipt}, changed={result.changed}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"brief archive: {exc}") from exc
