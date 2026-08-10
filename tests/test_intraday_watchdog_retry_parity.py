"""intraday_watchdog delivery evidence must survive an openclaw cron retry.

2026-08-10: the HK 10:30 and 11:30 slots were delivered by intraday_postflight
(WeChat + Telegram cosend, `sent_ok=true` at 10:31:40 and 11:31:37), openclaw
then auto-retried each run because post-turn summary generation failed, the
retry's preflight rewrote the context file, and its postflight correctly
declined to re-send. The watchdog compared the marker's `first_line` — written
from the block that was actually delivered — against the retry's regenerated
block, read "never delivered", and fired a deterministic fallback for two
reports already sitting in kcn's Telegram:

    _1030.json -> '🇭🇰 港股盯盘 | 08/10 10:30 HKT'   delivered, marker
    _1032.json -> '🇭🇰 港股盯盘 | 08/10 10:33 HKT'   retry, what the gate compared

Only a second bug hid it: the fallback could not send (`openclaw is not
installed`, the cron-PATH hole fixed by #457), so no duplicate landed. With that
path working, the same shape delivers the duplicate.

This is the same incident report_watchdog was fixed for on 2026-08-03; see
tests/test_report_watchdog_retry_parity.py. The port to Mode 7 is what this file
pins.

The opposite failure must stay caught: a marker whose context belongs to another
slot, or is a whole generation stale, must still get the backstop. Both
invariants are pinned here — a fix for either one that breaks the other fails
this file.
"""
import json
from datetime import datetime

JOB = '盘中盯盘'
SLOT = '2026-08-10T10:30:00+08:00'
DELIVERED_LINE = '🇭🇰 港股盯盘 | 08/10 10:30 HKT'
RETRY_LINE = '🇭🇰 港股盯盘 | 08/10 10:33 HKT'
DELIVERED_AT = datetime(2026, 8, 10, 10, 30, 5)
RETRY_AT = datetime(2026, 8, 10, 10, 32, 57)
NOW_MS = int(datetime(2026, 8, 10, 10, 40).timestamp() * 1000)


def _marker(**extra):
    marker = {
        'ts': int(datetime(2026, 8, 10, 10, 31, 40).timestamp() * 1000),
        'tg_ok': True,
        'first_line': DELIVERED_LINE,
        'job': JOB,
        'slot': SLOT,
        'context_id': '2b44c30f12e5',
        'context_generated_at': DELIVERED_AT.isoformat(),
    }
    marker.update(extra)
    return marker


def test_retry_regenerated_context_still_counts_as_delivered():
    """The 2026-08-10 10:30 and 11:30 false backstops."""
    from clawock_kcnyu.harness import intraday_watchdog as watchdog

    assert watchdog.marker_covers_slot(
        _marker(), JOB, SLOT, RETRY_LINE, NOW_MS,
        ctx_id='c67756a17272', ctx_generated_at=RETRY_AT.isoformat())


def test_an_exact_context_id_match_is_delivered():
    from clawock_kcnyu.harness import intraday_watchdog as watchdog

    assert watchdog.marker_covers_slot(
        _marker(), JOB, SLOT, DELIVERED_LINE, NOW_MS,
        ctx_id='2b44c30f12e5', ctx_generated_at=DELIVERED_AT.isoformat())


def test_a_context_a_whole_slot_older_is_not_this_slot():
    """The failure the id compare exists for: a marker left over from an earlier
    delivery must not suppress this slot's backstop just because the ids differ
    and the gate learned to forgive differing ids."""
    from clawock_kcnyu.harness import intraday_watchdog as watchdog

    stale = _marker(
        context_id='aaaaaaaaaaaa',
        context_generated_at=datetime(2026, 8, 10, 10, 0, 4).isoformat(),
    )

    assert not watchdog.marker_covers_slot(
        stale, JOB, SLOT, RETRY_LINE, NOW_MS,
        ctx_id='c67756a17272', ctx_generated_at=RETRY_AT.isoformat())


def test_a_marker_for_another_slot_is_still_rejected():
    """Slot identity outranks every id rule: the marker below is fresh, its
    context was generated seconds before this one, and it is still the wrong
    slot."""
    from clawock_kcnyu.harness import intraday_watchdog as watchdog

    other = _marker(slot='2026-08-10T11:30:00+08:00')

    assert not watchdog.marker_covers_slot(
        other, JOB, SLOT, RETRY_LINE, NOW_MS,
        ctx_id='c67756a17272', ctx_generated_at=RETRY_AT.isoformat())


def test_a_failed_telegram_cosend_is_never_delivered():
    from clawock_kcnyu.harness import intraday_watchdog as watchdog

    assert not watchdog.marker_covers_slot(
        _marker(tg_ok=False), JOB, SLOT, DELIVERED_LINE, NOW_MS,
        ctx_id='2b44c30f12e5', ctx_generated_at=DELIVERED_AT.isoformat())


def test_a_marker_predating_the_id_fields_still_uses_the_first_line():
    """Markers written before this fix carry neither field. They must keep
    working through the legacy compare rather than turning every slot into a
    false miss for the length of one deployment."""
    from clawock_kcnyu.harness import intraday_watchdog as watchdog

    legacy = _marker()
    legacy.pop('context_id')
    legacy.pop('context_generated_at')

    assert watchdog.marker_covers_slot(
        legacy, JOB, SLOT, DELIVERED_LINE, NOW_MS,
        ctx_id='c67756a17272', ctx_generated_at=RETRY_AT.isoformat())
    assert not watchdog.marker_covers_slot(
        legacy, JOB, SLOT, RETRY_LINE, NOW_MS,
        ctx_id='c67756a17272', ctx_generated_at=RETRY_AT.isoformat())


