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
import fcntl
import os
import subprocess
import tempfile
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

# A test process must also be physically incapable of writing ANOTHER
# workspace's published state (#1063).
#
# `CLAWOCK_WORKSPACE` is a permanent export in this host's shell, so a suite run
# from a worktree resolved `WS` — and `LEDGER`, which reaches load/upsert/write
# as a definition-time default argument captured at import — to the LIVE
# checkout instead of the checkout under test. That is how a fixture decision
# (`dec-20260824-00100-add_only_on_trigger`) was written into the live
# `memory/decisions.jsonl`, settled against real bars by the next brief,
# committed to master by the daily memory commit, and finally caught by the
# plan-origin cross-check in CI — a day later and three artifacts downstream.
#
# The write guard below could not see it: `_watched_state()` stats paths under
# ROOT, and those writes landed in a different tree entirely. A guard anchored
# to the wrong directory reports a clean run no matter what the suite does, so
# the fix belongs here, before any test module imports anything.
#
# Removed rather than repointed at ROOT: unset is the shape every GitHub
# Actions run already has, `workspace_root()` then falls back to the package's
# own checkout (= ROOT, because the sys.path inserts below make clawock resolve
# from src/ here), and a test that behaves differently when the variable merely
# EXISTS stays honest — `test_context_audit_covers_every_profile` is one, and
# pinning a value would have hidden that from every local run.
# Per-test `monkeypatch.setenv` isolation is untouched: this runs once, at
# import, and those tests set the variable to their own tmp_path afterwards.
_foreign_workspace = os.environ.pop("CLAWOCK_WORKSPACE", None)
if _foreign_workspace:
    print(f"conftest: dropped CLAWOCK_WORKSPACE={_foreign_workspace}; the suite "
          f"only ever touches the checkout under test ({ROOT}) — see #1063",
          file=sys.stderr)

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


#: A path that cannot exist, so `openclaw` resolution fails the way it does on
#: every machine that has no runtime installed — which is every CI runner.
_NO_OPENCLAW_BINARY = "/nonexistent/clawock-tests-have-no-openclaw"


def pytest_configure(config):
    """No test reaches the live OpenClaw runtime, on any host.

    `providers.openclaw.cron_cli_json` shells out to `openclaw cron … --json`,
    and that round-trips through the gateway: the module's own comment measures
    it at ~42s on a loaded host, and 4.6s is ordinary. CI never paid it, because
    no runner has `openclaw` on PATH and the call fails immediately — so the
    suite's cost on the one machine that DOES have the runtime was invisible to
    everything that watches the suite.

    Measured 2026-09-06 on the live box:

        tests/test_brief_watchdog_retry_budget.py     39.4s -> 4.5s   (17 passed)

    Speed is the smaller half. The larger half is that those runs were reaching
    the real cron of the live trading host to decide what a *unit test* asserted:
    `alert_brief_missing` stubs `brief_cron_job_state` but calls `brief_cron_job`
    as well, and nothing stubbed that. A test whose answer depends on whether
    this particular host has a healthy runtime is a test that means something
    different for every person who runs it — the same complaint as the two
    guarantees above, one layer out.

    `CLAWOCK_OPENCLAW_BIN` is the documented override, so this uses the public
    seam rather than patching the module. A test that genuinely wants the real
    binary sets the variable itself; `monkeypatch.setenv` inside a test wins over
    the value planted here.

    This needed three tests to opt out when it first landed, which was the wrong
    shape and is gone: they compared `OPENCLAW_BIN` — a `shutil.which` constant
    computed at import and blind to the environment — against argv the code had
    built from `runtime_paths().binary`, which honours it. Two names for one
    runtime, agreeing only by luck, and the sentinel is simply what made the luck
    run out. They now assert against the name the code actually used, and
    `test_cron_live_state.test_one_name_for_the_runtime` keeps the two from
    drifting apart again.
    """
    os.environ.setdefault("CLAWOCK_OPENCLAW_BIN", _NO_OPENCLAW_BINARY)


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


