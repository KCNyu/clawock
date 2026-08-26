"""#1069: raw memory prose may exist, but on a clock — and never in the repo.

kcn's rule (2026-08-26): 「这些 memory 可以有但要定时清理而且不能进 repo」, the
same shape the interactive agents' own memory has — a curated index that is
kept, raw per-session prose that ages out.

Two halves, both asserted here: `.gitignore` keeps the prose out of the
repository as a CLASS (the previous rule named sixteen files one by one, so the
seventeenth would have been committed), and `ops/host/prune_memory_prose.py`
deletes it on a retention window without ever being able to reach tracked data.
"""
import importlib.util
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SPEC = importlib.util.spec_from_file_location(
    "prune_memory_prose", ROOT / "ops" / "host" / "prune_memory_prose.py")
pruner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pruner)


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=True)


def _repo(tmp_path):
    """A workspace with the ignore rules under test and one tracked brief."""
    root = tmp_path / "ws"
    (root / "memory" / "dreaming" / "deep").mkdir(parents=True)
    (root / "memory" / ".tmp").mkdir(parents=True)
    _git(root.parent, "init", "-q", str(root))
    (root / ".gitignore").write_text(
        (ROOT / ".gitignore").read_text(encoding="utf-8"), encoding="utf-8")
    return root


def _write(root, rel, age_days):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("prose\n", encoding="utf-8")
    stamp = time.time() - age_days * 86400
    import os
    os.utime(path, (stamp, stamp))
    return path


def test_the_ignore_rule_covers_the_class_not_a_list_of_names():
    """The seventeenth one-off note must be ignored without editing .gitignore.

    #1062 listed sixteen exact filenames. Anything dated written after that —
    by a session that had no idea the list existed — landed straight in the
    index, which is how prose kept re-entering the repository.
    """
    probes = [
        "memory/2099-01-01.md",                  # daily note
        "memory/2099-01-01-1530.md",             # timestamped session note
        "memory/2099-01-01-some-topic.md",       # one-off named prose
    ]
    keep = [
        "memory/2099-01-01-pre-open.md",         # the published daily brief
        "memory/2099-01-01-plan.json",           # schema-gated plan
    ]
    out = subprocess.run(["git", "-C", str(ROOT), "check-ignore", *probes, *keep],
                         capture_output=True, text=True)
    ignored = set(out.stdout.split())
    assert set(probes) <= ignored, (
        f"memory prose that is not ignored would enter the repo: "
        f"{sorted(set(probes) - ignored)}")
    assert not (set(keep) & ignored), (
        f"the brief/plan surfaces must stay trackable: {sorted(set(keep) & ignored)}")


def test_prune_removes_aged_prose_and_keeps_the_recent(tmp_path):
    root = _repo(tmp_path)
    old_daily = _write(root, "memory/2099-01-01.md", 30)
    old_dream = _write(root, "memory/dreaming/deep/2099-01-01.md", 40)
    old_scratch = _write(root, "memory/.tmp/insights-2099-01-01.json", 30)
    fresh_daily = _write(root, "memory/2099-02-02.md", 2)
    fresh_dream = _write(root, "memory/dreaming/deep/2099-02-02.md", 5)

    pruner.prune(root)

    assert not old_daily.exists() and not old_dream.exists()
    assert not old_scratch.exists()
    assert fresh_daily.exists(), "inside the window, prose stays"
    assert fresh_dream.exists()


def test_prune_cannot_delete_tracked_data_even_when_a_glob_reaches_it(tmp_path):
    """The safety invariant: tracking, not the glob.

    A brief is dated exactly like a diary and is old the day after it ships. If
    the pattern were the only defence, one wrong character would delete the
    published archive — so the pruner deletes a file only when git both ignores
    it and does not track it, and this test forces the collision by tracking a
    file the glob does match.
    """
    root = _repo(tmp_path)
    trap = _write(root, "memory/2099-01-01-tracked-note.md", 90)
    _git(root, "add", "-f", "memory/2099-01-01-tracked-note.md")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "track")
    decoy = _write(root, "memory/2099-01-02-untracked-note.md", 90)

    report = pruner.prune(root)

    assert trap.exists(), "a tracked file was deleted; the guard is not holding"
    assert not decoy.exists(), "the untracked twin should have been pruned"
    prose = next(r for r in report if r["label"].startswith("session prose"))
    assert prose["protected"] == 1, report


def test_dry_run_reports_without_deleting(tmp_path):
    root = _repo(tmp_path)
    old = _write(root, "memory/2099-01-01.md", 30)
    report = pruner.prune(root, dry_run=True)
    assert old.exists()
    assert sum(r["removed"] for r in report) == 1


def test_every_class_has_a_window_and_none_reaches_curated_data():
    """A retention table is a policy; keep it readable and out of the ledger."""
    for label, pattern, days in pruner.CLASSES:
        assert 1 <= days <= 365, (label, days)
        assert pattern.startswith("memory/"), (
            f"{label} reaches outside memory/: {pattern}")
    patterns = [p for _, p, _ in pruner.CLASSES]
    for owned in ("memory/bars", "memory/snapshots", "memory/theses",
                  "memory/weekly", "memory/archive"):
        assert not any(p.startswith(owned) for p in patterns), (
            f"{owned} is repository data; no retention class may name it")


def test_the_pre_commit_hook_refuses_staged_prose(tmp_path):
    """`git add -f` walks past .gitignore; the hook is what stops it.

    This is not hypothetical: forty `memory/YYYY-MM-DD-HHMM.md` transcripts
    carrying WeChat and Telegram session keys reached a public repository
    exactly this way, staged by a sweep that used -f.
    """
    repo = tmp_path / "repo"
    (repo / "memory").mkdir(parents=True)
    (repo / ".githooks").mkdir()
    _git(repo.parent, "init", "-q", str(repo))
    hook = repo / ".githooks" / "pre-commit"
    hook.write_text((ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8"),
                    encoding="utf-8")
    hook.chmod(0o755)
    _git(repo, "config", "core.hooksPath", ".githooks")

    (repo / "memory" / "2099-01-01-note.md").write_text("prose\n", encoding="utf-8")
    (repo / "memory" / "2099-01-01-pre-open.md").write_text("brief\n", encoding="utf-8")
    _git(repo, "add", "-f", "memory/2099-01-01-note.md",
         "memory/2099-01-01-pre-open.md")

    done = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-m", "sweep"], capture_output=True, text=True)
    assert done.returncode != 0, "the hook let memory prose through"
    assert "2099-01-01-note.md" in done.stderr
    assert "pre-open" not in done.stderr, (
        "the published brief is not prose; blocking it would break the daily "
        "postflight commit")
