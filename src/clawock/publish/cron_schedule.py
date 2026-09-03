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
                         'slots': [{'at': slot, 'state': 'unmonitored'}
                                   for slot in slots]})
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
            cells.append({'at': slot, 'state': state})
        rows.append({'job': name, 'tz': tz_name, 'slots': cells})
    return {
        'date': now.astimezone(HKT).strftime('%Y-%m-%d'),
        'grace_minutes': GRACE_MINUTES,
        'jobs': rows,
    }
