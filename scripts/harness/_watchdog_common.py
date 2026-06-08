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
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

WS = Path(__file__).resolve().parents[2]
OC = Path('/root/.openclaw')
RUNS_DIR = OC / 'cron' / 'runs'
JOBS_JSON = OC / 'cron' / 'jobs.json'
SESSIONS_DIR = OC / 'agents' / 'main' / 'sessions'
LOG = WS / 'logs' / 'watchdog.jsonl'
HKT = timezone(timedelta(hours=8))
OPENCLAW_BIN = '/root/.local/share/pnpm/openclaw'


def log(event):
    """Append one JSON line to logs/watchdog.jsonl. Never raises."""
    try:
        event['ts'] = datetime.now(HKT).isoformat()
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open('a') as f:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f'(watchdog log failed: {e})', file=sys.stderr)


def _cron_cli_json(cli_args):
    """Run `openclaw cron <args>` and parse the JSON object it prints (after any
    leading 'Config warnings:' noise). Returns the dict, or None on any failure.
    This is the storage-agnostic path — 6.1 migrated cron from jobs.json/runs/*.jsonl
    into state/openclaw.sqlite, so direct file reads silently return nothing."""
    try:
        r = subprocess.run([OPENCLAW_BIN, 'cron', *cli_args],
                           capture_output=True, text=True, timeout=30)
        txt = r.stdout
        i = txt.find('{')
        if i < 0:
            return None
        return json.loads(txt[i:])
    except Exception:
        return None


def load_jobs():
    # Primary: CLI (works on 6.1 SQLite). Fallback: pre-migration jobs.json[.migrated].
    d = _cron_cli_json(['list', '--json'])
    if isinstance(d, dict) and isinstance(d.get('jobs'), list):
        return d['jobs']
    for p in (JOBS_JSON, JOBS_JSON.with_suffix('.json.migrated')):
        try:
            data = json.loads(p.read_text())
            return data if isinstance(data, list) else data.get('jobs', data.get('items', []))
        except Exception:
            continue
    return []


def find_job_id(job_name):
    for j in load_jobs():
        if isinstance(j, dict) and j.get('name') == job_name:
            return j.get('id')
    return None


def read_runs(job_id):
    """Finished-run records for a job, OLDEST→NEWEST (so callers' [-1] = newest).
    Primary: `openclaw cron runs` CLI (SQLite-backed on 6.1). Fallback: the old
    per-job JSONL (now *.jsonl.migrated after the 6.1 migration)."""
    d = _cron_cli_json(['runs', '--id', job_id])
    if isinstance(d, dict) and isinstance(d.get('entries'), list):
        finished = [e for e in d['entries'] if e.get('action') in (None, 'finished')]
        # CLI returns newest-first; reverse to match the old append-order contract.
        return list(reversed(finished))
    out = []
    for cand in (RUNS_DIR / f'{job_id}.jsonl', RUNS_DIR / f'{job_id}.jsonl.migrated'):
        if not cand.exists():
            continue
        for line in cand.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        break
    return out


def is_today_hkt(ts_ms):
    if not isinstance(ts_ms, (int, float)):
        return False
    return datetime.fromtimestamp(ts_ms / 1000, HKT).date() == datetime.now(HKT).date()


def today_runs(job_id):
    return [r for r in read_runs(job_id) if is_today_hkt(r.get('ts'))]


def resolve_target(runs):
    """WeChat target from this job's most recent successful delivery resolution,
    so we send wherever the job normally sends (no hardcoded account that rots
    when the bot is re-paired). Returns (channel, to, accountId)."""
    for r in reversed(runs):
        d = (r.get('delivery') or {}).get('resolved') or {}
        if d.get('ok') and d.get('to'):
            return d.get('channel'), d.get('to'), d.get('accountId')
    return None, None, None


# kcn's WeChat conversation — last-resort fallback if cron config can't be read.
KCN_WECHAT = ('openclaw-weixin', 'o9cq80-hGTruM-OSs8kNmDOtLVZI@im.wechat', '61bf112daf0d-im-bot')

# Public full-brief link (rendered from memory/{date}-pre-open.md by GH Pages).
BRIEF_URL_TMPL = 'https://kcnyu.github.io/clawock/memory/{date}-pre-open.html'


