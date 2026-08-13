#!/usr/bin/env python3
"""
_watchdog_common.py — shared helpers for report_watchdog.py + brief_watchdog.py.

Both watchdogs are LLM-free out-of-band safety nets (system crontab) that ask
"did this cron actually deliver?" and re-send the content if not. They shared
~70% of their code (run-record reading, target resolution, WeChat send, logging);
that lives here now so a fix lands once.

Also home to `transcript_loop_score` — the reliable delivery-failure signal.
Background: the cron run-record `summary` field is openclaw's truncated (~2KB)
meta-prose, NOT the announced message, so marker-matching on it both false-
positives (a clean delivery's summary is a "✅ done" checklist with no card
markers) and false-negatives. The actual mimo failure mode is a *repeat loop*
("Now let me output the WeChat message…" ×dozens) that only shows in the full
session transcript. transcript_loop_score detects that directly and cleanly
(observed: looped run score≈7 on a 97KB assistant blob; clean run score≈2 on 3KB).
"""
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

from clawock.workspace import workspace_root

WS = workspace_root(Path.cwd())
_CHECKOUT = WS
LOG = WS / 'logs' / 'watchdog.jsonl'
HKT = timezone(timedelta(hours=8))
# The binary path, the cron CLI call and the cron-state fallback chain moved
# into src/clawock/providers/openclaw.py so this module stops being the largest
# consumer that knows which runtime it is on — and so the chain is reachable
# from an installation, which it was not while it lived in this file: the wheel
# ships `clawock`, not `scripts/harness`. The OPENCLAW_BIN re-export retired with
# #267 once system_check stopped importing it from here (#353) — it was the last
# consumer, which is exactly the ordering that issue specified.
#
from clawock.providers import openclaw as _openclaw
from clawock.providers.openclaw import (
    cron_cli_json as _adapter_cron_json, runtime_paths as _openclaw_paths,
)

# Where the runtime keeps its session transcripts. The location is the runtime's,
# so the adapter owns it (#330 step 1): this module used to hard-code
# `Path('/root/.openclaw')`, which made it one of the ten sites that know which
# runtime they are on. Deriving it from the adapter's selected runtime is the
# fix the ratchet is asking for — not a relocated string, because
# `src/clawock/providers/` is the one place where knowing is correct and is already
# this module's source for runtime paths and the cron chain.
SESSIONS_DIR = _openclaw_paths().sessions_dir


def log(event):
    """Append one JSON line to logs/watchdog.jsonl. Never raises."""
    try:
        event['ts'] = datetime.now(HKT).isoformat()
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open('a') as f:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f'(watchdog log failed: {e})', file=sys.stderr)
    try:
        _record_watchdog_outcome(event)
    except Exception as e:
        print(f'(watchdog outcome record failed: {e})', file=sys.stderr)


def _record_watchdog_outcome(event):
    """Project watchdog delivery evidence into the independent outcome ledger."""
    if event.get('dry_run'):
        return
    tag = event.get('tag')
    if not isinstance(tag, str) or tag.startswith('intraday-'):
        # Intraday has an exact slot-aware cron_heartbeat bridge.
        return
    if tag == 'brief':
        job = '盘前深度简报'
    else:
        parts = tag.split('-', 1)
        if len(parts) != 2:
            return
        market, phase = parts
        from clawock.automation import workflow_outcomes
        job = workflow_outcomes.job_for(market, phase)
    from clawock.automation import workflow_outcomes
    action = event.get('action')
    if action == 'ok':
        status = 'not_required'
    elif action in {'mirror-telegram', 'deterministic-fallback', 'alert-brief-missing'}:
        status = 'success' if event.get('sent_ok') else 'failed'
    else:
        return
    workflow_outcomes.record_stage(
        job,
        'watchdog_delivery',
        status,
        action=action,
        reason=event.get('reason') or event.get('fail_reason'),
    )


def _cron_cli_json(cli_args):
    """Run `openclaw cron <args>` and parse the JSON object it prints (after any
    leading 'Config warnings:' noise). Returns the dict, or None on any failure.
    This is the storage-agnostic path — 6.1 migrated cron from jobs.json/runs/*.jsonl
    into state/openclaw.sqlite, so direct file reads silently return nothing."""
    return _adapter_cron_json(cli_args)


# Set by load_jobs() to record which source served the last call:
#   'cli'    — live gateway (authoritative for payload/model/delivery)
#   'sqlite' — live read-only state DB (authoritative, independent of gateway/temp dir)
#   'fossil' — pre-6.1 jobs.json[.migrated] (STALE for payload — schedule only)
#   'empty'  — nothing readable
# Callers that assert on live payload state (e.g. the cron-contract check) MUST
# consult this and refuse to report failures off a fossil.
LAST_LOAD_SOURCE = None
LAST_RUNS_SOURCE = None