#: Workers ship their write log to the controller under this key. xdist gives
#: each worker its own process, so `_WRITE_LOG` is per-worker and the verdict
#: below can only be reached by the one process that sees all of them.
_WORKER_WRITE_LOG = "clawock_write_log"

#: Filled on the controller as each worker exits.
_WRITES_FROM_WORKERS: list[dict] = []

try:  # pragma: no cover - depends on whether the optional plugin is installed
    import xdist  # noqa: F401  PLC0415
except ImportError:  # serial-only environment: the hook below would be unknown
    pass
else:
    def pytest_testnodedown(node, error):
        """Collect one worker's write log as it exits (xdist controller hook).

        This is the join step. Without it, running `-n` silently switched the
        write guard OFF — `pytest_sessionfinish` bailed out on every worker
        because attribution across four partial logs is meaningless, and the
        controller's own log is empty because the controller runs no tests. So
        the parallel suite enforced nothing, and the only thing that said so was
        a comment.
        """
        payload = getattr(node, "workeroutput", None) or {}
        _WRITES_FROM_WORKERS.extend(payload.get(_WORKER_WRITE_LOG) or [])


def _offenders(entries) -> set[str]:
    """The tests to fail the run over. Exact, and only meaningful serially.

    This watcher takes a filesystem snapshot around every test, so in a serial
    run anything that moved between one test's start and its end was moved BY
    that test. Under `-n` the snapshot is still global while the tests are not,
    and two measurements on 2026-09-06 show that no rule over these entries can
    fix that:

    * the session dashboard rebuild ran in one worker and a test in the OTHER
      worker reported the same four payloads as `created` — its window merely
      overlapped the build, and it was named `<-- NEW`;
    * scoping the verdict to "paths no tolerated writer touched" removes that
      false accusation and immediately buys the opposite one: a deliberately
      planted writer of `logs/zz-temp-offender.log` was EXCUSED, because the
      tolerated test had also *observed* that file appear and so the path
      counted as owned. Exit 0 on a run with a real new writer in it.

    A guard that accuses the wrong test, or excuses the right one, is worse than
    one that says "I cannot tell". So parallel runs get the table and no verdict;
    see `pytest_sessionfinish`.
    """
    return {entry["test"] for entry in entries if not _tolerated(entry["test"])}


def pytest_sessionfinish(session, exitstatus):
    """Fail the RUN when an untolerated writer touched published state.

    This assertion used to live in
    `test_import_layering.py::test_no_new_test_writes_to_published_state`, whose
    docstring said "this runs last by name". It is not last: pytest collects by
    path, and `test_i...` is followed by everything from `test_j` to `test_w` —
    `test_validate_sidecars.py` among them. Measured on 2026-08-26, a full suite
    printed

        tests/test_validate_sidecars.py::test_real_committed_dashboard_passes  <-- NEW
            created: assets/data/dashboard.json, ...

    and reported no failure for it: the marker was rendered, the assertion had
    already run. **A writer in any module sorting after the guard was invisible
    to it** — which is the half of the suite the guard was least likely to be
    watching, since the dashboard-shaped modules live there.

    A session hook has no position in the collection order, so there is nothing
    left to sort after it (#1089).
    """
    if session.config.getoption("collectonly", False):
        return
    # xdist: a worker sees only the tests it ran, so it reports rather than
    # judges. The controller joins the parts in `pytest_testnodedown` and reaches
    # the verdict once, over the whole run — the same verdict a serial run gets.
    if getattr(session.config, "workerinput", None) is not None:
        session.config.workeroutput[_WORKER_WRITE_LOG] = list(_WRITE_LOG)
        return
    entries = [*_WRITE_LOG, *_WRITES_FROM_WORKERS]
    if _WRITES_FROM_WORKERS:
        # A parallel run reports and does not judge — see `_offenders`. Before
        # the join above it did neither: `pytest_sessionfinish` returned on every
        # worker and the controller's own log is empty because it runs no tests,
        # so `-n` silently switched this guard off and nothing said so.
        # Deliberately unnamed. Measured: `pytest tests/test_import_layering.py
        # -n 2` flags `test_no_workflow_or_script_invokes_a_module_by_a_path_
        # that_moved`, a read-only module that records nothing serially — under
        # `-n` a bystander's window simply overlaps someone else's write. Naming
        # innocents every run is how a warning gets trained out of people, so the
        # parallel mode reports the count and where to get the answer.
        if _offenders(entries):
            reporter = session.config.pluginmanager.get_plugin("terminalreporter")
            if reporter is not None:
                reporter.write_line("")
                reporter.write_line(
                    "NOTE: published state changed during this -n run. Attribution "
                    "needs a serial run — under xdist the snapshot is global while "
                    "the tests are not, so this cannot tell a writer from a "
                    "bystander. `pytest tests/` without -n is the enforcing run.",
                    yellow=True)
        return
    offenders = sorted(_offenders(entries))
    if offenders:
        session.exitstatus = 1
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line("")
            reporter.write_line(
                "ERROR: these tests wrote into the checkout and are not on the "
                f"tolerated list: {offenders}", red=True)
            reporter.write_line(
                "Point them at an isolated workspace "
                "(monkeypatch.setenv('CLAWOCK_WORKSPACE', str(tmp_path))) rather "
                "than adding them to TOLERATED_WRITERS — that list is meant to "
                "shrink.", red=True)


