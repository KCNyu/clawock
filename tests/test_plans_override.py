"""User risk overrides stop the daily re-hang of the same cut (#552).

`clawock risk override <breach_id>` marks a breach as user-overridden. A user
who keeps adding to SPCH while the system re-hangs "SPCH cut 200" every slot is
not going to execute it — the plan context should stop carrying that risk_rule
cut while every other decision stays untouched.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from clawock.decision import plans


def _stamp_future(days=7):
    return (datetime.now(ZoneInfo("Asia/Hong_Kong")) + timedelta(days=days)
            ).isoformat()


def _write_ledger(path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")


def _open_row(ticker, action, driven_by="risk_rule"):
    return {
        "decision_id": f"dec-{ticker}-{action}",
        "plan_date": "2026-08-13",
        "ticker": ticker,
        "leg": "HK",
        "action": action,
        "driven_by": driven_by,
        "size": {"shares": 100},
        "condition": {"type": "open"},
        "execution": {"status": "unknown"},
        "evaluation": {"status": "pending"},
        "confidence": 0.8,
    }


def _write_breaches(path, rows):
    path.write_text(json.dumps({
        "schema_version": 1, "updated_at": "x", "records": rows,
    }))


def test_overridden_risk_tickers_reads_active_overrides(tmp_path):
    breaches = tmp_path / "risk_breaches.json"
    _write_breaches(breaches, [
        {"ticker": "SPCH", "status": "overridden", "override": {
            "status": "active", "reason": "无限子弹流",
            "created_at": "x", "expires_at": _stamp_future()}},
        {"ticker": "RKLX", "status": "open", "override": {}},
        {"ticker": "MSFU", "status": "overridden", "override": {
            "status": "active", "reason": "x", "expires_at": "2020-01-01T00:00:00"}},
    ])

    assert plans._overridden_risk_tickers(ledger_path=breaches) == {"SPCH"}


def test_open_decisions_context_drops_overridden_risk_cuts(tmp_path):
    ledger = tmp_path / "decisions.jsonl"
    _write_ledger(ledger, [
        _open_row("SPCH", "cut", "risk_rule"),
        _open_row("CRCL", "cut", "thesis"),
        _open_row("SPCH", "hold_and_watch", "technical"),
    ])
    breaches = tmp_path / "risk_breaches.json"
    _write_breaches(breaches, [
        {"ticker": "SPCH", "status": "overridden", "override": {
            "status": "active", "reason": "无限子弹流",
            "created_at": "x", "expires_at": _stamp_future()}},
    ])

    ctx = plans.open_decisions_context(
        leg="HK", today="2026-08-14", ledger=ledger, memory_dir=tmp_path,
    )

    assert ctx["overridden_by_user"] == ["SPCH"]
    open_rows = {row["decision_id"] for row in ctx["open"]}
    assert "dec-SPCH-cut" not in open_rows          # risk_rule cut dropped
    assert "dec-CRCL-cut" in open_rows              # thesis cut kept
    assert "dec-SPCH-hold_and_watch" in open_rows   # non-risk decision kept


def test_no_override_means_no_change(tmp_path):
    ledger = tmp_path / "decisions.jsonl"
    _write_ledger(ledger, [_open_row("SPCH", "cut", "risk_rule")])
    breaches = tmp_path / "risk_breaches.json"
    _write_breaches(breaches, [
        {"ticker": "SPCH", "status": "open", "override": {}},
    ])

    ctx = plans.open_decisions_context(
        leg="HK", today="2026-08-14", ledger=ledger, memory_dir=tmp_path,
    )

    assert "overridden_by_user" not in ctx
    assert "dec-SPCH-cut" in {row["decision_id"] for row in ctx["open"]}


def _active_override(breaches_path):
    _write_breaches(breaches_path, [
        {"ticker": "SPCH", "status": "overridden", "override": {
            "status": "active", "reason": "无限子弹流",
            "created_at": "x", "expires_at": _stamp_future()}},
    ])


def _ledger_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_override_settles_the_backlog_in_the_ledger(tmp_path):
    """#609: the read-side filter (#552) also settles — an overridden cut the
    user will not execute must not stay `unknown` forever, or the ledger
    accumulates one cut per morning and the unknown bucket grows without end."""
    ledger = tmp_path / "decisions.jsonl"
    _write_ledger(ledger, [
        _open_row("SPCH", "cut", "risk_rule"),
        _open_row("SPCH", "trim_on_rebound", "risk_rule"),
        _open_row("SPCH", "hold_and_watch", "technical"),
        _open_row("CRCL", "cut", "thesis"),
    ])
    breaches = tmp_path / "risk_breaches.json"
    _active_override(breaches)

    ctx = plans.open_decisions_context(
        leg="HK", today="2026-08-14", ledger=ledger, memory_dir=tmp_path)
    assert ctx["overridden_by_user"] == ["SPCH"]

    by_id = {r["decision_id"]: r for r in _ledger_rows(ledger)}
    assert by_id["dec-SPCH-cut"]["execution"]["status"] == "overridden_by_user"
    assert by_id["dec-SPCH-cut"]["execution"]["source"] == "risk_override"
    assert by_id["dec-SPCH-trim_on_rebound"]["execution"]["status"] == "overridden_by_user"
    # non-risk rows stay untouched
    assert by_id["dec-SPCH-hold_and_watch"]["execution"]["status"] == "unknown"
    assert by_id["dec-CRCL-cut"]["execution"]["status"] == "unknown"


def test_settled_rows_do_not_flood_back_after_override_expiry(tmp_path):
    """#609 TTL: once settled, an expired override has nothing to re-queue —
    the accumulated cut backlog cannot crowd out fresh decisions."""
    ledger = tmp_path / "decisions.jsonl"
    _write_ledger(ledger, [
        _open_row("SPCH", "cut", "risk_rule"),
        _open_row("CRCL", "cut", "thesis"),
    ])
    breaches = tmp_path / "risk_breaches.json"
    _active_override(breaches)

    # First pass: override active → dropped and settled.
    plans.open_decisions_context(
        leg="HK", today="2026-08-14", ledger=ledger, memory_dir=tmp_path)

    # Override TTL expires.
    _write_breaches(breaches, [
        {"ticker": "SPCH", "status": "overridden", "override": {
            "status": "expired", "reason": "无限子弹流",
            "created_at": "x", "expires_at": "2026-08-10T00:00:00"}},
    ])

    ctx = plans.open_decisions_context(
        leg="HK", today="2026-08-15", ledger=ledger, memory_dir=tmp_path)

    open_ids = {row["decision_id"] for row in ctx["open"]}
    assert "dec-SPCH-cut" not in open_ids  # settled earlier, no flood-back
    assert "dec-CRCL-cut" in open_ids      # the day's real open decision
    assert "overridden_by_user" not in ctx
