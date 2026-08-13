"""The postflight send claim must close the duplicate window without opening a
silent-miss one.

2026-08-13 (#508): the 09:30 hk-open slot reached kcn's WeChat twice. The run had
been auto-retried after a MiniMax header timeout; inside the retry the model's
exec shell hit its 60s overall-timeout, SIGTERM killed the shell but not the
`clawock report postflight` child, the model read SIGTERM as failure and re-ran
the same command, and the two postflights raced. `already_delivered` could not
stop them: it reads the send marker, and the marker is written only after both
sends return — a ~54s window in which both processes read "never delivered".

Two invariants are pinned here, and a fix for either that breaks the other fails
this file:

  A. a second sender inside that window must NOT send (the reported bug)
  B. the claim must never become a new way to silently not send (`feedback-
     detect-but-never-silence`) — a holder that died before sending, a stale
     claim, and unreadable plumbing all still send.

Not here, deliberately: a "race 8 real processes at one claim" test. It was
written, then mutation-checked against a read-then-write implementation of
`claim_send` — and still passed, because interpreter startup jitter is far wider
than the window it was supposed to expose. It could not tell the fixed code from
the bug, so it is not in this file. The atomicity of O_EXCL is a property of the
syscall; what these tests own is the decision table around it.
"""
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOW_MS = int(1786584800 * 1000)


def _common():
    from clawock.harness import _watchdog_common
    return _watchdog_common


def _dead_pid():
    """A pid that has been reaped, so it is genuinely gone."""
    p = subprocess.Popen([sys.executable, '-c', 'pass'])
    p.wait()
    return p.pid


# ── A. the duplicate the bug actually produced ──────────────────────────────

def test_first_caller_wins(tmp_path):
    won, reason = _common().claim_send(tmp_path / 'hk-open.claim', now_ms=NOW_MS)
    assert won is True
    assert reason == 'claimed'


def test_second_caller_while_holder_is_alive_does_not_send(tmp_path):
    c = _common()
    claim = tmp_path / 'hk-open.claim'
    assert c.claim_send(claim, now_ms=NOW_MS)[0] is True
    # Same live process holds it — this is the 09:33:22 postflight still running
    # when the model fired the 09:34:26 one.
    won, reason = c.claim_send(claim, now_ms=NOW_MS + 64_000)
    assert won is False
    assert reason == 'in-flight'


def test_holder_killed_mid_send_does_not_get_a_second_send(tmp_path):
    """The exact 08-13 shape: SIGTERM landed after WeChat, before the marker."""
    c = _common()
    claim = tmp_path / 'hk-open.claim'
    claim.write_text(json.dumps({
        'pid': _dead_pid(),
        'ts': NOW_MS,
        'send_started_at': NOW_MS + 31_000,
    }))

    won, reason = c.claim_send(claim, now_ms=NOW_MS + 64_000)

    assert won is False, 'a killed sender may already have reached WeChat'
    assert reason == 'holder-died-mid-send'


# ── B. the claim must not become a new silent-miss path ─────────────────────

def test_holder_that_died_before_sending_is_taken_over(tmp_path):
    c = _common()
    claim = tmp_path / 'hk-open.claim'
    claim.write_text(json.dumps({'pid': _dead_pid(), 'ts': NOW_MS, 'send_started_at': None}))

    won, reason = c.claim_send(claim, now_ms=NOW_MS + 64_000)

    assert won is True, 'nothing was sent, so the slot still needs a send'
    assert reason == 'took-over-claim-of-holder-that-never-sent'


def test_stale_claim_cannot_mute_a_later_slot(tmp_path):
    c = _common()
    claim = tmp_path / 'hk-open.claim'
    # Live pid, mid-send, but from 45 minutes ago: a crashed process whose pid
    # got recycled must not own this slot forever.
    claim.write_text(json.dumps({
        'pid': 1, 'ts': NOW_MS, 'send_started_at': NOW_MS + 1_000,
    }))

    won, reason = c.claim_send(claim, now_ms=NOW_MS + 45 * 60 * 1000)

    assert won is True
    assert reason == 'took-over-stale-claim'


