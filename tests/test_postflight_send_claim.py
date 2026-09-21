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

import pytest


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


# --- the marker's own durability (#1311) ------------------------------------
#
# The claim closes the window between two live senders. It says nothing about
# the window inside the marker write itself: `Path.write_text` truncates first
# and writes second, so a process killed between the two leaves a marker that
# parses as nothing at all. `already_delivered` answers False for an unreadable
# marker — deliberately, so a genuine miss is never muted — which means a torn
# marker and a never-sent slot are the same answer, and the watchdog re-sends a
# report kcn already has. The claim cannot catch it: claims expire in 30
# minutes (SEND_CLAIM_STALE_MS) and the re-send arrives later than that.
#
# This branch only runs when a process dies mid-write, so no green run can
# exercise it (see memory: fallback-branches-are-invisible-to-green-runs). The
# gate is therefore static: every delivery-marker write must route through the
# atomic writer, checked by enumerating the three postflights rather than by
# naming the lines that happen to be wrong today.

POSTFLIGHTS = ('brief_postflight', 'report_postflight', 'intraday_postflight')


def test_a_torn_marker_reads_as_never_delivered(tmp_path):
    """Why atomicity is not cosmetic here: this is the re-send."""
    c = _common()
    marker = tmp_path / 'report-sent-hk-open-2026-09-05.json'
    payload = json.dumps({'ts': NOW_MS, 'sent_ok': True, 'tg_ok': True})

    marker.write_text(payload)
    assert c.already_delivered(marker) is True

    # what a SIGKILL between truncate and write leaves behind
    marker.write_text(payload[:len(payload) // 2])
    assert c.already_delivered(marker) is False, (
        'a half-written marker must not be readable as delivered — it is not; '
        'that is the bug, because the caller then sends again')

    marker.write_text('')
    assert c.already_delivered(marker) is False


@pytest.mark.parametrize('module', POSTFLIGHTS)
def test_every_delivery_marker_write_is_atomic(module):
    """No postflight may write its send marker with bare `write_text`."""
    import ast

    source = Path(__file__).resolve().parents[1] / 'src' / 'clawock' / 'harness' / f'{module}.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))

    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'write_text'):
            continue
        target = ast.unparse(node.func.value)
        if 'marker' in target:
            offenders.append(f'{module}.py:{node.lineno}: {target}.write_text(...)')

    assert not offenders, (
        'delivery markers must be written with clawock.safe_io.safe_write_text '
        '(tmp + fsync + os.replace), not Path.write_text, which truncates the '
        'previous marker before it writes the new one:\n  ' + '\n  '.join(offenders))


# ── C. the handover: the claim may only be dropped once the marker holds ────
#
# 2026-09-21 (#1743). The claim is the lock held across the send; the marker is
# the receipt that makes the send un-repeatable afterwards. All three
# postflights wrote the marker inside a `try`, warned on failure, and released
# the claim outside it — so a send that reached WeChat but could not file its
# receipt (disk full, read-only filesystem, permissions) left neither, and
# openclaw's retry found nothing to stop it. That is #508 again, through a door
# the #508 fix left open.

def test_a_send_with_no_marker_keeps_its_claim(tmp_path):
    c = _common()
    claim = tmp_path / 'hk-open.claim'
    claim.write_text(json.dumps({'pid': 1, 'ts': NOW_MS, 'send_started_at': NOW_MS}))

    c.release_claim(claim, marker_written=False)

    assert claim.exists(), 'without a receipt the lock is all that stops a resend'


def test_a_send_that_filed_its_marker_drops_its_claim(tmp_path):
    """The direction that must not break: a completed send has to let go.

    A claim that outlives a healthy send refuses a LATER one — an intraday slot
    whose own send failed writes a marker that correctly does not block the
    next slot, and a surviving claim would.
    """
    c = _common()
    claim = tmp_path / 'hk-open.claim'
    claim.write_text(json.dumps({'pid': 1, 'ts': NOW_MS, 'send_started_at': NOW_MS}))

    c.release_claim(claim, marker_written=True)

    assert not claim.exists()


def test_the_kept_claim_is_what_turns_a_retry_away(tmp_path):
    """End to end, the bug and its fix in one sequence.

    Sender reaches WeChat, fails to write its marker, keeps the claim; the
    openclaw retry arrives as a fresh process and must decline.
    """
    c = _common()
    claim = tmp_path / 'hk-open.claim'
    claim.write_text(json.dumps({
        'pid': _dead_pid(), 'ts': NOW_MS, 'send_started_at': NOW_MS + 31_000,
    }))

    c.release_claim(claim, marker_written=False)
    won, reason = c.claim_send(claim, now_ms=NOW_MS + 64_000)

    assert won is False and reason == 'holder-died-mid-send'


def test_a_kept_claim_still_goes_stale_so_it_can_never_block_forever(tmp_path):
    """Keeping the claim delays a send; it must not be able to prevent one.

    `feedback-detect-but-never-silence`: the failure this whole harness exists
    to stop is a report that never goes out, so the lock has to expire.
    """
    c = _common()
    claim = tmp_path / 'hk-open.claim'
    claim.write_text(json.dumps({
        'pid': _dead_pid(), 'ts': NOW_MS, 'send_started_at': NOW_MS,
    }))

    c.release_claim(claim, marker_written=False)
    won, reason = c.claim_send(claim, now_ms=NOW_MS + c.SEND_CLAIM_STALE_MS + 1)

    assert won is True and reason == 'took-over-stale-claim'


def test_releasing_requires_saying_whether_the_marker_landed():
    """A default would let the next call site inherit the bug by saying nothing."""
    import inspect

    sig = inspect.signature(_common().release_claim)
    marker = sig.parameters['marker_written']
    assert marker.kind is inspect.Parameter.KEYWORD_ONLY
    assert marker.default is inspect.Parameter.empty


def test_every_postflight_ties_its_release_to_its_marker_write():
    """Three call sites, one rule — and the rule is only worth having while all
    three follow it. Counting them is what keeps this from passing by
    discovering nothing (#453)."""
    import re

    postflights = ['brief_postflight.py', 'intraday_postflight.py', 'report_postflight.py']
    for name in postflights:
        source = (ROOT / 'src' / 'clawock' / 'harness' / name).read_text(encoding='utf-8')
        calls = re.findall(r'release_claim\(([^)]*)\)', source)
        assert calls, f'{name}: no release_claim call found'
        for call in calls:
            assert 'marker_written=marker_written' in call, (
                f'{name}: release_claim({call}) does not follow its marker write')
