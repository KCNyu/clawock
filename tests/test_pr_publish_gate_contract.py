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