def load_jobs(source='auto'):
    """Cron jobs from auto|cli|sqlite|fossil, recording which source answered.

    The chain itself lives in `clawock.providers.openclaw` so it is reachable
    from an installation. This wrapper exists for the module global: five
    callers read `_watchdog_common.LAST_LOAD_SOURCE` after the call, and the
    cron-contract check refuses to report failures off a fossil.
    """
    global LAST_LOAD_SOURCE
    read = _openclaw.read_jobs(source)
    LAST_LOAD_SOURCE = read.source
    return read.entries


def find_job_id(job_name):
    for j in load_jobs():
        if isinstance(j, dict) and j.get('name') == job_name:
            return j.get('id')
    return None


def read_runs(job_id, source='auto'):
    """Finished-run records for a job, OLDEST→NEWEST (so callers' [-1] = newest).

    Same shape as load_jobs: the CLI → SQLite → fossil chain lives in the
    provider, this keeps LAST_RUNS_SOURCE for the callers that branch on it.
    """
    global LAST_RUNS_SOURCE
    read = _openclaw.read_runs(job_id, source)
    LAST_RUNS_SOURCE = read.source
    return read.entries


def is_today_hkt(ts_ms):
    if not isinstance(ts_ms, (int, float)):
        return False
    return datetime.fromtimestamp(ts_ms / 1000, HKT).date() == datetime.now(HKT).date()


def today_runs(job_id):
    return [r for r in read_runs(job_id) if is_today_hkt(r.get('ts'))]


# kcn's WeChat conversation — last-resort fallback if cron config can't be read.
KCN_WECHAT = ('openclaw-weixin', 'o9cq80-hGTruM-OSs8kNmDOtLVZI@im.wechat', '61bf112daf0d-im-bot')

# kcn's Telegram chat id — the cold-session-proof mirror target (bot @clawock_bot,
# revived 2026-07-03). Only messaged when the watchdog judges a WeChat push dropped.
KCN_TELEGRAM = '2033937852'

# Public full-brief link (rendered from memory/{date}-pre-open.md by GH Pages).
BRIEF_URL_TMPL = 'https://kcnyu.github.io/clawock/memory/{date}-pre-open.html'

_EARLY_SECTION_HEADER = '▎提前布局候选'
_EARLY_BLOCKER_LABELS = {
    'needs_primary_evidence': '缺一手披露',
    'needs_information_confirmation': '缺独立消息确认',
    'overheated_wait_rebreak': '过热，等回踩再突破',
    'leveraged_requires_validated_evidence': '杠杆代理仅观察',
    'no_20d_breakout': '未突破20日高',
    'no_short_peer_leadership': '短期同业领先不足',
}
_EARLY_STATE_LABELS = {
    'exploration_ready': '可小仓试探',
    'wait_pullback_rebreak': '候选·等回踩再突破',
    'wait_information': '候选·等消息确认',
    'candidate_only': '候选·仅观察',
}


def _brief_decision_packet(today):
    manifest = (WS / 'memory' / '.tmp' / f'brief-context-{today}' / 'manifest.json')
    if not manifest.exists():
        return None
    try:
        from clawock.decision import packet as decision_packet
        return decision_packet.read_packet(manifest)
    except Exception:
        return None


def _early_candidate_section(packet):
    """Compact, harness-owned candidate truth, deduplicated by underlying."""
    if not isinstance(packet, dict):
        return ''
    diagnostics = packet.get('add_alpha_diagnostics') or {}
    candidates = diagnostics.get('candidates') or []
    observed = [
        row for row in candidates
        if (row.get('early_trend') or {}).get('observed')
        or row.get('tier') in {'exploration', 'validated'}
    ]
    by_source = {}
    for row in observed:
        source = str(row.get('source_ticker') or row.get('ticker') or '?')
        current = by_source.get(source)
        # Prefer the directly held underlying over a leveraged/proxy row.
        if current is None or (current.get('is_proxy') and not row.get('is_proxy')):
            by_source[source] = row
    idea_count = len(by_source)
    exploration_count = len({
        str(row.get('source_ticker') or row.get('ticker') or '?')
        for row in observed
        if (row.get('early_trend') or {}).get('exploration_ready')
    })
    allowed_count = sum(bool(row.get('allowed')) for row in candidates)
    lines = [
        _EARLY_SECTION_HEADER,
        f'提示 {idea_count} 个底层机会 · 可小仓试探 {exploration_count} · 当前可加仓 {allowed_count}',
    ]
    ranked = sorted(
        by_source.items(),
        key=lambda item: (
            0 if (item[1].get('early_trend') or {}).get('exploration_ready') else 1,
            item[0],
        ),
    )[:2]
    for source, row in ranked:
        early = row.get('early_trend') or {}
        state = _EARLY_STATE_LABELS.get(
            early.get('state'), early.get('state') or row.get('state') or '候选'
        )
        proxies = sorted({
            str(candidate.get('ticker')) for candidate in observed
            if str(candidate.get('source_ticker') or candidate.get('ticker')) == source
            and candidate.get('is_proxy')
        })
        name = source + (f"（{','.join(proxies)} 映射）" if proxies else '')
        blockers = [
            _EARLY_BLOCKER_LABELS.get(blocker, blocker)
            for blocker in early.get('blockers') or []
            if blocker in _EARLY_BLOCKER_LABELS
        ][:2]
        suffix = f"；{'、'.join(blockers)}" if blockers else ''
        lines.append(f'- {name}: {state}{suffix}')
    if not ranked:
        lines.append('- 暂无确定性提前提示；不是“模型没写”，而是价格/同业条件未同时成立')
    return '\n'.join(lines)


