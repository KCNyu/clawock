"""One door for Python setup, one door for publishing to master.

Both composites already existed in spirit. `clawock-python` even documents the
problem in its own header — "Seven copies is seven places to forget" — and seven
*other* workflows went on hand-rolling the same two steps anyway (#806). The
versions then drifted into two setup-python majors with the older one sitting on
the release chain, and the most recently hand-rolled copy was added by the same
session that was quoting that header.

The publishing side is not a tidiness question at all. master's ruleset bypasses
exactly one actor, the deploy key, so a copy that reaches for a plain `git push`
is rejected — and it finds out on its first scheduled run, after doing the work,
with the runner about to be discarded (#803).

A comment did not hold either of these. An assertion might.
"""
from __future__ import annotations

from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
ACTIONS = ROOT / ".github" / "actions"

# brief-fallback publishes through its own step on purpose: it gates on
# logs/brief_postflight_status.json before committing, and pushes only when HEAD
# is genuinely ahead of FETCH_HEAD — postflight's internal commit can succeed
# while its push fails, and gating on a dirty index would strand that commit on
# a runner about to be destroyed. That is a documented difference, not a copy.
PUBLISHES_ITS_OWN = {"brief-fallback.yml"}


def test_the_workflows_exist_so_none_of_this_passes_vacuously():
    assert len(WORKFLOWS) > 10
    assert (ACTIONS / "clawock-python" / "action.yml").is_file()
    assert (ACTIONS / "clawock-commit" / "action.yml").is_file()


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_no_workflow_sets_up_python_by_hand(workflow):
    """The pinned version has to be decided in one place. When it was not, the
    release chain quietly stayed a major version behind everything else."""
    assert "actions/setup-python@" not in workflow.read_text(encoding="utf-8"), (
        f"{workflow.name} pins its own Python. Use ./.github/actions/clawock-python "
        "— it takes `python-version` and `install` (including `install: none` for "
        "jobs that need no package)."
    )


def test_the_composite_is_the_only_place_that_pins_python():
    composite = (ACTIONS / "clawock-python" / "action.yml").read_text(encoding="utf-8")
    assert "actions/setup-python@" in composite


def test_the_no_install_escape_hatch_actually_skips_the_install():
    """`install: none` exists so a stdlib-only job still comes through the one
    door. If the guard is dropped, those jobs silently gain a pip install and
    the escape hatch becomes a lie."""
    composite = (ACTIONS / "clawock-python" / "action.yml").read_text(encoding="utf-8")
    assert "if: inputs.install != 'none'" in composite


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_no_workflow_hand_rolls_the_commit_and_push(workflow):
    text = workflow.read_text(encoding="utf-8")
    if "git config user.name" not in text:
        return
    assert workflow.name in PUBLISHES_ITS_OWN, (
        f"{workflow.name} hand-rolls the bot identity and commit. Use "
        "./.github/actions/clawock-commit, which is also the only thing that "
        "guarantees the push goes through safe_push.sh — master's ruleset "
        "rejects anything else, and a copy discovers that on its first "
        "scheduled run, after doing the work."
    )


def test_the_documented_exception_still_earns_it():
    """If brief-fallback ever loses the two things that make it different, it is
    a copy again and belongs in the composite."""
    text = (ROOT / ".github" / "workflows" / "brief-fallback.yml").read_text(encoding="utf-8")
    assert "brief_postflight_status.json" in text, "the publish gate is gone"
    assert "FETCH_HEAD" in text, "the ahead-of-remote check is gone"
    assert "safe_push.sh" in text


def test_the_commit_composite_can_only_publish_through_safe_push():
    action = (ACTIONS / "clawock-commit" / "action.yml").read_text(encoding="utf-8")
    assert "ops/publish/safe_push.sh" in action
    code = "\n".join(l for l in action.splitlines() if not l.lstrip().startswith("#"))
    assert "git push" not in code, (
        "the composite must not push directly; safe_push.sh owns the deploy key, "
        "the rebase-retry and the conflict-marker guard"
    )


