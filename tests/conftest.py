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

**The import path.** The public and KCNyu distributions are inserted before
collection so a single test module never depends on editable-install state.

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
sys.path.insert(0, str(ROOT / "ops" / "host"))
sys.path.insert(0, str(ROOT / "ops" / "ci"))
sys.path.insert(0, str(ROOT / "ops" / "growth"))
sys.path.insert(0, str(ROOT / "ops" / "publish"))


def _git_status(paths):
    """Porcelain status for `paths`, or None where git cannot answer."""
    try:
        done = subprocess.run(["git", "status", "--porcelain", "--", *paths],
                              cwd=ROOT, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


# Directories a test has no business writing to. `assets/data` and `memory` are
# published state; `logs` and `site/assets` are build output. The publish-owned
# subset of these is snapshotted and restored by the session fixture below, but
# that only covers four files and only at session END — which is exactly how a
# test can leave state that changes what a LATER test sees.
WATCHED_DIRS = ("assets/data", "memory", "logs", "site/assets")


def _watched_state():
    """Path -> (size, mtime_ns) for everything under the watched directories.

    Cheap enough to run around every test: stat only, no hashing. It catches
    creation, deletion and rewrite, which is the whole failure class. A rewrite
    that preserves size AND mtime_ns would slip through, and nothing observed
    here does that.
    """
    state = {}
    for name in WATCHED_DIRS:
        base = ROOT / name
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file():
                try:
                    st = path.stat()
                except OSError:
                    continue
                state[path] = (st.st_size, st.st_mtime_ns)
    return state


@pytest.fixture
def isolated_workflow_ledger(tmp_path_factory, monkeypatch):
    """Point the workflow-outcome ledger at a temp directory.

    The report-assembly suites drive real postflights, which record stages. The
    ledger resolves its paths per call now (#816), but these tests need the rest
    of the real workspace — the book, the config — so redirecting
    CLAWOCK_WORKSPACE wholesale would break them. Patching the four path
    functions isolates exactly the shared file and nothing else.

    Returns the directory, for a test that wants to read back what was written.
    """
    from clawock.automation import workflow_outcomes  # noqa: PLC0415

    # A directory of its own, NOT a child of the test's `tmp_path`: several of
    # these tests list their tmp_path and assert on exactly what is in it.
    ledger = tmp_path_factory.mktemp("workflow-ledger")
    monkeypatch.setattr(workflow_outcomes, "local_path", lambda: ledger / "local.json")
    monkeypatch.setattr(workflow_outcomes, "public_path", lambda: ledger / "public.json")
    monkeypatch.setattr(workflow_outcomes, "lock_path", lambda: ledger / "lock")
    monkeypatch.setattr(workflow_outcomes, "tmp_dir", lambda: ledger)
    return ledger


@pytest.fixture
def isolated_watchdog_log(tmp_path_factory, monkeypatch):
    """Point `logs/watchdog.jsonl` at a temp directory.

    Same shape as the ledger: the watchdog appends a line per run, and a test
    driving a real watchdog appended to the checkout's own log (#816). The path
    resolves per call now, so patching the one function is enough.
    """
    from clawock.harness import _watchdog_common  # noqa: PLC0415

    target = tmp_path_factory.mktemp("watchdog") / "watchdog.jsonl"
    monkeypatch.setattr(_watchdog_common, "log_path", lambda: target)
    return target


@pytest.fixture
def isolated_integrity_report(tmp_path_factory, monkeypatch):
    """Point `assets/data/integrity_report.json` at a temp directory (#816)."""
    from clawock.portfolio import integrity  # noqa: PLC0415

    target = tmp_path_factory.mktemp("integrity") / "integrity_report.json"
    monkeypatch.setattr(integrity, "out_path", lambda: target)
    return target


@pytest.fixture
def restores_untracked_artifact():
    """Undo an artifact a subprocess necessarily wrote into the checkout.

    Some gates can only be tested by running them for real against this
    repository. `money_checker.sh` is one: it pins CLAWOCK_WORKSPACE to the root
    it is guarding, on purpose, so no environment the test sets can redirect it
    — the point of the gate is that it checks the repo being pushed. Its
    `assets/data/integrity_report.json` is therefore a correct side effect, and
    the fix is to put the tree back rather than to weaken the test (#816).

    Restores to the exact bytes found, or deletes the file if it was absent.
    """
    saved: dict = {}

    def track(relative):
        path = ROOT / relative
        saved[path] = path.read_bytes() if path.exists() else None
        return path

    yield track

    for path, blob in saved.items():
        if blob is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(blob)


_WRITE_LOG = []
_LAST_SEEN = {}


def pytest_sessionstart(session):
    """Baseline before ANY fixture runs.

    Taking it inside the first test's fixture setup does not work: session-scoped
    fixtures are set up first, so the session dashboard rebuild is already baked
    into the baseline and the run reports itself clean. That was the second
    wrong version of this.
    """
    _LAST_SEEN.clear()
    _LAST_SEEN.update(_watched_state())


@pytest.fixture(autouse=True)
def _attribute_writes_to_the_test_that_made_them(request):
    """Name the test that touched published state.

    #816: `test_dropped_blocks_are_still_reachable_elsewhere` failed only in
    full-suite order and passed alone, because an UNTRACKED file
    (`assets/data/workflow-outcomes.json`) is absent in a clean checkout, gets
    created during a run, and then persists — silently arming an assertion that
    is dormant otherwise. Nothing could say which test created it.

    Compares against a running checkpoint rather than snapshotting inside the
    test's own window, because a higher-scoped fixture is set up BEFORE any
    function-scoped one: the session rebuild would happen outside a
    before/after pair and be missed entirely. That was the first version of
    this fixture, and it reported a clean run against a module that definitely
    rewrites four files.

    This records rather than forbids. Attribution first, cleanup second —
    guessing at the writer is what let this sit unexplained through two
    sightings.
    """
    yield
    after = _watched_state()

    created = sorted(set(after) - set(_LAST_SEEN))
    removed = sorted(set(_LAST_SEEN) - set(after))
    changed = sorted(p for p in set(_LAST_SEEN) & set(after)
                     if _LAST_SEEN[p] != after[p])
    if created or removed or changed:
        _WRITE_LOG.append({
            "test": request.node.nodeid,
            "created": [str(p.relative_to(ROOT)) for p in created],
            "removed": [str(p.relative_to(ROOT)) for p in removed],
            "changed": [str(p.relative_to(ROOT)) for p in changed],
        })
    _LAST_SEEN.clear()
    _LAST_SEEN.update(after)


# Writers that are known and, for now, tolerated. Each entry is a test-id prefix
# with the reason it writes. The list may only shrink — the assertion in
# `test_no_new_test_writes_to_published_state` is what makes that true, so a new
# writer has to be argued for rather than appended to.
#
# `memory/.tmp/**` is the workspace's own scratch area and gitignored, but it is
# still shared state between tests: two modules writing one ledger there is the
# same class of coupling, one directory further down. Listed, not exempted.
TOLERATED_WRITERS = {
    # The session dashboard rebuild, attributed to whichever test first requests
    # the fixture. This one is not debt: the builder is supposed to run against
    # the real tree — the money-reconciliation tests compare its payload with
    # portfolio.json, and a rebuild into a temp copy would be checking a
    # different book. Its residue, not its writes, was ever the problem, and the
    # session fixture below restores all four files.
    "tests/test_dashboard_payload_size.py::test_payload_stays_under_the_published_cap",
}

def _tolerated(node_id: str) -> bool:
    return any(node_id.startswith(prefix) for prefix in TOLERATED_WRITERS)


def pytest_terminal_summary(terminalreporter):
    """Print the attribution table, so a polluted run explains itself."""
    if not _WRITE_LOG:
        return
    terminalreporter.section("tests that wrote to published state (#816)")
    for entry in _WRITE_LOG:
        parts = []
        for kind in ("created", "removed", "changed"):
            if entry[kind]:
                shown = ", ".join(entry[kind][:4])
                more = f" (+{len(entry[kind]) - 4} more)" if len(entry[kind]) > 4 else ""
                parts.append(f"{kind}: {shown}{more}")
        mark = "" if _tolerated(entry["test"]) else "  <-- NEW"
        terminalreporter.write_line(
            f"{entry['test']}{mark}\n    " + "\n    ".join(parts))


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
    # Run through the source tree explicitly; CI installs first, but a focused
    # local invocation should exercise the same package without editable state.
    subprocess.run([sys.executable, "-m", "clawock.publish.dashboard"],
                   cwd=ROOT, check=True, capture_output=True,
                   env={**os.environ, "CLAWOCK_PROFILE": "kcnyu",
                        "PYTHONPATH": str(ROOT / "src")})
    return DASHBOARD