def pytest_terminal_summary(terminalreporter):
    """Print the attribution table, so a polluted run explains itself.

    Reads the joined view for the same reason the verdict does: under `-n` the
    controller writes the summary but ran none of the tests, so its own log is
    empty and the table would come out blank on exactly the runs most likely to
    need it.
    """
    entries = [*_WRITE_LOG, *_WRITES_FROM_WORKERS]
    if not entries:
        return
    terminalreporter.section("tests that wrote to published state (#816)")
    for entry in entries:
        parts = []
        for kind in ("created", "removed", "changed"):
            if entry[kind]:
                shown = ", ".join(entry[kind][:4])
                more = f" (+{len(entry[kind]) - 4} more)" if len(entry[kind]) > 4 else ""
                parts.append(f"{kind}: {shown}{more}")
        # `<-- NEW` is an accusation, and under `-n` it lands on bystanders as
        # often as on writers. The table stays (it is an observation, and a
        # useful one); the verdict marker does not.
        mark = ("" if _tolerated(entry["test"]) or _WRITES_FROM_WORKERS
                else "  <-- NEW")
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


def _xdist_worker(config) -> str | None:
    """This worker's id under xdist, or None when running serially."""
    info = getattr(config, "workerinput", None)
    return info.get("workerid") if info else None


@pytest.fixture(scope="session")
def freshly_built_dashboard(request, publish_owned_artifacts_are_left_as_found):
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
    # Session-scoped means once per PROCESS, and under xdist every worker is its
    # own process — so `-n 4` would run four builders against these same four
    # files at once. They are not written atomically, and a reader in another
    # worker can see a half-built payload. A file lock makes the build happen
    # once per run and makes every other worker wait for it, which is both
    # correct and no slower than the serial case (#816).
    lock_path = Path(tempfile.gettempdir()) / "clawock-test-dashboard-build.lock"
    stamp = lock_path.with_suffix(".stamp")
    build_id = os.environ.get("PYTEST_XDIST_TESTRUNUID", str(os.getpid()))

    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            already = stamp.read_text(encoding="utf-8") if stamp.exists() else ""
            if already != build_id:
                # Run through the source tree explicitly; CI installs first, but a
                # focused local invocation should exercise the same package
                # without editable state.
                subprocess.run([sys.executable, "-m", "clawock.publish.dashboard"],
                               cwd=ROOT, check=True, capture_output=True,
                               env={**os.environ, "CLAWOCK_PROFILE": "kcnyu",
                                    "PYTHONPATH": str(ROOT / "src")})
                stamp.write_text(build_id, encoding="utf-8")
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    return DASHBOARD