def _inject_early_candidate_section(card, packet):
    section = _early_candidate_section(packet)
    if not section:
        return card
    lines = card.splitlines()
    start = next(
        (index for index, line in enumerate(lines)
         if line.strip() == _EARLY_SECTION_HEADER),
        None,
    )
    if start is not None:
        end = start + 1
        while end < len(lines):
            stripped = lines[end].strip()
            if stripped.startswith('▎') or stripped.startswith('📈'):
                break
            end += 1
        lines[start:end] = section.splitlines() + ['']
        return '\n'.join(lines).strip()
    insert = next(
        (index for index, line in enumerate(lines)
         if line.strip().startswith('📈')),
        len(lines),
    )
    prefix = lines[:insert]
    suffix = lines[insert:]
    if prefix and prefix[-1].strip():
        prefix.append('')
    prefix.extend(section.splitlines())
    if suffix:
        prefix.append('')
    return '\n'.join(prefix + suffix).strip()


def build_brief_card(today, decision_packet=None):
    """The WeChat card for the 08:00 盘前深度简报 — single source of truth shared by
    brief_postflight (primary send) and brief_watchdog (backstop).

    Preference order:
      1. LLM-written card at memory/.tmp/brief-card-{date}.txt — the rich TL;DR
         (核心结论 narrative) the model composes in the SKILL's Step 5.
      2. Deterministic fallback from memory/{date}-plan.json (book + ≤4 decisions +
         full-brief link) if the model didn't write the card file — never silent.

    In both paths the harness inserts/replaces the deterministic early-candidate
    section from the generation-bound packet. Model omission cannot hide it.
    """
    url = BRIEF_URL_TMPL.format(date=today)
    decision_packet = decision_packet or _brief_decision_packet(today)
    card_file = WS / 'memory' / '.tmp' / f'brief-card-{today}.txt'
    try:
        if card_file.exists():
            txt = card_file.read_text().strip()
            if txt:
                return _inject_early_candidate_section(txt, decision_packet)
    except Exception:
        pass  # fall through to deterministic build
    lines = [f'📊 盘前深度简报｜{today} 08:00 HKT']
    try:
        plan = json.loads((WS / 'memory' / f'{today}-plan.json').read_text())
        bk = plan.get('book') or {}
        if bk:
            lines.append(f"Book: USD${bk.get('usd_total_pnl', '?')} | "
                         f"HK leg {bk.get('hk_leg_hkd', '?')}HKD | US leg {bk.get('us_leg_usd', '?')}USD")
        acts = [a for a in (plan.get('decisions') or []) if isinstance(a, dict)][:4]
        if acts:
            lines.append('今日动作：')
            for i, a in enumerate(acts, 1):
                condition = a.get('condition') or {}
                trig = condition.get('price')
                trig = f"@{trig}" if trig is not None else (condition.get('type') or '')
                conf = a.get('confidence')
                conf = f" conf{round(float(conf) * 100)}%" if conf is not None else ''
                lines.append(f"{i}. {a.get('ticker', '?')} [{a.get('strategy_id', '?')}] {a.get('action', '')} {trig}{conf}")
    except Exception:
        pass  # link-only fallback
    lines += ['', f'📈 完整报告：{url}']
    return _inject_early_candidate_section('\n'.join(lines), decision_packet)


def resolve_wechat_target(market=None):
    """(channel, to, accountId) for kcn's WeChat conversation, read from cron
    config (`cron list --json`, storage-agnostic, doesn't rot if the bot is
    re-paired). All cron jobs target the same conversation, so any job's WeChat
    delivery target works; `market` is accepted for API symmetry. Falls back to
    the known constant. Used by intraday_postflight (primary sender) + watchdog."""
    d = _cron_cli_json(['list', '--json'])
    if isinstance(d, dict):
        for j in d.get('jobs', []):
            dl = j.get('delivery') or {}
            if dl.get('channel') == 'openclaw-weixin' and dl.get('to'):
                return dl.get('channel'), dl.get('to'), dl.get('accountId')
    return KCN_WECHAT


def _delivery(account=None):
    """The delivery provider for this workspace. OpenClaw today, by construction
    swappable — that is the whole point of the interface."""
    from clawock.providers.delivery import OpenClawDelivery
    return OpenClawDelivery(account=account)


