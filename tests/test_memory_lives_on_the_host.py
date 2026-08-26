"""The agent's memory is host-local and index-first (#1071).

kcn, 2026-08-26: 「这些 memory 可以有但……不能进仓库」「类似于我们 shared memory 那种
index+md 形式的维护，然后对照清理」.

So the workspace memory has the same shape the interactive agents' own store
has — `MEMORY.md` is the index, `memory/*.md` are the topic files it links —
and three properties are asserted here:

* it cannot enter the repository, stated as a CLASS (#1062 listed sixteen files
  by name, so the seventeenth was committed) and enforced again at commit time
  because `git add -f` walks past .gitignore;
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
        "MEMORY.md",                             # the index itself
        "DREAMS.md",                             # OpenClaw's raw dream log
        "memory/2099-01-01.md",                  # day log
        "memory/2099-01-01-1530.md",             # promoted chat transcript
        "memory/2099-01-01-some-topic.md",       # one-off named note
        "memory/feedback_something.md",          # shared-memory-shaped topic file
    ]
    keep = ["memory/2099-01-01-pre-open.md", "memory/2099-01-01-plan.json"]
    out = subprocess.run(["git", "-C", str(ROOT), "check-ignore", *probes, *keep],
                         capture_output=True, text=True)
    ignored = set(out.stdout.split())
    assert set(probes) <= ignored, (
        f"memory that is not ignored would enter the repo: "
        f"{sorted(set(probes) - ignored)}")
    assert not (set(keep) & ignored), (
        f"the brief/plan surfaces must stay trackable: {sorted(set(keep) & ignored)}")


def test_nothing_memory_shaped_is_still_tracked():
    tracked = _git(ROOT, "ls-files").stdout.split()
    offenders = [name for name in tracked
                 if name in {"MEMORY.md", "DREAMS.md"}
                 or (name.startswith("memory/") and name.count("/") == 1
                     and name.endswith(".md") and not name.endswith("-pre-open.md"))]
    assert offenders == [], f"memory is still in the repository: {offenders}"


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
    _git(repo, "config", "core.hooksPath", ".githooks")

    (repo / "MEMORY.md").write_text("index\n", encoding="utf-8")
    (repo / "memory" / "2099-01-01-note.md").write_text("prose\n", encoding="utf-8")
    (repo / "memory" / "2099-01-01-pre-open.md").write_text("brief\n", encoding="utf-8")
    _git(repo, "add", "-f", "MEMORY.md", "memory/2099-01-01-note.md",
         "memory/2099-01-01-pre-open.md")

    done = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-m", "sweep"], capture_output=True, text=True)
    assert done.returncode != 0, "the hook let the memory through"
    assert "MEMORY.md" in done.stderr and "2099-01-01-note.md" in done.stderr
    assert "pre-open" not in done.stderr, (
        "the published brief is not memory; blocking it would break the daily "
        "postflight commit")


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
