"""
_harness_common.py — shared helpers for brief/report/intraday harness scripts.

Extracted to avoid duplicating _git / rebuild_dashboard / push retry logic
across multiple postflight scripts. All functions accept the workspace root
as path argument or default to the resolved workspace root.
"""
from clawock.utilities import PACKAGED_UTILITIES
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from clawock.workspace import workspace_root

WS = workspace_root(Path.cwd())
_CHECKOUT = WS

# Single-publisher mutex for all dashboard build outputs (Option 1, 2026-07-04).
# Shared by the host harness rebuild and publish_dashboard.sh crontab so the two
# never build/write the generated files concurrently.
DASHBOARD_PUBLISH_LOCK = '/tmp/dashboard_publish.lock'

# Where rebuild_dashboard records its last outcome so the daily cron health
# check can surface silent build failures / degradations (kcn doesn't want
# per-cron alerts — see feedback_no_individual_cron_alerts).
DASHBOARD_BUILD_STATUS = 'logs/dashboard_build_status.json'


def compute_context_id(result):
    """A per-GENERATION id for a preflight output.

    The model echoes it back to postflight (`--context-id`), which refuses to
    assemble prose against a context that has since been replaced. This is the
    guard the 2026-07-24 incident needed: the agent ran preflight a SECOND time
    mid-turn, so disk held generation B while its prose described generation A —
    'one context per run' is not something the harness can assume.

    NOT a digest of the underlying data: `raw_wechat_block` embeds the fetch
    minute, so any re-run yields a fresh id even with identical portfolio numbers.
    That is the intended contract — the id pins prose to THIS exact preflight
    output, and the failure mode is always fail-safe (a mismatch drops to the
    data block, never marries fresh numbers to stale prose). The only way to get
    a rejection is for prose to carry an id from a superseded generation, which is
    exactly what we want caught. `context_id` itself is not yet in `result`.

    Shared by report_preflight (Mode 6) and intraday_preflight (Mode 7) so both
    legs pin prose the same way.
    """
    blob = json.dumps(result, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def pct(c, pc):
    """Percentage change from pc → c. Returns 0 if pc invalid."""
    if not pc:
        return 0.0
    try:
        return round((float(c) - float(pc)) / float(pc) * 100, 2)
    except Exception:
        return 0.0


def git_cmd(*args, cwd=None):
    """Run git command in workspace. Returns (success_bool, combined_output).

    Harness postflight commits are automated, so they're attributed to the bot via
    per-invocation `-c` (NOT persistent `git config`): this shows github-actions[bot]
    as author WITHOUT clobbering the local git identity that interactive Claude-Code
    sessions commit under (kcn wants those under his own name, automated under bot).
    """
    cwd = cwd or WS
    base = ['git', '-C', str(cwd)]
    if args and args[0] == 'commit':
        base += ['-c', 'user.name=github-actions[bot]',
                 '-c', 'user.email=41898282+github-actions[bot]@users.noreply.github.com']
    try:
        r = subprocess.run(base + list(args),
                           capture_output=True, text=True, timeout=30)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)


def refresh_today_snapshot(ws=None):
    """Overwrite memory/snapshots/{date}.json with current portfolio.json.

    Why: brief_preflight writes today's snapshot at 08:00 HKT before HK open,
    so today_change is stale (often negative) by the time the market closes.
    Calling this before rebuild_dashboard keeps the equity curve's last point
    in sync with the live portfolio. Non-fatal on error.

    Date selection (HKT-aware):
      - Mon-Fri:      write today (HK + US markets active)
      - Sat 00-06:    write Fri (US close at ~04:00/05:00 HKT belongs to Fri)
      - Sun / Sat 07+: skip (no market activity, would create stale snapshot)

    Returns (ok, snapshot_filename_or_message). On skip returns (False, msg)
    — caller should treat as non-fatal.
    """
    from datetime import datetime, timedelta
    ws = ws or WS
    try:
        pf = ws / 'portfolio.json'
        if not pf.exists():
            return False, 'portfolio.json missing'
        now = datetime.now()
        wd = now.weekday()  # Mon=0 .. Sun=6
        if wd <= 4:
            target = now
        elif wd == 5 and now.hour < 7:
            target = now - timedelta(days=1)
        else:
            return False, f'skipped (weekend: {now.strftime("%a %H:%M")})'
        date = target.strftime('%Y-%m-%d')
        snap = ws / 'memory' / 'snapshots' / f'{date}.json'
        snap.write_bytes(pf.read_bytes())
        return True, snap.name
    except Exception as e:
        return False, str(e)