def send_wechat(channel, to, account, message, dry_run):
    """Deliver to WeChat through the delivery provider. Returns (ok, tail).

    Now routed through clawock.providers.delivery. `ok` is unchanged: the
    provider reports `failed` exactly where this used to see a non-zero exit,
    so every caller keeps the same two-state answer. The richer status —
    WeChat's success is `unknown`, never `confirmed`, because the cold session
    can drop it silently — is available to callers that ask for it, and
    migrating the watchdogs' mirror-on-suspicion logic onto it is a separate
    change with live delivery consequences.
    """
    result = _delivery(account).send(channel, str(to), message, dry_run=dry_run)
    return result.status != 'failed', result.detail


def send_telegram(target, message, dry_run):
    """Deliver to Telegram through the delivery provider. Returns (ok, tail).

    Telegram is the cold-session-proof backup channel: unlike WeChat it has no
    idle-session silent-drop (the #81096/#81316 wontfix), so when the intraday
    watchdog judges a WeChat push probably dropped it mirrors here instead."""
    result = _delivery().send('telegram', str(target), message, dry_run=dry_run)
    return result.status != 'failed', result.detail


BRIEF_CONTRACT_MODE = 'daily-deep-brief'
# The runtime marks a run failed with these; anything else (including a missing
# status) is not evidence that the attempt is over.
FAILED_RUN_STATUSES = {'error', 'failed', 'failure', 'timeout', 'timed_out',
                       'cancelled', 'canceled'}


def _brief_job_names():
    """Names the contract gives the daily deep brief, or an empty set.

    The contract already names exactly one `daily-deep-brief` job, so renaming
    it there cannot leave a watchdog looking for a job that no longer exists.
    """
    try:
        from clawock.scheduling import load_contract

        return {job.get('name') for job in load_contract().get('jobs', [])
                if job.get('mode') == BRIEF_CONTRACT_MODE}
    except Exception:
        return set()


def brief_cron_job():
    """The live cron job for the daily deep brief, or None if it cannot be read."""
    names = _brief_job_names()
    if not names:
        return None
    listing = _cron_cli_json(['list', '--json'])
    if not isinstance(listing, dict):
        return None
    for job in listing.get('jobs') or []:
        if job.get('name') in names:
            return job
    return None


def brief_cron_job_state():
    """Same job, read straight from the runtime's state DB instead of the CLI.

    The CLI round-trips through the gateway, which on a bad morning is a
    component that may be hung — and its 120s subprocess timeout would then be
    120s of a caller holding still. SQLite is a local read-only file open with
    its own 5s timeout, it is authoritative for exactly the runtime state this
    is wanted for (`consecutiveErrors`), and it answers whether or not the
    gateway is alive.
    """
    names = _brief_job_names()
    if not names:
        return None
    for job in _openclaw.read_jobs('sqlite').entries:
        if isinstance(job, dict) and job.get('name') in names:
            return job
    return None


def cron_run_ended_in_failure(job, today, now=None):
    """Did this job's latest run already end in failure, today?

    Three answers, not two. `None` means no evidence — an unreadable job, a job
    still running, or one whose last run was another day — and a watchdog must
    not act on it, because absence of a report is what #490 showed gets
    misread as a failure.
    """
    if not isinstance(job, dict):
        return None
    state = job.get('state') if isinstance(job.get('state'), dict) else {}
    if job.get('status') == 'running' or state.get('runningAtMs') is not None:
        return None
    last_status = str(state.get('lastStatus') or state.get('lastRunStatus') or '').lower()
    last_run_at = state.get('lastRunAtMs')
    if not isinstance(last_run_at, (int, float)):
        return None
    ran_on = datetime.fromtimestamp(last_run_at / 1000, HKT).strftime('%Y-%m-%d')
    if ran_on != today:
        return None
    if last_status in FAILED_RUN_STATUSES:
        return True
    return False if last_status else None


def rerun_cron_job(job_id, dry_run=False):
    """Queue one more run of an on-host cron job. Returns (ok, tail)."""
    if dry_run:
        return True, f'(dry-run) openclaw cron run {job_id}'
    return _openclaw.run_cron_job(job_id)


def cron_retry_budget(job):
    """Has this job run out of runtime retries? See providers.openclaw."""
    return _openclaw.cron_retry_budget(job)


# Raising `cron.retry.maxAttempts` past this is rejected by the runtime's config
# schema, so it bounds what the operator can do about an exhausted budget.
CRON_MAX_ALLOWED_ATTEMPTS = _openclaw.RUNTIME_MAX_ALLOWED_ATTEMPTS


