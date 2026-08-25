"""The #1038 untracking migration guard, driven against real repos.

`pull_guarded` wraps the autostash pull that both host-side pull sites use
(`refresh_live.sh`, `safe_push.sh`). While origin/master carries the deletion
of the tracked daily notes, a checkout with a locally-dirty diary would hit a
modify/delete stash-pop conflict — aborted automation at best, a re-staged or
lost day of notes at worst. The guard backs those exact files up before the
pull and restores whatever the rebase removed.

These tests drive the real functions through real git history (upstream repo +
clone in tmp_path), so the assertions are about outcomes — which files survive,
which get deleted, what is left behind — not about the script's wording.
"""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "ops" / "publish" / "untrack_guard.sh"

DIARY = "memory/2026-01-01.md"
BACKUP_DIR = "memory/.tmp/pre-untrack-backup"


def _run(repo, *args, **kw):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(repo),
             "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
        **kw)


def _guarded_pull(repo):
    """Source the real guard file and run the real pull wrapper in `repo`."""
    script = f'set -e\n. "{GUARD}"\npull_guarded origin master\n'
    return subprocess.run(
        ["bash", "-c", script], cwd=str(repo), capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(repo)})


@pytest.fixture
def desk(tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _run(upstream, "init", "-q", "-b", "master")
    (upstream / "memory").mkdir()
    (upstream / "memory" / DIARY.removeprefix("memory/")).write_text("base day log\n")
    _run(upstream, "add", "-A")
    _run(upstream, "commit", "-qm", "base")

    checkout = tmp_path / "checkout"
    _run(tmp_path, "clone", "-q", str(upstream), str(checkout))
    return upstream, checkout


def test_dirty_diary_meeting_its_deletion_is_restored(desk):
    upstream, checkout = desk
    # Local edits land after the clone; master then stops tracking the file.
    (checkout / DIARY).write_text("local edits made today\n")
    (upstream / DIARY).unlink()
    _run(upstream, "commit", "-qam", "untrack daily notes")

    r = _guarded_pull(checkout)
    assert r.returncode == 0, r.stderr

    restored = checkout / DIARY
    assert restored.read_text() == "local edits made today\n"
    assert not (checkout / BACKUP_DIR).exists(), "backup must clean up after itself"


def test_clean_diary_survives_the_untracking_on_disk(desk):
    """The point of the guard: index deletion flows through, the DISK copy stays.

    A plain --ff-only merge silently removes a clean tracked file whose path
    master deleted — that is the data-loss path for workspace continuity
    (AGENTS.md reads today+yesterday from disk)."""
    upstream, checkout = desk
    (upstream / DIARY).unlink()
    _run(upstream, "commit", "-qam", "untrack daily notes")

    r = _guarded_pull(checkout)
    assert r.returncode == 0, r.stderr
    # Untracked (master no longer carries it), but very much still on disk.
    assert (checkout / DIARY).read_text() == "base day log\n"
    assert not (checkout / BACKUP_DIR).exists()


def test_ff_only_publisher_path_is_also_guarded(desk):
    """publish_dashboard.sh merges --ff-only every 20 minutes; drive the same
    backup/restore pair around its merge shape directly."""
    upstream, checkout = desk
    (upstream / DIARY).unlink()
    _run(upstream, "commit", "-qam", "untrack daily notes")
    _run(checkout, "fetch", "-q", "origin", "master")
    script = (
        f'set -e\n. "{GUARD}"\n'
        'pull_guard_backup origin master\n'
        f'rm "{DIARY}"   # what --ff-only does to a clean path master deleted\n'
        'pull_guard_restore\n'
    )
    r = subprocess.run(["bash", "-c", script], cwd=str(checkout),
                       capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(checkout)})
    assert r.returncode == 0, r.stderr
    assert (checkout / DIARY).read_text() == "base day log\n"
    assert not (checkout / BACKUP_DIR).exists()


def test_guard_scope_is_bare_dated_dailies_only(desk):
    upstream, checkout = desk
    other = upstream / "memory" / "2026-01-01-notes.md"
    other.write_text("tagged prose\n")
    _run(upstream, "add", "-A")
    _run(upstream, "commit", "-qm", "add tagged file")

    _run(checkout, "pull", "-q", "origin", "master")
    # Dirty only the bare-dated diary; the tagged sibling stays clean.
    (checkout / DIARY).write_text("dirty\n")
    (upstream / DIARY).unlink()
    other.unlink()
    _run(upstream, "commit", "-qam", "untrack daily notes")

    r = _guarded_pull(checkout)
    assert r.returncode == 0, r.stderr
    assert (checkout / DIARY).read_text() == "dirty\n"
    # The tagged file was clean and outside the guard's scope: deleted as asked.
    assert not (checkout / "memory" / "2026-01-01-notes.md").exists()


def test_no_deletions_means_plain_fast_forward(desk):
    upstream, checkout = desk
    (upstream / "README.md").write_text("x\n")
    _run(upstream, "add", "-A")
    _run(upstream, "commit", "-qm", "unrelated")
    (checkout / "scratch.txt").write_text("in-flight work\n")

    r = _guarded_pull(checkout)
    assert r.returncode == 0, r.stderr
    assert (checkout / "README.md").read_text() == "x\n"
    assert (checkout / "scratch.txt").read_text() == "in-flight work\n", \
        "ordinary dirty files must pass through exactly as before"
    assert not (checkout / BACKUP_DIR).exists(), \
        "no deletions in range → no backup machinery may even start"


def test_both_host_side_pull_sites_use_the_guard():
    """Contract pin: all three merge sites must go through the shared helper,
    so a fourth raw merge cannot quietly reopen the window."""
    for script in (ROOT / "ops/host/refresh_live.sh",
                   ROOT / "ops/publish/safe_push.sh",
                   ROOT / "ops/publish/publish_dashboard.sh"):
        text = script.read_text(encoding="utf-8")
        assert "ops/publish/untrack_guard.sh" in text, \
            f"{script.name} no longer sources the guard"
    for script, fn in ((ROOT / "ops/host/refresh_live.sh", "pull_guarded"),
                       (ROOT / "ops/publish/safe_push.sh", "pull_guarded"),
                       (ROOT / "ops/publish/publish_dashboard.sh",
                        "pull_guard_backup")):
        assert f"{fn} " in (script.read_text(encoding="utf-8")), \
            f"{script.name} no longer calls {fn}"
    text = GUARD.read_text(encoding="utf-8")
    assert "rebase.autoStash=true" in text, "the wrapper lost the autostash knob"
