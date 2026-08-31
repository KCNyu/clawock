"""A failed Telegram co-send must record why (2026-08-31).

`tg_ok=false` in the marker is the single fact that makes a watchdog fire, and
three co-sends failed that morning — brief 08:08, hk-open 09:34, intraday-hk
10:04. Each cost a mirror, and none of them left a reason anywhere: the
transport's failure tail was returned to a caller that dropped it, and the log
line recorded only `sent_ok: false`. The reason belongs in the same record as
the outcome that acts on it.
"""
from clawock.harness import _watchdog_common as common


def _capture(monkeypatch):
    written = []
    monkeypatch.setattr(common, 'log', written.append)
    return written


def test_a_failed_cosend_records_the_transports_reason(monkeypatch):
    written = _capture(monkeypatch)
    monkeypatch.setattr(common, 'send_telegram',
                        lambda target, message, dry_run: (False, 'EPIPE: broken pipe'))

    ok, _ = common.cosend_telegram('body', 'brief')

    assert ok is False
    assert written[0]['detail'] == 'EPIPE: broken pipe', (
        'the failure tail must reach the log the watchdog decision is read from')


def test_a_silent_failure_says_so_rather_than_leaving_the_field_out(monkeypatch):
    """An empty tail is itself a finding — "the transport said nothing" is a
    different failure from "the transport explained itself"."""
    written = _capture(monkeypatch)
    monkeypatch.setattr(common, 'send_telegram',
                        lambda target, message, dry_run: (False, ''))

    common.cosend_telegram('body', 'hk-open')

    assert written[0]['detail'] == 'no output from the transport'


def test_a_raising_transport_is_recorded_as_the_exception(monkeypatch):
    written = _capture(monkeypatch)

    def boom(target, message, dry_run):
        raise RuntimeError('gateway refused the connection')

    monkeypatch.setattr(common, 'send_telegram', boom)

    ok, _ = common.cosend_telegram('body', 'intraday-hk')

    assert ok is False
    assert 'gateway refused the connection' in written[0]['detail']


def test_a_successful_cosend_stays_a_one_line_record(monkeypatch):
    """No detail on success: the log is read by eye, and a reason field on a
    send that worked is noise that makes the failures harder to spot."""
    written = _capture(monkeypatch)
    monkeypatch.setattr(common, 'send_telegram',
                        lambda target, message, dry_run: (True, 'messageId 1164'))

    ok, _ = common.cosend_telegram('body', 'brief')

    assert ok is True
    assert 'detail' not in written[0]
