"""`oldest` has to mean oldest, and has to survive a rebase.

`check_publish_backlog` escalates on either half of

    count >= BACKLOG_WARN_COMMITS or hours >= BACKLOG_WARN_HOURS

and the second half never fired. Two bugs in one line:

  * `git log -1` returns the NEWEST commit — the log is newest-first — so a
    variable named `oldest` held the most recent one. Measured on the live repo
    over five commits: `-1` answered 00:42:36 while the true oldest was
    23:52:35.
  * `%ct` is the committer date, and `push_with_rebase_retry` rebases; every
    retry rewrites it to now.

Both push the reading toward zero, which is what the host's history shows:
all eight backlog warnings ever recorded read `oldest 0.0h`, so the check only
ever escalated on `count`. The incident the age half exists for is the opposite
shape — 2026-08-31, a SMALL number of commits stranded for EIGHT hours behind a
pre-push refusal (see this suite's sibling) — and it would have read 0.0h.

Driven through a REAL git repo on purpose. The sibling suite's fake answers any
`git log` with one stamp regardless of argv, so it proves the branch runs and
can say nothing about whether the arguments ask the right question — which is
exactly how this survived.
"""
import importlib.util
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def system_check():
    for path in (ROOT, ROOT / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(
        "kcnyu_system_check_backlog_age", ROOT / "ops" / "system_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(repo, *args, **kw):
    return subprocess.run(["git", "-C", str(repo), *args],
                          check=True, capture_output=True, text=True, **kw).stdout


@pytest.fixture
def repo(tmp_path):
    """master, an `origin/master` behind it, and commits of known ages."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "-b", "master", str(work)], check=True)
    _run(work, "config", "user.email", "t@e.st")
    _run(work, "config", "user.name", "t")
    _run(work, "remote", "add", "origin", str(origin))
    (work / "seed.txt").write_text("seed\n")
    _run(work, "add", "seed.txt")
    _run(work, "commit", "-qm", "seed")
    _run(work, "push", "-q", "origin", "master")
    return work


def _commit_aged(repo, name, hours_ago):
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S",
                          time.localtime(time.time() - hours_ago * 3600))
    (repo / name).write_text(name)
    _run(repo, "add", name)
    _run(repo, "commit", "-qm", name,
         env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp,
              "PATH": "/usr/bin:/bin", "HOME": str(repo)})


def _backlog(system_check, monkeypatch, repo):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.chdir(repo)
    result = system_check.Result()
    system_check.check_publish_backlog(result)
    assert len(result.checks) == 1
    _, severity, message = result.checks[0]
    return severity, message


def test_the_age_is_the_oldest_commit_not_the_newest(
        system_check, monkeypatch, repo):
    """The reported number must describe the commit that has waited longest."""
    _commit_aged(repo, "old.txt", hours_ago=5)
    _commit_aged(repo, "new.txt", hours_ago=0)

    severity, message = _backlog(system_check, monkeypatch, repo)

    assert severity == system_check.WARNING
    assert "oldest 5." in message, message      # not 0.0h


def test_a_small_backlog_stranded_for_hours_escalates(
        system_check, monkeypatch, repo):
    """The 2026-08-31 shape: below the count threshold, far past the age one.
    Under the old reading this was `1 commit(s) unpushed, oldest 0.0h` — OK."""
    _commit_aged(repo, "stuck.txt", hours_ago=8)

    severity, message = _backlog(system_check, monkeypatch, repo)

    assert severity == system_check.WARNING
    assert "1 commit(s) unpushed" in message
    assert "oldest 8." in message


def test_a_fresh_single_commit_is_still_a_normal_publish_cycle(
        system_check, monkeypatch, repo):
    """The fix must not turn every ordinary tick into a warning."""
    _commit_aged(repo, "fresh.txt", hours_ago=0)

    severity, _ = _backlog(system_check, monkeypatch, repo)

    assert severity == system_check.OK


def test_a_rebase_does_not_reset_the_age(system_check, monkeypatch, repo, tmp_path):
    """`push_with_rebase_retry` rebases on every retry, and a rebase that
    actually replays commits REWRITES `%ct` to now. `%at` survives it — and the
    question is how long the work has waited, not when git last touched it.

    The remote has to move for the rebase to replay anything; a rebase onto the
    commit you are already on is a no-op and proves nothing.
    """
    _commit_aged(repo, "stuck.txt", hours_ago=6)
    before = _backlog(system_check, monkeypatch, repo)[1]

    # Someone else pushes: now our pending commit has to be replayed.
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(repo / ".." / "origin.git"),
                    str(other)], check=True)
    _run(other, "config", "user.email", "o@e.st")
    _run(other, "config", "user.name", "o")
    (other / "theirs.txt").write_text("theirs\n")
    _run(other, "add", "theirs.txt")
    _run(other, "commit", "-qm", "theirs")
    _run(other, "push", "-q", "origin", "master")

    _run(repo, "fetch", "-q", "origin")
    _run(repo, "rebase", "origin/master")
    # The rebase really did rewrite the committer date…
    committer_age_h = (time.time() - int(
        _run(repo, "log", "-1", "--format=%ct").strip())) / 3600
    assert committer_age_h < 0.1, committer_age_h

    after = _backlog(system_check, monkeypatch, repo)[1]

    assert "oldest 6." in before, before
    assert "oldest 6." in after, after      # …and the age survived it
