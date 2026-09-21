"""An intraday claim belongs to one slot, and only that slot may read it.

2026-09-21 (#1742). `intraday-send-{market}.claim` carried no slot and no date,
so every 30-minute slot in a day used the same file. A postflight that died
mid-send left it behind with `send_started_at`, and the NEXT slot's watchdog
read it as its own sender dying mid-send:

    10:03  slot N   postflight marks send started, then dies
    10:33  slot N+1 postflight never runs at all
    10:43  slot N+1 watchdog reads the 10:20 claim — 23 min old, inside the
                    25-minute marker window — and announces
                    「⚠️ 该槽位 WeChat 送达未被确认」 for a send that never started

The age bound is the mitigation #1685 added; it cannot separate the two claims,
only rule out old ones, and the slots are closer together than the window.

Both halves are pinned here: the false alert must stop, and the real one must
not. A claim from an earlier slot proves nothing about this slot; a claim from
this slot still proves everything it used to.
"""
from datetime import datetime, timedelta, timezone

import json

import pytest

HKT = timezone(timedelta(hours=8))
SLOT_N = "2026-09-21T10:03:00+08:00"
SLOT_N1 = "2026-09-21T10:33:00+08:00"


def _claim(tmp_path, market, slot, *, started_at):
    """Write a claim the way a postflight that reached `mark_send_started` would."""
    from clawock.automation import delivery_receipts

    path = delivery_receipts.claim_path(tmp_path, "intraday", market=market, slot=slot)
    path.write_text(json.dumps(
        {"pid": 999999, "ts": started_at, "send_started_at": started_at}))
    return path


def _ms(hour, minute):
    return int(datetime(2026, 9, 21, hour, minute, tzinfo=HKT).timestamp() * 1000)


def test_the_previous_slots_dead_sender_is_not_this_slots_claim(tmp_path):
    """The reported incident, as the watchdog sees it."""
    from clawock.harness.intraday_watchdog import this_slots_claim

    _claim(tmp_path, "hk", SLOT_N, started_at=_ms(10, 20))

    assert this_slots_claim(tmp_path, "hk", SLOT_N1) is None


def test_this_slots_dead_sender_is_still_found(tmp_path):
    """The direction that must not break: a real mid-send death still reports.

    Naming the claim per slot would be worth nothing if it also hid the case
    the reason exists for.
    """
    from clawock.harness.intraday_watchdog import this_slots_claim

    _claim(tmp_path, "hk", SLOT_N1, started_at=_ms(10, 40))

    found = this_slots_claim(tmp_path, "hk", SLOT_N1)
    assert found and found["send_started_at"] == _ms(10, 40)


def test_the_other_market_is_still_a_different_claim(tmp_path):
    from clawock.harness.intraday_watchdog import this_slots_claim

    _claim(tmp_path, "us", SLOT_N1, started_at=_ms(10, 40))

    assert this_slots_claim(tmp_path, "hk", SLOT_N1) is None


def test_a_slotless_claim_is_still_read_so_a_real_death_is_never_missed(tmp_path):
    """A postflight that could not resolve its slot writes the old name.

    Ignoring it would trade a false alert for a silent one, which is the wrong
    direction for this whole subsystem (`feedback-detect-but-never-silence`).
    It keeps the age bound it always had — that is what the watchdog applies to
    whatever this returns.
    """
    from clawock.automation import delivery_receipts
    from clawock.harness.intraday_watchdog import this_slots_claim

    legacy = delivery_receipts.claim_path(tmp_path, "intraday", market="hk")
    assert legacy.name == "intraday-send-hk.claim"
    legacy.write_text(json.dumps({"pid": 1, "ts": _ms(10, 40),
                                  "send_started_at": _ms(10, 40)}))

    found = this_slots_claim(tmp_path, "hk", SLOT_N1)
    assert found and found["send_started_at"] == _ms(10, 40)


def test_this_slots_claim_wins_over_a_slotless_one(tmp_path):
    """Both present: the specific file is the answer, not whichever is read first."""
    from clawock.automation import delivery_receipts
    from clawock.harness.intraday_watchdog import this_slots_claim

    delivery_receipts.claim_path(tmp_path, "intraday", market="hk").write_text(
        json.dumps({"pid": 1, "ts": _ms(9, 0), "send_started_at": _ms(9, 0)}))
    _claim(tmp_path, "hk", SLOT_N1, started_at=_ms(10, 40))

    found = this_slots_claim(tmp_path, "hk", SLOT_N1)
    assert found["send_started_at"] == _ms(10, 40)


def test_no_claim_at_all_stays_no_claim(tmp_path):
    from clawock.harness.intraday_watchdog import this_slots_claim

    assert this_slots_claim(tmp_path, "hk", SLOT_N1) is None


@pytest.mark.parametrize("started, expected_gap", [
    (_ms(10, 40), True),    # this slot, in flight three minutes ago
    (_ms(9, 50), False),    # older than one marker window — the #1685 bound
])
def test_the_age_bound_from_1685_still_applies_to_what_we_hand_it(started, expected_gap):
    """Slot identity is a second line, not a replacement.

    #1685 added the age bound because the claim could not be told apart by
    name. The name tells them apart now, and the bound stays: the fall-back
    name is still slot-less, and a stale claim proves nothing either way.
    """
    from clawock.harness._watchdog_common import wechat_gap_reason
    from clawock.harness.intraday_watchdog import MARKER_FRESH_MS

    gap = wechat_gap_reason({"send_started_at": started},
                            fresh_ms=MARKER_FRESH_MS, now_ms=_ms(10, 43))
    assert bool(gap) is expected_gap
