#!/usr/bin/env python3
"""Assemble the Jekyll source tree from owned repository directories.

Static website source lives in ``site/``. Runtime-generated public data stays
in the KCNyu workspace at its producer-owned paths until the data-plane
contract is migrated. This staging step joins those inputs without making the
repository root double as the website source directory.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _copy(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    elif source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def stage(output_dir: Path, *, source_root: Path = ROOT) -> Path:
    output_dir = output_dir.resolve()
    source_root = source_root.resolve()
    site_source = source_root / "site"
    if not (site_source / "index.html").is_file():
        raise ValueError(f"site source has no index.html: {site_source}")
    if output_dir.exists():
        raise ValueError(f"site staging output already exists: {output_dir}")

    shutil.copytree(site_source, output_dir)

    # Product/legal documentation is repository-owned but publicly rendered.
    for relative in ("docs", "THIRD_PARTY_LICENSES", "LICENSE", "NOTICE"):
        _copy(source_root / relative, output_dir / relative)

    # These files are live-instance outputs. Copying is intentionally one-way:
    # Jekyll must never write back into the portfolio workspace.
    _copy(source_root / "site" / "evidence.md", output_dir / "evidence.md")
    _copy(source_root / "assets" / "data", output_dir / "assets" / "data")
    for report in sorted((source_root / "memory").glob("*-pre-open.md")):
        _copy(report, output_dir / "memory" / report.name)
    _copy(source_root / "memory" / "weekly", output_dir / "memory" / "weekly")

    print(f"staged Jekyll source: {site_source} + public runtime inputs -> {output_dir}")
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "_site-source")
    args = parser.parse_args()
    stage(args.output_dir)


if __name__ == "__main__":
    main()