def test_postflight_marker_records_the_context_identity_the_gate_needs():
    """The gate above can only work if postflight writes the two fields. This is
    the half that was missing: Mode 7's context has carried `context_id` and
    `generated_at` all along, and the marker threw both away."""
    from clawock_kcnyu.harness import intraday_postflight as postflight

    marker = postflight.delivery_marker_payload(
        {
            'heartbeat': {'job': JOB, 'slot': SLOT},
            'context_id': '2b44c30f12e5',
            'generated_at': DELIVERED_AT.isoformat(),
        },
        ts=1_000_000,
        sent_ok=True,
        tg_ok=True,
        first_line=DELIVERED_LINE,
        market='hk',
        out='ok',
    )

    assert marker['context_id'] == '2b44c30f12e5'
    assert marker['context_generated_at'] == DELIVERED_AT.isoformat()


def test_the_regeneration_window_is_shared_with_report_watchdog():
    """Mode 6 was fixed on 2026-08-03 and Mode 7 kept paying for it until today.
    A second copy of the rule is how that happens again, so the helper must be
    one object, not two that look alike."""
    from clawock_kcnyu.harness import _watchdog_common, report_watchdog
    from clawock_kcnyu.harness import intraday_watchdog

    shared = _watchdog_common.same_generation_window
    assert intraday_watchdog.same_generation_window is shared
    assert report_watchdog.same_generation_window is shared


def test_the_retry_window_is_tighter_than_the_intraday_cadence():
    """Slots are 30 minutes apart. A regeneration window at or above that could
    call the previous slot's context a retry of this one, so the number itself
    is part of the invariant."""
    from clawock_kcnyu.harness import intraday_watchdog as watchdog

    assert watchdog.REGEN_WINDOW_S < 30 * 60


def test_a_delivered_slot_is_not_downgraded_by_a_failed_backstop(tmp_path, monkeypatch):
    """The second defect in #458: the failure branch recorded telegram_sent=false
    over postflight's truthful telegram_sent=true, so the heartbeat claimed a
    delivered slot was undelivered."""
    from clawock_kcnyu.harness import intraday_watchdog as watchdog

    recorded = []
    monkeypatch.setattr(watchdog.cron_heartbeat, 'record',
                        lambda *a, **kw: recorded.append((a, kw)))
    monkeypatch.setattr(watchdog, 'send_telegram', lambda *a, **kw: (False, 'boom'))

    class Args:
        market = 'hk'
        dry_run = False

    watchdog.deliver_fallback(
        'block', 'intraday-hk', '未完成', Args(), datetime(2026, 8, 10, 10, 40),
        tmp_path / 'flag', JOB, SLOT, 1_000_000,
        telegram_already_delivered=True)

    assert recorded, 'a failed fallback must still leave a trace'
    _, kwargs = recorded[-1]
    assert kwargs['telegram_sent'] is True, (
        'postflight delivered this slot; a failed backstop must not rewrite that')


def test_a_never_delivered_slot_still_records_the_failure(tmp_path, monkeypatch):
    """The other side of the same branch: when nothing was delivered, a failed
    fallback must keep saying so."""
    from clawock_kcnyu.harness import intraday_watchdog as watchdog

    recorded = []
    monkeypatch.setattr(watchdog.cron_heartbeat, 'record',
                        lambda *a, **kw: recorded.append((a, kw)))
    monkeypatch.setattr(watchdog, 'send_telegram', lambda *a, **kw: (False, 'boom'))

    class Args:
        market = 'hk'
        dry_run = False

    watchdog.deliver_fallback(
        'block', 'intraday-hk', '未完成', Args(), datetime(2026, 8, 10, 10, 40),
        tmp_path / 'flag', JOB, SLOT, 1_000_000)

    _, kwargs = recorded[-1]
    assert kwargs['telegram_sent'] is False
    assert kwargs['watchdog_state'] == 'deterministic_fallback_failed'


def test_the_context_file_this_incident_produced_still_reads_as_delivered():
    """A last guard against a fix that only satisfies hand-built fixtures: the
    two artifacts below are verbatim from the 2026-08-10 incident."""
    from clawock_kcnyu.harness import intraday_watchdog as watchdog

    delivered = json.loads(json.dumps({
        'context_id': '2b44c30f12e5',
        'generated_at': '2026-08-10T10:30:05',
        'raw_wechat_block': DELIVERED_LINE + '\n...',
    }))
    retried = json.loads(json.dumps({
        'context_id': 'c67756a17272',
        'generated_at': '2026-08-10T10:32:57',
        'raw_wechat_block': RETRY_LINE + '\n...',
    }))

    marker = _marker(
        context_id=delivered['context_id'],
        context_generated_at=delivered['generated_at'],
        first_line=delivered['raw_wechat_block'].splitlines()[0],
    )

    assert watchdog.marker_covers_slot(
        marker, JOB, SLOT,
        retried['raw_wechat_block'].splitlines()[0], NOW_MS,
        ctx_id=retried['context_id'],
        ctx_generated_at=retried['generated_at'])
