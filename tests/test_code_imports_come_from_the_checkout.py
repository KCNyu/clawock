"""Code resolves from the checkout; only data resolves from the workspace.

`workspace_root()` is overridable with CLAWOCK_WORKSPACE so the engine can run
against someone else's book (#246). But a foreign workspace holds market data —
snapshots, ledgers, plans — not `scripts/data/trading_calendar.py`. A module that
puts `WS / 'scripts' / 'data'` on sys.path therefore resolves OUR code out of
THEIR directory: it fails if the directory is absent, and silently imports
whatever is there if it is not (#269).

The two roles are the same directory on every live run, which is exactly why the
confusion spread to 28 files without anything breaking. It becomes real the first
time the override is used — the feature the README sells.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Nothing is exempt any more. `system_check` migrated last — for the same reason
# it goes last in the decoupling sequence, that it is what proves the rest still
# works — and its own run against the live host is what closed this out.
MIGRATING_LAST: set[str] = set()

_WS_IMPORT = re.compile(r"sys\.path\.insert\(\s*0\s*,\s*str\(\s*WS\s*/")


def test_no_module_resolves_code_through_the_workspace():
    offenders = []
    for path in sorted(ROOT.glob("scripts/**/*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in MIGRATING_LAST:
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if _WS_IMPORT.search(line):
                offenders.append(f"{rel}:{lineno}")
    assert not offenders, (
        "these put the WORKSPACE on sys.path to import our own modules, so a "
        f"CLAWOCK_WORKSPACE override resolves code out of the data dir: {offenders}")


def test_the_two_roots_actually_diverge_under_the_override(tmp_path):
    """The distinction has to be observable, or the rule above is bookkeeping.

    Deliberately NOT an "import fails without the fix" test. Most of these sites
    are shadowed: `scripts/data/*` gets its own directory on sys.path just by
    being executed, and `_harness_common` inserts the correct checkout path at
    module top before the line that was wrong. So an end-to-end import passes
    either way, and a test written that way would look like proof while
    discriminating nothing — the line-level guard above is the one that bites,
    and it is mutation-verified.

    What is worth pinning end-to-end is that the override is real: workspace_root
    follows it, the checkout does not, and a script still runs against a book
    that contains no code at all.
    """
    foreign = tmp_path / "someone-elses-book"
    (foreign / "memory").mkdir(parents=True)
    (foreign / "assets" / "data").mkdir(parents=True)
    (foreign / "portfolio.json").write_text('{"portfolios": {}}', encoding="utf-8")
    assert not (foreign / "scripts").exists(), "the point is that code is absent"

    env = dict(os.environ, CLAWOCK_WORKSPACE=str(foreign))
    probe = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, {str(ROOT / 'scripts' / 'data')!r})\n"
         "from pathlib import Path\n"
         "from workspace import workspace_root\n"
         "print(workspace_root(Path.cwd()))\n"],
        capture_output=True, text=True, timeout=60, env=env, cwd=str(ROOT),
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == str(foreign), (
        "the override is not in effect, so nothing below proves anything")

    ran = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "data" / "mover_news.py"), "--help"],
        capture_output=True, text=True, timeout=60, env=env, cwd=str(ROOT),
    )
    assert ran.returncode == 0, (
        "a script could not even start against a code-less workspace:\n"
        f"{ran.stdout}\n{ran.stderr}")