def snapshot_date_for_now():
    """Returns the date string refresh_today_snapshot would write, or None if
    it would skip. Used by callers (like report_postflight) that need to know
    the snapshot filename for git add. Mirrors refresh_today_snapshot's date logic.
    """
    from datetime import datetime, timedelta
    now = datetime.now()
    wd = now.weekday()
    if wd <= 4:
        return now.strftime('%Y-%m-%d')
    if wd == 5 and now.hour < 7:
        return (now - timedelta(days=1)).strftime('%Y-%m-%d')
    return None


# Only files a GH Action actually produces belong here — this list is checked out
# from origin, so anything local wins. `catalysts.json` was in it but no workflow
# has ever built it: `clawock catalysts` runs in brief preflight alone. So
# the sync clobbered each freshly-fetched copy with origin's older one, and since
# it wasn't committed either, origin only moved when an unrelated commit happened
# to sweep it up — a loop that kept it stale from both ends.
GHA_DATA_FILES = ['sentiment.json', 'macro.json', 'us_news_digest.json',
                  'influencer_feed.json']


def sync_gha_data_files(ws=None):
    """Fetch + checkout the latest GH Action–managed data files from origin/master
    without touching the working tree's other changes.

    Why: GH Actions (sentiment/macro/news/catalysts scans) push fresh JSON to remote
    but our local working tree doesn't auto-pull. If we rebuild_dashboard without
    syncing first, dashboard.json embeds stale data — verified 2026-05-22: brief at
    08:06 HKT embedded 5-21 sentiment because the 5-22 sentiment GHA didn't finish
    until 09:27 HKT, and even later commits (16:03) still showed 5-21 data because
    pull-rebase happens AFTER rebuild_dashboard.

    Non-fatal: any step failing just leaves the local copy in place.

    Returns (ok, summary_msg).
    """
    ws = ws or WS
    try:
        fetch = subprocess.run(
            ['git', 'fetch', 'origin', 'master', '--quiet'],
            capture_output=True, text=True, timeout=15, cwd=str(ws),
        )
        if fetch.returncode != 0:
            return False, f'fetch failed: {fetch.stderr[-150:]}'

        relpaths = [f'assets/data/{f}' for f in GHA_DATA_FILES]
        # Fast path: one checkout for the whole batch (this chain runs on every
        # postflight slot; N spawns here were N needless git startups).
        batch = subprocess.run(
            ['git', 'checkout', 'origin/master', '--', *relpaths],
            capture_output=True, text=True, timeout=10, cwd=str(ws),
        )
        if batch.returncode == 0:
            return True, f'synced {len(GHA_DATA_FILES)}/{len(GHA_DATA_FILES)}'
        # A missing artifact on origin would fail the whole batch — fall back to
        # the per-file checkout so the files that do exist still refresh.
        synced = []
        for f in GHA_DATA_FILES:
            r = subprocess.run(
                ['git', 'checkout', 'origin/master', '--', f'assets/data/{f}'],
                capture_output=True, text=True, timeout=10, cwd=str(ws),
            )
            if r.returncode == 0:
                synced.append(f)
        return True, f'synced {len(synced)}/{len(GHA_DATA_FILES)}'
    except Exception as e:
        return False, str(e)


