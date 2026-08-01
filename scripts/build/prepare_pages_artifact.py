#!/usr/bin/env python3
"""Stage a public allowlist from an already-built GitHub Pages site.

This script never edits source data. Jekyll first builds ``_site`` from the
complete checkout; public files are then copied into a fresh ``_pages`` tree.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "config/pages-public.json"


def load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text())


def reconcile_sitemap(output_dir: Path, site_url: str) -> int:
    """Drop sitemap URLs that the allowlisted artifact does not publish."""
    sitemap = output_dir / "sitemap.xml"
    tree = ET.parse(sitemap)
    root = tree.getroot()
    public = urlsplit(site_url.rstrip("/"))
    base_path = public.path.rstrip("/")
    removed = 0
    for entry in list(root):
        loc = next(
            (node for node in entry if node.tag.rsplit("}", 1)[-1] == "loc"),
            None,
        )
        target = urlsplit((loc.text or "").strip()) if loc is not None else None
        if target is None or target.scheme != public.scheme or target.netloc != public.netloc:
            root.remove(entry)
            removed += 1
            continue
        path = unquote(target.path)
        if path in (base_path, f"{base_path}/"):
            relative = ""
        elif path.startswith(f"{base_path}/"):
            relative = path[len(base_path) + 1:]
        else:
            root.remove(entry)
            removed += 1
            continue
        candidates = [output_dir / relative]
        if not relative or relative.endswith("/"):
            candidates.append(output_dir / relative / "index.html")
        if not any(candidate.is_file() for candidate in candidates):
            root.remove(entry)
            removed += 1
    namespace = root.tag.partition("}")[0].removeprefix("{")
    if namespace:
        ET.register_namespace("", namespace)
    tree.write(sitemap, encoding="utf-8", xml_declaration=True)
    return removed


def prepare(
    site_dir: Path,
    output_dir: Path,
    *,
    source_root: Path = ROOT,
) -> tuple[int, int]:
    site_dir = site_dir.resolve()
    output_dir = output_dir.resolve()
    if not site_dir.is_dir():
        raise ValueError(f"Pages site directory does not exist: {site_dir}")
    if not (site_dir / "index.html").is_file():
        raise ValueError(f"refusing to stage a directory without index.html: {site_dir}")
    if output_dir == site_dir or output_dir.is_relative_to(site_dir):
        raise ValueError("Pages output must be a fresh sibling of the Jekyll site")
    if output_dir.exists():
        raise ValueError(f"Pages output already exists: {output_dir}")

    contract = load_contract()
    browser_data = tuple(contract["browser_data"])
    includes = tuple(contract["artifact_include"])
    repository_only = tuple(contract["repository_only"])
    overlap = [
        path
        for path in browser_data
        if not any(fnmatch.fnmatch(path, pattern) for pattern in includes)
        or any(fnmatch.fnmatch(path, pattern) for pattern in repository_only)
    ]
    if overlap:
        raise ValueError(f"browser data is not public in Pages: {overlap}")

    # Stage by allowlist instead of pruning the Jekyll tree: a new internal file
    # cannot become public merely because Jekyll learned how to render it.
    copied: list[str] = []
    for pattern in includes:
        for source in site_dir.glob(pattern):
            if not source.is_file():
                continue
            source.resolve().relative_to(site_dir)
            relative = source.relative_to(site_dir)
            destination = output_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied.append(relative.as_posix())

    removed_sitemap_urls = reconcile_sitemap(output_dir, contract["site_url"])

    missing_pages = [
        path for path in contract["required_pages"] if not (output_dir / path).is_file()
    ]
    if missing_pages:
        raise ValueError(f"required pages missing from artifact: {missing_pages}")

    # Optional sidecars may not exist before their first producer run. Once one
    # exists in the checkout, Jekyll and the public staging step must preserve it.
    missing_data = [
        path
        for path in browser_data
        if (source_root / path).is_file() and not (output_dir / path).is_file()
    ]
    if missing_data:
        raise ValueError(f"browser data missing from Pages artifact: {missing_data}")

    before = sum(path.stat().st_size for path in site_dir.rglob("*") if path.is_file())
    after = sum(path.stat().st_size for path in output_dir.rglob("*") if path.is_file())
    print(
        f"Pages artifact: {before:,} -> {after:,} bytes "
        f"({before - after:,} excluded; {len(set(copied))} public files; "
        f"{removed_sitemap_urls} sitemap URLs excluded)"
    )
    return before, after


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-dir", type=Path, default=ROOT / "_site")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "_pages")
    args = parser.parse_args()
    prepare(args.site_dir, args.output_dir)


if __name__ == "__main__":
    main()
