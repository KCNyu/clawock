"""#1038: the daily notes are workspace continuity, not repository data.

Untracking them must stay true over time: no new `memory/YYYY-MM-DD.md` may
re-enter the index (the auto-commit table row is gone, but a future writer
could still sweep one up), and the .gitignore rule must cover exactly the
bare-dated diaries — not their `-pre-open.md` / `-plan.json` twins, which are
site-rendered and schema-gated respectively.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DAILY = "memory/2099-01-01.md"
BARE_DATED = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


def _git(*args):
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True)


def test_no_tracked_file_is_a_bare_dated_daily_note():
    out = _git("ls-files", "--", "memory/").stdout.splitlines()
    offenders = [f for f in out if BARE_DATED.match(Path(f).name)]
    assert not offenders, (
        f"daily notes re-entered tracking: {offenders}. They were untracked in "
        "#1038 — workspace continuity reads them from disk; the repo carries "
        "only -pre-open.md / -plan.json / weekly surfaces.")


def test_ignore_rule_covers_the_diary_and_not_its_site_or_schema_twins():
    ignored = _git("check-ignore", DAILY, "memory/2099-01-01-pre-open.md",
                   "memory/2099-01-01-plan.json")
    # rc=1 means at least one path is NOT ignored; find which.
    if ignored.returncode != 0:
        not_ignored = set(ignored.args[4:]) - set(ignored.stdout.splitlines())
        assert not any(p.endswith(".md") and "pre-open" not in p
                       for p in not_ignored), (
            f"the bare-dated diary must be ignored, got exceptions: {not_ignored}")
    covered = set(ignored.stdout.splitlines())
    assert DAILY in covered, "new daily notes must be born ignored"
    assert "memory/2099-01-01-pre-open.md" not in covered, \
        "pre-open briefs are site-rendered — they must stay trackable"
    assert "memory/2099-01-01-plan.json" not in covered, \
        "plan files sit behind the pre-commit schema gate — they must stay trackable"


def test_agents_md_auto_commit_table_no_longer_commits_dailies():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "`memory/YYYY-MM-DD.md` created or updated" not in text, \
        "the auto-commit table row was removed with the untracking (#1038); " \
        "a writer following it would re-stage ignored files by force"
