"""Contracts for the PR gate and the two automation-only publish identities."""

from pathlib import Path
import os
import subprocess


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PUBLISH_CALLS = (
    "ops/publish/safe_push.sh",
    "ops/publish/gha_commit_push.sh",
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
        ["bash", str(ROOT / "ops" / "publish" / "safe_push.sh")],
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
    identity = (ROOT / "ops" / "publish" / "publish_identity.sh").read_text()
    assert '"/root/.openclaw/workspace"' in identity
    assert '"/root/.ssh/clawock_runtime_publish"' in identity


def test_a_checkout_that_is_not_the_live_workspace_gets_no_publish_identity(tmp_path):
    """Interactive worktrees must not inherit the live deploy key.

    Both selection branches are refused here: no Actions secret in the
    environment, and a checkout that is not `/root/.openclaw/workspace`. On the
    live host `/root/.ssh/clawock_runtime_publish` is readable, so the toplevel
    comparison is the only thing standing between an interactive worktree and a
    key that bypasses the ruleset — this exercises it. On a runner the key is
    absent as well, so the assertion holds for a second reason.

    Behavioural rather than a grep, because the selection now lives in a file
    that two publishers source: a text assertion would keep passing if only one
    of them still consulted it.
    """
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    probe = subprocess.run(
        ["bash", "-c",
         f". {ROOT / 'ops' / 'publish' / 'publish_identity.sh'}; "
         'printf "%s|%s|%s" "$PUBLISH_SSH_KEY" "$PUBLISH_REMOTE" "${GIT_SSH_COMMAND:-}"'],
        cwd=tmp_path,
        env={k: v for k, v in os.environ.items() if k != "CLAWOCK_PUBLISH_SSH_KEY"},
        check=True, capture_output=True, text=True,
    )

    assert probe.stdout == "||", (
        "an interactive checkout selected a publishing identity: "
        f"{probe.stdout!r}")


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


def _ledger_repo(tmp_path, *, with_portfolio=True):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args],
                       check=True, capture_output=True, text=True)
    git("init", "-q")
    git("config", "user.name", "test")
    git("config", "user.email", "test@example.com")
    if with_portfolio:
        (tmp_path / "portfolio.json").write_text("{}\n")
    else:
        (tmp_path / "README.md").write_text("no money here\n")
    git("add", "-A")
    git("commit", "-qm", "seed")
    return tmp_path


def test_pre_push_refuses_a_ledger_workspace_whose_checker_is_missing(tmp_path):
    """A missing checker used to `exit 0` — reading "absent" as "passed", and
    because that sits above the money gate it disarmed preflight_integrity too.
    Verified before the fix: system_check.py removed + an unreconciled book
    pushed clean."""
    repo = _ledger_repo(tmp_path)
    hook = repo / "pre-push"
    hook.write_text((ROOT / ".githooks" / "pre-push").read_text())

    result = subprocess.run(["bash", str(hook)], cwd=repo, capture_output=True,
                            text=True, input="")

    assert result.returncode != 0, (
        "a workspace carrying portfolio.json pushed with no checker installed")
    assert "system_check.py is missing" in result.stdout


def test_pre_push_still_allows_a_repo_that_carries_no_money_file(tmp_path):
    """The fail-closed branch must not turn into a blanket block on any repo
    without the checker — only a ledger workspace is a broken install."""
    repo = _ledger_repo(tmp_path, with_portfolio=False)
    hook = repo / "pre-push"
    hook.write_text((ROOT / ".githooks" / "pre-push").read_text())

    result = subprocess.run(["bash", str(hook)], cwd=repo, capture_output=True,
                            text=True, input="")

    assert result.returncode == 0, result.stdout + result.stderr


def test_pre_push_does_not_apply_master_ledger_gates_to_data_plane(tmp_path):
    """The orphan data ref contains dashboard artifacts, not the ledger.

    A temporarily unreconciled working-tree portfolio must not freeze that
    independent publication path. This is behavioural: changing the target ref
    to master makes the same missing-checker fixture fail closed, so merely
    deleting the hook body cannot satisfy both assertions.
    """
    repo = _ledger_repo(tmp_path)
    hook = repo / "pre-push"
    hook.write_text((ROOT / ".githooks" / "pre-push").read_text())
    zero = "0" * 40
    one = "1" * 40

    data_update = f"refs/heads/data-plane {one} refs/heads/data-plane {zero}\n"
    data = subprocess.run(
        ["bash", str(hook)], cwd=repo, capture_output=True, text=True,
        input=data_update,
    )
    assert data.returncode == 0, data.stdout + data.stderr

    master_update = f"refs/heads/master {one} refs/heads/master {zero}\n"
    master = subprocess.run(
        ["bash", str(hook)], cwd=repo, capture_output=True, text=True,
        input=master_update,
    )
    assert master.returncode != 0
    assert "system_check.py is missing" in master.stdout


