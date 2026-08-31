import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

from clawock.automation import workflow_outcomes as outcomes  # noqa: E402
from clawock.publish.outcomes import summarize_records  # noqa: E402


# Every write prunes the ledger against KEEP_HOURS, so a slot literal is only
# usable while it is inside that window: from 2026-07-28 these fixed 07-24
# slots were pruned between one record_stage call and the next, and each test
# read back a record holding only its own last stage. Freezing "now" beside the
# slots keeps the fixtures readable and makes the assertions time-independent —
# see clawock-no-live-numbers-in-static-copy.
FROZEN_NOW = datetime(2026, 7, 24, 23, 0, tzinfo=outcomes.HKT)


def _isolate(tmp_path, monkeypatch):
    # Isolate the WORKSPACE, not three individual paths. The ledger used to
    # freeze its paths at import from `Path.cwd()`, so patching the constants
    # was the only seam available — and any production caller that named a
    # different workspace was ignored, which is how #816's stray
    # `assets/data/workflow-outcomes.json` got written into the real checkout.
    # The paths resolve per call now, so `CLAWOCK_WORKSPACE` is the real seam.
    workspace = tmp_path / "ws"
    (workspace / "memory" / ".tmp").mkdir(parents=True, exist_ok=True)
    (workspace / "assets" / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLAWOCK_WORKSPACE", str(workspace))
    monkeypatch.setattr(
        outcomes,
        "_now",
        lambda at=None: (at or FROZEN_NOW)
        if (at or FROZEN_NOW).tzinfo
        else at.replace(tzinfo=timezone.utc),
    )
    return workspace


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


def test_preflight_failure_degrades_a_delivered_product(tmp_path, monkeypatch):
    # A failed preflight (e.g. unreadable context bundle) must never combine
    # with a successful primary delivery into a clean "success" verdict.
    _isolate(tmp_path, monkeypatch)
    slot = "2026-07-24T08:00:00+08:00"
    job = "盘前深度简报"

    outcomes.record_stage(job, "preflight", "failed", slot=slot,
                          reason="brief context 解析失败")
    outcomes.record_stage(job, "llm", "success", slot=slot)
    outcomes.record_stage(job, "postflight", "success", slot=slot)
    record = outcomes.record_stage(job, "primary_delivery", "success", slot=slot)

    assert record["final_product"]["status"] == "degraded"


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

    ledger = json.loads(outcomes.local_path().read_text())
    ledger["records"][0]["raw_execution"] = {"status": "error"}
    outcomes.local_path().write_text(json.dumps(ledger))
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


def test_heartbeat_bridge_maps_the_publish_failed_state_like_completed(
    tmp_path, monkeypatch
):
    """intraday_postflight emits state='publish_failed' when the sends landed
    but the data plane did not publish. That state used to fall through every
    bridge branch, so a slot kcn actually received kept no llm/postflight/
    primary evidence and its final_product stayed pending forever (#1005)."""
    _isolate(tmp_path, monkeypatch)
    outcomes.record_from_heartbeat(
        {
            "job": "美股盘中盯盘",
            "market": "us",
            "slot": "2026-07-24T22:00:00+08:00",
            "state": "publish_failed",
            "postflight_status": "pass",
            "data_plane_status": "committed_local",
            "wechat_sent": True,
            "telegram_sent": True,
        }
    )

    record = outcomes.load_ledger()["records"][0]
    assert record["stages"]["llm"]["status"] == "success"
    assert record["stages"]["postflight"]["status"] == "warning"
    assert record["stages"]["primary_delivery"]["status"] == "success"
    assert record["final_product"]["status"] == "degraded"


def test_a_send_claim_declined_process_never_files_the_primary_verdict(
    tmp_path, monkeypatch
):
    """A process claim_send refused is not a witness of the delivery: filing its
    wechat_sent=False as a verdict overwrote the concurrent claim holder's
    success whenever the declined process's slow commit work let it write last
    (#1006). Its llm/postflight evidence still counts; only the primary verdict
    is left to the process that actually sent."""
    _isolate(tmp_path, monkeypatch)
    outcomes.record_from_heartbeat(
        {
            "job": "美股盘中盯盘",
            "market": "us",
            "slot": "2026-07-24T22:00:00+08:00",
            "state": "completed",
            "postflight_status": "pass",
            "wechat_sent": False,
            "send_claim_declined": True,
        }
    )

    record = outcomes.load_ledger()["records"][0]
    assert record["stages"]["llm"]["status"] == "success"
    assert record["stages"]["primary_delivery"]["status"] == "unknown"


def test_a_declined_flag_does_not_suppress_a_confirmed_delivery(
    tmp_path, monkeypatch
):
    _isolate(tmp_path, monkeypatch)
    outcomes.record_from_heartbeat(
        {
            "job": "美股盘中盯盘",
            "market": "us",
            "slot": "2026-07-24T22:00:00+08:00",
            "state": "completed",
            "postflight_status": "pass",
            "wechat_sent": False,
            "telegram_sent": True,
            "send_claim_declined": True,
        }
    )

    record = outcomes.load_ledger()["records"][0]
    assert record["stages"]["primary_delivery"]["status"] == "success"
    assert record["stages"]["primary_delivery"]["channel"] == "telegram"


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

    from clawock.providers import openclaw

    run_at_ms = int(
        outcomes.datetime.fromisoformat(slot).timestamp() * 1000
    )

    monkeypatch.setattr(
        openclaw,
        "read_jobs",
        lambda _source: openclaw.CronRead(
            [{"id": "brief-id", "name": job}], "sqlite"
        ),
    )
    monkeypatch.setattr(
        openclaw,
        "read_runs",
        lambda _job_id, _source: openclaw.CronRead([{
                "runAtMs": run_at_ms,
                "ts": run_at_ms + 1000,
                "status": "error",
                "error": "private provider detail",
            }], "sqlite"),
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
    assert "private provider detail" not in outcomes.local_path().read_text()


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


# ── #763: the recorder's own failure path ────────────────────────────────────

def test_a_recorder_failure_warns_instead_of_breaking_the_caller(
    tmp_path, monkeypatch, capsys
):
    """record_stage promises it "never lets observability break a job".

    Until 2026-08-19 the module had no `import sys`, so both except handlers
    raised NameError and did the exact opposite: a bad argument took the calling
    postflight down with it. Mutation check: remove `import sys` and this test
    fails on the raised NameError, not on the assertion.
    """
    workspace = _isolate(tmp_path, monkeypatch)
    assert outcomes.record_stage("港股开盘报告", "llm", "not-a-real-status") == {}
    # stderr is where this used to end. It now also lands in the ledger, which
    # is the surface that publishes (#1214) — asserted on the row, because the
    # warning text is prose and the row is the contract.
    assert "stage_not_recorded" in capsys.readouterr().err
    rows = _degradations(workspace)
    assert [row["kind"] for row in rows] == ["stage_not_recorded"], rows
    assert "港股开盘报告/llm" in rows[0]["detail"]


def test_reconciliation_failure_also_only_warns(tmp_path, monkeypatch, capsys):
    ws = _isolate(tmp_path, monkeypatch)
    receipts = ws / "memory" / ".tmp"
    monkeypatch.setattr(
        outcomes, "load_ledger", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    (receipts / "brief-sent-2026-07-24.json").write_text(
        json.dumps({"sent_ok": True})
    )
    # Still broad, still non-fatal: `publish()` runs inside
    # `rebuild_dashboard`'s own try, so letting this raise would trade "a
    # receipt was not reconciled" for "the dashboard was not published" (#1214).
    assert outcomes.reconcile_delivery_receipts() == 0
    assert "delivery_reconcile_skipped" in capsys.readouterr().err
    rows = _degradations(ws)
    assert [row["kind"] for row in rows] == ["delivery_reconcile_skipped"], rows
    # The exception type is in the detail, so a defect reads as a defect
    # instead of as a quiet nothing.
    assert "RuntimeError" in rows[0]["detail"], rows[0]


# ── #764: advisory-only findings are not a degraded product ──────────────────

def _record_slot(job, slot, *, llm_status, **llm_details):
    outcomes.record_stage(job, "preflight", "success", slot=slot)
    outcomes.record_stage(job, "llm", llm_status, slot=slot, **llm_details)
    outcomes.record_stage(
        job, "postflight", "warning", slot=slot,
        data_plane_status="published", **llm_details,
    )
    return outcomes.record_stage(
        job, "primary_delivery", "success", slot=slot,
    )


def test_advisory_only_slot_is_not_filed_as_degraded(tmp_path, monkeypatch):
    """The delivered report carried no banner, so the ledger must not say degraded.

    validation.split_advisory guarantees an advisory-only finding never reaches
    the banner: the reader gets a clean report plus one non-blocking ℹ️ line.
    Filing that as "degraded generation/input" made the ledger contradict what
    was delivered on 21 of 64 slots over 2026-08-17..19.
    """
    _isolate(tmp_path, monkeypatch)
    record = _record_slot(
        "港股收盘报告", "2026-07-24T16:00:00+08:00",
        llm_status="warning", issue_count=1, escalating_count=0, advisory_count=1,
    )
    assert record["final_product"]["status"] == "success"
    # Detected, never silenced: the finding is still countable on the stage.
    assert record["stages"]["llm"]["advisory_count"] == 1
    assert record["stages"]["llm"]["status"] == "warning"


def test_an_escalating_finding_still_degrades_the_slot(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    record = _record_slot(
        "港股收盘报告", "2026-07-24T16:00:00+08:00",
        llm_status="warning", issue_count=2, escalating_count=1, advisory_count=1,
    )
    assert record["final_product"]["status"] == "degraded"


def test_a_writer_that_reports_no_split_keeps_the_conservative_reading(
    tmp_path, monkeypatch
):
    """No escalating_count means nobody audited it — stay degraded."""
    _isolate(tmp_path, monkeypatch)
    record = _record_slot(
        "港股收盘报告", "2026-07-24T16:00:00+08:00",
        llm_status="warning", issue_count=1,
    )
    assert record["final_product"]["status"] == "degraded"


def test_an_unpublished_data_plane_degrades_even_when_findings_are_advisory(
    tmp_path, monkeypatch
):
    """The advisory exemption is about findings, not about a failed publish."""
    _isolate(tmp_path, monkeypatch)
    slot = "2026-07-24T16:00:00+08:00"
    job = "港股收盘报告"
    outcomes.record_stage(job, "preflight", "success", slot=slot)
    outcomes.record_stage(
        job, "llm", "warning", slot=slot, escalating_count=0, advisory_count=1
    )
    outcomes.record_stage(
        job, "postflight", "warning", slot=slot,
        data_plane_status="stale", escalating_count=0, advisory_count=1,
    )
    record = outcomes.record_stage(job, "primary_delivery", "success", slot=slot)
    assert record["final_product"]["status"] == "degraded"


# ── #765: a delivered slot must not stay `pending` because the sender died ───

def _receipts(tmp_path, monkeypatch):
    """The isolated workspace's own receipt directory.

    Receipts have to sit where the ledger looks for them, and since #816 that
    is `<workspace>/memory/.tmp` resolved per call — not a path the test picks
    and patches in.
    """
    return _isolate(tmp_path, monkeypatch) / "memory" / ".tmp"


def test_a_receipt_reconciles_a_slot_whose_sender_was_killed_after_the_send(
    tmp_path, monkeypatch
):
    """2026-08-19 13:30: `exec` SIGTERM'd postflight 35s after WeChat had landed.

    The stages that prove delivery are written at the end of main(), after
    commit + dashboard + data-plane publish, so the ledger kept claiming
    `pending` for a report kcn had already received. The receipt written at send
    time is the durable evidence; reconciliation reads it.
    """
    _isolate(tmp_path, monkeypatch)
    tmp = _receipts(tmp_path, monkeypatch)
    slot = "2026-07-24T13:30:00+08:00"
    job = "港股午后快报"
    outcomes.record_stage(job, "preflight", "success", slot=slot)
    outcomes.record_stage(
        job, "llm", "warning", slot=slot, escalating_count=0, advisory_count=1
    )
    assert outcomes.load_ledger()["records"][0]["final_product"]["status"] == "pending"

    (tmp / "report-sent-hk-pm-2026-07-24.json").write_text(
        json.dumps({"sent_ok": True, "tg_ok": True, "market": "hk", "phase": "pm"})
    )
    assert outcomes.reconcile_delivery_receipts() == 1
    record = outcomes.load_ledger()["records"][0]
    assert record["stages"]["primary_delivery"]["status"] == "success"
    assert record["stages"]["primary_delivery"]["source"] == "delivery_receipt"
    # The receipt carries the per-channel facts (#968): the reconciled stage
    # must name them, not fold them back into "wechat_or_telegram".
    assert record["stages"]["primary_delivery"]["channel"] == "wechat+telegram"
    assert record["stages"]["primary_delivery"]["wechat_ok"] is True
    assert record["stages"]["primary_delivery"]["telegram_ok"] is True
    assert record["final_product"]["status"] == "success"


def test_reconciliation_records_a_failed_send_as_failed(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    tmp = _receipts(tmp_path, monkeypatch)
    slot = "2026-07-24T08:00:00+08:00"
    outcomes.record_stage("盘前深度简报", "preflight", "success", slot=slot)
    (tmp / "brief-sent-2026-07-24.json").write_text(
        json.dumps({"sent_ok": False, "tg_ok": False})
    )
    assert outcomes.reconcile_delivery_receipts() == 1
    record = outcomes.load_ledger()["records"][0]
    assert record["stages"]["primary_delivery"]["status"] == "failed"


def test_the_summary_names_the_slot_that_only_half_shipped(tmp_path, monkeypatch):
    """「1 档成品恢复或降级」答不出是哪一档（kcn 2026-08-25）。

    点名不能靠 ``recent`` —— 它是按时间截断的尾巴，忙日里 16 条全是盘中盯盘，
    当天唯一那次 recovered 早被挤出去了。全窗口扫一遍、单独出一张有上限的表，
    才是「哪一档」这个问题的答案。
    """
    from clawock.publish.outcomes import summarize_records

    now = datetime(2026, 7, 24, 20, 0, tzinfo=outcomes.HKT)
    records = [
        {"job": "港股收盘报告", "slot": "2026-07-24T16:00:00+08:00",
         "final_product": {"status": "recovered"}},
    ] + [
        # 16 条更晚的正常槽位：足够把上面那条挤出 recent 尾巴。
        {"job": "盘中盯盘", "slot": f"2026-07-24T17:{minute:02d}:00+08:00",
         "final_product": {"status": "success"}}
        for minute in range(0, 32, 2)
    ]

    summary = summarize_records(records, hours=36, now=now)

    assert all(row["job"] != "港股收盘报告" for row in summary["recent"]), (
        "fixture no longer exercises the case: the soft slot still fits in recent")
    assert summary["degraded_slots"] == [
        {"job": "港股收盘报告", "slot": "2026-07-24T16:00:00+08:00",
         "status": "recovered"},
    ]


def test_a_reconciled_wechat_drop_is_counted_by_the_summary(tmp_path, monkeypatch):
    """#771's count reads wechat_ok/telegram_ok flags. A reconciled slot whose
    receipt says WeChat failed and Telegram carried it must land in
    `wechat_dropped_telegram_covered`, not vanish behind a constant string."""
    from clawock.publish.outcomes import summarize_records

    _isolate(tmp_path, monkeypatch)
    tmp = _receipts(tmp_path, monkeypatch)
    slot = "2026-07-24T13:30:00+08:00"
    job = "港股午后快报"
    outcomes.record_stage(job, "preflight", "success", slot=slot)
    outcomes.record_stage(job, "llm", "success", slot=slot)
    (tmp / "report-sent-hk-pm-2026-07-24.json").write_text(
        json.dumps({"sent_ok": False, "tg_ok": True, "market": "hk", "phase": "pm"})
    )
    assert outcomes.reconcile_delivery_receipts() == 1
    summary = summarize_records(
        outcomes.load_ledger()["records"], hours=36,
        now=datetime(2026, 7, 24, 20, 0, tzinfo=outcomes.HKT),
    )
    assert summary["wechat_dropped_telegram_covered"] == 1
    # 数得出还要点得出：卡片逐项要写「掉的是哪一档、几点的」。
    assert summary["wechat_dropped_slots"] == [{"job": job, "slot": slot}]


def test_reconciliation_never_invents_a_slot_the_ledger_is_not_tracking(
    tmp_path, monkeypatch
):
    """A receipt is evidence about a tracked slot, not licence to create one."""
    _isolate(tmp_path, monkeypatch)
    tmp = _receipts(tmp_path, monkeypatch)
    (tmp / "report-sent-hk-close-2026-07-24.json").write_text(
        json.dumps({"sent_ok": True, "market": "hk", "phase": "close"})
    )
    assert outcomes.reconcile_delivery_receipts() == 0
    assert outcomes.load_ledger()["records"] == []


def test_reconciliation_never_overwrites_a_verdict_the_ledger_already_has(
    tmp_path, monkeypatch
):
    """A watchdog or a later run knows more than a receipt file does."""
    _isolate(tmp_path, monkeypatch)
    tmp = _receipts(tmp_path, monkeypatch)
    slot = "2026-07-24T13:30:00+08:00"
    job = "港股午后快报"
    outcomes.record_stage(job, "preflight", "success", slot=slot)
    outcomes.record_stage(job, "primary_delivery", "failed", slot=slot)
    (tmp / "report-sent-hk-pm-2026-07-24.json").write_text(
        json.dumps({"sent_ok": True, "market": "hk", "phase": "pm"})
    )
    assert outcomes.reconcile_delivery_receipts() == 0
    record = outcomes.load_ledger()["records"][0]
    assert record["stages"]["primary_delivery"]["status"] == "failed"


def test_no_receipt_means_the_slot_stays_pending(tmp_path, monkeypatch):
    """`pending` is the honest answer when nothing proves delivery."""
    _isolate(tmp_path, monkeypatch)
    _receipts(tmp_path, monkeypatch)
    slot = "2026-07-24T13:30:00+08:00"
    outcomes.record_stage("港股午后快报", "preflight", "success", slot=slot)
    assert outcomes.reconcile_delivery_receipts() == 0
    record = outcomes.load_ledger()["records"][0]
    assert record["final_product"]["status"] == "pending"


def test_an_intraday_receipt_reconciles_its_own_named_slot(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    tmp = _receipts(tmp_path, monkeypatch)
    slot = "2026-07-24T10:30:00+08:00"
    outcomes.record_stage("盘中盯盘", "preflight", "success", slot=slot)
    (tmp / "intraday-sent-hk.json").write_text(
        json.dumps({"sent_ok": True, "job": "盘中盯盘", "slot": slot})
    )
    assert outcomes.reconcile_delivery_receipts() == 1
    assert (
        outcomes.load_ledger()["records"][0]["stages"]["primary_delivery"]["status"]
        == "success"
    )


def test_falling_back_to_the_published_ledger_is_never_silent(
    tmp_path, monkeypatch, capsys
):
    """That fallback then writes PUBLIC's content back over LOCAL — say so."""
    _isolate(tmp_path, monkeypatch)
    outcomes.public_path().write_text(
        json.dumps({"schema_version": outcomes.SCHEMA_VERSION, "records": []})
    )
    outcomes.local_path().write_text("{ not json")
    ledger = outcomes.load_ledger()
    assert ledger["records"] == []
    assert "ledger_fallback_to_published" in capsys.readouterr().err
    # And in the ledger the caller is holding, so the note rides into whatever
    # that caller writes next rather than living only in a build log (#1214).
    assert [row["kind"] for row in ledger[outcomes.DEGRADATIONS_KEY]] == [
        "ledger_fallback_to_published"]


# ── #771: which channel actually carried the slot ────────────────────────────

def test_a_wechat_drop_covered_by_telegram_is_still_a_successful_product(
    tmp_path, monkeypatch
):
    """The backstop working is not a failure — that is the whole design."""
    _isolate(tmp_path, monkeypatch)
    slot = "2026-07-24T12:00:00+08:00"
    job = "港股午盘报告"
    outcomes.record_stage(job, "preflight", "success", slot=slot)
    outcomes.record_stage(
        job, "llm", "warning", slot=slot, escalating_count=0, advisory_count=1
    )
    record = outcomes.record_stage(
        job, "primary_delivery", "success", slot=slot,
        channel=outcomes.delivery_channel(False, True),
        wechat_ok=False, telegram_ok=True,
    )
    assert record["final_product"]["status"] == "success"
    # …but the drop is now on the record instead of only in a pruned receipt.
    assert record["stages"]["primary_delivery"]["channel"] == "telegram"
    assert record["stages"]["primary_delivery"]["wechat_ok"] is False


def test_delivery_channel_names_what_carried_it():
    assert outcomes.delivery_channel(True, True) == "wechat+telegram"
    assert outcomes.delivery_channel(True, False) == "wechat"
    assert outcomes.delivery_channel(False, True) == "telegram"
    assert outcomes.delivery_channel(False, False) == "none"


def test_intraday_heartbeats_record_the_channel_too(tmp_path, monkeypatch):
    """Intraday reaches the ledger through cron_heartbeat, not record_stage."""
    _isolate(tmp_path, monkeypatch)
    outcomes.record_from_heartbeat({
        "job": "盘中盯盘",
        "slot": "2026-07-24T10:30:00+08:00",
        "state": "completed",
        "postflight_status": "pass",
        "data_plane_status": "published",
        "wechat_sent": False,
        "telegram_sent": True,
    })
    delivery = outcomes.load_ledger()["records"][0]["stages"]["primary_delivery"]
    assert delivery["status"] == "success"
    assert delivery["channel"] == "telegram"
    assert delivery["wechat_ok"] is False


def test_wechat_drops_covered_by_telegram_are_counted():
    """A known, upstream-wontfix failure that nothing chased was also uncounted.

    2026-08-18..19 dropped 5 slots to `ret=-2 prepare failed`; Telegram covered
    every one, so no product was lost and no signal existed. Answering "how many
    this week" meant grepping receipts that are pruned within days (#771).
    """
    now = datetime(2026, 7, 24, 20, 0, tzinfo=outcomes.HKT)

    def slot(hour, wechat_ok, telegram_ok):
        return {
            "job": "盘中盯盘",
            "slot": f"2026-07-24T{hour:02d}:00:00+08:00",
            "stages": {"primary_delivery": {
                "status": "success",
                "wechat_ok": wechat_ok, "telegram_ok": telegram_ok,
            }},
            "final_product": {"status": "success"},
        }

    summary = summarize_records(
        [slot(10, False, True), slot(11, True, True), slot(12, False, True)],
        hours=36, now=now,
    )
    assert summary["wechat_dropped_telegram_covered"] == 2


def test_a_record_without_channel_flags_is_not_counted_as_a_drop():
    """An older record proves nothing either way — do not invent a failure."""
    now = datetime(2026, 7, 24, 20, 0, tzinfo=outcomes.HKT)
    summary = summarize_records([{
        "job": "盘中盯盘",
        "slot": "2026-07-24T10:00:00+08:00",
        "stages": {"primary_delivery": {
            "status": "success", "channel": "wechat_or_telegram",
        }},
        "final_product": {"status": "success"},
    }], hours=36, now=now)
    assert summary["wechat_dropped_telegram_covered"] == 0


# ── the observer failing to observe itself (#1214) ───────────────────────────

def _degradations(workspace):
    return json.loads(
        (workspace / "memory" / ".tmp" / "workflow-outcomes.json").read_text()
    ).get(outcomes.DEGRADATIONS_KEY) or []


def test_a_record_with_no_readable_slot_leaves_a_trace(tmp_path, monkeypatch):
    """It used to vanish, taking every stage it carried with it.

    `_prune` dropped the whole record on any timestamp it could not parse, so a
    postflight that wrote one malformed `slot` erased that slot's preflight,
    LLM, delivery and watchdog stages — and nothing anywhere said a record had
    been dropped.
    """
    workspace = _isolate(tmp_path, monkeypatch)
    outcomes.record_stage("brief", "preflight", "success",
                          slot="2026-07-24T08:00:00+08:00")

    ledger = json.loads(
        (workspace / "memory" / ".tmp" / "workflow-outcomes.json").read_text())
    ledger["records"].append({"job": "brief", "slot": "not-a-timestamp"})
    (workspace / "memory" / ".tmp" / "workflow-outcomes.json").write_text(
        json.dumps(ledger))

    outcomes.record_stage("brief", "llm", "success",
                          slot="2026-07-24T08:00:00+08:00")

    rows = _degradations(workspace)
    assert any(row["kind"] == "prune_dropped_unparseable_slot" for row in rows), (
        f'the dropped record left no trace; degradations={rows}')


def test_a_failed_reconcile_says_which_detector_it_disabled(tmp_path, monkeypatch):
    """A skipped raw-execution reconcile does not degrade false-red detection.

    It disables it: `publish.outcomes` needs `raw_execution.status == "error"`
    to call a red run false, and a skipped pass leaves that field at "unknown"
    forever. The skip is still non-fatal — it must not take the desk down — but
    it can no longer be silent.
    """
    workspace = _isolate(tmp_path, monkeypatch)
    outcomes.record_stage("brief", "preflight", "success",
                          slot="2026-07-24T08:00:00+08:00")

    def _boom(*_args, **_kwargs):
        raise OSError("cron runs unreadable")

    monkeypatch.setattr(outcomes, "load_ledger", _boom)
    assert outcomes.reconcile_raw_execution() is False
    monkeypatch.undo()

    rows = _degradations(workspace)
    kinds = [row["kind"] for row in rows]
    assert "raw_execution_reconcile_skipped" in kinds, kinds
    detail = next(row for row in rows
                  if row["kind"] == "raw_execution_reconcile_skipped")["detail"]
    assert "false-red" in detail, detail


def test_a_repeated_degradation_counts_rather_than_floods(tmp_path, monkeypatch):
    """Twenty identical rows would push the real ones out of the window."""
    workspace = _isolate(tmp_path, monkeypatch)
    ledger = outcomes._empty()
    for _ in range(5):
        outcomes.note_degradation(ledger, "kind_a", "same detail")
    outcomes.note_degradation(ledger, "kind_b", "other")
    rows = ledger[outcomes.DEGRADATIONS_KEY]
    assert [row["kind"] for row in rows] == ["kind_a", "kind_b"]
    assert rows[0]["count"] == 5
    assert rows[0]["first_at"] and rows[0]["last_at"]


def test_degradations_ride_into_the_published_copy(tmp_path, monkeypatch):
    """stderr reaches no gate; `logs/watchdog.jsonl` is not read either.

    `intraday_watchdog` already settled that: "a line in watchdog.jsonl is not
    something kcn reads, so treating it as surfaced would be exactly the silent
    downgrade that is forbidden here". The ledger is the surface that publishes.
    """
    workspace = _isolate(tmp_path, monkeypatch)
    outcomes.record_stage("brief", "preflight", "success",
                          slot="2026-07-24T08:00:00+08:00")
    outcomes.note_degradation(None, "heartbeat_bridge_failed", "brief/slot: boom")
    outcomes.publish()

    published = json.loads(
        (workspace / "assets" / "data" / "workflow-outcomes.json").read_text())
    kinds = [row["kind"] for row in published.get(outcomes.DEGRADATIONS_KEY) or []]
    assert "heartbeat_bridge_failed" in kinds, published


def test_a_defect_reads_as_a_defect_rather_than_as_a_quiet_nothing(
        tmp_path, monkeypatch):
    """Narrowing these handlers was tried and reverted; this is what replaced it.

    `publish()` runs inside `rebuild_dashboard`'s own try, so letting an
    unnamed exception out of here would trade "a receipt was not reconciled"
    for "the dashboard was not published" — a worse failure, and one this
    module exists not to cause. So it still returns 0. What it no longer does
    is return 0 indistinguishably from "nothing to reconcile": the exception
    type is in the ledger, and `RecursionError` is not a condition any I/O path
    produces.
    """
    workspace = _isolate(tmp_path, monkeypatch)
    # A receipt to reconcile, or the pass returns before it reaches the ledger
    # and the test would be asserting on a path it never took.
    (workspace / "memory" / ".tmp" / "brief-sent-2026-07-24.json").write_text(
        json.dumps({"sent_ok": True}))

    def _bug(*_args, **_kwargs):
        raise RecursionError("a defect, not a fault")

    monkeypatch.setattr(outcomes, "load_ledger", _bug)
    assert outcomes.reconcile_delivery_receipts() == 0
    monkeypatch.undo()

    rows = _degradations(workspace)
    assert [row["kind"] for row in rows] == ["delivery_reconcile_skipped"], rows
    assert "RecursionError" in rows[0]["detail"], rows[0]


def test_the_card_carries_the_faults_beside_the_counts_they_undermine(
        tmp_path, monkeypatch):
    """Otherwise the note has only moved from one place nobody reads to another.

    A reconcile that never ran and a reconcile with nothing to do produced the
    identical card. They still produce the same counts — that is the point of
    failing open — but the card now says which of the two it is.
    """
    from clawock.publish import outcomes as published

    workspace = _isolate(tmp_path, monkeypatch)
    outcomes.record_stage("brief", "preflight", "success",
                          slot="2026-07-24T08:00:00+08:00")
    outcomes.note_degradation(None, "delivery_reconcile_skipped",
                              "OSError: disk full")
    outcomes.publish()

    payload = json.loads(
        (workspace / "assets" / "data" / "workflow-outcomes.json").read_text())
    rows = published.degradations_of(payload)
    assert [row["kind"] for row in rows] == ["delivery_reconcile_skipped"], rows
    # And a clean ledger says nothing, so the field's presence is the signal.
    assert published.degradations_of({"records": []}) == []
