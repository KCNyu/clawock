"""#1038: the daily notes are neither repository data nor continuity any more.

They were untracked first and, on 2026-08-26, removed from disk: raw per-session
logs with zero consumers, superseded by the curated surfaces (`MEMORY.md` here,
the interactive coding agents' own durable memory outside this repository).

Staying retired has three halves. No new `memory/YYYY-MM-DD.md` may re-enter the
index (a future writer could still sweep one up); the .gitignore rule must cover
exactly the bare-dated diaries — not their `-pre-open.md` / `-plan.json` twins,
which are site-rendered and schema-gated respectively; and no instruction file
may ask a session to read or write one, which is how the habit would come back.
"""
import json
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


# The instruction surface: everything a session is told to read at startup, plus
# the skills those sessions route into. #1066 cleaned AGENTS.md and left nine
# other files still pointing at the diaries — the sweep is the point, so the
# scan is a glob, not a list.
INSTRUCTION_DOCS = ("AGENTS.md", "CLAUDE.md", "BOOTSTRAP.md", "MEMORY.md",
                    "TOOLS.md", "USER.md", "INVESTMENT_SOP.md", "SOUL.md",
                    "IDENTITY.md", "HEARTBEAT.md")


def _instruction_texts():
    for name in INSTRUCTION_DOCS:
        path = ROOT / name
        if path.exists():
            yield name, path.read_text(encoding="utf-8")
    for path in sorted(ROOT.glob("skills/*/SKILL.md")):
        yield path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8")


def test_no_instruction_file_asks_a_session_to_read_or_write_a_diary():
    """The habit comes back through the instructions, not through the code.

    AGENTS.md used to open with "Read `memory/YYYY-MM-DD.md` (today +
    yesterday)" and list the diaries as continuity. A session following that
    finds nothing on disk and helpfully starts writing them again — into an
    ignored path no one reads, which is exactly the pile that was cleared.

    #1066 fixed AGENTS.md only. Nine other instruction files still carried the
    same pointer (CLAUDE.md's required reads, INVESTMENT_SOP's write rules,
    TOOLS.md's maintenance table, two portfolio skills' required reads), so a
    session reading any of them would have restarted the habit that afternoon.
    """
    diary = re.compile(r"memory/(\{[^}]*\})?\s*YYYY-MM-DD(\{[^}]*\})?\.md")
    offenders = {}
    for name, text in _instruction_texts():
        hits = [line.strip() for line in text.splitlines()
                if diary.search(line) and "retired in #1038" not in line]
        # AGENTS.md carries the one allowed mention: the note saying they are gone.
        if name == "AGENTS.md":
            hits = [h for h in hits if not h.startswith(("- Dated diaries", "then removed"))]
        if hits:
            offenders[name] = hits
    assert offenders == {}, (
        f"instruction files still point at the retired diaries: {offenders}")
    assert "retired in #1038" in (ROOT / "AGENTS.md").read_text(encoding="utf-8"), (
        "the note explaining that the diaries are gone is what stops the next "
        "session from recreating them; keep it")


def test_no_instruction_file_keeps_a_hand_maintained_holdings_mirror():
    """#1067: a ticker list nobody syncs is worse than no ticker list.

    `memory/current-portfolio-summary.md` was written on 2026-05-14 and read by
    five instruction surfaces — INVESTMENT_SOP, MEMORY.md, TOOLS.md and both
    portfolio skills — as "the active ticker list (also lists exited names so
    you know what NOT to analyze)". By 2026-08-26 it named RKLB / PLTU / SOXL /
    ROBN / MSFU as active (all `shares == 0`), never mentioned SPCX / SPCH /
    SKHY (all held), and declared the Korean chain dead while SKHY was in the
    book — which the risk-review skill had copied into "Do not run any KR
    fetch". `portfolio.json` answers both halves exactly, so the mirror is
    deleted and nothing may reintroduce one.
    """
    offenders = {name: [line.strip() for line in text.splitlines()
                        if "current-portfolio-summary" in line]
                 for name, text in _instruction_texts()}
    offenders = {k: v for k, v in offenders.items() if v}
    assert offenders == {}, (
        f"the hand-maintained holdings mirror is referenced again: {offenders}")
    assert not (ROOT / "memory" / "current-portfolio-summary.md").exists(), \
        "the mirror is back on disk; active/exited comes from portfolio.json"


