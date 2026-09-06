"""A command written in a SKILL.md has to be a command that runs (#777).

SKILL.md is not prose for a human to skim — it is handed to an execution engine
that types what it reads. `skills/daily-deep-brief/SKILL.md` told it to run
`node ../tavily-search/scripts/search.mjs`, which resolves only from inside
`skills/daily-deep-brief/`, and nothing ever puts it there. On 2026-08-21 the
model took four `Cannot find module` hits, guessed the path from openclaw's own
bundled-skills prefix, fell back to a whole-filesystem `find /`, then killed
that background session — and the kill's `isError` toolResult marked the entire
cron run as failed, on a morning where the brief had in fact been generated and
delivered to both channels.

So the invariant is not about that one line: **every script path a SKILL.md
tells the agent to run must name a file that exists in this repository.**
`{placeholder}` templates are exempt — those are for the loader to fill in.

This is the skills-side twin of #663's host-crontab gate: a command that cannot
run is a silent no-op wherever it is written down.
"""
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"

# `node scripts/x.mjs`, `python3 ops/y.py`, `bash ops/z.sh` — the interpreter
# forms these documents actually use. Backticks/quotes end the path.
INVOCATION = re.compile(r'\b(?:node|python3|bash)\s+([^\s`"\']+\.(?:mjs|js|py|sh))')
# Repository directories a documented absolute host path can be re-rooted from,
# so the gate works both on this host and on a CI checkout that lives elsewhere.
REPO_DIRS = ("skills", "ops", "scripts", "src", "config", "tests")


def _candidates(raw):
    """Every place `raw` could legitimately name, most specific first."""
    path = Path(raw)
    if not path.is_absolute():
        yield ROOT / path
        return
    parts = path.parts
    for marker in REPO_DIRS:
        if marker in parts:
            yield ROOT.joinpath(*parts[parts.index(marker):])
    yield path  # a genuine host path, on the host that has it


def _documented_commands():
    for skill_md in sorted(SKILLS.rglob("*.md")):
        for lineno, line in enumerate(skill_md.read_text().splitlines(), 1):
            for raw in INVOCATION.findall(line):
                yield skill_md.relative_to(ROOT), lineno, raw


def test_the_scan_actually_finds_commands():
    """A regex that matches nothing would make every assertion below vacuous."""
    found = list(_documented_commands())
    assert len(found) >= 10, f"only {len(found)} documented commands — the scan broke"


@pytest.mark.parametrize(
    "doc,lineno,raw",
    [pytest.param(d, n, raw, id=f"{d}:{n}") for d, n, raw in _documented_commands()],
)
def test_every_documented_script_path_resolves(doc, lineno, raw):
    if "{" in raw:
        return  # loader-substituted template, e.g. `node {baseDir}/scripts/search.mjs`
    assert any(c.is_file() for c in _candidates(raw)), (
        f"{doc}:{lineno} tells the agent to run `{raw}`, which resolves to no file "
        f"in this repository — the agent will improvise a path instead"
    )


def test_the_documented_section_list_is_one_the_tool_accepts():
    """Same invariant, one step in: an argument a SKILL.md tells the agent to
    pass has to be one the tool takes.

    The list is written out three times — the packet builds the sections, the
    tool enum accepts them, and this document tells the agent which to ask for.
    The middle copy had drifted to seven of twelve; this pins the third one to
    the first so it cannot drift on its own. A documented value the tool refuses
    is a `ToolError` in the middle of a brief, which is the same silent no-op
    #777 was about.
    """
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from clawock.decision import packet as packet_mod

    text = (SKILLS / "daily-deep-brief" / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"可选 section：`([^`]+)`", text)
    assert match, "the skill no longer documents the section list"
    documented = match.group(1).split("|")

    assert documented == list(packet_mod.QUERYABLE_SECTIONS), (
        f"documented={documented} accepted={list(packet_mod.QUERYABLE_SECTIONS)}")

