"""A lost push race has to be survivable where the pusher owns no git identity.

`safe_push.sh` promises, in its own header, that every committer gets identical
push behaviour. It did not: `pull --rebase` REWRITES commits and therefore needs
a committer identity, and the bot callers are forbidden to configure one —
`gha_commit_push.sh` injects the bot per `git commit` with `-c` precisely so a
run inside a real workspace can never clobber kcn's interactive identity. On a
GitHub-hosted runner nothing else supplies one (the `runner` account's gecos
name is empty), so the rebase died on `fatal: empty ident name` and the script
reported

    ✗ rebase conflict — abort, leaving commit local
    Manual resolution needed: git pull --rebase + resolve + git push

for a push whose only problem was ref lag. The retry ladder — the whole reason
this script exists — was one attempt on a runner and three everywhere else.
Observed on sentiment-scan 2026-08-28 and 2026-08-30 (run 33343134261).

These tests drive the real script against real repositories, in an environment
where git cannot resolve an identity, because the bug lived entirely in what git
does with the environment it is handed.
"""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "publish" / "safe_push.sh"

#: An environment in which git cannot answer "who is committing". `git var
#: GIT_COMMITTER_IDENT` fails here exactly as it does on a runner; forcing an
#: empty name is only how the condition is reached on a developer box, where the
#: passwd gecos would otherwise supply one.
NO_IDENTITY = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_COMMITTER_NAME": "",
    "GIT_AUTHOR_NAME": "",
}

BOT = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


def _git(cwd, *args, env=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True, env=env)


def _env(base=None, **extra):
    import os
    env = dict(os.environ)
    env.pop("CLAWOCK_PUBLISH_SSH_KEY", None)
    env.update(base or {})
    env.update(extra)
    return env


@pytest.fixture
def repos(tmp_path):
    """A bare origin, a rival that wins the race, and a pusher with no identity."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "master", str(origin)],
                   check=True, capture_output=True)

    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", str(origin), str(seed)],
                   check=True, capture_output=True)
    _git(seed, "-c", "user.name=seed", "-c", "user.email=seed@example.invalid",
         "commit", "--allow-empty", "-m", "seed")
    _git(seed, "push", "origin", "master")

    # The pusher clones BEFORE the rival lands, or there is no race to lose and
    # the push succeeds on attempt 1 without ever reaching the rebase — which is
    # how the first draft of this test passed against the unfixed script.
    runner = tmp_path / "runner"
    subprocess.run(["git", "clone", str(origin), str(runner)],
                   check=True, capture_output=True)

    rival = tmp_path / "rival"
    subprocess.run(["git", "clone", str(origin), str(rival)],
                   check=True, capture_output=True)
    (rival / "rival.json").write_text("{}\n", encoding="utf-8")
    _git(rival, "add", "rival.json")
    _git(rival, "-c", "user.name=rival", "-c", "user.email=rival@example.invalid",
         "commit", "-m", "rival wins the race")
    _git(rival, "push", "origin", "master")

    # Carrying a commit made the way the bot makes them: identity injected for
    # this one command, never written to config.
    (runner / "mine.json").write_text("{}\n", encoding="utf-8")
    _git(runner, "add", "mine.json")
    _git(runner, "-c", f"user.name={BOT}", "-c", f"user.email={BOT_EMAIL}",
         "commit", "-m", "sentiment: daily scan")
    return origin, runner


def test_the_environment_this_reproduces_really_has_no_identity(repos):
    """Guard the fixture, not the fix: if git can answer this, the test below
    proves nothing about a runner."""
    _origin, runner = repos
    probe = subprocess.run(["git", "var", "GIT_COMMITTER_IDENT"], cwd=runner,
                           capture_output=True, text=True, env=_env(NO_IDENTITY))
    assert probe.returncode != 0, (
        "this environment resolves a committer identity, so it is not the "
        "runner condition the rebase failed under")


def test_a_lost_race_is_replayed_when_nobody_configured_an_identity(repos):
    origin, runner = repos
    result = subprocess.run(["bash", str(SCRIPT), "origin", "master"],
                            cwd=runner, capture_output=True, text=True,
                            env=_env(NO_IDENTITY))
    assert result.returncode == 0, (
        f"safe_push.sh gave up on a lost race with no identity configured:\n"
        f"{result.stdout}\n{result.stderr}")
    assert "rebase conflict" not in (result.stdout + result.stderr), (
        "a ref-lag rejection was reported as a content conflict")

    log = subprocess.run(["git", "log", "--format=%s|%cn", "-3"],
                         cwd=origin, capture_output=True, text=True).stdout
    assert "sentiment: daily scan" in log, "the pusher's commit never landed"
    assert "rival wins the race" in log, "the winner's commit was overwritten"


def test_the_replayed_commit_keeps_the_committer_it_was_made_with(repos):
    """The replay identity is HEAD's own committer, so this introduces no second
    answer to "who is the bot" — and a rewritten commit must not become
    `root <root@…>` on whatever box happened to run the retry."""
    origin, runner = repos
    subprocess.run(["bash", str(SCRIPT), "origin", "master"], cwd=runner,
                   capture_output=True, text=True, env=_env(NO_IDENTITY))
    line = subprocess.run(
        ["git", "log", "-1", "--format=%cn <%ce>", "master"],
        cwd=origin, capture_output=True, text=True).stdout.strip()
    assert line == f"{BOT} <{BOT_EMAIL}>", line


def test_a_configured_identity_is_left_alone(repos):
    """Where git can resolve an identity the script must behave exactly as
    before — the replay prefix is empty and nothing is injected."""
    origin, runner = repos
    env = _env({"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"})
    _git(runner, "config", "user.name", "configured")
    _git(runner, "config", "user.email", "configured@example.invalid")
    result = subprocess.run(["bash", str(SCRIPT), "origin", "master"],
                            cwd=runner, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no git identity here" not in result.stdout
    line = subprocess.run(["git", "log", "-1", "--format=%cn", "master"],
                          cwd=origin, capture_output=True, text=True).stdout.strip()
    assert line == "configured", line
