#!/usr/bin/env python3
"""Prune repository-only files from an already-built GitHub Pages artifact.

This script never edits source data. Jekyll first builds ``_site`` from the
complete checkout; only that disposable deployment copy is pruned.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "config/pages-public.json"


def load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text())


def prepare(site_dir: Path, *, source_root: Path = ROOT) -> tuple[int, int]:
    site_dir = site_dir.resolve()
    if not site_dir.is_dir():
        raise ValueError(f"Pages site directory does not exist: {site_dir}")
    if not (site_dir / "index.html").is_file():
        raise ValueError(f"refusing to prune a directory without index.html: {site_dir}")

    contract = load_contract()
    browser_data = tuple(contract["browser_data"])
    excludes = tuple(contract["artifact_excludes"])
    overlap = [
        path
        for path in browser_data
        if any(fnmatch.fnmatch(path, pattern) for pattern in excludes)
    ]
    if overlap:
        raise ValueError(f"browser data is excluded from Pages: {overlap}")

    # Optional sidecars may not exist before their first producer run. Once one
    # exists in the checkout, Jekyll must have copied it into the deployment.
    missing = [
        path
        for path in browser_data
        if (source_root / path).is_file() and not (site_dir / path).is_file()
    ]
    if missing:
        raise ValueError(f"browser data missing from Pages artifact: {missing}")

    before = sum(path.stat().st_size for path in site_dir.rglob("*") if path.is_file())
    removed: list[str] = []
    for pattern in excludes:
        for path in site_dir.glob(pattern):
            if not path.is_file():
                continue
            # ``glob`` is rooted at site_dir, but keep the deletion boundary
            # explicit so a future contract edit cannot escape via ``..``.
            path.resolve().relative_to(site_dir)
            removed.append(path.relative_to(site_dir).as_posix())
            path.unlink()
    after = sum(path.stat().st_size for path in site_dir.rglob("*") if path.is_file())
    print(
        f"Pages artifact: {before:,} -> {after:,} bytes "
        f"({before - after:,} removed across {len(removed)} files)"
    )
    for path in sorted(removed):
        print(f"  excluded: {path}")
    return before, after


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-dir", type=Path, default=ROOT / "_site")
    args = parser.parse_args()
    prepare(args.site_dir)


if __name__ == "__main__":
    main()
