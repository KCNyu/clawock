"""The lost-race recovery has to survive a data path that is a directory.

`gha_commit_push.sh` takes the paths a scan job owns and, when its push loses a
race, re-applies them on top of the winner. Two of the callers pass a whole
tree — `assets/data/factor-snapshots/{sentiment,macro}`, one dated row per day —
and the recovery copied each path with a plain `cp`. `git add` takes a directory
happily, so the first-try path always worked and the failure lived only in the
branch that runs when something already went wrong: `cp` refused the directory,
`set -e` killed the step ~10ms in, and the scan's data was dropped by the code
written to save it (sentiment-scan on 2026-08-28 and 2026-08-30).

These tests drive the real script against real repositories, because the bug was
in shell semantics that no contract assertion over the YAML could see.
"""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "publish" / "gha_commit_push.sh"


def _git(cwd, *args, **kwargs):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True, **kwargs)


@pytest.fixture
def repos(tmp_path):
    """A bare origin, our runner's clone, and a rival clone that wins the race."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "master", str(origin)],
                   check=True, capture_output=True)

    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", str(origin), str(seed)],
                   check=True, capture_output=True)
    _git(seed, "config", "user.email", "seed@example.invalid")
    _git(seed, "config", "user.name", "seed")
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "push", "origin", "master")

    runner = tmp_path / "runner"
    rival = tmp_path / "rival"
    for clone in (runner, rival):
        subprocess.run(["git", "clone", str(origin), str(clone)],
                       check=True, capture_output=True)
        _git(clone, "config", "user.email", "clone@example.invalid")
        _git(clone, "config", "user.name", "clone")
    return origin, runner, rival


def _write_scan(repo, day, payload):
    """What a scan job leaves behind: a sidecar file and a dated snapshot row."""
    (repo / "assets" / "data" / "factor-snapshots" / "sentiment").mkdir(
        parents=True, exist_ok=True)
    (repo / "assets" / "data" / "sentiment.json").write_text(payload, encoding="utf-8")
    (repo / "assets" / "data" / "factor-snapshots" / "sentiment"
     / f"{day}.json").write_text(payload, encoding="utf-8")


def _run_script(repo):
    env = dict(os.environ)
    env.pop("CLAWOCK_PUBLISH_SSH_KEY", None)
    return subprocess.run(
        ["bash", str(SCRIPT), "sentiment: scan",
         "assets/data/sentiment.json", "assets/data/factor-snapshots/sentiment"],
        cwd=repo, capture_output=True, text=True, env=env)


def _lose_the_race(rival, extra_row=None):
    """Land a commit first that also touches this job's sidecar.

    Disjoint-per-job is the design, but the rebase retry inside `safe_push.sh`
    really did hit a conflict on 2026-08-30 — that is the state that hands
    control to the recovery branch, so it is the state worth testing.
    """
    data = rival / "assets" / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "sentiment.json").write_text('{"scan": "theirs"}\n', encoding="utf-8")
    _git(rival, "add", "assets/data/sentiment.json")
    if extra_row:
        snaps = data / "factor-snapshots" / "sentiment"
        snaps.mkdir(parents=True, exist_ok=True)
        (snaps / f"{extra_row}.json").write_text('{"scan": "theirs"}\n',
                                                 encoding="utf-8")
        _git(rival, "add", f"assets/data/factor-snapshots/sentiment/{extra_row}.json")
    _git(rival, "commit", "-m", "sentiment: someone else got there first")
    _git(rival, "push", "origin", "master")


def test_a_lost_race_republishes_a_directory_slice(repos):
    origin, runner, rival = repos
    _write_scan(runner, "2026-08-31", '{"scan": "ours"}\n')
    _lose_the_race(rival)

    done = _run_script(runner)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "lost a race" in done.stdout + done.stderr
    published = _git(origin, "show",
                     "master:assets/data/factor-snapshots/sentiment/2026-08-31.json")
    assert published.stdout == '{"scan": "ours"}\n', (
        "the directory slice is what `cp` used to refuse")
    assert _git(origin, "log", "--oneline", "master").stdout.count("\n") >= 3, (
        "the run we lost to must still be in history")


def test_the_winners_rows_in_the_same_directory_survive(repos):
    """The snapshot tree is one dated row per writer, so re-applying ours must
    overlay the winner's tree, not replace it."""
    origin, runner, rival = repos
    _write_scan(runner, "2026-08-31", '{"scan": "ours"}\n')

    _lose_the_race(rival, extra_row="2026-08-30")

    done = _run_script(runner)

    assert done.returncode == 0, done.stdout + done.stderr
    for day, payload in (("2026-08-30", '{"scan": "theirs"}\n'),
                         ("2026-08-31", '{"scan": "ours"}\n')):
        shown = _git(origin, "show",
                     f"master:assets/data/factor-snapshots/sentiment/{day}.json")
        assert shown.stdout == payload, f"{day} row was lost"


def test_an_uncontested_push_still_takes_the_short_path(repos):
    origin, runner, _rival = repos
    _write_scan(runner, "2026-08-31", '{"scan": "ours"}\n')

    done = _run_script(runner)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "lost a race" not in done.stdout + done.stderr
    assert _git(origin, "show", "master:assets/data/sentiment.json").stdout == (
        '{"scan": "ours"}\n')


def test_nothing_to_commit_is_not_a_failure(repos):
    origin, runner, _rival = repos

    done = _run_script(runner)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "no change" in done.stdout
