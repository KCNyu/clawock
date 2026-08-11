#!/usr/bin/env python3
"""Render one public package release from the matching CHANGELOG section.

The repository contains high-frequency private-instance/runtime commits that do
not ship in the ``clawock`` distribution. GitHub's generated release notes would
therefore describe the wrong product. ``CHANGELOG.md`` is the existing public
package boundary; this tool makes the GitHub Release use that same boundary.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def changelog_section(text: str, version: str) -> str:
    heading = re.compile(
        rf"^## \[{re.escape(version)}\](?:\s+[—-]\s+.*)?$", re.MULTILINE)
    matches = list(heading.finditer(text))
    if len(matches) != 1:
        raise ValueError(
            f"CHANGELOG must contain exactly one [{version}] heading; "
            f"found {len(matches)}")
    start = matches[0].end()
    remainder = text[start:]
    boundaries = [match.start() for pattern in (r"^##\s+", r"^\[[^\]]+\]:")
                  if (match := re.search(pattern, remainder, re.MULTILINE))]
    end = start + min(boundaries) if boundaries else len(text)
    body = text[start:end].strip()
    if not body:
        raise ValueError(f"CHANGELOG [{version}] section is empty")

    # Keep reference-style issue/PR links working, but do not drag every other
    # version's comparison/release URL into this version's notes.
    definitions = dict(re.findall(
        r"^\[([^\]]+)\]:\s*(\S+)\s*$", text, re.MULTILINE))
    used = dict.fromkeys(re.findall(r"\[([^\]]+)\](?!\()", body))
    refs = [f"[{label}]: {definitions[label]}" for label in used
            if label in definitions]
    return body + (("\n\n" + "\n".join(refs)) if refs else "")


def release_notes(text: str, version: str) -> str:
    pypi = f"https://pypi.org/project/clawock/{version}/"
    return (
        f"Install from [PyPI]({pypi}):\n\n"
        f"```console\npython -m pip install clawock=={version}\n```\n\n"
        f"{changelog_section(text, version)}\n"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        notes = release_notes(args.changelog.read_text(encoding="utf-8"), args.version)
    except (OSError, ValueError) as exc:
        print(f"ERROR: cannot render GitHub release notes: {exc}", file=sys.stderr)
        return 2
    if args.output:
        args.output.write_text(notes, encoding="utf-8")
    else:
        print(notes, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