def _record_dashboard_build(build_ok, publish_ok, output, ws=None):
    """Persist build *and* publication outcomes to the dashboard status file.

    Why: report_postflight / brief_postflight call rebuild_dashboard() and discard
    the return value, so a hard crash (returncode!=0) or a silent section
    degradation (`warn:` / `⚠️` lines on stderr) would freeze the dashboard while
    commits keep flowing — invisible until someone eyeballs the live page. This
    file is the single observable surface; cron_health_check reads it at EOD so the
    failure shows up in the daily review instead of as an immediate per-cron alert.

    Non-fatal: never raises.
    """
    ws = ws or WS
    try:
        from datetime import datetime, timezone
        warn_count = sum(
            1 for ln in (output or '').splitlines()
            if 'warn:' in ln or '⚠' in ln or 'FATAL' in ln
        )
        # Counted apart from warn_count on purpose: a repaired sidecar rendered
        # its card, so the build is not degraded and must not ride the health
        # check's exit 2. But an agent that ships invalid JSON every morning is a
        # producer bug, and a repair nobody ever sees is the silent fixer this
        # was explicitly not supposed to become.
        repair_count = sum(
            1 for ln in (output or '').splitlines() if 'repair:' in ln
        )
        ok = bool(build_ok and publish_ok)
        status = {
            'checked_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'ok': ok,
            'build_ok': bool(build_ok),
            # None means publication was not attempted because the build itself
            # failed. Keeping that distinct from a rejected push makes the next
            # operator action unambiguous.
            'publish_ok': None if publish_ok is None else bool(publish_ok),
            'warn_count': warn_count,
            'repair_count': repair_count,
            # Git hooks and remote rules print the useful cause *before* their
            # generic "failed to push" footer. The old 500-char tail hid it.
            'tail': (output or '')[-4000:],
        }
        path = ws / DASHBOARD_BUILD_STATUS
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(status, ensure_ascii=False, indent=2))
        if not build_ok:
            print(f'🔴 dashboard build FAILED — recorded to {DASHBOARD_BUILD_STATUS}; '
                  f'local outputs were not refreshed. tail: {(output or "")[-500:]}',
                  file=sys.stderr)
        elif not publish_ok:
            print(f'🔴 data-plane publish FAILED — recorded to '
                  f'{DASHBOARD_BUILD_STATUS}; local outputs were rebuilt but the '
                  f'public generation may be stale. tail: {(output or "")[-500:]}',
                  file=sys.stderr)
        elif warn_count:
            print(f'⚠️  build_dashboard ok but {warn_count} degraded section(s) — '
                  f'see {DASHBOARD_BUILD_STATUS}', file=sys.stderr)
        elif repair_count:
            print(f'🔧 build_dashboard ok, {repair_count} sidecar(s) needed JSON '
                  f'repair — see {DASHBOARD_BUILD_STATUS}', file=sys.stderr)
    except Exception as e:
        print(f'(could not record dashboard build status: {e})', file=sys.stderr)


def rebuild_dashboard(ws=None):
    """Run the installed dashboard builder to refresh its four public outputs.

    Refreshes today's snapshot AND syncs GH Action-managed data files first, so
    the equity curve reflects latest portfolio state and the embedded sentiment/
    macro/news data are not 24 h stale.

    Records the outcome via _record_dashboard_build so a failure is observable in
    the daily cron health check even when callers discard the return value.

    Returns (ok, diagnostic_output). ``ok`` covers both the local build and the
    data-plane publication. A publication fault must not prevent report delivery,
    but callers must surface it as an operational failure so cron retries and
    health checks cannot turn a frozen public dashboard green.
    """
    ws = ws or WS
    refresh_today_snapshot(ws)
    sync_gha_data_files(ws)
    try:
        # Single-publisher lock (2026-07-04): dashboard outputs now have exactly two
        # writer categories — this harness path and the scheduled
        # publish_dashboard.sh crontab. Data-scan Actions commit sidecars only;
        # the rare off-host brief fallback reuses this same harness path.
        # flock serializes the build so a harness run and
        # the publisher can't interleave writes to the same generated file.
        # --previous: all three postflights publish what they build, so they opt
        # in to restoring cards whose memory/.tmp sidecar is absent (#262 slice 2
        # made workspace-only the builder's default). This is the ONE caller
        # where the flag does something: brief-fallback.yml reaches here through
        # brief_postflight on an Actions checkout that has a brief-context but no
        # insights / intraday / sector-scan sidecars — without it those cards
        # publish blank, the 2026-06-21 regression. On the host it is a no-op.
        # The recovery source is the last PUBLISHED generation, materialised out
        # of the data branch — not this checkout's copy. On a fresh Actions
        # checkout (brief-fallback, the one caller where --previous does
        # anything) there is no copy to read: #314 took the outputs out of the
        # tree, so pointing at the worktree would resolve to nothing exactly
        # where recovery matters. Non-fatal: a missing recovery source must not
        # stop a publish, and build_dashboard reports it loudly either way (#315).
        previous = ws / '.data-plane.cache'
        subprocess.run(
            ['python3', str(ws / 'ops' / 'pages' / 'fetch_data_plane.py'),
             '--into', str(previous)],
            capture_output=True, text=True, timeout=60, cwd=str(ws), check=False,
        )
        from clawock.automation import workflow_outcomes
        workflow_outcomes.publish()
        r = subprocess.run(
            # 走本解释器的 -m 而不是 PATH 上的 console script（#918）：装在
            # 别处的入口点与这里 import 的包可能不是同一份，而缺失时的失败
            # 是安静的（FileNotFoundError 被上面的宽 except 吞掉）。
            ['flock', DASHBOARD_PUBLISH_LOCK,
             sys.executable, '-m', 'clawock', 'dashboard-build',
             '--previous', str(previous / 'assets' / 'data' / 'dashboard.json')],
            capture_output=True, text=True, timeout=30, cwd=str(ws),
        )
        build_ok = r.returncode == 0
        publish_ok = None
        full = r.stdout + r.stderr
        # The decision map rides the same cadence but deliberately not the same
        # generation: `clawock.publish.outputs` owns a four-file write set that
        # is swapped in atomically, and a fifth file whose failure is survivable
        # does not belong inside a contract whose whole point is that all four
        # land or none do. It is a read-only view — a broken one costs a page,
        # not a number — so its return code is recorded and never gates the
        # publish.
        if build_ok:
            try:
                mapped = subprocess.run(
                    [sys.executable, '-m', 'clawock', 'decision-map'],
                    capture_output=True, text=True, timeout=180, cwd=str(ws),
                )
                full += mapped.stdout + mapped.stderr
            except (OSError, subprocess.SubprocessError) as error:
                full += f'\ndecision-map: {error}'
        if build_ok:
            publish_ok, publish_detail = _publish_generation(ws)
            full += publish_detail
        ok = bool(build_ok and publish_ok)
        _record_dashboard_build(build_ok, publish_ok, full, ws)
        return ok, full[-2000:]
    except Exception as e:
        _record_dashboard_build(False, None, str(e), ws)
        return False, str(e)


