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
    # Every member of the published generation, read from the publisher rather
    # than restated — the set grew from four to six in #325, and a fixture that
    # named them would have silently tested a smaller generation.
    sys.path.insert(0, str(ROOT / "ops" / "publish"))
    from publish_data_branch import DATA_PLANE_FILES
    for name in DATA_PLANE_FILES:
        target = work / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"generated_at": "2026-08-05T00:00:00Z", "name": name}),
            encoding="utf-8")
    (work / "README.md").write_text("source\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "seed")
    _git(work, "push", "-u", "origin", "master")
    return work


def _fake_gh(tmp_path, *, exit_code=0):
    """A `gh` that records its arguments AND the request body it was handed.

    Recording only the arguments is what let a real 422 through: the body was
    being sent as `--raw-field client_payload={...}`, which GitHub receives as a
    *string*, and it requires an object. A fake that just exits 0 agrees with
    anything — the assertions below parse what it captured.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "gh.log"
    body = tmp_path / "gh.body"
    (bin_dir / "gh").write_text(
        f'#!/usr/bin/env bash\n'
        f'printf "%s\\n" "$*" >> {log}\n'
        f'if [ -t 0 ]; then :; else cat > {body}; fi\n'
        f'exit {exit_code}\n',
        encoding="utf-8")
    (bin_dir / "gh").chmod(0o755)
    return bin_dir, log, body


def _publish(workspace, bin_dir, *extra):
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    return subprocess.run(
        [sys.executable, str(ROOT / "ops/publish/publish_data_branch.py"),
         "--root", str(workspace), "--remote", "origin", *extra],
        cwd=workspace, env=env, capture_output=True, text=True)


def test_the_dispatch_names_the_event_the_workflow_listens_for(tmp_path):
    """Two files have to agree on a string neither can validate at runtime. A
    rename on one side alone leaves the publisher reporting a successful request
    for an event nothing handles — every gate green, site frozen."""
    bin_dir, log, body = _fake_gh(tmp_path)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    subprocess.run([sys.executable, "-c",
                    "import sys; sys.path.insert(0, %r);"
                    "from clawock.publish import GitHubDispatchDeployer as D;"
                    "D('KCNyu/clawock').request('why')" % str(ROOT / "src")],
                   env=env, check=True, capture_output=True, text=True)

    assert "repos/KCNyu/clawock/dispatches" in log.read_text()
    sent = json.loads(body.read_text())
    declared = re.search(r"repository_dispatch:\s*\n\s*types:\s*\[([^\]]+)\]",
                         WORKFLOW).group(1)

    assert sent["event_type"] in [name.strip() for name in declared.split(",")]
    # GitHub rejects a `client_payload` that is not an object, with a 422 the
    # publisher reports as "the site deploy was not requested" — a real failure
    # that a fake `gh` exiting 0 was perfectly happy with.
    assert isinstance(sent.get("client_payload"), dict), sent


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
    bin_dir, _, _ = _fake_gh(tmp_path, exit_code=1)

    result = _publish(workspace, bin_dir, "--deploy")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "site deploy was not requested" in result.stderr
    assert "published" in result.stdout, (
        "the publish itself succeeded and must still be reported")


def test_an_unchanged_generation_asks_for_nothing(workspace, tmp_path):
    """72 ticks a day, and most change nothing. Asking every time would rebuild
    and redeploy the site for a generation it already serves."""
    bin_dir, log, body = _fake_gh(tmp_path)

    first = _publish(workspace, bin_dir, "--deploy")
    second = _publish(workspace, bin_dir, "--deploy")

    assert first.returncode == 0 and second.returncode == 0
    assert "already holds this generation" in second.stdout
    assert len(log.read_text().splitlines()) == 1, (
        "the unchanged republish must not have asked for a deploy")


def test_publishing_without_the_flag_asks_no_one(workspace, tmp_path):
    """A third party publishing to a filesystem has nobody to ask. The deploy
    request is this instance's configuration, so it is opt-in."""
    bin_dir, log, body = _fake_gh(tmp_path)

    result = _publish(workspace, bin_dir)

    assert result.returncode == 0
    assert not log.exists(), "a publish without --deploy must not invoke gh"


def test_the_null_deployer_reports_rather_than_pretends():
    """"No deploy step" is a decision the code states once, not a branch every
    caller writes."""
    assert NullDeployer().request("anything")
    assert GitHubDispatchDeployer("owner/repo").event_type == "data-plane-published"
