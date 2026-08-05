"""
_harness_common.py — shared helpers for brief/report/intraday harness scripts.

Extracted to avoid duplicating _git / rebuild_dashboard / push retry logic
across multiple postflight scripts. All functions accept the workspace root
as path argument or default to the resolved workspace root.
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

# Resolve from this file's location so harness helpers work both under openclaw
# cron (local /root/.openclaw/workspace) and on GH Action runners (checkout dir).
# parents[2] = scripts/harness/<this> → workspace root. Identical to the old
# hardcoded /root path locally, but correct on a runner too. (2026-05-30)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'data'))
from workspace import workspace_root  # noqa: E402

# The text/numeric validation primitives moved into the installed package so the
# report core can run without a repository checkout. Re-exported here so all ten
# in-repo importers keep working unchanged.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from clawock.validation import (  # noqa: E402,F401
    REPORT_ASSEMBLED_TARGET_CHARS,
    REPORT_CHAR_LIMITS,
    report_prose_budget,
    ADVISORY_MARK,
    MAX_NUMERIC_SAMPLES,
    MIN_CHECKED_AMOUNT,
    advisory_prefix,
    categorize_issues,
    check_md_table_column_consistency,
    check_numeric_claims,
    check_raw_tables_verbatim,
    is_advisory,
    split_advisory,
    validate_forbidden_phrases,
)

WS = workspace_root(Path(__file__).resolve().parents[2])
sys.path.insert(0, str(WS / 'scripts' / 'data'))

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
# has ever built it: fetch_catalysts.py runs in brief preflight [12/14] alone. So
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

        synced = []
        for f in GHA_DATA_FILES:
            relpath = f'assets/data/{f}'
            r = subprocess.run(
                ['git', 'checkout', 'origin/master', '--', relpath],
                capture_output=True, text=True, timeout=10, cwd=str(ws),
            )
            if r.returncode == 0:
                synced.append(f)
        return True, f'synced {len(synced)}/{len(GHA_DATA_FILES)}'
    except Exception as e:
        return False, str(e)


def _record_dashboard_build(ok, output, ws=None):
    """Persist the last build_dashboard outcome to logs/dashboard_build_status.json.

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
        status = {
            'checked_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'ok': bool(ok),
            'warn_count': warn_count,
            'repair_count': repair_count,
            'tail': (output or '')[-500:],
        }
        path = ws / DASHBOARD_BUILD_STATUS
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(status, ensure_ascii=False, indent=2))
        if not ok:
            print(f'🔴 build_dashboard FAILED — recorded to {DASHBOARD_BUILD_STATUS}; '
                  f'dashboard.json NOT refreshed. tail: {(output or "")[-200:]}',
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
    """Re-run build_dashboard.py to refresh its four public dashboard outputs.

    Refreshes today's snapshot AND syncs GH Action-managed data files first, so
    the equity curve reflects latest portfolio state and the embedded sentiment/
    macro/news data are not 24 h stale.

    Records the outcome via _record_dashboard_build so a failure is observable in
    the daily cron health check even when callers discard the return value.

    Returns (ok, last_300_chars_of_output). Failure is non-fatal — caller
    should log but not abort the commit pipeline.
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
            ['python3', str(ws / 'scripts' / 'build' / 'fetch_data_plane.py'),
             '--into', str(previous)],
            capture_output=True, text=True, timeout=60, cwd=str(ws), check=False,
        )
        r = subprocess.run(
            ['flock', DASHBOARD_PUBLISH_LOCK,
             'python3', str(ws / 'scripts' / 'data' / 'build_dashboard.py'),
             '--previous', str(previous / 'assets' / 'data' / 'dashboard.json')],
            capture_output=True, text=True, timeout=30, cwd=str(ws),
        )
        ok = r.returncode == 0
        full = r.stdout + r.stderr
        _record_dashboard_build(ok, full, ws)
        return ok, full[-300:]
    except Exception as e:
        _record_dashboard_build(False, str(e), ws)
        return False, str(e)


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
    script = WS / 'scripts' / 'data' / 'safe_push.sh'
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

    Avoids importing scripts/data/safe_io.py path-juggling in each postflight.
    """
    sys.path.insert(0, str(WS / 'scripts' / 'data'))
    from safe_io import safe_write_text as _swt  # type: ignore
    _swt(str(path), text)