def _publish_generation(ws):
    """Put the generation this rebuild just produced on the data branch.

    Here rather than in each postflight on purpose. Before #326 a postflight
    published by committing — the commit matched `pages.yml`'s `paths:` and the
    deploy followed. With the outputs untracked that path is gone, so a
    generation built by an intraday slot would sit in the worktree until the next
    scheduled tick: up to 20 minutes, on every slot, which is the opposite of
    what intraday monitoring is for (#328).

    On the shared path every generation-builder already goes through, so a fourth
    postflight gets this by construction. A hand-maintained list of callers is
    exactly what missed three postflights in #319 and had to be repaired in #322.

    Returns ``(ok, detail)``. These callers deliver reports; a publishing fault
    must not take report delivery down with it, but it is still a failed
    postflight and must be visible to cron retry/health surfaces.

    Idempotent: the store compares against what the branch actually holds, so an
    interleaved scheduled tick makes this a no-op rather than a conflict — which
    is why it does not need to hold the build lock.
    """
    try:
        r = subprocess.run(
            ['bash', str(ws / 'ops' / 'publish' / 'publish_generation.sh')],
            capture_output=True, text=True, timeout=120, cwd=str(ws),
        )
    except Exception as e:                       # noqa: BLE001 - reported, not raised
        return False, f'\n  data-plane publish failed: {e}'
    # A failed git push ends with a generic one-line summary. The hook/remote
    # reason precedes it, so 200 characters erased the only actionable evidence
    # in the 2026-08-08 data-plane freeze (#370).
    tail = (r.stdout + r.stderr).strip()[-2000:]
    if r.returncode != 0:
        return False, f'\n  data-plane publish failed: {tail}'
    return True, f'\n  {tail}'


def dashboard_publication_state(ws=None):
    """Return the last explicit data-plane outcome for postflight wiring.

    Older status files only carried ``ok``; treating an old ``ok=true`` record as
    published keeps rolling upgrades compatible. New records distinguish a
    failed local build from a failed public push.
    """
    ws = ws or WS
    try:
        status = json.loads((ws / DASHBOARD_BUILD_STATUS).read_text())
    except Exception:
        return 'unavailable'
    if status.get('build_ok', status.get('ok')) is not True:
        return 'rebuild_failed'
    if status.get('publish_ok', status.get('ok')) is not True:
        return 'publish_failed'
    return 'published'