def dispatch_brief_fallback(dry_run=False):
    """Fire .github/workflows/brief-fallback.yml on demand. Returns (ok, tail_of_output).

    Why the on-box watchdog triggers this instead of leaving it to the workflow's own
    `cron: 25 0 * * 1-5` (08:25 HKT): GHA scheduled crons routinely fire 1-3h late
    (2026-07-15 landed 11:41 HKT), and the workflow refuses to build a pre-open brief
    once HKT hour >= 10 — so its own schedule lands AFTER its own lateness gate and it
    skips. Every fallback run through 2026-07-15 was such a skip; the path had never
    once generated a brief until it was dispatched by hand on 2026-07-16.
    workflow_dispatch has no such delay (observed: job started 9s after the call).

    Off-host on purpose: the box is what dies under the 08:00 brief, so the recovery
    path must not need the box to be healthy — only alive enough to make one API call."""
    from clawock.providers.delivery import delivery_disabled

    cmd = ['gh', 'workflow', 'run', 'brief-fallback.yml']
    if delivery_disabled():
        return False, 'outbound dispatch blocked by CLAWOCK_DELIVERY_DISABLED'
    if dry_run:
        return True, '(dry-run) ' + ' '.join(cmd)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=str(WS))
        return r.returncode == 0, (r.stdout + r.stderr)[-400:]
    except Exception as e:
        return False, str(e)[:300]


BRIEF_FALLBACK_WORKFLOW = 'brief-fallback.yml'
# 09:05 dispatch + this budget must finish before 10:00 HKT, after which
# brief-fallback.yml refuses to build a pre-open brief anyway. Observed runtime is
# ~5-8 min (2026-08-11: 8m01s), so 15 min covers a slow run without risking the
# hard cutoff, and a timeout here is reported as 'pending', never as success.
BRIEF_FALLBACK_POLL_BUDGET_S = 15 * 60
BRIEF_FALLBACK_POLL_INTERVAL_S = 30


def _parse_iso(value):
    """Timezone-aware datetime from an ISO-8601 string, or None.

    Both offset forms have to normalise to the same instant: the dispatch timestamp is
    written in HKT (`...T09:05:04+08:00`) while GitHub reports `createdAt` in UTC
    (`...T01:05:04Z`). Comparing those as strings ranks the UTC one earlier and drops
    the very run we just dispatched, which would make every outcome 'unknown'."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None


def _gh_json(args, timeout=60):
    """Run a `gh` command expecting JSON on stdout. Returns (parsed, error).

    `error` is None only on success. Keeping it separate matters here: a lookup
    that FAILED and a lookup that found nothing used to collapse into the same
    `None`, so a broken `gh` reported itself as "no run found" — the same shape
    of lie this function's only consumer exists to stop telling.
    """
    try:
        r = subprocess.run(['gh'] + args, capture_output=True, text=True,
                           timeout=timeout, cwd=str(WS))
    except Exception as e:
        return None, f'gh {args[0]} failed: {str(e)[:120]}'
    if r.returncode != 0:
        return None, f'gh {args[0]} exited {r.returncode}: {(r.stderr or "").strip()[:120]}'
    try:
        return json.loads(r.stdout), None
    except Exception as e:
        return None, f'gh {args[0]} returned unparseable JSON: {str(e)[:120]}'


_RUN_URL_RE = re.compile(r'/actions/runs/(\d+)')


def run_id_from_dispatch_out(dispatch_out):
    """The run id `gh workflow run` already printed, or None.

    `dispatch_brief_fallback` returns the run's URL. Reading the id out of it
    beats re-discovering the run by timestamp, which is what #512 was: the
    dispatch stamp carries microseconds, GitHub truncates `createdAt` to the
    second, and the run we had just dispatched always sorted as "older than the
    dispatch" and got discarded."""
    m = _RUN_URL_RE.search(str(dispatch_out or ''))
    return m.group(1) if m else None


