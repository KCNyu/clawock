"""Where each kind of memory lives (#1071 → corrected by #1074).

kcn, 2026-08-26: 「memory.md dreams.md 可以提交呀 但是 memory/*.md 不应该吧 那个是
coding agent 写的 不是 clawock 里面很多都是过期的」.

Three things shared one rule in #1072 and they have three different authors:
`MEMORY.md` and `DREAMS.md` are written by openclaw's own dreaming job and are
clawock runtime state (every cron payload is assembled from the index, and eight
tracked instruction files name it as the authority), while `memory/*.md` is
prose the interactive coding agents write in their own format — their durable
store is /root/.shared-memory, so a copy here is a leak.

Four properties are asserted:

* the coding-agent class cannot enter the repository, stated as a CLASS (#1062
  listed sixteen files by name, so the seventeenth was committed) and enforced
  again at commit time because `git add -f` walks past .gitignore;
* the two root files CAN, and are — the mistake #1074 undoes;
* the published daily brief is NOT memory and must stay trackable, or the daily
  postflight commit would block on its own output;
* drift between the index and the topic files is reported both ways, as a
  report rather than a deletion — which note is finished is a judgement, and a
  timer deciding it by mtime would delete the durable note nobody had to touch
  for three months.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def system_check():
    for path in (ROOT, ROOT / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(
        "kcnyu_system_check_memory", ROOT / "ops" / "system_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=True)


def test_the_whole_memory_class_is_out_of_the_repository():
    probes = [
        "memory/2099-01-01.md",                  # day log
        "memory/2099-01-01-1530.md",             # promoted chat transcript
        "memory/2099-01-01-some-topic.md",       # one-off named note
        "memory/feedback_something.md",          # shared-memory-shaped topic file
    ]
    # Not memory prose: the two root files are openclaw's own runtime state
    # (#1074), and the brief/plan are repository data the site renders.
    keep = ["MEMORY.md", "DREAMS.md",
            "memory/2099-01-01-pre-open.md", "memory/2099-01-01-plan.json"]
    out = subprocess.run(["git", "-C", str(ROOT), "check-ignore", *probes, *keep],
                         capture_output=True, text=True)
    ignored = set(out.stdout.split())
    assert set(probes) <= ignored, (
        f"memory that is not ignored would enter the repo: "
        f"{sorted(set(probes) - ignored)}")
    assert not (set(keep) & ignored), (
        f"the brief/plan surfaces must stay trackable: {sorted(set(keep) & ignored)}")


def test_no_coding_agent_prose_is_tracked_but_the_runtime_index_is():
    """Both halves, because each one alone was shipped wrong once.

    #1062 asserted only the first half by listing filenames, and the file that
    was not on the list went into a public repository. #1072 then over-applied
    the class to `MEMORY.md`/`DREAMS.md`, which are not coding-agent prose at
    all — so the second half is asserted too, and a future sweep cannot quietly
    take them out again.
    """
    tracked = set(_git(ROOT, "ls-files").stdout.split())
    offenders = [name for name in sorted(tracked)
                 if name.startswith("memory/") and name.count("/") == 1
                 and name.endswith(".md") and not name.endswith("-pre-open.md")]
    assert offenders == [], (
        f"coding-agent prose is in the repository: {offenders}")

    missing = [name for name in ("MEMORY.md", "DREAMS.md") if name not in tracked]
    assert missing == [], (
        f"openclaw's own memory left the repository again (#1074): {missing}")


def test_the_pre_commit_hook_refuses_staged_memory(tmp_path):
    """`git add -f` walks past .gitignore; the hook is what stops it.

    Not hypothetical: forty `memory/YYYY-MM-DD-HHMM.md` transcripts carrying
    WeChat and Telegram session keys reached a public repository exactly this
    way, staged by a sweep that used -f.
    """
    repo = tmp_path / "repo"
    (repo / "memory").mkdir(parents=True)
    (repo / ".githooks").mkdir()
    _git(repo.parent, "init", "-q", str(repo))
    hook = repo / ".githooks" / "pre-commit"
    hook.write_text((ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8"),
                    encoding="utf-8")
    hook.chmod(0o755)
    identity = repo / ".githooks" / "_identity_check.sh"
    identity.write_text(
        (ROOT / ".githooks" / "_identity_check.sh").read_text(encoding="utf-8"),
        encoding="utf-8")
    identity.chmod(0o755)
    _git(repo, "config", "core.hooksPath", ".githooks")

    (repo / "MEMORY.md").write_text("index\n", encoding="utf-8")
    (repo / "memory" / "2099-01-01-note.md").write_text("prose\n", encoding="utf-8")
    (repo / "memory" / "2099-01-01-pre-open.md").write_text("brief\n", encoding="utf-8")
    _git(repo, "add", "-f", "MEMORY.md", "memory/2099-01-01-note.md",
         "memory/2099-01-01-pre-open.md")

    def commit():
        return subprocess.run(
            ["git", "-C", str(repo), "-c", "user.email=shengyu.li.evgeny@gmail.com",
             "-c", "user.name=KCNyu",
             "commit", "-m", "sweep"], capture_output=True, text=True)

    done = commit()
    assert done.returncode != 0, "the hook let the coding-agent prose through"
    assert "2099-01-01-note.md" in done.stderr
    assert "MEMORY.md" not in done.stderr, (
        "MEMORY.md is openclaw's runtime state (#1074); blocking it would stop "
        "commit_dreaming.sh and leave the live worktree permanently dirty")
    assert "pre-open" not in done.stderr, (
        "the published brief is not memory; blocking it would break the daily "
        "postflight commit")

    # Drop only the prose: what remains is exactly what the hook must let by.
    _git(repo, "rm", "--cached", "-q", "-f", "memory/2099-01-01-note.md")
    done = commit()
    assert done.returncode == 0, (
        f"the hook blocked a legitimate commit: {done.stderr}")


@pytest.fixture
def live(system_check, monkeypatch, tmp_path):
    ws = tmp_path / "workspace"
    (ws / "memory").mkdir(parents=True)
    monkeypatch.setattr(system_check, "LIVE_WORKSPACE", ws)
    return ws


def _curation(system_check):
    result = system_check.Result()
    system_check.check_memory_curation(result)
    return result.checks[0]


def test_a_topic_file_the_index_never_links_is_reported(system_check, live):
    (live / "MEMORY.md").write_text(
        "- [rules](memory/rules.md) — read before X\n", encoding="utf-8")
    (live / "memory" / "rules.md").write_text("linked\n", encoding="utf-8")
    (live / "memory" / "stray.md").write_text("nobody links me\n", encoding="utf-8")

    name, severity, message = _curation(system_check)
    assert severity == system_check.WARNING
    assert "memory/stray.md" in message
    assert "not in the index" in message


def test_an_index_link_to_a_deleted_note_is_reported(system_check, live):
    (live / "MEMORY.md").write_text(
        "- [gone](memory/gone.md) — deleted last week\n", encoding="utf-8")
    name, severity, message = _curation(system_check)
    assert severity == system_check.WARNING
    assert "resolve to nothing" in message and "memory/gone.md" in message


def test_the_published_brief_is_not_a_memory_orphan(system_check, live):
    """`memory/*-pre-open.md` is site content, not a note MEMORY.md must link.

    Seventy-two of them sit next to the topic files; counting them as orphans
    would bury the two real ones and train everybody to ignore this check.
    """
    (live / "MEMORY.md").write_text("- [rules](memory/rules.md) — x\n", encoding="utf-8")
    (live / "memory" / "rules.md").write_text("linked\n", encoding="utf-8")
    for day in ("2026-08-24", "2026-08-25"):
        (live / "memory" / f"{day}-pre-open.md").write_text("brief\n", encoding="utf-8")

    name, severity, message = _curation(system_check)
    assert severity == system_check.OK, message


def test_wiki_style_links_count_as_links(system_check, live):
    """The shared-memory store links with [[name]]; the same index may too."""
    (live / "MEMORY.md").write_text("see [[rules]] for X\n", encoding="utf-8")
    (live / "memory" / "rules.md").write_text("linked\n", encoding="utf-8")
    name, severity, message = _curation(system_check)
    assert severity == system_check.OK, message


def test_a_missing_index_is_itself_the_warning(system_check, live):
    (live / "memory" / "stray.md").write_text("x\n", encoding="utf-8")
    name, severity, message = _curation(system_check)
    assert severity == system_check.WARNING
    assert "MEMORY.md is missing" in message


def test_the_health_gate_requires_the_index_in_every_checkout(
        system_check, monkeypatch, tmp_path):
    """One tier again, because there is one truth again (#1074).

    The two-tier split existed only because #1072 untracked the index: keeping
    the allowlist entries then reported "missing: DREAMS.md, MEMORY.md" as
    CRITICAL — and pre-push runs this file, so the 20-minute publisher, every
    watchdog and every agent push were blocked at once (#1073). With the files
    tracked, the allowlist entries are correct and the baseline is required
    everywhere, worktrees included, since every checkout ships them.
    """
    import json as _json
    entries = _json.loads(
        (ROOT / "config" / "root-allowlist.json").read_text(encoding="utf-8"))["entries"]
    for name in ("MEMORY.md", "DREAMS.md"):
        assert name in entries, (
            f"{name} is tracked at the repository root, so the allowlist must "
            f"own it or `root ownership` reports it as unowned")

    assert "MEMORY.md" in system_check.BASELINE_TRACKED
    assert not hasattr(system_check, "BASELINE_HOST_LOCAL"), (
        "the host-local tier was #1073's workaround for #1072; it must not "
        "outlive the mistake it worked around")

    # Any checkout at all — worktree or live box — with the full baseline: OK.
    elsewhere = tmp_path / "worktree"
    elsewhere.mkdir()
    for name in system_check.BASELINE_TRACKED:
        (elsewhere / name).write_text("x", encoding="utf-8")
    monkeypatch.setattr(system_check, "WS", elsewhere)
    monkeypatch.setattr(system_check, "LIVE_WORKSPACE", tmp_path / "live")
    result = system_check.Result()
    system_check.check_baseline_files(result)
    assert result.checks[0][1] == system_check.OK, result.checks

    # And the index missing is CRITICAL there too, not only on the live box.
    (elsewhere / "MEMORY.md").unlink()
    result = system_check.Result()
    system_check.check_baseline_files(result)
    assert result.checks[0][1] == system_check.CRITICAL
    assert "MEMORY.md" in result.checks[0][2]