def test_the_commit_composite_stages_nothing_when_nothing_changed():
    """Every copy it replaced had this, and a composite that lost it would turn
    ~35 quiet scheduled runs a week into ~35 empty commits."""
    action = (ACTIONS / "clawock-commit" / "action.yml").read_text(encoding="utf-8")
    assert "git diff --cached --quiet" in action
    assert "committed=false" in action


def test_the_deploy_key_is_not_an_input_to_the_composite():
    """It stays an `env:` at step scope, which is the shape the deploy-key
    scoping test enforces. Threading it through `with:` would move a secret into
    a place that test cannot see."""
    action = (ACTIONS / "clawock-commit" / "action.yml").read_text(encoding="utf-8")
    inputs = action.split("inputs:", 1)[1].split("runs:", 1)[0]
    assert "CLAWOCK_PUBLISH_SSH_KEY" not in inputs


def test_dependency_review_runs_on_prs_without_being_able_to_block_them():
    """#811. Dependabot reports after a dependency lands on master; this is the
    PR-time half.

    It is advisory on purpose. Its red is decided by the outside world — a CVE
    disclosed this morning against a package nobody in this PR touched — rather
    than by the diff. A gate whose failures are unrelated to the change under
    review is one people learn to route around, and this repository has already
    paid for false reds several times over.
    """
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "dependency-review-action@" in workflow

    step = workflow.split("- name: Dependency review", 1)[1].split("- name:", 1)[0]
    assert "github.event_name == 'pull_request'" in step, "it can only read a PR diff"
    assert "continue-on-error: true" in step, (
        "dependency review must not be able to fail the required `validate` check"
    )

    ref = next(line.split("@", 1)[1].split()[0] for line in step.splitlines()
               if "dependency-review-action@" in line)
    assert re.fullmatch(r"[0-9a-f]{40}", ref), f"pin it to a commit, got {ref!r}"


def test_the_required_check_list_has_not_quietly_grown():
    """If dependency review is ever added to the ruleset's required contexts,
    the reasoning above is void and this should be a deliberate decision, not a
    side effect."""
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    job = workflow.split("\n  validate:", 1)[1].split("\n  smoke-data-fetch:", 1)[0]
    advisory = [name for name in ("Dependency review",) if f"- name: {name}" in job]
    for name in advisory:
        block = job.split(f"- name: {name}", 1)[1].split("- name:", 1)[0]
        assert "continue-on-error: true" in block


# --- the Playwright door (#884) ----------------------------------------------
#
# clawock-python exists because seven hand-rolled setup copies drifted; two
# consumers install the Playwright browser stack today, and the same drift is
# one copy away. The composite owns the version pin and the shared cache key.

PLAYWRIGHT_COMPOSITE = ACTIONS / "clawock-playwright" / "action.yml"
PLAYWRIGHT_CONSUMERS = {"ci.yml", "screenshot-refresh.yml"}


def test_the_playwright_composite_owns_the_version_and_the_cache_key():
    composite = PLAYWRIGHT_COMPOSITE.read_text(encoding="utf-8")
    assert "actions/setup-node@" in composite
    version = re.search(r"default: '(\d+\.\d+\.\d+)'", composite)
    assert version, "the playwright pin must be a plain default input"
    for marker in (
        f"playwright-${{{{ inputs.version }}}}-${{{{ runner.os }}}}",
        "path: ~/.cache/ms-playwright",
        f"playwright@${{{{ inputs.version }}}}",
    ):
        assert marker in composite, marker


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda p: p.name)
def test_no_workflow_installs_playwright_by_hand(workflow):
    """The ~150MB browser build and its version pin have one door."""
    text = workflow.read_text(encoding="utf-8")
    assert "npx playwright install" not in text and "ms-playwright" not in text, (
        f"{workflow.name} installs Playwright by hand. Use "
        "./.github/actions/clawock-playwright — it owns the version pin and "
        "the browser cache key shared with the other consumer."
    )


@pytest.mark.parametrize("name", sorted(PLAYWRIGHT_CONSUMERS))
def test_every_playwright_consumer_goes_through_the_door(name):
    path = ROOT / ".github" / "workflows" / name
    assert path.is_file(), f"{name} disappeared; update PLAYWRIGHT_CONSUMERS"
    assert "./.github/actions/clawock-playwright" in path.read_text(encoding="utf-8")
