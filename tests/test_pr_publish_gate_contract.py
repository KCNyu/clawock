"""Contracts for the PR gate and the two automation-only publish identities."""

from pathlib import Path
import os
import subprocess


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PUBLISH_CALLS = (
    "scripts/data/safe_push.sh",
    "scripts/data/gha_commit_push.sh",
)
SECRET_BINDING = (
    "CLAWOCK_PUBLISH_SSH_KEY: ${{ secrets.CLAWOCK_PUBLISH_SSH_KEY }}"
)


def _publishing_workflows():
    return [
        path
        for path in sorted(WORKFLOWS.glob("*.yml"))
        if any(call in path.read_text() for call in PUBLISH_CALLS)
    ]


def test_each_publishing_workflow_scopes_deploy_key_to_push_step():
    writers = _publishing_workflows()
    assert writers, "no GitHub-hosted publishing workflows found"

    for workflow in writers:
        lines = workflow.read_text().splitlines()
        bindings = [
            (index, line)
            for index, line in enumerate(lines)
            if line.strip() == SECRET_BINDING
        ]
        assert len(bindings) == 1, (
            f"{workflow.name} must bind the publish key exactly once"
        )

        index, line = bindings[0]
        assert len(line) - len(line.lstrip()) == 10, (
            f"{workflow.name} exposes the deploy key above step scope"
        )
        assert lines[index - 1].strip() == "env:", (
            f"{workflow.name} publish key is not in a step env block"
        )


def test_safe_push_uses_and_cleans_ephemeral_actions_key(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    git_log = tmp_path / "git.log"
    fake_git = fake_bin / "git"
    fake_git.write_text(
        """#!/bin/sh
if [ "$1" = "grep" ]; then
  exit 1
fi
if [ "$1" = "push" ]; then
  printf '%s\\n' "$*" > "$FAKE_GIT_LOG"
  printf '%s\\n' "$GIT_SSH_COMMAND" >> "$FAKE_GIT_LOG"
  exit 0
fi
exit 1
"""
    )
    fake_git.chmod(0o755)

    fake_secret = "not-a-real-private-key"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "FAKE_GIT_LOG": str(git_log),
            "CLAWOCK_PUBLISH_SSH_KEY": fake_secret,
        }
    )
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "data" / "safe_push.sh")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    log_lines = git_log.read_text().splitlines()
    assert log_lines[0] == "push git@github.com:KCNyu/clawock.git master"
    assert "-i " in log_lines[1]
    key_path = Path(log_lines[1].split("-i ", 1)[1].split(" ", 1)[0])
    assert not key_path.exists(), "temporary deploy key survived safe_push exit"
    assert fake_secret not in result.stdout
    assert fake_secret not in result.stderr


def test_live_runtime_key_is_limited_to_live_checkout():
    safe_push = (ROOT / "scripts" / "data" / "safe_push.sh").read_text()
    assert '"/root/.openclaw/workspace"' in safe_push
    assert '"/root/.ssh/clawock_runtime_publish"' in safe_push


def test_every_workflow_that_stages_the_money_file_pushes_through_the_gate():
    """The money-conservation check lived only in .githooks/pre-push, which a
    fresh actions/checkout never installs (no workflow sets core.hooksPath). So
    brief-fallback could stage portfolio.json and push it with cash, positions
    and P&L never reconciled — purely because of where the push originated.

    The gate now lives in safe_push.sh; this asserts nothing can route around it.
    """
    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    offenders = []
    for path in workflows:
        text = path.read_text()
        stages_money = any(
            "portfolio.json" in line and line.strip().startswith(("git add", "- git add"))
            or ("git add" in line and "portfolio.json" in line)
            for line in text.splitlines())
        if stages_money and "safe_push.sh" not in text:
            offenders.append(path.name)

    assert not offenders, (
        "these workflows stage portfolio.json but do not push through "
        f"safe_push.sh, so the money gate is not on their path: {offenders}")


def test_safe_push_runs_the_money_check_when_the_money_file_moves():
    text = (ROOT / "scripts" / "data" / "safe_push.sh").read_text()

    assert "preflight_integrity.py" in text, (
        "safe_push.sh no longer runs the money-conservation check — the Actions "
        "publish path is unprotected again")
    # Scoped, not blanket: a dashboard-only publish must not be blocked by it.
    assert "portfolio.json" in text and "PORTFOLIO_TOUCHED" in text