def build_brief_card(today):
    """The WeChat card for the 08:00 盘前深度简报 — single source of truth shared by
    brief_postflight (primary send) and brief_watchdog (backstop).

    Preference order:
      1. LLM-written card at memory/.tmp/brief-card-{date}.txt — the rich TL;DR
         (核心结论 narrative) the model composes in the SKILL's Step 5. Sent verbatim.
      2. Deterministic fallback from memory/{date}-plan.json (book + ≤4 actions +
         full-brief link) if the model didn't write the card file — never silent.
    """
    url = BRIEF_URL_TMPL.format(date=today)
    card_file = WS / 'memory' / '.tmp' / f'brief-card-{today}.txt'
    try:
        if card_file.exists():
            txt = card_file.read_text().strip()
            if txt:
                return txt
    except Exception:
        pass  # fall through to deterministic build
    lines = [f'📊 盘前深度简报｜{today} 08:00 HKT']
    try:
        plan = json.loads((WS / 'memory' / f'{today}-plan.json').read_text())
        bk = plan.get('book') or {}
        if bk:
            lines.append(f"Book: USD${bk.get('usd_total_pnl', '?')} | "
                         f"HK leg {bk.get('hk_leg_hkd', '?')}HKD | US leg {bk.get('us_leg_usd', '?')}USD")
        acts = [a for a in (plan.get('actions') or []) if isinstance(a, dict)][:4]
        if acts:
            lines.append('今日动作：')
            for i, a in enumerate(acts, 1):
                trig = a.get('trigger_price')
                trig = f"@{trig}" if trig is not None else (a.get('trigger_type') or '')
                conf = a.get('confidence')
                conf = f" conf{round(float(conf) * 100)}%" if conf is not None else ''
                lines.append(f"{i}. {a.get('ticker', '?')} {a.get('bucket', '')} {trig}{conf}")
    except Exception:
        pass  # link-only fallback
    lines += ['', f'📈 完整报告：{url}']
    return '\n'.join(lines)


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


def send_wechat(channel, to, account, message, dry_run):
    """openclaw message send. Returns (ok, tail_of_output)."""
    cmd = [OPENCLAW_BIN, 'message', 'send',
           '--channel', channel, '--target', to, '-m', message, '--json']
    if account:
        cmd[3:3] = ['--account', account]
    if dry_run:
        cmd.append('--dry-run')
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return r.returncode == 0, (r.stdout + r.stderr)[-400:]


def send_telegram(target, message, dry_run):
    """openclaw message send to Telegram. Returns (ok, tail_of_output).

    Telegram is the cold-session-proof backup channel: unlike WeChat it has no
    idle-session silent-drop (the #81096/#81316 wontfix), so when the intraday
    watchdog judges a WeChat push probably dropped it mirrors here instead."""
    cmd = [OPENCLAW_BIN, 'message', 'send',
           '--channel', 'telegram', '--target', str(target), '-m', message, '--json']
    if dry_run:
        cmd.append('--dry-run')
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return r.returncode == 0, (r.stdout + r.stderr)[-400:]


def cron_session_ids():
    """Set of every cron run's sessionId (across all cron/runs/*.jsonl). Used to
    EXCLUDE cron sessions when looking for kcn's last human inbound — cron runs
    live in the same agents/main/sessions/ dir and their 'user' turn is the
    harness prompt (every 30min), which would otherwise look like fresh human
    activity and keep the session perpetually 'warm'."""
    ids = set()
    if not RUNS_DIR.exists():
        return ids
    for p in RUNS_DIR.glob('*.jsonl'):
        try:
            for line in p.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                sid = json.loads(line).get('sessionId')
                if sid:
                    ids.add(sid)
        except Exception:
            continue
    return ids


def last_human_inbound_ms(before_ms=None, lookback_hours=24):
    """Timestamp (ms) of kcn's most recent inbound message to the bot, optionally
    only counting messages at/before `before_ms`. Scans non-cron main-agent
    session transcripts (mtime within lookback_hours) for role=user entries.

    This is our session-warmth proxy: the WeChat cold-session drop has NO read
    receipt and `delivered` is poisoned (always true), so the only honest signal
    of 'did kcn actually get it' is how long since kcn last talked to the bot.
    Returns None if no human inbound found in the window.

    Synthetic role=user turns are excluded: cron harness prompts (via cron
    sessions) and — critically — the `[OpenClaw heartbeat poll]` injected every
    hour, which would otherwise masquerade as a fresh human message and keep the
    session perpetually 'warm' (2026-06-02: a 10:50 heartbeat made an 11:30 cold
    session read as idle=39m and suppressed the Telegram backup)."""
    if not SESSIONS_DIR.exists():
        return None
    cron_ids = cron_session_ids()
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    floor_ms = now_ms - lookback_hours * 3600 * 1000
    best = None
    for p in SESSIONS_DIR.glob('*.jsonl'):
        if p.name.endswith('.trajectory.jsonl'):
            continue
        if p.stem in cron_ids:
            continue
        try:
            if p.stat().st_mtime * 1000 < floor_ms:
                continue
        except OSError:
            continue
        try:
            for line in p.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                m = e.get('message', e)
                if m.get('role') != 'user':
                    continue
                ts = m.get('timestamp')
                if not isinstance(ts, (int, float)):
                    continue
                if before_ms is not None and ts > before_ms:
                    continue
                if _is_synthetic_user(m.get('content')):
                    continue
                if best is None or ts > best:
                    best = ts
        except Exception:
            continue
    return best


def _is_synthetic_user(content):
    """True if a role=user turn is machine-injected (heartbeat poll, system tag)
    rather than a real kcn message — must not count as session warmth."""
    if isinstance(content, list):
        text = ' '.join(b.get('text', '') for b in content
                        if isinstance(b, dict) and b.get('type') == 'text')
    elif isinstance(content, str):
        text = content
    else:
        return True
    t = text.strip()
    if not t:
        return True
    return t.startswith('[OpenClaw') or 'heartbeat poll' in t


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