def await_brief_fallback_outcome(since_iso, dry_run=False,
                                 budget_s=BRIEF_FALLBACK_POLL_BUDGET_S,
                                 interval_s=BRIEF_FALLBACK_POLL_INTERVAL_S,
                                 sleep=time.sleep, now=None, dispatch_out=None):
    """Block until the dispatched brief-fallback run finishes. Returns (state, detail).

    state is one of 'success' | 'failure' | 'pending' | 'unknown'.

    Why this exists (2026-08-11): `dispatch_brief_fallback` returns the exit status of
    `gh workflow run`, i.e. "the dispatch was accepted" — and the 09:05 alert used that
    to tell kcn "✅ 已 dispatch ... 约 5-10 分钟落盘并 push". That day the dispatch was
    accepted and the run failed 8 minutes later (the model hit max_tokens, so plan.json
    never validated and nothing was written). Both the on-box 08:00 path and the only
    automatic recovery path were dead, and the last signal kcn received was a green
    check. Detecting a miss and then reporting a fabricated success is worse than not
    detecting it, so the miss alert now reports what the run actually did.

    Never returns 'success' on a timeout or on any lookup failure: an unverified run is
    'pending'/'unknown', which the alert renders as "outcome unverified", not as done."""
    now = now or (lambda: datetime.now(HKT))
    if dry_run:
        return 'pending', '(dry-run) outcome polling skipped'

    deadline = now().timestamp() + budget_s
    # Preferred: the dispatch already told us WHICH run this is, so no time-window
    # heuristic is needed at all (#512). It also removes the "two dispatches in the
    # same minute" ambiguity the search path never handled.
    run_id = run_id_from_dispatch_out(dispatch_out)
    # A dispatch we cannot date cannot be used to reject stale runs, so fall back to
    # "any run" rather than silently discarding every candidate.
    since = _parse_iso(since_iso)
    if since is not None:
        # GitHub reports createdAt truncated to the second while the dispatch stamp
        # carries microseconds, and `gh workflow run` only returns once the run
        # exists — so the run we just dispatched lands in the SAME second and used
        # to compare as strictly older, discarding the only candidate that could
        # ever match (#512: two consecutive days recorded 'unknown' for runs that
        # had actually FAILED). Truncating our side too compares like with like.
        since = since.replace(microsecond=0)
    run = None
    lookup_error = None
    while True:
        if run_id:
            run, lookup_error = _gh_json(
                ['run', 'view', run_id,
                 '--json', 'databaseId,status,conclusion,url,createdAt'])
        else:
            runs, lookup_error = _gh_json(
                ['run', 'list', '--workflow', BRIEF_FALLBACK_WORKFLOW,
                 '--event', 'workflow_dispatch', '--limit', '5',
                 '--json', 'databaseId,status,conclusion,url,createdAt'])
            if runs:
                # Only consider runs created at/after our dispatch, so a stale earlier
                # run can never be mistaken for this one's outcome. Compared as instants:
                # the two sides arrive in different timezones (see _parse_iso).
                dated = [(r, _parse_iso(r.get('createdAt'))) for r in runs]
                fresh = [(r, t) for r, t in dated
                         if t is not None and (since is None or t >= since)]
                if fresh:
                    run = max(fresh, key=lambda rt: rt[1])[0]
        if run and run.get('status') == 'completed':
            conclusion = run.get('conclusion') or 'unknown'
            url = run.get('url') or ''
            if conclusion == 'success':
                return 'success', url
            return 'failure', f'{conclusion} {url} {_gh_run_failure_detail(run)}'.strip()
        if now().timestamp() + interval_s > deadline:
            if run:
                return 'pending', (f'still {run.get("status") or "unknown"} after '
                                   f'{budget_s // 60}min: {run.get("url") or ""}')
            # "we could not look" and "there is nothing to find" are different
            # facts, and the alert should not present the first as the second.
            if lookup_error:
                return 'unknown', (f'run lookup kept failing for '
                                   f'{budget_s // 60}min: {lookup_error}')
            scope = f'run {run_id}' if run_id else 'workflow_dispatch run'
            return 'unknown', f'no {scope} found within {budget_s // 60}min'
        sleep(interval_s)


def _gh_run_failure_detail(run, max_len=300):
    """Best-effort one-line reason a fallback run failed; '' when unavailable."""
    run_id = run.get('databaseId')
    if not run_id:
        return ''
    try:
        r = subprocess.run(['gh', 'run', 'view', str(run_id), '--log-failed'],
                           capture_output=True, text=True, timeout=120, cwd=str(WS))
    except Exception:
        return ''
    if r.returncode != 0:
        return ''
    # Keep the last real output lines; the failing step's error is at the tail.
    lines = [ln.split('\t')[-1].strip() for ln in r.stdout.splitlines() if ln.strip()]
    lines = [ln for ln in lines if not ln.startswith('##[group]')]
    return ' / '.join(lines[-3:])[:max_len]


def cosend_telegram(message, tag, dry_run=False):
    """Unconditional Telegram co-send for high-value cron reports (brief / staged
    report / intraday). Called from each postflight RIGHT AFTER the WeChat send.

    WHY ALWAYS, not on cold-detection (2026-07-03, kcn's call): WeChat cannot
    confirm REAL delivery — a cold-session silent drop still returns a messageId
    and sent_ok=true (#81096/#81316 wontfix), so no marker/token signal reliably
    tells a landed send from a dropped one. Rather than guess the WeChat state, we
    ALWAYS also push the same body to Telegram (the cold-proof channel, @clawock_bot).
    A duplicate when WeChat did land is far cheaper than a silent miss. Best-effort:
    never raises; logs the outcome to watchdog.jsonl. Returns (ok, tail_of_output)."""
    try:
        ok, out = send_telegram(KCN_TELEGRAM, message, dry_run)
    except Exception as e:
        ok, out = False, str(e)[:300]
    log({'tag': tag, 'action': 'telegram-cosend', 'sent_ok': bool(ok), 'dry_run': bool(dry_run)})
    return ok, out


