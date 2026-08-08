#!/usr/bin/env python3
"""Put the published generation where Jekyll will pick it up (#314).

The four dashboard outputs are moving off `master` onto an orphan data branch,
but the browser must keep fetching them from `assets/data/…` on the site. Jekyll
builds `_site` from the checkout, so the generation has to be in the checkout
before `jekyll-build-pages` runs. This is the step that puts it there.

Deliberately not `git checkout <ref> -- <paths>`: that writes the index as well,
and this runs inside a checkout whose state other steps depend on. The files are
read out of the fetched tree and written as one write set, the same way they were
published.

**Failure is loud on purpose.** While `master` still carries the same four files,
a fetch that fell back to them would be invisible — and it would go on being
invisible after they stop being tracked, at which point the site would quietly
serve whatever generation the checkout happened to have. `prepare_pages_artifact`
already refuses to build an artifact with pages missing; this refuses one built
from a data plane it could not read.

Usage (see .github/workflows/pages.yml):
  python3 scripts/build/fetch_data_plane.py
  python3 scripts/build/fetch_data_plane.py --branch other --into .
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# The checkout root, spelled out rather than via ROOT: `clawock` is not installed
# on the live host, so an import that resolves only because some other module
# widened sys.path first is a side effect, not a dependency (#265).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "data"))

from clawock.publish import GitBranchStore  # noqa: E402
from publish_data_branch import DATA_BRANCH, DATA_PLANE_FILES  # noqa: E402


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
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"")
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", "replace")
        print(f"✗ data-plane: cannot read {args.remote}/{args.branch}: "
              f"{detail.strip() or exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"✗ data-plane: {exc}", file=sys.stderr)
        return 1
    print(f"✓ data-plane: {len(written)} outputs from {args.remote}/{args.branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
