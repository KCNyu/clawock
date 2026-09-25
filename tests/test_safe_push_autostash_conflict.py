"""A replayed autostash that conflicts must not leave conflict markers behind.

`git -c rebase.autoStash=true pull --rebase` exits 0 when the commits rebase
cleanly but re-applying the stashed working-tree edits conflicts (git 2.43).
`safe_push.sh` took that 0 as "rebase clean" and pushed, leaving the file it
could not re-apply as an unmerged path full of `<<<<<<<` markers: every reader
of it fails to parse, and the next committer's `git add` can commit it.

Driven against real repositories, because the bug is entirely in what git does.
"""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "publish" / "safe_push.sh"
ID = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True)


def test_an_autostash_conflict_is_settled_not_left_in_the_tree(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "master", str(origin)],
                   check=True, capture_output=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", str(origin), str(seed)], check=True, capture_output=True)
    (seed / "state.json").write_text('{"v": 1}\n')
    _git(seed, "add", "state.json")
    _git(seed, *ID, "commit", "-m", "seed")
    _git(seed, "push", "origin", "master")

    pusher = tmp_path / "pusher"
    subprocess.run(["git", "clone", str(origin), str(pusher)], check=True, capture_output=True)

    (seed / "state.json").write_text('{"v": 2}\n')
    _git(seed, *ID, "commit", "-am", "rival writes state")
    _git(seed, "push", "origin", "master")

    (pusher / "mine.txt").write_text("x\n")
    _git(pusher, "add", "mine.txt")
    _git(pusher, *ID, "commit", "-m", "mine")
    (pusher / "state.json").write_text('{"v": 9}\n')   # an in-flight, uncommitted write

    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    env.pop("CLAWOCK_PUBLISH_SSH_KEY", None)
    _git(pusher, "config", "user.name", "t")
    _git(pusher, "config", "user.email", "t@example.invalid")
    result = subprocess.run(["bash", str(SCRIPT), "origin", "master"], cwd=pusher,
                            capture_output=True, text=True, env=env)
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert "mine" in _git(origin, "log", "--format=%s", "-3").stdout
    assert _git(pusher, "diff", "--name-only", "--diff-filter=U").stdout == ""
    assert "<<<<<<<" not in (pusher / "state.json").read_text()
    assert (pusher / "state.json").read_text() == '{"v": 2}\n'
    assert "autostash replay conflicted on: state.json" in out
    # the uncommitted edit is not destroyed — git kept it in the stash
    assert '"v": 9' in _git(pusher, "stash", "show", "-p").stdout
