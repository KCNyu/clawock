"""Storing a generation and making it visible are different jobs (#314).

They were the same act here: a `dashboard:` commit matched the Pages workflow's
`paths:` filter, so pushing the data *was* the trigger. Once the data leaves
`master` the trigger leaves with it, and the failure mode is the quiet one — the
site keeps serving the last generation it happened to build, with every gate
green.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clawock.publish import GitHubDispatchDeployer, NullDeployer  # noqa: E402

WORKFLOW = (ROOT / ".github/workflows/pages.yml").read_text()


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def workspace(tmp_path):
    """A checkout with a remote and a fake `gh`, so a publish can run for real."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "master", str(origin))
    work = tmp_path / "work"
    (work / "assets" / "data").mkdir(parents=True)
    _git(work, "init", "-b", "master")
    _git(work, "config", "user.name", "test")
    _git(work, "config", "user.email", "test@example.invalid")
    _git(work, "remote", "add", "origin", str(origin))
    for name in ("overview", "dashboard", "decision_audit", "shadow_portfolio"):
        (work / "assets" / "data" / f"{name}.json").write_text(
            json.dumps({"generated_at": "2026-08-05T00:00:00Z", "name": name}),
            encoding="utf-8")
    (work / "README.md").write_text("source\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "seed")
    _git(work, "push", "-u", "origin", "master")
    return work


def _fake_gh(tmp_path, *, exit_code=0):
    """A `gh` that records its arguments instead of talking to GitHub."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "gh.log"
    (bin_dir / "gh").write_text(
        f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> {log}\nexit {exit_code}\n',
        encoding="utf-8")
    (bin_dir / "gh").chmod(0o755)
    return bin_dir, log


def _publish(workspace, bin_dir, *extra):
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/data/publish_data_branch.py"),
         "--root", str(workspace), "--remote", "origin", *extra],
        cwd=workspace, env=env, capture_output=True, text=True)


def test_the_dispatch_names_the_event_the_workflow_listens_for(tmp_path):
    """Two files have to agree on a string neither can validate at runtime. A
    rename on one side alone leaves the publisher reporting a successful request
    for an event nothing handles — every gate green, site frozen."""
    bin_dir, log = _fake_gh(tmp_path)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    subprocess.run([sys.executable, "-c",
                    "import sys; sys.path.insert(0, %r);"
                    "from clawock.publish import GitHubDispatchDeployer as D;"
                    "D('KCNyu/clawock').request('why')" % str(ROOT)],
                   env=env, check=True, capture_output=True, text=True)

    sent = log.read_text()
    event = re.search(r"event_type=(\S+)", sent).group(1)
    declared = re.search(r"repository_dispatch:\s*\n\s*types:\s*\[([^\]]+)\]",
                         WORKFLOW).group(1)

    assert event in [name.strip() for name in declared.split(",")]
    assert "repos/KCNyu/clawock/dispatches" in sent


def test_a_dispatched_run_is_allowed_to_deploy():
    """The build job runs for pull requests too, so the deploy job's condition is
    the only thing deciding what reaches the site. Adding the trigger without
    adding it here would build the new generation and deploy nothing."""
    block = WORKFLOW.split("  deploy:", 1)[1].split("needs:", 1)[0]
    condition = "\n".join(line for line in block.splitlines()
                          if not line.strip().startswith("#"))

    assert "github.event_name == 'repository_dispatch'" in condition
    assert "pull_request" not in condition, (
        "a pull request build must never reach the live site")


def test_a_publish_that_could_not_ask_for_a_deploy_is_not_success(workspace, tmp_path):
    """A generation on the branch that never reached the site is exactly the
    failure this seam exists to surface — nothing else in the system notices a
    frozen site. It must not exit 0."""
    bin_dir, _ = _fake_gh(tmp_path, exit_code=1)

    result = _publish(workspace, bin_dir, "--deploy")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "site deploy was not requested" in result.stderr
    assert "published" in result.stdout, (
        "the publish itself succeeded and must still be reported")


def test_an_unchanged_generation_asks_for_nothing(workspace, tmp_path):
    """72 ticks a day, and most change nothing. Asking every time would rebuild
    and redeploy the site for a generation it already serves."""
    bin_dir, log = _fake_gh(tmp_path)

    first = _publish(workspace, bin_dir, "--deploy")
    second = _publish(workspace, bin_dir, "--deploy")

    assert first.returncode == 0 and second.returncode == 0
    assert "already holds this generation" in second.stdout
    assert len(log.read_text().splitlines()) == 1, (
        "the unchanged republish must not have asked for a deploy")


def test_publishing_without_the_flag_asks_no_one(workspace, tmp_path):
    """A third party publishing to a filesystem has nobody to ask. The deploy
    request is this instance's configuration, so it is opt-in."""
    bin_dir, log = _fake_gh(tmp_path)

    result = _publish(workspace, bin_dir)

    assert result.returncode == 0
    assert not log.exists(), "a publish without --deploy must not invoke gh"


def test_the_null_deployer_reports_rather_than_pretends():
    """"No deploy step" is a decision the code states once, not a branch every
    caller writes."""
    assert NullDeployer().request("anything")
    assert GitHubDispatchDeployer("owner/repo").event_type == "data-plane-published"
