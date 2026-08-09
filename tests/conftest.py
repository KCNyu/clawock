"""Session-level guarantees that belong to no single test module.

There are two, and both exist because a test module must not depend on which
other module happened to run first.

**The rebuild.** The money-reconciliation tests compare the dashboard payload
against `portfolio.json`, and at any given commit the *tracked* dashboard.json
may be older than the tracked portfolio.json (the publisher commits them on
different cadences), so a rebuild is what makes the money check meaningful. The
rebuild used to live inside `test_dashboard_payload_size`, and
`test_validate_sidecars` reconciled whatever that module had left behind —
correct only because `test_dashboard_...` sorts before `test_validate_...`.
Nothing stated it, so running the money gate on its own was not a valid
invocation, and any rename, split-by-file or shuffled ordering would have
reported "money does not reconcile" for what was really an ordering accident.
It is a session fixture now: requested by name, built once, at most one
subprocess per session either way. The rebuild is load-bearing; only its
residue is the problem.

**The import path.** Remaining `scripts/data` modules still import some siblings
by bare name, so that directory has to be on `sys.path` before collection imports
anything. Roughly twenty test modules
insert it at import time, which made a single-module run work or fail on
alphabetical luck: `pytest tests/test_validate_sidecars.py` alone died in
collection. Doing it here covers every module and every invocation.

The residue is not cosmetic. #295 was pushed carrying four regenerated
artifacts because the suite had been run and `git add -A` swept them up; the
stale copies collided with the 20-minute publisher and GitHub marked the PR
DIRTY. A conflict caught that one. A generated file that happened to be
*newer* than master's would have merged silently and published a payload
nobody built on purpose. In `/root/.openclaw/workspace` the same rebuild
rewrites the live artifacts outside the publish lock.

So: snapshot before, restore after, and verify the restore actually worked.
Restoring to the session's starting bytes rather than to HEAD keeps a
developer's own uncommitted edits intact.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

# A test process must be physically incapable of reaching kcn's real WeChat,
# Telegram, or fallback workflow.  This is deliberately established before
# test-module collection, so import order and monkeypatch target changes cannot
# reopen live delivery.
os.environ["CLAWOCK_DELIVERY_DISABLED"] = "1"

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "assets" / "data" / "dashboard.json"

# Import time, not fixture time: collection imports the test modules, which
# import remaining operator scripts by bare name. See the module docstring.
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "instances" / "kcnyu" / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "data"))


def _git_status(paths):
    """Porcelain status for `paths`, or None where git cannot answer."""
    try:
        done = subprocess.run(["git", "status", "--porcelain", "--", *paths],
                              cwd=ROOT, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


@pytest.fixture(scope="session", autouse=True)
def publish_owned_artifacts_are_left_as_found():
    from clawock.publish.outputs import output_paths

    outputs = output_paths(ROOT)
    before = {path: (ROOT / path).read_bytes() for path in outputs
              if (ROOT / path).exists()}
    status_before = _git_status(outputs)

    yield

    for path, blob in before.items():
        (ROOT / path).write_bytes(blob)

    status_after = _git_status(outputs)
    if status_before is not None:
        assert status_after == status_before, (
            "the suite changed the publish-owned artifacts and the restore did "
            "not put them back; a later `git add -A` would carry them into a "
            f"code PR:\n{status_after}")


@pytest.fixture(scope="session")
def freshly_built_dashboard(publish_owned_artifacts_are_left_as_found):
    """The real builder run once, against the real tree, before anything reads
    the payload it produces.

    Depends on the restore guard by name so the snapshot is always taken before
    the first byte is rewritten — the ordering that keeps the rebuild's residue
    out of a code PR.

    Returns the path rather than the parsed payload: the callers that matter
    read it as bytes (the size cap) as well as as JSON, and taking the path
    from the fixture is what makes each of them state the dependency instead of
    reaching for a module constant that may or may not be fresh.
    """
    subprocess.run([sys.executable, "scripts/data/build_dashboard.py"],
                   cwd=ROOT, check=True, capture_output=True)
    return DASHBOARD
