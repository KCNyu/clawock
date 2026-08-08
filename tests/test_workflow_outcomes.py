import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

import workflow_outcomes as outcomes  # noqa: E402


# Every write prunes the ledger against KEEP_HOURS, so a slot literal is only
# usable while it is inside that window: from 2026-07-28 these fixed 07-24
# slots were pruned between one record_stage call and the next, and each test
# read back a record holding only its own last stage. Freezing "now" beside the
# slots keeps the fixtures readable and makes the assertions time-independent —
# see clawock-no-live-numbers-in-static-copy.
FROZEN_NOW = datetime(2026, 7, 24, 23, 0, tzinfo=outcomes.HKT)


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(outcomes, "LOCAL_PATH", tmp_path / "local.json")
    monkeypatch.setattr(outcomes, "PUBLIC_PATH", tmp_path / "public.json")
    monkeypatch.setattr(outcomes, "LOCK_PATH", tmp_path / "outcomes.lock")
    monkeypatch.setattr(
        outcomes,
        "_now",
        lambda at=None: (at or FROZEN_NOW)
        if (at or FROZEN_NOW).tzinfo
        else at.replace(tzinfo=timezone.utc),
    )


def test_stages_remain_independent_and_primary_delivery_can_be_degraded(
    tmp_path, monkeypatch
):
    _isolate(tmp_path, monkeypatch)
    slot = "2026-07-24T09:30:00+08:00"
    job = "港股开盘报告"

    outcomes.record_stage(job, "preflight", "success", slot=slot)
    outcomes.record_stage(job, "llm", "warning", slot=slot, reason="peer fetch")
    outcomes.record_stage(job, "postflight", "success", slot=slot)
    record = outcomes.record_stage(job, "primary_delivery", "success", slot=slot)

    assert record["final_product"]["status"] == "degraded"
    assert record["stages"]["preflight"]["status"] == "success"
    assert record["stages"]["llm"]["reason"] == "peer fetch"
    assert record["stages"]["watchdog_delivery"]["status"] == "unknown"


def test_readability_advisory_detail_does_not_degrade_a_delivered_product(
    tmp_path, monkeypatch
):
    _isolate(tmp_path, monkeypatch)
    slot = "2026-07-24T08:00:00+08:00"
    job = "盘前深度简报"
    readability = {
        "status": "advisory", "bytes": 29_109,
        "target_bytes": 28_000, "extreme_bytes": 40_000,
        "over_by_bytes": 1_109,
    }

    outcomes.record_stage(job, "preflight", "success", slot=slot)
    outcomes.record_stage(
        job, "llm", "success", slot=slot, readability=readability)
    outcomes.record_stage(
        job, "postflight", "success", slot=slot, readability=readability)
    record = outcomes.record_stage(
        job, "primary_delivery", "success", slot=slot)

    assert record["final_product"]["status"] == "success"
    assert record["stages"]["postflight"]["readability"] == readability
    assert outcomes.summarize(hours=100000)["counts"] == {"success": 1}


