"""Shell entry points that run our code must be able to import it.

`.githooks/pre-commit` validates staged plans by piping a heredoc into a bare
`python3`. That import resolved only because the package used to sit at the
repository root, so the hook's own working directory put it on `sys.path`. #392
moved the package behind `src/`, and the block became dead code: every commit
staging a `memory/*-plan.json` failed with `ModuleNotFoundError`, while
`brief postflight` still reported `status: pass` and had already delivered a
card linking to the report the failed commit was supposed to publish (#445).

It hid for two days because the block runs only when a plan is staged, which
happens on brief days — the first weekday after the move was the first execution.

This is the shell-side companion to `test_code_imports_come_from_the_checkout`:
that one pins where Python modules resolve their imports from, this one pins
that the scripts *spawning* Python leave it able to resolve them at all.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".githooks" / "pre-commit"

# A plan that parses as JSON but cannot satisfy the v2 decision schema. The
# point is not which rule it breaks — it is that reaching a schema verdict at
# all proves `clawock.decision.ledger` was imported.
SCHEMA_INVALID_PLAN = '{"schema_version": "v2", "decisions": "not-a-list"}'


def _stripped_env(repo: Path) -> dict:
    """Only what cron gives a hook: no PYTHONPATH, no virtualenv, minimal PATH.

    Inheriting this process's environment would hand the hook the very thing
    under test — pytest runs with the package importable, so the bug is
    invisible from inside the suite unless the environment is stripped first.
    """
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(repo),
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }


@pytest.fixture
def repo_with_staged_plan(tmp_path):
    """A real git repo running the real hook against a staged plan file."""
    repo = tmp_path / "checkout"
    (repo / "memory").mkdir(parents=True)

    # The hook imports the package out of the tree it is committing into, so the
    # tree needs one. Symlinking keeps this honest: it is the checkout's src/,
    # not an installed copy, that has to answer.
    (repo / "src").symlink_to(ROOT / "src")

    hooks = repo / ".githooks"
    hooks.mkdir()
    shutil.copy2(HOOK, hooks / "pre-commit")
    (hooks / "pre-commit").chmod(0o755)

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=repo, check=True)

    plan = repo / "memory" / "2026-01-01-plan.json"
    plan.write_text(SCHEMA_INVALID_PLAN)
    subprocess.run(["git", "add", "memory/2026-01-01-plan.json"], cwd=repo, check=True)
    return repo


def _commit(repo: Path):
    return subprocess.run(
        ["git", "commit", "-m", "plan"],
        cwd=repo, env=_stripped_env(repo),
        capture_output=True, text=True,
    )


def test_the_hook_can_import_the_package_it_validates_with(repo_with_staged_plan):
    """The failure must be a schema verdict, never an import error.

    Asserting only "the commit fails" would pass while the bug is present — it
    failed then too, just for the wrong reason. The discriminating signal is
    *which* failure it is.
    """
    result = _commit(repo_with_staged_plan)
    combined = result.stdout + result.stderr

    assert "ModuleNotFoundError" not in combined, (
        "the hook spawned a Python that cannot import clawock, so plan "
        f"validation never ran:\n{combined}")
    assert "No module named" not in combined, combined


def test_an_invalid_plan_is_actually_rejected(repo_with_staged_plan):
    """Importability is worthless if the validator then waves everything through.

    Pairs with the test above: that one proves the import happened, this one
    proves the import is load-bearing.
    """
    result = _commit(repo_with_staged_plan)
    assert result.returncode != 0, (
        "a plan whose `decisions` is not a list was committed anyway:\n"
        f"{result.stdout}{result.stderr}")


# ---------------------------------------------------------------------------
# Find the next one by shape, not by name.
#
# A hand-written list of known call sites has the same failure mode as the code
# it guards — #322 shipped exactly that and stayed green while three writers
# went unlisted. So this walks the tree and asks a question about each file
# instead of consulting an inventory.
# ---------------------------------------------------------------------------

_SPAWNS_PYTHON = re.compile(r"(?:^|[|;&(]|\s)(?:env\s+[^|;&]*)?python3?\b")
_IMPORTS_CLAWOCK = re.compile(r"^\s*(?:from|import)\s+clawock\b", re.MULTILINE)
# Only the invocation itself counts. Matching anywhere in the file would let a
# comment that merely mentions PYTHONPATH vouch for the command below it — the
# mutation run proved that, by staying green with the fix removed.
_MAKES_IT_IMPORTABLE = re.compile(r"PYTHONPATH|python3?\s+-m\s+clawock")


def _shell_entry_points():
    for base in (".githooks", "ops"):
        for path in sorted((ROOT / base).rglob("*")):
            if not path.is_file() or path.suffix not in ("", ".sh"):
                continue
            try:
                text = path.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            first = text.splitlines()[0] if text else ""
            if first.startswith("#!") and ("bash" in first or "sh" in first):
                yield path, text


def _python_spawns(text):
    """Yield (invocation, body) pairs: the command line, and the code it runs.

    Backslash continuations are folded first, so the environment prefix and the
    `python3` it applies to stay one unit — that is precisely the relationship
    being asserted, and a line-at-a-time scan would sever it.
    """
    folded = text.replace("\\\n", " ")
    lines = folded.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#") or not _SPAWNS_PYTHON.search(line):
            continue
        heredoc = re.search(r"<<-?'?([A-Za-z_][A-Za-z0-9_]*)'?", line)
        if heredoc:
            terminator = heredoc.group(1)
            body = []
            for follow in lines[i + 1:]:
                if follow.strip() == terminator:
                    break
                body.append(follow)
            yield line, "\n".join(body)
        else:
            yield line, line


def test_no_shell_entry_point_spawns_a_python_that_cannot_import_clawock():
    offenders = []
    for path, text in _shell_entry_points():
        for invocation, body in _python_spawns(text):
            if not _IMPORTS_CLAWOCK.search(body):
                continue
            if not _MAKES_IT_IMPORTABLE.search(invocation):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}: {invocation.strip()[:70]}")
    assert not offenders, (
        "these spawn a Python that imports clawock without making the package "
        f"resolvable, so they are dead under cron's bare environment: {offenders}")


def test_the_sweep_would_catch_the_regression_it_was_written_for(tmp_path):
    """Guard the guard: the sweep above must reject the pre-fix hook.

    Its first version passed on the broken file, because a nearby comment
    containing the word `clawock` satisfied the check. A sweep that cannot fail
    on the exact code that caused the incident is decoration.
    """
    broken = HOOK.read_text().replace('PYTHONPATH="$WS/src${PYTHONPATH:+:$PYTHONPATH}" ', "")
    assert broken != HOOK.read_text(), "the fix is no longer shaped as expected"
    flagged = [
        inv for inv, body in _python_spawns(broken)
        if _IMPORTS_CLAWOCK.search(body) and not _MAKES_IT_IMPORTABLE.search(inv)
    ]
    assert flagged, "the sweep does not flag the very hook this issue was filed for"