def already_delivered(marker_path, within_ms=None):
    """Idempotency guard for a postflight's PRIMARY send — returns True if a prior
    run of this same slot already delivered (WeChat OR Telegram), so the send must
    be skipped.

    WHY (2026-07-11): openclaw marks a cron run `error` and AUTO-RETRIES the whole
    agent turn when the *post-turn summary generation* fails — its model fallback
    chain (minimax→glm→deepseek→anthropic…) is frequently all-down (overloaded /
    billing / session-limit; see memory: openclaw-xiaomi-fallback). But the WeChat
    report already went out inside that turn, so each retry re-runs the harness and
    re-sends → kcn got the same slot 2–4×. The delivery layer is per-run single-send;
    the dup is at the RUN layer. This guard makes the postflight send idempotent per
    slot regardless of how many times openclaw retries. Genuine misses (marker shows
    neither channel succeeded) are NOT blocked, and the watchdog remains the backstop.

    marker_path : the per-slot send marker written by the postflight
      (report-sent-{market}-{phase}-{date}.json, brief-sent-{date}.json,
       intraday-sent-{market}.json).
    within_ms   : None → any-age marker blocks (report/brief markers are keyed per
      phase+date and legitimately fire once/day). Set a window for intraday, whose
      marker is per-market (not per-slot): a retry lands within minutes while the
      legit next slot is ~30min later, so only a *recent* marker means "retry".
    """
    try:
        m = json.loads(Path(marker_path).read_text())
    except Exception:
        return False
    if not (m.get('sent_ok') or m.get('tg_ok')):
        return False
    if within_ms is not None:
        age = int(datetime.now().timestamp() * 1000) - (m.get('ts') or 0)
        if age >= within_ms:
            return False
    return True


