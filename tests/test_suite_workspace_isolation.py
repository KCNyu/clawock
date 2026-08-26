"""The suite may only ever write the checkout it is running from (#1063).

`CLAWOCK_WORKSPACE` is exported permanently on the host that runs this
repository, so `pytest` started in a worktree used to resolve the harness
constants — `WS`, and the `LEDGER` default argument bound at definition time —
to the LIVE workspace. A fixture decision written by
`test_postflight_entry_price_source.py` during an iteration landed in the live
`memory/decisions.jsonl`, was settled against real bars by the next brief,
committed to master by the daily memory commit, and reddened CI a day later.

`tests/conftest.py` drops the variable at import time, so a local run has the
same shape as CI. These tests assert it from both ends: the constants really do
resolve inside the checkout, and a hostile value handed to a fresh child
process does not survive the conftest import.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_harness_constants_resolve_inside_this_checkout():
    """The in-process half: what every real suite run must already be true of."""
    from clawock.decision import ledger
    from clawock.harness import brief_postflight

    # The ledger path reaches load/upsert/write as a definition-time default,
    # which is the seam that leaked: assert the bound default, not just the
    # module constant a later patch could shadow.
    bound = ledger.load_decisions.__defaults__[0]
    for path in (ledger.LEDGER, bound, brief_postflight.WS):
        assert ROOT in Path(path).resolve().parents or Path(path).resolve() == ROOT, (
            f"{path} resolves outside the checkout under test ({ROOT})")

    assert "CLAWOCK_WORKSPACE" not in os.environ, (
        "a CLAWOCK_WORKSPACE override survived into the test process; the "
        f"suite must run in the unset shape CI has, got {os.environ.get('CLAWOCK_WORKSPACE')}")


def test_a_foreign_workspace_does_not_survive_conftest_import(tmp_path):
    """The regression itself, in a fresh process handed the live-workspace hazard.

    Importing `tests/conftest.py` is what pytest does before it imports any test
    module, and the drop happens at exactly that moment — so a plain child
    interpreter proves the seam without starting a second pytest session (which
    would rewrite the four publish-owned artifacts through its own session
    fixture and register this test as a new writer of published state).

    Without the drop the child resolves the ledger to
    `<hostile>/memory/decisions.jsonl` — which is precisely what a real run
    against /root/.openclaw/workspace did silently, because nothing asserted it.
    """
    hostile = tmp_path / "another-workspace"
    (hostile / "memory").mkdir(parents=True)
    program = (
        "import os, sys, json\n"
        "sys.path.insert(0, 'tests')\n"
        "import conftest\n"
        "from clawock.decision import ledger\n"
        "from clawock.harness import brief_postflight\n"
        "print(json.dumps({\n"
        "    'env': os.environ.get('CLAWOCK_WORKSPACE'),\n"
        "    'ledger': str(ledger.LEDGER),\n"
        "    'bound': str(ledger.load_decisions.__defaults__[0]),\n"
        "    'ws': str(brief_postflight.WS),\n"
        "}))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", program], cwd=ROOT, capture_output=True, text=True,
        env=dict(os.environ, CLAWOCK_WORKSPACE=str(hostile)),
    )
    assert done.returncode == 0, done.stderr[-2000:]
    seen = json.loads(done.stdout.strip().splitlines()[-1])

    assert seen["env"] is None, (
        f"the hostile CLAWOCK_WORKSPACE survived conftest import: {seen['env']}")
    for key in ("ledger", "bound", "ws"):
        assert str(hostile) not in seen[key], (
            f"{key} resolved into the hostile workspace: {seen[key]}")
        assert seen[key].startswith(str(ROOT)), (
            f"{key} resolved outside the checkout under test: {seen[key]}")
    assert "dropped CLAWOCK_WORKSPACE" in done.stderr, (
        "the child never reported the override, so the assertions above may be "
        "passing for some other reason")
    # And nothing may have been created in the workspace the hazard pointed at.
    assert sorted(p.name for p in hostile.rglob("*")) == ["memory"]
