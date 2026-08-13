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
            ['flock', DASHBOARD_PUBLISH_LOCK,
             'clawock', 'dashboard-build',
             '--previous', str(previous / 'assets' / 'data' / 'dashboard.json')],
            capture_output=True, text=True, timeout=30, cwd=str(ws),
        )
        build_ok = r.returncode == 0
        publish_ok = None
        full = r.stdout + r.stderr
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
