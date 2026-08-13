"""No source file may be invisible to `git add`.

`.gitignore` carried `build/` for pip/setuptools output. Unanchored, that pattern
matches at any depth, so it also matched `ops/pages/` — the directory holding
`prepare_pages_artifact.py`. Those files stayed tracked because they predate the
rule, which is precisely what made it invisible: the directory looked normal, and
a NEW script added there was silently dropped. `git add -A` reported nothing,
`git status` showed nothing, and the commit shipped without it.

This checks the shape that hides a file rather than any one pattern, so the next
unanchored rule cannot reintroduce it somewhere else.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Directories whose contents are hand-written source. Generated trees
# (assets/data, memory) are deliberately not here: some of what they hold is
# meant to be ignored.
SOURCE_TREES = ("src", "site", "ops", "scripts", "tests", ".github")


def test_no_hand_written_source_file_is_gitignored():
    candidates = [
        path.relative_to(ROOT).as_posix()
        for tree in SOURCE_TREES
        for path in (ROOT / tree).rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".sh", ".yml", ".yaml", ".js", ".json", ".md"}
        and "__pycache__" not in path.parts
    ]
    assert candidates, "no source files found — the globs are wrong"

    result = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "--stdin"],
        input="\n".join(candidates), capture_output=True, text=True,
    )
    ignored = [line for line in result.stdout.splitlines() if line.strip()]

    assert not ignored, (
        "these source files are gitignored, so adding one is a silent no-op: "
        f"{ignored}")
