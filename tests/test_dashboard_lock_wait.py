"""A publisher tick holding the dashboard lock is not a failed build (#1904).

`rebuild_dashboard` used to wait for the lock inside the build's own 30s
timeout, so a slow publisher tick surfaced as `build_ok=false` →
`rebuild_failed` → postflight exit 2, with nothing wrong with the build.
"""
import fcntl
import json
import time

from clawock.harness import _harness_common as common


def _hold_lock(path):
    handle = open(path, "a+")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def test_a_lock_the_publisher_keeps_is_named_busy_not_a_failed_build(
        tmp_path, monkeypatch):
    lock = tmp_path / "dashboard_publish.lock"
    monkeypatch.setenv("CLAWOCK_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(common, "DASHBOARD_PUBLISH_LOCK", str(lock))
    monkeypatch.setattr(common, "DASHBOARD_LOCK_WAIT_SECONDS", 1)
    monkeypatch.setattr(common, "refresh_today_snapshot", lambda _ws: None)
    monkeypatch.setattr(common, "sync_gha_data_files", lambda _ws: None)

    holder = _hold_lock(lock)
    try:
        started = time.monotonic()
        ok, _ = common.rebuild_dashboard(tmp_path)
        waited = time.monotonic() - started
    finally:
        holder.close()

    status = json.loads((tmp_path / common.DASHBOARD_BUILD_STATUS).read_text())
    assert ok is False
    assert status["lock_busy"] is True and status["publish_ok"] is None
    assert common.dashboard_publication_state(tmp_path) == "lock_busy"
    # The wait is its own bound, not the build's timeout expiring under it.
    assert waited < common.DASHBOARD_BUILD_TIMEOUT_SECONDS


def test_an_old_status_without_the_field_still_reads_as_before(tmp_path):
    path = tmp_path / common.DASHBOARD_BUILD_STATUS
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"ok": False, "build_ok": False}))
    assert common.dashboard_publication_state(tmp_path) == "rebuild_failed"
