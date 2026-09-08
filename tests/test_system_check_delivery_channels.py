"""A delivery leg can rot for days behind a working fallback (2026-09-06).

Every report co-sends to WeChat and Telegram and the slot counts as delivered
if either lands. That is the right design — WeChat cannot confirm a
cold-session drop, so gating on it would suppress real reports. The cost is
that **one leg can fail a third of the time and nothing says so**: postflight
prints to stderr, the watchdog correctly stays quiet because Telegram carried
the slot, and no gate or view ever adds the failures up.

Measured over the ledger's own four-day window on 2026-09-06: Telegram 98/100,
WeChat 67/100, WeChat trending 84% -> 76% -> 68% across three consecutive days,
zero alerts anywhere. Finding that took an ad-hoc script; that is the bug.

The check must NOT be a fix for the delivery mechanism (re-send, keepalive and
channel-switch have each been declined). It only makes the trend legible.

Channels are enumerated from the `*_ok` fields the ledger carries, so this stays
true when a third channel appears — a hardcoded (wechat, telegram) pair would
report a healthy system the day someone adds one.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def system_check():
    for path in (ROOT, ROOT / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(
        "kcnyu_system_check_delivery", ROOT / "ops" / "system_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ledger(tmp_path, slots):
    """Write a workflow-outcomes ledger holding exactly `slots`."""
    out = tmp_path / "assets" / "data"
    out.mkdir(parents=True, exist_ok=True)
    records = [
        {"job": "港股开盘报告", "slot": f"2026-09-0{1 + i // 8}T{9 + i % 8:02d}:30:00+08:00",
         "stages": {"primary_delivery": {"status": "success", **channels}}}
        for i, channels in enumerate(slots)
    ]
    (out / "workflow-outcomes.json").write_text(
        json.dumps({"schema_version": 1, "records": records}), encoding="utf-8")
    return tmp_path


def _run(system_check, monkeypatch, tmp_path, slots):
    _ledger(tmp_path, slots)
    monkeypatch.setenv("CLAWOCK_WORKSPACE", str(tmp_path))
    r = system_check.Result()
    system_check.check_delivery_channel_health(r)
    return [row for row in r.checks if row[0] == "delivery channels"]


def test_a_leg_failing_a_third_of_the_time_is_reported(
        system_check, monkeypatch, tmp_path):
    """The 2026-09-06 shape: Telegram perfect, WeChat two thirds."""
    slots = [{"wechat_ok": i % 3 != 0, "telegram_ok": True} for i in range(30)]
    rows = _run(system_check, monkeypatch, tmp_path, slots)
    assert rows, "a leg at 67% next to one at 100% must produce a row"
    _, status, detail = rows[0]
    assert status == system_check.WARNING, (
        "WARNING, not CRITICAL: a delivery statistic is not a reason to block a "
        "push, and check_model_chain_health set that precedent")
    assert "wechat" in detail
    assert "telegram" in detail, "say which leg is carrying it, not only which is rotting"


def test_two_healthy_legs_do_not_warn(system_check, monkeypatch, tmp_path):
    slots = [{"wechat_ok": True, "telegram_ok": True} for _ in range(30)]
    rows = _run(system_check, monkeypatch, tmp_path, slots)
    assert rows and rows[0][1] == system_check.OK
    assert "30/30" in rows[0][2], "the healthy row still has to carry the numbers"


def test_a_slot_nobody_received_outranks_a_degrading_leg(
        system_check, monkeypatch, tmp_path):
    """Every channel false = the report reached no human that slot."""
    slots = [{"wechat_ok": i % 3 != 0, "telegram_ok": True} for i in range(29)]
    slots.append({"wechat_ok": False, "telegram_ok": False})
    rows = _run(system_check, monkeypatch, tmp_path, slots)
    assert rows and rows[0][1] == system_check.WARNING
    assert "every channel failed" in rows[0][2], (
        "a slot with no delivery at all must not be summarised as a percentage — "
        "it is a different failure from a leg that is merely degrading")


def test_channels_come_from_the_ledger_not_from_a_hardcoded_pair(
        system_check, monkeypatch, tmp_path):
    """A third channel must be covered the day it starts writing its result."""
    slots = [{"wechat_ok": True, "telegram_ok": True, "signal_ok": i % 4 != 0}
             for i in range(32)]
    rows = _run(system_check, monkeypatch, tmp_path, slots)
    assert rows, "a new channel at 75% must be visible without touching this gate"
    assert "signal" in rows[0][2], (
        "the channel set is enumerated from the *_ok fields; hardcoding "
        "(wechat, telegram) would report this ledger as healthy")


def test_a_ledger_that_is_not_there_is_silent(system_check, monkeypatch, tmp_path):
    """Not every host publishes reports; absence is not a finding."""
    monkeypatch.setenv("CLAWOCK_WORKSPACE", str(tmp_path))
    r = system_check.Result()
    system_check.check_delivery_channel_health(r)
    assert not [row for row in r.checks if row[0] == "delivery channels"]


def test_a_channel_down_right_now_is_named_as_a_run_not_only_a_rate(
        system_check, monkeypatch, tmp_path):
    """2026-09-08: WeChat carried every slot to 13:33, then failed 14:00, 14:30,
    15:00 and 15:30 in a row on `ret=-2 prepare failed`.

    The 38-slot rate moved from 79% to 68% — the same drift a channel that drops
    one slot now and then produces. A rate is an average over the window; the
    question an operator has at 15:30 is whether the leg is there *now*.
    """
    slots = ([{"wechat_ok": True, "telegram_ok": True}] * 30
             + [{"wechat_ok": False, "telegram_ok": True,
                 "wechat_detail": "OutboundDeliveryError: sendMessage ret=-2 "
                                  "errmsg=prepare failed"}] * 4)
    rows = _run(system_check, monkeypatch, tmp_path, slots)

    assert len(rows) == 1
    _, level, message = rows[0]
    assert level == system_check.WARNING
    assert "last 4 consecutive slot(s)" in message
    # And it says why, because the record now carries the transport's reason.
    assert "ret=-2" in message


def test_a_run_is_reported_even_while_the_rate_still_reads_healthy(
        system_check, monkeypatch, tmp_path):
    """The rate is the last 38 slots; the run is the last two hours.

    A channel that has been perfect for weeks and died an hour ago sits well
    inside its healthy rate — which is exactly the moment somebody would want
    to be told.
    """
    slots = ([{"wechat_ok": True, "telegram_ok": True}] * 60
             + [{"wechat_ok": False, "telegram_ok": True}] * 3)
    rows = _run(system_check, monkeypatch, tmp_path, slots)

    assert len(rows) == 1
    _, level, message = rows[0]
    assert level == system_check.WARNING, 'a healthy rate must not hide a run'
    assert "last 3 consecutive slot(s)" in message


def test_the_same_rate_scattered_is_not_a_run(system_check, monkeypatch, tmp_path):
    """Same failure count, spread out: that is the case the rate already covers,
    and calling it an outage would make the run signal meaningless."""
    slots = [{"wechat_ok": i % 4 != 0, "telegram_ok": True} for i in range(32)]
    rows = _run(system_check, monkeypatch, tmp_path, slots)

    assert len(rows) == 1
    assert "consecutive" not in rows[0][2]
