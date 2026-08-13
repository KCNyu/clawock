"""Nothing that a cron job can reach may spawn a bare `clawock`.

A job started from the user crontab runs with PATH=/usr/bin:/bin. The installed
console script lives in ~/.local/bin. So a bare `clawock` is not "the CLI is
broken" there — it is FileNotFoundError, and every caller turns that into
something worse than a missing command:

  * `ops/publish/safe_push.sh` refused a verifiable book, stranding the 23:50
    gold `portfolio.json` commit in front of every later push;
  * `ops/system_check.py` reported CRITICAL, which blocked the 03:20 dreaming
    commit through the pre-push hook.

Both were fixed on 2026-08-10, three hours apart, because the first fix was
written against the two sites I already knew about instead of asking where else
the shape occurs. This test asks. It discovers call sites rather than listing
them, so the next one fails here instead of at 03:20 on a live host.

The rule is not "never name clawock" — it is "resolve it before spawning it":
prefer the installed command, fall back to the package in this checkout.
"""
from pathlib import Path
import ast
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
# The host-operations surface: what the *user crontab* and the git hooks launch,
# which is where PATH=/usr/bin:/bin actually applies.
#
# Package lifecycle modules are deliberately out of scope, and not by
# oversight: it is reached through `clawock brief|report|intraday`, which is what
# the OpenClaw payloads literally invoke. If that code is running at all, the
# name already resolved — the runtime's own environment is the proof. Widening
# this test to cover it would fail 15 working call sites and teach the next
# reader to delete the test.
SEARCH_ROOTS = ("ops", ".githooks")

# The shell resolver is the one place allowed to say the bare word, because
# saying it *is* its job: it probes for the command and falls back when absent.
# `ops/system_check.py` is deliberately NOT exempt. Exempting the file that had
# the bug is how the first version of this test passed against the bug it was
# written for — its Python resolver returns the *resolved absolute path*, so it
# has no bare literal to hide behind.
RESOLVERS = {
    "ops/publish/money_checker.sh",
}


def _python_files():
    for name in SEARCH_ROOTS:
        for path in sorted((ROOT / name).rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path


def _shell_files():
    for name in SEARCH_ROOTS:
        base = ROOT / name
        for path in sorted(base.rglob("*")):
            if path.is_file() and (path.suffix == ".sh" or base.name == ".githooks"):
                yield path


def test_no_python_caller_spawns_a_bare_clawock():
    """An argv vector whose first element is the literal string."""
    offenders = []
    for path in _python_files():
        rel = str(path.relative_to(ROOT))
        if rel in RESOLVERS:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), rel)
        except SyntaxError as exc:  # pragma: no cover - would fail elsewhere
            pytest.fail(f"{rel} does not parse: {exc}")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            first = node.args[0]
            if not isinstance(first, (ast.List, ast.Tuple)) or not first.elts:
                continue
            head = first.elts[0]
            if isinstance(head, ast.Constant) and head.value == "clawock":
                offenders.append(f"{rel}:{node.lineno}")

    assert not offenders, (
        "these spawn `clawock` by name, which resolves only when the caller's "
        "PATH happens to include ~/.local/bin — it does not under cron: "
        f"{offenders}. Use ops/system_check.py:clawock_argv, or the shell "
        "resolver ops/publish/money_checker.sh.")


# A command word at the start of a line, or right after a pipe / && / ; / $( .
BARE_CALL = re.compile(r"(?:^|[|;&]|\$\(|\bif\s+|\bthen\s+|!\s*)\s*clawock\s")


def test_no_shell_caller_invokes_a_bare_clawock():
    """Same rule for the shell side, where the first failure happened."""
    offenders = []
    for path in _shell_files():
        rel = str(path.relative_to(ROOT))
        if rel in RESOLVERS:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if BARE_CALL.search(code):
                offenders.append(f"{rel}:{number}  {line.strip()[:70]}")

    assert not offenders, (
        "these invoke `clawock` as a bare command; under the user crontab's "
        f"PATH=/usr/bin:/bin it is not found:\n  " + "\n  ".join(offenders))


def test_the_resolver_prefers_the_installed_command_but_does_not_need_it(monkeypatch):
    """The resolver's own contract, both branches.

    Without this the test above is satisfiable by deleting every call site.
    """
    import sys
    sys.path.insert(0, str(ROOT / "ops"))
    import system_check  # noqa: E402

    monkeypatch.setattr(system_check.shutil, "which", lambda _name: "/usr/bin/clawock")
    argv, _ = system_check.clawock_argv("doctor")
    assert argv == ["/usr/bin/clawock", "doctor"], argv

    monkeypatch.setattr(system_check.shutil, "which", lambda _name: None)
    argv, env = system_check.clawock_argv("doctor")
    assert argv[1:] == ["-m", "clawock.cli", "doctor"], argv
    assert str(ROOT / "src") in env["PYTHONPATH"], (
        "the fallback spawns a subprocess, which does not inherit sys.path — "
        "without PYTHONPATH it cannot import the package it just chose")
