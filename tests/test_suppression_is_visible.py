"""Detection must never degrade into silence.

Three separate ways the harness had learned to notice something and then not
say it, all fixed together because they are the same mistake:

* #134 — advisory findings shared the banner's truncated issue list, so the
  invented-number line was cut precisely on reports that already had two or
  three other findings;
* #135 — a failed intraday validation sent nothing at all, while the staged
  reports send the harness-owned data block behind a red banner. A market slot
  with no message is indistinguishable from a dead cron;
* #136 — `plan_surface` returned `{}` both when there were no open decisions and
  when reading them threw, so a failed read reads as a clean day. That is the
  #119 defect (a report contradicting the day's own discipline plan) coming back
  with no signal.

The tests assert on delivered output — prefix strings, the body handed to the
sender, the returned context — not on internal helpers, because the defect in
each case was that the internal state was right and nothing carried it out.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

from clawock import plan_surface
# The validation primitives come from the package, not through the harness
# module that used to re-export them (#267).
sys.path.insert(0, str(ROOT))
from clawock import validation as val  # noqa: E402


ADVISORY = f"07226 6200 股 未在 context 中 {val.ADVISORY_MARK}"
ADVISORY_2 = f"区间 +0.3~-0.4% 自相矛盾 {val.ADVISORY_MARK}"


# --------------------------------------------------------------------------
# #134 — advisory findings get their own line
# --------------------------------------------------------------------------


def test_advisory_only_report_is_not_dressed_as_a_warning():
    """It stays `warn` (delivered either way) but reads as information."""
    escalating, advisories = val.split_advisory([ADVISORY])
    assert escalating == []
    assert val.advisory_prefix(advisories).startswith("ℹ️ 数字校验（不影响投递）")
    assert "⚠️" not in val.advisory_prefix(advisories)


def test_advisory_survives_a_banner_full_of_other_issues():
    """The defect: `issues[:2]` dropped the advisory on exactly the bad reports."""
    issues = ["缺段标记 ▎技术面", "报告长度 3100 字 > 3000 软上限 (warn)", ADVISORY]
    escalating, advisories = val.split_advisory(issues)
    assert len(escalating) == 2
    prefix = val.advisory_prefix(advisories)
    assert "07226 6200 股" in prefix


def test_advisory_line_bounds_itself():
    many = [f"{i} 股 未在 context 中 {val.ADVISORY_MARK}" for i in range(5)]
    prefix = val.advisory_prefix(many)
    assert "另 3 条" in prefix
    assert prefix.count(";") <= 2


def test_no_advisory_means_no_line():
    assert val.advisory_prefix([]) == ""
    assert val.split_advisory(["缺段标记 ▎技术面"]) == (["缺段标记 ▎技术面"], [])


def test_the_advisory_mark_is_not_shown_to_the_reader():
    """`(advisory)` is a routing token for categorize_issues, not prose."""
    assert val.ADVISORY_MARK not in val.advisory_prefix([ADVISORY])


def test_advisory_still_cannot_change_the_verdict():
    """The #123 guarantee, re-asserted here because this PR touches its callers."""
    assert val.categorize_issues([ADVISORY], ("必须",), warn_max=2) == "warn"
    two_warnings = ["a", "b"]
    assert val.categorize_issues(two_warnings, ("必须",), warn_max=2) == "warn"
    assert val.categorize_issues(two_warnings + [ADVISORY, ADVISORY_2],
                                ("必须",), warn_max=2) == "warn"


# --------------------------------------------------------------------------
# #135 — a rejected intraday report still delivers the data block
# --------------------------------------------------------------------------


@pytest.fixture
def postflight():
    return pytest.importorskip("intraday_postflight")


def test_marker_records_whether_the_prose_actually_landed(postflight):
    ctx = {"heartbeat": {"job": "盘中盯盘", "slot": "2026-07-27T14:00:00+08:00"}}
    delivered = postflight.delivery_marker_payload(
        ctx, ts=1, sent_ok=True, tg_ok=True, first_line="x", market="hk", out="")
    failed = postflight.delivery_marker_payload(
        ctx, ts=1, sent_ok=True, tg_ok=True, first_line="x", market="hk", out="",
        delivery_state="failed")
    assert delivered["delivery_state"] == "delivered"
    assert failed["delivery_state"] == "failed"
    # Both are real sends: the watchdog must not re-send either.
    assert failed["sent_ok"] is True


