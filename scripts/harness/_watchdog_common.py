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


# kcn's WeChat conversation — last-resort fallback if cron config can't be read.
KCN_WECHAT = ('openclaw-weixin', 'o9cq80-hGTruM-OSs8kNmDOtLVZI@im.wechat', '61bf112daf0d-im-bot')

# kcn's Telegram chat id — the cold-session-proof mirror target (bot @clawock_bot,
# revived 2026-07-03). Only messaged when the watchdog judges a WeChat push dropped.
KCN_TELEGRAM = '2033937852'

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
