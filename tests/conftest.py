"""Session-level guarantees that belong to no single test module.

Right now there is one: the suite must not leave the publish-owned dashboard
artifacts rewritten.

`test_dashboard_payload_size.test_rebuild_is_idempotent_and_keeps_the_trim`
runs the real `build_dashboard.py` against the real tree, which is deliberate —
`test_validate_sidecars` then reconciles that fresh payload against
`portfolio.json`, and at any given commit the *tracked* dashboard.json is
older than the tracked portfolio.json (the publisher commits them on different
cadences), so a rebuild is what makes the money check meaningful. The rebuild
is load-bearing; only its residue is the problem.

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
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


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
    sys.path.insert(0, str(ROOT / "scripts" / "data"))
    from dashboard_outputs import DASHBOARD_OUTPUTS

    before = {path: (ROOT / path).read_bytes() for path in DASHBOARD_OUTPUTS
              if (ROOT / path).exists()}
    status_before = _git_status(DASHBOARD_OUTPUTS)

    yield

    for path, blob in before.items():
        (ROOT / path).write_bytes(blob)

    status_after = _git_status(DASHBOARD_OUTPUTS)
    if status_before is not None:
        assert status_after == status_before, (
            "the suite changed the publish-owned artifacts and the restore did "
            "not put them back; a later `git add -A` would carry them into a "
            f"code PR:\n{status_after}")