def push_with_rebase_retry(remote='origin', branch='master', attempts=3):
    """git push via safe_push.sh — THE single hardened push path. Returns
    (pushed_ok, last_output).

    Was a hand-rolled push/rebase loop, which silently lacked safe_push.sh's two
    hardening knobs (2026-06-10 unification):
      • `-c rebase.autoStash=true` — plain `pull --rebase` REFUSES on a dirty tree
        ("you have unstaged changes"), and a postflight tree is often dirty with
        other in-flight files (portfolio.json mid-refresh, dreaming appending
        MEMORY.md) — the exact failure that stranded commits before 2026-05-30.
      • conflict-marker gate — refuses to publish a half-merged file (the
        2026-06-03 blank-dashboard incident).
    Delegating keeps every committer's push behaviour identical, per the header
    contract in safe_push.sh. `attempts` is kept for API compat (safe_push.sh has
    its own MAX_RETRIES=3).
    """
    script = WS / 'ops' / 'publish' / 'safe_push.sh'
    try:
        r = subprocess.run(['bash', str(script), remote, branch],
                           capture_output=True, text=True, timeout=120, cwd=str(WS))
        return r.returncode == 0, (r.stdout + r.stderr).strip()[-500:]
    except Exception as e:
        return False, str(e)


# --- numeric claims -------------------------------------------------------
# Prose may quote the context; it may not compute. On 2026-07-27 the 09:30 report
# shipped "日内可能再伤 1.5-2 万 HK$" for an exposure whose actual -2% impact was
# about HK$1,000 — off by ~20x — and a "+0.3~-0.4%" range for two ETFs the context
# put at +0.3% each. Both passed every existing check, because nothing looked at a
# numeral (issue #120).
#



def safe_write_text(path, text):
    """Re-export safe_io.safe_write_text for harness scripts.

    Keeps each postflight on the package-owned atomic-write implementation.
    """
    from clawock.safe_io import safe_write_text as _swt
    _swt(str(path), text)