def test_failed_validation_sends_the_data_block_and_not_the_prose(postflight, tmp_path,
                                                                 monkeypatch):
    sent = _run_postflight(postflight, tmp_path, monkeypatch,
                           prose="这份散文缺了必需的段标记", issues_status="fail")
    assert sent, "a failed intraday validation must still deliver something"
    body = sent[0]
    assert "▎恒生科技" in body, "the harness-owned data block must be delivered"
    assert "这份散文缺了必需的段标记" not in body, "the rejected prose must be dropped"
    assert body.startswith("🔴")


def test_passing_validation_still_sends_the_prose(postflight, tmp_path, monkeypatch):
    sent = _run_postflight(postflight, tmp_path, monkeypatch,
                           prose="▎盘中观察\n▎我的看法\n一切正常", issues_status="pass")
    assert sent and "一切正常" in sent[0]


def _run_postflight(module, tmp_path, monkeypatch, *, prose, issues_status):
    """Drive main() with delivery and publishing stubbed, return sent messages."""
    sent = []
    monkeypatch.setattr(module, "TMP", tmp_path)
    monkeypatch.setattr(module, "resolve_wechat_target", lambda m: ("c", "t", "a"))
    monkeypatch.setattr(module, "send_wechat",
                        lambda c, t, a, message, dry_run: (sent.append(message), (True, "ok"))[1])
    monkeypatch.setattr(module, "cosend_telegram", lambda message, tag: (True, "ok"))
    monkeypatch.setattr(module, "already_delivered", lambda *a, **k: False)
    monkeypatch.setattr(module.trading_calendar, "closed_reason", lambda m: None)
    monkeypatch.setattr(module, "rebuild_dashboard", lambda: (False, ""))
    monkeypatch.setattr(module.cron_heartbeat, "record", lambda *a, **k: {})

    ctx = {
        "status": "ok",
        "market": "hk",
        "raw_wechat_block": "▎恒生科技 5,432.10 (+0.35%)\n00100 225.4 +15.51%",
        "anomalies": [],
        "should_alert": False,
        "heartbeat": {"job": "盘中盯盘", "slot": "2026-07-27T14:00:00+08:00"},
        "generated_at": "2026-07-27T06:00:00+00:00",
    }
    (tmp_path / "intraday-context-hk-latest.json").write_text(
        json.dumps(ctx, ensure_ascii=False))
    monkeypatch.setattr(module, "load_context", lambda market: (ctx, None))
    monkeypatch.setattr(module, "read_report_text", lambda market, f: (prose, None))
    monkeypatch.setattr(module, "validate",
                        lambda text, c, **kw: [] if issues_status == "pass" else ["缺段标记 ▎我的看法"])
    monkeypatch.setattr(module, "categorize", lambda issues: issues_status)
    monkeypatch.setattr(sys, "argv", ["intraday_postflight.py", "--market", "hk"])
    module.main()
    return sent


# --------------------------------------------------------------------------
# #136 — "could not read it" is a value, not silence
# --------------------------------------------------------------------------


def test_a_broken_plan_read_is_reported_as_an_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("decisions.jsonl unreadable")

    monkeypatch.setattr(plan_surface, "_load_ledger", boom)
    ctx = plan_surface.open_decisions_context(leg="HK")
    assert ctx.get("error"), "a failed read must not look like a clean day"
    assert "unreadable" in ctx["error"]


def test_a_genuinely_empty_plan_stays_empty(tmp_path):
    """The other half of the contract: no false alarm on a quiet day."""
    ledger = tmp_path / "decisions.jsonl"
    ledger.write_text("")
    ctx = plan_surface.open_decisions_context(leg="HK", ledger=ledger,
                                              memory_dir=tmp_path)
    assert ctx == {}


def test_the_skill_tells_the_model_what_an_error_means():
    """A context field nothing reads is the same as no field at all."""
    for skill in ("hk-stock-analysis", "us-stock-analysis"):
        body = (ROOT / "skills" / skill / "SKILL.md").read_text()
        assert "`error` 字段" in body
        assert "今日计划未取到" in body
