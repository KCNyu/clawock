"""One definition of where a send is filed, what a receipt says, which channels go.

Seven modules used to spell the receipt names and fold `sent_ok`/`tg_ok` their own
way (2026-09-12 architecture pass). They share `delivery_receipts` now; the last test
keeps it that way.
"""
import json
import re
from pathlib import Path

import pytest

from clawock.automation import delivery_receipts as receipts
from clawock.harness import _watchdog_common as common

ROOT = Path(__file__).resolve().parents[1]


def test_the_names_are_the_ones_every_existing_receipt_already_has():
    assert receipts.receipt_name("brief", date="2026-09-11") == "brief-sent-2026-09-11.json"
    assert (receipts.receipt_name("report", market="hk", phase="open", date="2026-09-11")
            == "report-sent-hk-open-2026-09-11.json")
    assert receipts.receipt_name("intraday", market="us") == "intraday-sent-us.json"
    assert receipts.claim_name("brief", date="2026-09-11") == "brief-send-2026-09-11.claim"
    assert (receipts.claim_name("report", market="us", phase="close", date="2026-09-11")
            == "report-send-us-close-2026-09-11.claim")
    assert receipts.claim_name("intraday", market="hk") == "intraday-send-hk.claim"
    with pytest.raises(ValueError):
        receipts.receipt_name("weekly", date="x")


def test_parsing_round_trips_every_kind():
    assert receipts.parse_receipt_name("report-sent-hk-open-2026-09-11.json") == (
        "report", ["hk", "open", "2026", "09", "11"])
    assert receipts.parse_receipt_name("brief-sent-2026-09-11.json") == (
        "brief", ["2026", "09", "11"])
    assert receipts.parse_receipt_name("intraday-sent-us.json") == ("intraday", ["us"])
    assert receipts.parse_receipt_name("wechat-sends.json") is None


def test_sent_ok_is_wechat_and_tg_ok_is_telegram_and_only_true_counts(tmp_path):
    body = receipts.build_receipt(ts=1, sent_ok=0, tg_ok="yes", out="x" * 300, first_line="L")
    assert body["sent_ok"] is False and body["tg_ok"] is True and len(body["out"]) == 200
    path = tmp_path / "r.json"
    path.write_text(json.dumps(body))
    assert receipts.channels(receipts.read_receipt(path)) == (False, True)
    assert receipts.delivered(receipts.read_receipt(path))
    assert receipts.channels({"sent_ok": "true", "tg_ok": 1}) == (False, False)
    (tmp_path / "bad.json").write_text("[1, 2]")
    assert receipts.read_receipt(tmp_path / "bad.json") is None
    assert receipts.read_receipt(tmp_path / "absent.json") is None


def test_the_policy_table_decides_which_channels_are_called(monkeypatch):
    calls = []

    def wechat(channel, to, account, message, dry_run=False):
        calls.append("wechat")
        return True, "ok"

    def telegram(message, tag):
        calls.append("telegram")
        return True, "ok"

    def resolve(market=None):
        return "openclaw-weixin", "kcn", None

    monkeypatch.setitem(receipts.CHANNELS, "intraday", ("telegram",))
    result = common.send_per_policy("intraday", "m", tag="t", market="hk",
                                    wechat=wechat, telegram=telegram, resolve=resolve)
    assert calls == ["telegram"] and result == (False, "wechat is not in the delivery policy", True)

    calls.clear()
    monkeypatch.setitem(receipts.CHANNELS, "intraday", ("wechat", "telegram"))
    assert common.send_per_policy("intraday", "m", tag="t", market="hk", wechat=wechat,
                                  telegram=telegram, resolve=resolve) == (True, "ok", True)
    assert calls == ["wechat", "telegram"]


def test_a_failed_wechat_never_stops_telegram():
    def wechat(*a, **k):
        raise RuntimeError("gateway gone")

    def resolve(market=None):
        return "c", "t", None

    ok, out, tg = common.send_per_policy("brief", "m", tag="brief", wechat=wechat,
                                         telegram=lambda m, t: (True, ""), resolve=resolve)
    assert (ok, tg) == (False, True) and "gateway gone" in out


def test_no_module_spells_a_receipt_name_of_its_own():
    """The names live in `delivery_receipts`. A second spelling is how the seven
    readers drifted apart in the first place; prose in docstrings is fine."""
    pattern = re.compile(r"""(f?['"])(brief|report|intraday)-(sent|send)-""")
    offenders = []
    for path in list((ROOT / "src").rglob("*.py")) + list((ROOT / "ops").rglob("*.py")):
        if path.name == "delivery_receipts.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if pattern.search(code):
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:90]}")
    assert not offenders, "use delivery_receipts.receipt_name / claim_name:\n" + "\n".join(offenders)


def test_only_the_intraday_claim_takes_the_slot_and_the_receipt_never_does():
    """The two files answer different questions, so only one of them moves.

    `intraday-sent-{market}.json` answers "when did this market last receive an
    intraday report" — every reader and every file already on disk depends on
    that name. The claim answers "is THIS slot's send in flight", and naming it
    per-market made the two indistinguishable (#1742).
    """
    slot = "2026-09-21T10:03:00+08:00"

    assert (receipts.claim_name("intraday", market="hk", slot=slot)
            == "intraday-send-hk-20260921-1003.claim")
    # The receipt is untouched by a slot it is not given and would not use.
    assert receipts.receipt_name("intraday", market="hk") == "intraday-sent-hk.json"
    # Neither are the kinds whose names already carry phase and date.
    assert (receipts.claim_name("report", market="us", phase="close", date="2026-09-11")
            == "report-send-us-close-2026-09-11.claim")
    assert receipts.claim_name("brief", date="2026-09-11") == "brief-send-2026-09-11.claim"


def test_two_intraday_slots_never_share_one_claim_file():
    """The defect in one line: 10:03's leftover must not be 10:33's lock."""
    names = {receipts.claim_name("intraday", market="hk", slot=slot)
             for slot in ("2026-09-21T10:03:00+08:00", "2026-09-21T10:33:00+08:00")}
    assert len(names) == 2, names
    # …and a different market is still a different claim, as it always was.
    assert (receipts.claim_name("intraday", market="us", slot="2026-09-21T10:03:00+08:00")
            != receipts.claim_name("intraday", market="hk", slot="2026-09-21T10:03:00+08:00"))


@pytest.mark.parametrize("slot", [None, "", "not-a-timestamp", 20261003, {}])
def test_a_slot_that_cannot_be_resolved_keeps_the_name_it_always_had(slot):
    """Additive, never load-bearing: a caller that cannot name its slot still
    takes a lock, and the age bound in `wechat_gap_reason` (#1685) stays its
    backstop. Falling back to no claim at all would trade a false alert for a
    duplicate send, which is the failure #508 exists to stop."""
    assert receipts.slot_key(slot) is None
    assert (receipts.claim_name("intraday", market="hk", slot=slot)
            == "intraday-send-hk.claim")


def test_the_slot_key_is_the_one_the_watchdog_already_dedupes_on():
    """Both sides have to land on the same file name, so there is one spelling.

    `intraday_watchdog` has derived `%Y%m%d-%H%M` from `expected_slot` for its
    dedupe flag since before this; the postflight holds the same string as
    `heartbeat['slot']` (#1555 matches the marker on it).
    """
    from datetime import datetime

    slot = "2026-09-21T10:03:00+08:00"
    assert receipts.slot_key(slot) == datetime.fromisoformat(slot).strftime("%Y%m%d-%H%M")