def run_analyze(market):
    """Refresh one market's quotes through the packaged analyzer.

    Both preflights ran a byte-identical copy of this. It is the only place the
    120s analyzer budget is written down, and two copies means two places to
    forget when it moves.
    """
    module = PACKAGED_UTILITIES[f'analyze-{market}']
    try:
        r = subprocess.run(
            [sys.executable, '-m', module, '--wechat', '--md-table'],
            capture_output=True, text=True, timeout=120,
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, '', f'{module} timeout (120s)'


# ── holdings md-table anomalies ───────────────────────────────────────────
# Both report_preflight and intraday_preflight parsed the same seven-column
# holdings table with the same ≥3% rule and the same ≥5% split, in two copies
# that had already drifted apart in what they emitted per row (`severity` vs
# `reason`) — and a change to the row shape would have had to be made twice
# (#918). One parser, superset row: callers keep reading the key they always
# read. The gate itself (≥3% is an anomaly, ≥5% is the severe half) is
# unchanged — this move is not the place to renegotiate it.
_ANOMALY_PCT = re.compile(r'([+\-])([\d\.]+)%')
ANOMALY_MOVE_PCT = 3.0
ANOMALY_SEVERE_PCT = 5.0


def parse_holdings_anomalies(stdout):
    """Rows of the `--md-table` holdings block whose day move is ≥3%.

    Row shape (7 cols, both markets, since 2026-05-21):
      HK: `| 00100 | 60 | 822.83 | 722.00 | +5.1% | -12.2% | -6,050 |`
      US: `| RKLB |  5 |  71.00 | 134.28 | +0.0% | +89.1% |   +316 |`
    Cell[0]=ticker, [1]=shares, [2]=cost, [3]=price, [4]=today%, [5]=pnl%,
    [6]=pnl_abs. Header / separator rows are filtered (代码 / `:---`).
    """
    anomalies = []
    for line in (stdout or '').splitlines():
        s = line.strip()
        if not s.startswith('|') or not s.endswith('|'):
            continue
        cells = [c.strip() for c in s.strip('|').split('|')]
        if len(cells) < 7:
            continue
        ticker = cells[0]
        if ticker == '代码' or ticker.startswith(':'):  # header / separator
            continue
        match = _ANOMALY_PCT.search(cells[4])
        if not match:
            continue
        sign, pct_str = match.groups()
        pct = float(pct_str)
        if pct < ANOMALY_MOVE_PCT:
            continue
        severe = pct >= ANOMALY_SEVERE_PCT
        anomalies.append({
            'ticker': ticker,
            'move_pct': (1 if sign == '+' else -1) * pct,
            # 两个键都给：severity 是 intraday（以及下游 add_side）读的，
            # reason 是 report 的输出契约。合并时任何一边都不该丢字段。
            'severity': 'high' if severe else 'medium',
            'reason': '跳空/异动' if severe else '日内大幅波动',
        })
    return anomalies


# ── rendered signal lines ─────────────────────────────────────────────────
# One reader for both harnesses (#918). The two used to differ in a way that
# left each leg with its own blind spot:
#
#   * intraday matched whole tokens against ('ALERT','WATCH','STOP','TRIM'),
#     so it never saw the **US** renderer's label, which is `STOP-LOSS`
#     (`us_analysis.generate_signal`). Verified on the 2026-08-25 US close
#     block: two `▼ STOP-LOSS …` lines counted as zero, and `decide_alert`
#     wakes on `stop + alert`, so a US position hitting its stop line could
#     pass a slot in silence.
#   * report matched substrings (`'WATCH' in line`), which caught STOP-LOSS by
#     accident but also reads `WATCHDOG` as a WATCH signal and never counted
#     ALERT at all — the one level that outranks STOP.
#
# So: whole-token match (never a substring), against the vocabulary *both*
# renderers actually emit. Severity is the level, not the spelling.
SIGNAL_LEVELS = ('ALERT', 'WATCH', 'STOP', 'TRIM')

# Rendered word (letters only, so `✋STOP?` / `STOP?` / `STOP-LOSS` all land)
# → canonical level. HK writes `ALERT / WATCH / TRIM / STOP?`, US writes
# `WATCH / TRIM / STOP-LOSS` (plus BUY/HOLD variants, which are not risk
# signals and are deliberately absent here).
SIGNAL_WORDS = {
    'ALERT': 'ALERT',
    'WATCH': 'WATCH',
    'TRIM': 'TRIM',
    'STOP': 'STOP',
    'STOPLOSS': 'STOP',
}

_SIGNAL_SECTION = '⚠️ 信号'
_REASON_BULLETS = ('·', '•', '-')
_SECTION_ENDS = ('📉', '📰')


def read_signal_line(line):
    """`(level, ticker)` for a rendered signal line, or `(None, None)`.

    Both renderers write `<marker> <LEVEL> <ticker> | …`, so the level is one
    of the first two tokens — it never merely *appears inside* one. That
    distinction is the whole point: `WATCHDOG` contains WATCH, and a substring
    test reads that line as a signal and publishes the next word as its ticker.
    """
    tokens = (line or '').split()
    # `· …` 是渲染器给理由行用的续行标记，不是一条信号 —— 理由文案里出现
    # STOP/WATCH 这类词是正常的（「浮亏 -31.0% 警惕止损」那种），跟着数就会
    # 把一条信号数成两条。
    if tokens and tokens[0] in _REASON_BULLETS:
        return None, None
    for index, token in enumerate(tokens[:2]):
        word = re.sub(r'[^A-Z]', '', token.upper())
        level = SIGNAL_WORDS.get(word)
        if level:
            ticker = tokens[index + 1] if index + 1 < len(tokens) else None
            return level, ticker
    return None, None


def parse_signal_lines(stdout):
    """`(counts, detail)` over the rendered `⚠️ 信号` block.

    The block runs until the risk (`📉`) or news (`📰`) line. Reason lines
    inside it are indented `· …` continuations and carry no level, so they
    fall out on their own.
    """
    counts = {level.lower(): 0 for level in SIGNAL_LEVELS}
    detail = []
    in_signals = False
    for line in (stdout or '').splitlines():
        if _SIGNAL_SECTION in line or line.strip() == '信号':
            in_signals = True
            continue
        if not in_signals:
            continue
        stripped = line.strip()
        if stripped.startswith(_SECTION_ENDS):
            break
        if not stripped:
            continue
        level, ticker = read_signal_line(stripped)
        if level:
            counts[level.lower()] += 1
            detail.append({'level': level, 'line': stripped, 'ticker': ticker})
    return counts, detail