def test_unreadable_claim_fails_open(tmp_path):
    c = _common()
    claim = tmp_path / 'hk-open.claim'
    claim.write_text('{not json')

    won, reason = c.claim_send(claim, now_ms=NOW_MS)

    assert won is True, 'broken plumbing must never be why kcn got no report'
    assert reason.startswith('claim-unreadable-fail-open')


def test_uncreatable_claim_fails_open(tmp_path):
    c = _common()
    won, reason = c.claim_send(tmp_path / 'no-such-dir' / 'hk-open.claim', now_ms=NOW_MS)

    assert won is True
    assert reason.startswith('claim-unavailable-fail-open')


# ── the state transition the two halves hinge on ────────────────────────────

def test_report_deliver_flips_the_claim_before_it_sends(tmp_path, monkeypatch):
    """The ordering IS the fix. `mark_send_started` after the send would leave the
    same window the marker already leaves, and every unit test above would still
    pass — so the order is pinned against the real deliver path."""
    from clawock.harness import report_postflight as rp
    c = _common()

    claim = tmp_path / 'hk-open.claim'
    c.claim_send(claim, now_ms=NOW_MS)
    seen = {}

    def _fake_send(channel, to, account, message, dry_run):
        seen['claim_at_send'] = json.loads(claim.read_text())
        return True, 'openclaw-weixin:stub'

    monkeypatch.setattr(rp, 'TMP', tmp_path)
    monkeypatch.setattr(rp, 'resolve_wechat_target', lambda market: ('ch', 'to', 'acct'))
    monkeypatch.setattr(rp, 'send_wechat', _fake_send)
    monkeypatch.setattr(rp, 'cosend_telegram', lambda message, tag: (True, ''))

    sent_ok, _ = rp.deliver_wechat('hk', 'open', '2026-08-13', '', 'body', claim_path=claim)

    assert sent_ok is True
    assert seen['claim_at_send']['send_started_at'] is not None, (
        'the claim must already read as mid-send while WeChat is being called; '
        'otherwise a process killed here looks like it never sent'
    )


def _deliver(rp, monkeypatch, tmp_path, claim, send_result):
    monkeypatch.setattr(rp, 'TMP', tmp_path)
    monkeypatch.setattr(rp, 'resolve_wechat_target', lambda market: ('ch', 'to', 'acct'))
    monkeypatch.setattr(rp, 'send_wechat',
                        lambda channel, to, account, message, dry_run: send_result)
    monkeypatch.setattr(rp, 'cosend_telegram', lambda message, tag: (True, ''))
    return rp.deliver_wechat('hk', 'open', '2026-08-13', '', 'body', claim_path=claim)


def test_a_completed_send_releases_the_claim(tmp_path, monkeypatch):
    """After a send finishes, the marker owns idempotency. A claim left behind
    would go on refusing senders that the marker itself does not refuse."""
    from clawock.harness import report_postflight as rp
    claim = tmp_path / 'hk-open.claim'
    _common().claim_send(claim, now_ms=NOW_MS)

    _deliver(rp, monkeypatch, tmp_path, claim, (True, 'openclaw-weixin:stub'))

    assert not claim.exists()


def test_a_failed_send_releases_the_claim_so_the_next_slot_is_not_muted(tmp_path, monkeypatch):
    """The one that bites: a send that FAILED writes a marker with
    sent_ok/tg_ok false, so `already_delivered` correctly lets the next slot
    through — and the claim must not be what stops it instead."""
    from clawock.harness import report_postflight as rp
    c = _common()
    claim = tmp_path / 'hk-open.claim'
    c.claim_send(claim, now_ms=NOW_MS)

    _deliver(rp, monkeypatch, tmp_path, claim, (False, 'wechat exploded'))

    assert not claim.exists()
    won, reason = c.claim_send(claim, now_ms=NOW_MS + 5 * 60 * 1000)
    assert won is True, 'the next slot must still be able to send'
    assert reason == 'claimed'


def test_mark_send_started_flips_a_claim_to_mid_send(tmp_path):
    c = _common()
    claim = tmp_path / 'hk-open.claim'
    c.claim_send(claim, now_ms=NOW_MS)
    assert json.loads(claim.read_text())['send_started_at'] is None

    c.mark_send_started(claim)

    held = json.loads(claim.read_text())
    assert isinstance(held['send_started_at'], int)
    assert held['pid'] == json.loads(claim.read_text())['pid']