_EXIT_CLAIM = re.compile(r"已清仓|不再追踪|no longer tracked|is exited|are exited", re.I)
_TICKER = re.compile(r"\b([A-Z]{2,5}|\d{5})\b")
# Only the clause carrying the claim counts. "07709/07747 are exited, but SKHY
# can be held" is the correct sentence, and a line-wide scan would read it as
# calling SKHY exited — the opposite of what it says.
_CONTRAST = re.compile(r"\bbut\b|但|而(?!已)|except|however", re.I)
# `|` ends a clause for the same reason `。` does. The dreaming promoter
# flattens a whole markdown table onto one MEMORY.md line, and a row's cells are
# unrelated facts: "| RKLX | -69.2% | … | RKLB（已清仓，swap_to=null） |" says the
# *swap target* RKLB is exited, about the held position RKLX. Without the cell
# boundary the scan pulled RKLX out of column 1 into RKLB's claim in column 5,
# and master went red on 2026-09-05 over a line that is right.
_CLAUSE_ENDS = ("。", ". ", "; ", "；", "|")


def _exit_claim_clause(line):
    """The part of `line` that actually carries an exit claim, or None."""
    hit = _EXIT_CLAIM.search(line)
    if not hit:
        return None
    clause = line[:hit.end()]
    cut = None
    for sep in _CONTRAST.finditer(clause):
        cut = sep.start()
    clause = clause[cut:] if cut is not None else clause
    for sep in _CLAUSE_ENDS:
        if sep in clause:
            clause = clause.rsplit(sep, 1)[-1]
    return clause


def test_no_instruction_file_calls_a_held_position_exited():
    """The mirror's actual damage: a skill told not to look at a live holding.

    Generalised past the one file — any instruction that names a ticker in an
    "exited / no longer tracked" sentence is checked against the book.
    """
    book = json.loads((ROOT / "portfolio.json").read_text(encoding="utf-8"))
    held = {h["ticker"] for leg in book["portfolios"].values()
            for h in leg.get("holdings", []) if (h.get("shares") or 0) > 0}
    assert held, "an empty book would make this assertion vacuous"

    offenders = {}
    for name, text in _instruction_texts():
        for line in text.splitlines():
            clause = _exit_claim_clause(line)
            if clause is None:
                continue
            named = held & set(_TICKER.findall(clause))
            if named:
                offenders.setdefault(name, []).append((sorted(named), line.strip()))
    assert offenders == {}, (
        f"instruction files call a held position exited: {offenders}")


def test_the_exit_claim_scan_reads_a_table_row_by_cell():
    """The clause rule is the whole gate; pin both directions of it.

    Without these the `|` boundary could be widened until nothing ever trips,
    and the check would stay green by seeing nothing — the failure mode this
    module exists to prevent, one level up.
    """
    row = ("| RKLX | -69.2% | 5.24% | +224.6% | RKLB（已清仓，swap_to=null） "
           "| +89.9% |")
    assert "RKLX" not in _exit_claim_clause(row)
    assert "RKLB" in _exit_claim_clause(row)
    # A real offender has no cell wall to hide behind.
    assert "RKLX" in _exit_claim_clause("RKLX 已清仓，不用再看了")
    assert "SKHY" in _exit_claim_clause("Do not fetch KR: SKHY is exited.")
    # The contrast rule still holds.
    assert "SKHY" not in _exit_claim_clause("07709/07747 are exited, but SKHY is held")
    assert _exit_claim_clause("RKLX is a held position") is None
