import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

import workflow_outcomes as outcomes  # noqa: E402


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(outcomes, "LOCAL_PATH", tmp_path / "local.json")
    monkeypatch.setattr(outcomes, "PUBLIC_PATH", tmp_path / "public.json")
    monkeypatch.setattr(outcomes, "LOCK_PATH", tmp_path / "outcomes.lock")


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


def test_dashboard_renderer_labels_raw_and_final_status_separately():
    renderer = (ROOT / "assets" / "js" / "dashboard.render.js").read_text()

    assert "执行=${raw} / 成品=${final}" in renderer
    assert "raw_error_but_product_usable" in renderer