def test_watchdog_recovery_does_not_erase_failed_primary_delivery(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    slot = "2026-07-24T10:00:00+08:00"
    job = "盘中盯盘"

    outcomes.record_stage(job, "preflight", "success", slot=slot)
    outcomes.record_stage(job, "llm", "success", slot=slot)
    outcomes.record_stage(job, "postflight", "failed", slot=slot)
    outcomes.record_stage(job, "primary_delivery", "failed", slot=slot)
    record = outcomes.record_stage(job, "watchdog_delivery", "success", slot=slot)

    assert record["final_product"]["status"] == "recovered"
    assert record["stages"]["postflight"]["status"] == "failed"
    assert record["stages"]["primary_delivery"]["status"] == "failed"


def test_raw_error_is_reported_beside_usable_final_product(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    slot = "2026-07-24T08:00:00+08:00"
    job = "盘前深度简报"
    outcomes.record_stage(job, "preflight", "success", slot=slot)
    outcomes.record_stage(job, "llm", "success", slot=slot)
    outcomes.record_stage(job, "postflight", "success", slot=slot)
    outcomes.record_stage(job, "primary_delivery", "success", slot=slot)

    ledger = json.loads(outcomes.LOCAL_PATH.read_text())
    ledger["records"][0]["raw_execution"] = {"status": "error"}
    outcomes.LOCAL_PATH.write_text(json.dumps(ledger))
    summary = outcomes.summarize(hours=100000)

    assert summary["counts"] == {"success": 1}
    assert summary["raw_error_but_product_usable"] == 1
    record = summary["recent"][0]
    assert record["raw_execution"]["status"] == "error"
    assert record["final_product"]["status"] == "success"


def test_heartbeat_bridge_maps_completed_and_watchdog_to_separate_stages(
    tmp_path, monkeypatch
):
    _isolate(tmp_path, monkeypatch)
    event = {
        "job": "美股盘中盯盘",
        "market": "us",
        "slot": "2026-07-24T22:00:00+08:00",
        "state": "completed",
        "postflight_status": "pass",
        "wechat_sent": False,
        "telegram_sent": True,
    }
    outcomes.record_from_heartbeat(event)
    outcomes.record_from_heartbeat(
        {
            "job": event["job"],
            "slot": event["slot"],
            "state": "watchdog_backstop",
            "telegram_sent": True,
        }
    )

    record = outcomes.load_ledger()["records"][0]
    assert record["stages"]["postflight"]["status"] == "success"
    assert record["stages"]["primary_delivery"]["status"] == "success"
    assert record["stages"]["watchdog_delivery"]["status"] == "success"
    assert record["final_product"]["status"] == "recovered"


def test_heartbeat_bridge_preserves_data_only_fallback_as_degraded(
    tmp_path, monkeypatch
):
    _isolate(tmp_path, monkeypatch)
    outcomes.record_from_heartbeat(
        {
            "job": "美股盘中盯盘",
            "market": "us",
            "slot": "2026-07-24T22:00:00+08:00",
            "state": "completed",
            "postflight_status": "fail",
            "data_plane_status": "published",
            "wechat_sent": True,
            "telegram_sent": True,
        }
    )

    record = outcomes.load_ledger()["records"][0]
    assert record["stages"]["llm"]["status"] == "failed"
    assert record["stages"]["postflight"]["status"] == "warning"
    assert record["stages"]["primary_delivery"]["status"] == "success"
    assert record["final_product"]["status"] == "degraded"


def test_heartbeat_bridge_marks_data_publish_failure_as_postflight_warning(
    tmp_path, monkeypatch
):
    _isolate(tmp_path, monkeypatch)
    outcomes.record_from_heartbeat(
        {
            "job": "美股盘中盯盘",
            "slot": "2026-07-24T22:00:00+08:00",
            "state": "completed",
            "postflight_status": "pass",
            "data_plane_status": "rebuild_failed",
            "wechat_sent": True,
        }
    )

    record = outcomes.load_ledger()["records"][0]
    assert record["stages"]["llm"]["status"] == "success"
    assert record["stages"]["postflight"]["status"] == "warning"
    assert record["final_product"]["status"] == "degraded"


def test_market_closed_is_a_skipped_product_not_a_failure(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    record = outcomes.record_stage(
        "港股收盘报告",
        "preflight",
        "skipped",
        slot="2026-07-24T16:00:00+08:00",
        reason="holiday",
    )

    assert record["final_product"]["status"] == "skipped"


def test_reconcile_adds_raw_error_without_changing_final_product(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    slot = "2026-07-24T08:00:00+08:00"
    job = "盘前深度简报"
    for stage in ("preflight", "llm", "postflight", "primary_delivery"):
        outcomes.record_stage(job, stage, "success", slot=slot)

    sys.path.insert(0, str(ROOT / "scripts" / "harness"))
    import _watchdog_common as common

    run_at_ms = int(
        outcomes.datetime.fromisoformat(slot).timestamp() * 1000
    )

    def load_jobs(_source):
        common.LAST_LOAD_SOURCE = "sqlite"
        return [{"id": "brief-id", "name": job}]

    monkeypatch.setattr(common, "load_jobs", load_jobs)
    monkeypatch.setattr(
        common,
        "read_runs",
        lambda _job_id, _source: [{
            "runAtMs": run_at_ms,
            "ts": run_at_ms + 1000,
            "status": "error",
            "error": "private provider detail",
        }],
    )

    assert outcomes.reconcile_raw_execution() is True
    record = outcomes.load_ledger()["records"][0]
    assert record["raw_execution"] == {
        "status": "error",
        "run_at_ms": run_at_ms,
        "finished_at_ms": run_at_ms + 1000,
        "run_id": None,
        "error_present": True,
    }
    assert record["final_product"]["status"] == "success"
    assert "private provider detail" not in outcomes.LOCAL_PATH.read_text()


def test_slots_older_than_the_retention_window_are_pruned(tmp_path, monkeypatch):
    """The behaviour the frozen clock above exists to keep out of the way.

    Pruning on write is what bounds the ledger; it is also what silently ate
    the stage history of any test whose slot drifted past KEEP_HOURS. Both
    offsets are derived from KEEP_HOURS deliberately: the claim under test is
    that a write prunes at all, not that the window is 96 hours, so retuning
    the window must not turn this red.
    """
    _isolate(tmp_path, monkeypatch)
    fresh = (FROZEN_NOW - timedelta(hours=2)).isoformat()
    expired = (FROZEN_NOW - timedelta(hours=outcomes.KEEP_HOURS + 2)).isoformat()

    outcomes.record_stage("盘前深度简报", "preflight", "success", slot=expired)
    outcomes.record_stage("盘中盯盘", "preflight", "success", slot=fresh)

    slots = [record["slot"] for record in outcomes.load_ledger()["records"]]
    assert slots == [fresh]


def test_dashboard_renderer_labels_raw_and_final_status_separately():
    renderer = (ROOT / "site" / "assets" / "js" / "dashboard.render.js").read_text()

    assert "执行=${raw} / 成品=${final}" in renderer
    assert "可读性=${readability.status}" in renderer
    assert "raw_error_but_product_usable" in renderer