def test_data_plane_publisher_preserves_hook_stdout_and_git_stderr():
    publisher = (ROOT / "ops" / "publish" / "publish_data_branch.py").read_text()

    assert "exc.stdout, exc.stderr" in publisher
    assert "[-2000:]" in (
        ROOT / "instances" / "kcnyu" / "src" / "clawock_kcnyu" / "harness" /
        "_harness_common.py"
    ).read_text(), "postflight truncated the hook reason back out of the result"


def _safe_push_in(repo):
    """Copy the publisher and the files it sources next to each other.

    A deployment of safe_push.sh is all of them. Not tolerating an absent one is
    deliberate: an unreadable identity helper must fail rather than silently
    push under whatever git happens to be configured with, and an unreadable
    money checker must fail rather than skip the money gate.
    """
    for name in ("safe_push.sh", "publish_identity.sh", "money_checker.sh"):
        (repo / name).write_text((ROOT / "ops" / "publish" / name).read_text())
    return repo / "safe_push.sh"


def test_safe_push_refuses_the_money_file_when_the_checker_is_missing(tmp_path):
    """A missing package CLI cannot silently certify a changed money file.

    The other half of the cron-PATH fix below: nothing on PATH *and* nothing
    importable from the checkout must still refuse. The fallback exists so a
    verifiable book gets published, not so the gate becomes a formality.
    """
    repo = _ledger_repo(tmp_path)
    script = _safe_push_in(repo)

    result = subprocess.run(
        ["/bin/bash", str(script)], cwd=repo, capture_output=True,
        text=True, input="", env={**os.environ, "PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 4, (
        f"expected the push refused, got rc={result.returncode}\n{result.stdout}")
    assert "checker is unavailable" in result.stdout


CRON_ENV = {"PATH": "/usr/bin:/bin", "HOME": "/root", "LANG": "C.UTF-8"}
"""What a job started from the user crontab actually gets. The installed
console script lives in ~/.local/bin, which is not on this PATH."""


def test_safe_push_finds_the_money_checker_under_a_bare_cron_environment(tmp_path):
    """The gate must resolve the checker without help from PATH.

    On 2026-08-09 the nightly gold refresh committed portfolio.json and then
    could not push it: started from the user crontab, `command -v clawock`
    found nothing, so the gate refused. It was right to refuse an unverifiable
    book — but the book was verifiable, and the money commit then sat on the
    live checkout in front of every later push, because the gate re-runs for as
    long as an unpushed portfolio.json commit exists.

    Asserted behaviourally, in the environment that broke it: reverting to a
    bare `command -v clawock` makes this red because the run never reaches the
    check at all.
    """
    repo = _ledger_repo(tmp_path)
    script = _safe_push_in(repo)
    # The fallback runs the package out of the checkout being pushed.
    (repo / "src").symlink_to(ROOT / "src")

    result = subprocess.run(["bash", str(script)], cwd=repo, capture_output=True,
                            text=True, input="", env=CRON_ENV)

    assert "running money-conservation check" in result.stdout, (
        "the gate never got as far as checking the book:\n" + result.stdout)
    assert "neither on PATH nor importable" not in result.stdout, (
        "the checker was reported unavailable although the package is right "
        "here in the checkout:\n" + result.stdout)


def test_safe_push_runs_the_money_check_when_the_money_file_moves(tmp_path):
    repo = _ledger_repo(tmp_path)
    script = _safe_push_in(repo)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "integrity-invoked"
    checker = bin_dir / "clawock"
    checker.write_text(
        "#!/bin/sh\n"
        f"touch {marker}\n"
        "exit 2\n"
    )
    checker.chmod(0o755)

    result = subprocess.run(
        ["bash", str(script)], cwd=repo, capture_output=True, text=True, input="",
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )

    assert result.returncode == 4
    assert marker.exists(), "the package integrity command was not invoked"
    assert "does not reconcile" in result.stdout