# A claim older than this is not a concurrent sender: report slots are hours
# apart and the whole postflight (send → cosend → marker → commit) runs in about
# a minute. The window only has to outlast one postflight, and it must expire so
# a crashed sender cannot mute a later slot forever.
SEND_CLAIM_STALE_MS = 30 * 60 * 1000


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _write_claim(path, payload):
    tmp = Path(f'{path}.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False))
    os.replace(tmp, path)


def claim_send(claim_path, *, stale_after_ms=SEND_CLAIM_STALE_MS, now_ms=None):
    """Take the right to send this slot BEFORE sending. Returns (won, reason).

    WHY (2026-08-13, #508): `already_delivered` reads the send marker, but the
    marker is only written AFTER WeChat AND the Telegram cosend have returned —
    about 54s after a postflight starts. Two postflights racing inside that
    window both read "never delivered today" and both send. That is exactly what
    kcn got on the 09:30 hk-open slot: the model's exec shell hit its 60s
    overall-timeout, SIGTERM killed the shell but not the postflight child, the
    model read that as a failure and re-ran the same command, and WeChat got the
    report twice (Telegram once — the first process died between the two sends,
    which is what proves it had already reached WeChat).

    The claim closes that window because it is taken before the first send, not
    after the last one. O_EXCL is the whole lock.

    A claim whose holder is gone is only taken over when the holder had NOT
    started sending. If it died mid-send we cannot know whether WeChat got the
    message, and a duplicate is the failure kcn actually reported — so we skip
    and let the watchdog's marker-based backstop own the slot. That keeps the
    guard from silencing a genuine miss (`feedback-detect-but-never-silence`):
    no marker gets written, so the watchdog still sees an undelivered slot.

    Never blocks delivery on its own plumbing: if the claim file cannot be
    created or read, this fails OPEN (sends anyway). A duplicate is recoverable,
    a silently unsent report is the failure this whole harness exists to stop.
    """
    path = Path(claim_path)
    now = int(datetime.now().timestamp() * 1000) if now_ms is None else now_ms
    mine = {'pid': os.getpid(), 'ts': now, 'send_started_at': None}
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        pass
    except OSError as e:
        return True, f'claim-unavailable-fail-open: {e}'
    else:
        with os.fdopen(fd, 'w') as f:
            f.write(json.dumps(mine, ensure_ascii=False))
        return True, 'claimed'

    try:
        held = json.loads(path.read_text())
    except Exception as e:
        # An unreadable claim proves nothing about a send. Fail open.
        return True, f'claim-unreadable-fail-open: {e}'

    held_ts = held.get('ts')
    if not isinstance(held_ts, (int, float)) or now - held_ts >= stale_after_ms:
        _write_claim(path, mine)
        return True, 'took-over-stale-claim'
    holder = held.get('pid')
    if holder and _pid_alive(holder):
        return False, 'in-flight'
    if held.get('send_started_at'):
        return False, 'holder-died-mid-send'
    _write_claim(path, mine)
    return True, 'took-over-claim-of-holder-that-never-sent'


def release_claim(claim_path):
    """Drop the claim once this slot's send has run to completion (marker written).

    Without this the claim outlives the process that finished normally, and a
    LATER slot can be refused by it. Concretely: an intraday send that failed
    leaves a marker with sent_ok=false/tg_ok=false, so `already_delivered`
    correctly does not block the next slot — but a surviving claim carrying
    `send_started_at` would, and the next slot would go out as nothing at all.

    After release, "a claim exists" means exactly "a sender died holding it",
    which is the only case the claim is meant to arbitrate. The marker, not the
    claim, is what keeps a completed send from being repeated.
    """
    try:
        Path(claim_path).unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        print(f'warn: send claim release failed: {e}', file=sys.stderr)


def mark_send_started(claim_path):
    """Record that the send is now in flight, so a claim left behind by a killed
    process is readable as "may already have reached WeChat" rather than "never
    got going". Best-effort: a claim we cannot update just looks stale later,
    which fails toward sending, never toward silence."""
    path = Path(claim_path)
    try:
        held = json.loads(path.read_text())
    except Exception:
        held = {'pid': os.getpid()}
    held['send_started_at'] = int(datetime.now().timestamp() * 1000)
    try:
        _write_claim(path, held)
    except Exception as e:
        print(f'warn: send claim update failed: {e}', file=sys.stderr)


def last_report_text(session_id, first_line):
    """The actual announced intraday report — the last assistant text block in
    the cron session transcript that contains the data block's first line. We
    mirror THIS verbatim to Telegram (not the run-record `summary`, which is
    truncated meta-prose). Returns the text, or None if not found."""
    if not session_id:
        return None
    p = SESSIONS_DIR / f'{session_id}.jsonl'
    if not p.exists():
        return None
    found = None
    try:
        for line in p.read_text().splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            m = e.get('message', e)
            if m.get('role') != 'assistant':
                continue
            c = m.get('content')
            texts = []
            if isinstance(c, list):
                texts = [b.get('text', '') for b in c
                         if isinstance(b, dict) and b.get('type') == 'text']
            elif isinstance(c, str):
                texts = [c]
            for t in texts:
                if first_line and first_line in t:
                    # trim any leading model meta-prose ("Postflight passed…")
                    # so the mirror starts clean at the report's first line.
                    found = t[t.index(first_line):]  # keep LAST match = delivered report
    except Exception as e:
        print(f'(report extract failed: {e})', file=sys.stderr)
    return found


def same_generation_window(marker, ctx_generated_at, *, window_s, backward_s):
    """Was the delivered report built from THIS slot's data, a regeneration apart?

    The preflight `context_id` is a per-invocation hash, so an openclaw auto-retry
    (re-runs preflight, then hits postflight's idempotency lock and deliberately
    does NOT rewrite the marker) guarantees the two ids differ — the one case an
    id compare exists to survive. Comparing the source contexts' own timestamps
    separates that from the failure the id compare was added for (2026-07-24
    美股收盘报告 delivered 07/22 numbers): a retry regenerates minutes later, a
    genuinely stale body is a whole slot, or a day, behind.

    The window is asymmetric — a retry's context is always the NEWER one, so only
    a small backward tolerance is allowed for clock and write ordering. Its size
    belongs to the caller: report phases sit hours apart, Mode 7 slots 30 minutes,
    and a window at or above the cadence would call the previous slot a retry.

    Shared rather than copied on purpose. Mode 6 was fixed on 2026-08-03 and Mode
    7 kept paying for the same bug until 2026-08-10 (#458) because the rule lived
    in one file and the second mode never learned it.
    """
    marker_at = marker.get('context_generated_at')
    if not marker_at or not ctx_generated_at:
        return False
    try:
        delta = (datetime.fromisoformat(ctx_generated_at)
                 - datetime.fromisoformat(marker_at)).total_seconds()
    except (TypeError, ValueError):
        return False
    return -backward_s <= delta <= window_s


def transcript_loop_score(session_id):
    """Max repeat-count of any 50-char window across all assistant text in the
    session transcript. A clean run scores ~1-2; the mimo repeat-loop failure
    scores high (≈7+). Returns (score, blob_len); (0, 0) if no transcript."""
    if not session_id:
        return 0, 0
    p = SESSIONS_DIR / f'{session_id}.jsonl'
    if not p.exists():
        return 0, 0
    txt = []
    try:
        for line in p.read_text().splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            m = e.get('message', e)
            if m.get('role') != 'assistant':
                continue
            c = m.get('content')
            if isinstance(c, list):
                txt += [b.get('text', '') for b in c
                        if isinstance(b, dict) and b.get('type') == 'text']
            elif isinstance(c, str):
                txt.append(c)
    except Exception as e:
        print(f'(transcript read failed: {e})', file=sys.stderr)
        return 0, 0
    blob = '\n'.join(txt)
    if len(blob) < 300:
        return 0, len(blob)
    windows = [blob[i:i + 50] for i in range(0, len(blob) - 50, 25)]
    top = Counter(windows).most_common(1)
    return (top[0][1] if top else 0), len(blob)
