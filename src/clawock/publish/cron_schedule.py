"""Today's cron timetable, folded small enough to ship inside the dashboard.

The panel answers one question per slot: *did this fire and land?* The verdict
is not derived here — `workflow_outcomes._derive_final` already computes it once
for the ledger, and a second opinion computed for the display is how a green
light starts disagreeing with the ledger it claims to summarise. This module
only joins two things that already exist:

  expected  = the tracked cron contract, expanded for the day
  actual    = the published outcome records' `final_product.status`

A slot with no record yet is not a failure until its grace window has passed;
before that it is simply upcoming, which is why this needs `now` and not just
the date.

Every non-`ok` slot also carries a `note`: {disposition, text}. `disposition`
reuses the data-health card's own four words (需处理/观察/已知不修/正常) so the
reader is not asked to learn a second vocabulary. `text` is a sentence built
purely from fields the ledger already published for that slot — never a new
pass/fail judgment, only a description of the one the ledger already made.
The `degraded` split in particular mirrors `workflow_outcomes._advisory_only`
exactly (`escalating_count == 0`), reading the same field it reads, so this
narrates the ledger's reasoning rather than inventing a second one.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from clawock.scheduling import effective_schedule, parse_cron_slots

HKT = ZoneInfo('Asia/Hong_Kong')

#: How long after a slot fires before "no record" stops meaning "still running".
#: The runs take 4-6 minutes and the watchdog re-dispatch lands by +10, so a slot
#: with nothing on it 20 minutes later genuinely did not report.
GRACE_MINUTES = 20

#: How far a record may sit from an expected slot and still be that slot's run.
#: Capped further by half the gap between adjacent slots, so two 30-minute slots
#: can never claim the same record.
SNAP_MINUTES = 15

#: Ledger verdict -> what the panel shows. An explicit table so a ledger status
#: nobody mapped shows up as `unknown` rather than silently rendering green —
#: the failure mode of a `.get(status, 'ok')` default.
STATE_OF_VERDICT = {
    'success': 'ok',
    'degraded': 'degraded',
    'recovered': 'recovered',
    'failed': 'failed',
    'pending': 'running',
    'skipped': 'closed',
}


def _has_harness(job):
    """Whether this job runs a harness that reports into the outcome ledger.

    The contract writes an em dash for the jobs that have none (Memory Dreaming
    is the only one today). Anything falsy or a dash means the ledger will never
    carry a record for it, no matter how well the job ran.
    """
    harness = str(job.get('harness') or '').strip()
    return bool(harness) and harness not in {'-', '—', '–'}


#: The same four words the data-health card already uses for disposition —
#: one vocabulary across the whole card, not a second one invented here.
NEEDS_ACTION, WATCH, KNOWN_NOT_FIXED, NORMAL = (
    'needs_action', 'watch', 'known_not_fixed', 'normal')


def _note(disposition, text):
    return {'disposition': disposition, 'text': text}


def _narrate_recovered(record):
    # #1278: MiniMax holds an overloaded request 100-143s before it 429s, and
    # the schedule was moved specifically so the FIRST attempt of a slot lands
    # off the top of the hour. A slot that still needed the watchdog is the
    # rarer case that first attempt lost anyway — the retry is the system
    # working as designed, not a fault to chase.
    return _note(WATCH, '首次投递超时，watchdog 重投后送达；这是已知机制'
                        '（MiniMax 过载超时，重投几乎必成，见 #1278），无需处理')


def _narrate_degraded(record):
    postflight = (record.get('stages') or {}).get('postflight') or {}
    delivery = (record.get('stages') or {}).get('primary_delivery') or {}
    wechat_ok = delivery.get('wechat_ok')
    telegram_ok = delivery.get('telegram_ok')
    escalating = postflight.get('escalating_count')
    issues = postflight.get('issue_count') or 0
    data_plane = postflight.get('data_plane_status')

    # WeChat's context-token drop is diagnosed and deliberately left unfixed
    # (#771) — Telegram is the reliable channel on those slots, not a gap.
    if wechat_ok is False and telegram_ok:
        return _note(KNOWN_NOT_FIXED,
                    '微信投递失败（上游 ret=-2 prepare failed），Telegram 已接住；'
                    '已知不修（#771）')
    # `escalating_count` is the exact field `_advisory_only` reads — a nonzero
    # count is the same signal that made the ledger call this slot degraded,
    # not a re-judgment of it.
    if escalating:
        return _note(NEEDS_ACTION,
                    f'内容校验有 {issues} 条问题，其中 {escalating} 条不是仅供参考的'
                    '——报告已投递但可能有误，查 workflow-outcomes.json 这一槽的 stages')
    # The other way `_advisory_only`'s AND fails: content was clean but the
    # dashboard commit had not published yet the moment this record was
    # written. The scheduled publisher ticks every 20 minutes and catches up
    # on its own — this is a bookkeeping lag, not a delivery problem.
    if data_plane and data_plane not in {'published', 'current', 'skipped'}:
        return _note(WATCH,
                    '两个渠道都已送达，内容校验没有问题；仪表盘发布还在排队，'
                    '几分钟内自动追上，无需处理')
    reason = (record.get('final_product') or {}).get('reason')
    return _note(WATCH, reason or '降级送达')


def _narrate_failed(record):
    return _note(NEEDS_ACTION, '这一槽没有产出，成品未落地——这段时间没有报告送达')


_MISSED_NOTE = _note(
    NEEDS_ACTION, '到点了但账本里没有这一槽的记录，需要看是不是卡住了')
_UNMONITORED_NOTE = _note(
    NORMAL, '这个 job 没有 harness，账本本来就看不到它的记录，不代表没跑')

_NARRATORS = {
    'recovered': _narrate_recovered,
    'degraded': _narrate_degraded,
    'failed': _narrate_failed,
}


def _note_for(state, record):
    """The note for one cell, or None when a bare light says everything."""
    if record and state in _NARRATORS:
        return _NARRATORS[state](record)
    if state == 'missed':
        return _MISSED_NOTE
    return None


def _local_slots(job, day_utc):
    """The HH:MM slots this job should fire on `day_utc`, in its own timezone."""
    schedule = effective_schedule(job, day_utc)
    expr, tz_name = schedule.get('expr'), schedule.get('tz') or 'Asia/Shanghai'
    if not expr:
        return [], tz_name
    return parse_cron_slots(expr, tz_name, day_utc), tz_name


def _records_by_slot(records, job_name, day, tz, slots):
    """This job's records for `day`, snapped to the expected slot each belongs to.

    Snapped rather than joined exactly because a record carries the slot the
    contract held *when it ran*: on the day a schedule moves, every record is
    minutes off the new grid and an exact join paints the whole day as missed
    (#1278 moved nine jobs by three minutes — a panel reading that as nine
    outages is worse than no panel). The tolerance is capped at half the gap
    between adjacent slots, so windows never overlap and a genuinely absent run
    still finds nothing to snap to.
    """
    grid = []
    for slot in slots:
        hour, minute = (int(part) for part in slot.split(':'))
        grid.append((slot, datetime.combine(day, datetime.min.time(), tzinfo=tz)
                     .replace(hour=hour, minute=minute)))
    tolerance = timedelta(minutes=SNAP_MINUTES)
    if len(grid) > 1:
        gaps = [later[1] - earlier[1] for earlier, later in zip(grid, grid[1:])]
        tolerance = min(tolerance, min(gaps) / 2)
    found = {}
    for record in records:
        if record.get('job') != job_name:
            continue
        try:
            at = datetime.fromisoformat(record['slot']).astimezone(tz)
        except (KeyError, TypeError, ValueError):
            continue
        if at.date() != day:
            continue
        nearest = min(grid, key=lambda cell: abs(cell[1] - at), default=None)
        if nearest and abs(nearest[1] - at) <= tolerance:
            found.setdefault(nearest[0], record)
    return found


def timetable(contract, records, *, now=None):
    """One row per job, one light per slot, for the day `now` falls in."""
    now = now or datetime.now(HKT)
    now_utc = now.astimezone(ZoneInfo('UTC'))
    # An empty ledger is not a day when nothing ran — it is a day we cannot
    # speak about (a fresh checkout, or the file not written yet). Returning no
    # rows hides the card, which is the honest answer; the alternative paints
    # every past slot red and blames the cron for a bookkeeping gap.
    if not records:
        return {'date': now.astimezone(HKT).strftime('%Y-%m-%d'),
                'grace_minutes': GRACE_MINUTES, 'jobs': []}
    rows = []
    for job in contract.get('jobs', []):
        name = job.get('name')
        slots, tz_name = _local_slots(job, now_utc)
        if not slots:
            continue  # not a firing day for this job; an empty row says nothing
        tz = ZoneInfo(tz_name)
        day = now.astimezone(tz).date()
        # A job with no harness writes no ledger record, so the ledger can say
        # nothing about it — painting its slot red would report an outage every
        # single day and teach the reader to ignore the panel. `system_check`
        # names the same blind spot in the same words ("this gate cannot see
        # them"). The criterion is the contract's own `harness` field rather
        # than "absent from the ledger": the ledger is windowed, so absence
        # there also describes a job that simply has not run for a few days.
        if not _has_harness(job):
            rows.append({'job': name, 'tz': tz_name, 'unmonitored': True,
                         'slots': [{'at': slot, 'state': 'unmonitored',
                                   'note': _UNMONITORED_NOTE} for slot in slots]})
            continue
        found = _records_by_slot(records, name, day, tz, slots)
        cells = []
        for slot in slots:
            hour, minute = (int(part) for part in slot.split(':'))
            fires_at = datetime.combine(day, datetime.min.time(), tzinfo=tz).replace(
                hour=hour, minute=minute)
            record = found.get(slot)
            if record:
                verdict = (record.get('final_product') or {}).get('status')
                state = STATE_OF_VERDICT.get(verdict, 'unknown')
            elif now.astimezone(tz) < fires_at:
                state = 'upcoming'
            elif now.astimezone(tz) - fires_at < timedelta(minutes=GRACE_MINUTES):
                state = 'running'
            else:
                state = 'missed'
            cell = {'at': slot, 'state': state}
            note = _note_for(state, record)
            if note:
                cell['note'] = note
            cells.append(cell)
        rows.append({'job': name, 'tz': tz_name, 'slots': cells})
    return {
        'date': now.astimezone(HKT).strftime('%Y-%m-%d'),
        'grace_minutes': GRACE_MINUTES,
        'jobs': rows,
    }
