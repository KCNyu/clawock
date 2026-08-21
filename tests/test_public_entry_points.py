"""The repository's public front door.

An outside reader arrives with one of four things: a defect, a question, an
idea, or something they built. Until #786 only the first had anywhere to go —
Discussions was off and the only issue form was `bug_report` — so the other
three either became a fake bug report or, far more likely, nothing at all. In
14 days /issues had 6 unique visitors and /pulls had 4, so people were looking.

These assertions are about keeping the door open, not about taste. The failure
mode is silent: nobody files an issue saying "I had a question and left".
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"


@pytest.fixture(scope="module")
def contact_links() -> list[dict]:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["contact_links"]


@pytest.mark.parametrize("category", ["q-a", "ideas", "show-and-tell"])
def test_the_non_bug_visitor_has_somewhere_to_go(contact_links, category):
    urls = [link["url"] for link in contact_links]
    wanted = f"https://github.com/KCNyu/clawock/discussions/categories/{category}"
    assert wanted in urls, (
        f"no entry point for {category}; a reader with something that is not a "
        "defect is pushed into filing a fake bug report"
    )


def test_every_contact_link_says_what_it_is_for(contact_links):
    for link in contact_links:
        assert link.get("name"), f"contact link without a name: {link}"
        assert link.get("about"), f"contact link without an about: {link['name']}"
        assert link["url"].startswith("https://"), link["url"]


def test_the_security_route_stays_ahead_of_the_public_ones(contact_links):
    """A vulnerability must never be the thing someone files publicly because
    the private route was buried under three friendly links."""
    names = [link["name"] for link in contact_links]
    security = next(i for i, n in enumerate(names) if "security" in n.lower())
    assert security < len(names) - 1, "the private disclosure route must not be last"


def test_a_release_opens_an_announcement_thread_without_being_able_to_break_the_release():
    """The thread is worth having — it makes a release repliable and indexable —
    but it is not the deliverable. Putting --discussion-category on
    `gh release create` would let a Discussions failure leave a tagged version
    with no GitHub Release at all, and the retry then collides with the release
    that partially exists.
    """
    workflow = RELEASE.read_text(encoding="utf-8")
    job = workflow.split("\n  github-release:\n", 1)[1]

    assert "discussions: write" in job, "the job needs permission to open the thread"
    assert "--discussion-category Announcements" in job

    # Comments in this job discuss --discussion-category at length; only the
    # executable lines decide what actually happens.
    code = "\n".join(line for line in job.splitlines()
                     if not line.lstrip().startswith("#"))

    create = code.index("gh release create")
    edit = code.index("gh release edit")
    assert edit > create, "the announcement must come after the release exists"
    assert "--discussion-category" not in code[create:edit], (
        "the announcement must not be an argument to `gh release create` — a "
        "failure there would abort publishing the release itself"
    )
    assert "continue-on-error: true" in code[:edit], (
        "a missing announcement thread must not fail the release job"
    )
