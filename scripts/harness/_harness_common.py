"""
_harness_common.py — shared helpers for brief/report/intraday harness scripts.

Extracted to avoid duplicating _git / rebuild_dashboard / push retry logic
across multiple postflight scripts. All functions accept the workspace root
as path argument or default to the resolved workspace root.
"""
import json
import subprocess
import sys
from pathlib import Path

# Resolve from this file's location so harness helpers work both under openclaw
# cron (local /root/.openclaw/workspace) and on GH Action runners (checkout dir).
# parents[2] = scripts/harness/<this> → workspace root. Identical to the old
# hardcoded /root path locally, but correct on a runner too. (2026-05-30)
WS = Path(__file__).resolve().parents[2]

# Where rebuild_dashboard records its last outcome so the daily cron health
# check can surface silent build failures / degradations (kcn doesn't want
# per-cron alerts — see feedback_no_individual_cron_alerts).
DASHBOARD_BUILD_STATUS = 'logs/dashboard_build_status.json'


def pct(c, pc):
    """Percentage change from pc → c. Returns 0 if pc invalid."""
    if not pc:
        return 0.0
    try:
        return round((float(c) - float(pc)) / float(pc) * 100, 2)
    except Exception:
        return 0.0


def git_cmd(*args, cwd=None):
    """Run git command in workspace. Returns (success_bool, combined_output)."""
    cwd = cwd or WS
    try:
        r = subprocess.run(['git', '-C', str(cwd)] + list(args),
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
      - Sat 00-06:    write Fri (US close at ~04:00 HKT belongs to Fri)
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


GHA_DATA_FILES = ['sentiment.json', 'macro.json', 'us_news_digest.json', 'catalysts.json']


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
        status = {
            'checked_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'ok': bool(ok),
            'warn_count': warn_count,
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
    except Exception as e:
        print(f'(could not record dashboard build status: {e})', file=sys.stderr)


def rebuild_dashboard(ws=None):
    """Re-run build_dashboard.py to refresh assets/data/dashboard.json.

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
        r = subprocess.run(
            ['python3', str(ws / 'scripts' / 'data' / 'build_dashboard.py')],
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
    """git push with rebase+retry on race. Returns (pushed_ok, last_output).

    If rebase itself fails (real conflict on same file), abort rebase and stop —
    don't loop forever. Manual resolution will be needed.
    """
    last_out = ''
    for i in range(1, attempts + 1):
        ok, out = git_cmd('push', remote, branch)
        if ok:
            return True, out
        last_out = out
        # Race with another cron commit — try rebase
        rebase_ok, rebase_out = git_cmd('pull', '--rebase', remote, branch)
        if not rebase_ok:
            # Conflict — don't loop, leave commit local for manual resolution
            git_cmd('rebase', '--abort')  # cleanup
            return False, f'rebase conflict (manual resolution needed): {rebase_out[-200:]}'
    return False, last_out


def _extract_md_tables(text):
    """Yield lists of consecutive lines that look like markdown table rows."""
    cur = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith('|') and s.endswith('|'):
            cur.append(ln)
        elif cur:
            yield cur
            cur = []
    if cur:
        yield cur


def check_raw_tables_verbatim(text, raw_wechat_block):
    """Verify every markdown-table line in raw_wechat_block appears verbatim in text.

    preflight builds the holdings table via _wechat_table.py (7-col, known correct).
    LLMs sometimes paraphrase rows or drop a separator segment when "copying" —
    e.g. 5/21+ regression where header had 7 cols but separator only 6, breaking
    markdown renderers. Strict substring match catches that.

    Returns list of issue strings (empty = pass).
    """
    if not raw_wechat_block:
        return []
    issues = []
    for tbl in _extract_md_tables(raw_wechat_block):
        for ln in tbl:
            if ln not in text:
                issues.append(f'表格行未 verbatim 复制: "{ln.strip()[:50]}..."')
                break  # one issue per table is enough
    return issues


def check_md_table_column_consistency(text):
    """Verify every markdown table inside text has uniform pipe-segment counts
    across its header/separator/data rows.

    Use this when there's no canonical `raw_wechat_block` to compare against —
    e.g. LLM-authored pre-open.md where tables are composed (not copied).
    A diverging segment count breaks markdown renderers.

    Returns list of issue strings.
    """
    issues = []
    for i, tbl in enumerate(_extract_md_tables(text), start=1):
        counts = {ln.count('|') for ln in tbl}
        if len(counts) > 1:
            issues.append(f'markdown 表格 #{i} 列数不一致: pipe-segments={sorted(counts)}')
    return issues


def validate_forbidden_phrases(text, phrases, label='报告'):
    """Return one issue per forbidden phrase found in text."""
    return [f'{label}含敷衍词 "{p}"' for p in phrases if p in text]


def categorize_issues(issues, critical_substrings, warn_max=2, extra_critical=None):
    """Common pass/warn/fail decision used by all postflights.

    - empty issues → pass
    - any issue containing any critical_substring OR matching extra_critical(i) → fail
    - otherwise warn if ≤ warn_max issues else fail

    extra_critical: optional callable(issue_str) -> bool for compound checks
    (e.g. hard char limit detection that can't be a simple substring).
    """
    if not issues:
        return 'pass'
    has_critical = any(
        any(c in i for c in critical_substrings)
        or (extra_critical is not None and extra_critical(i))
        for i in issues
    )
    if has_critical:
        return 'fail'
    return 'warn' if len(issues) <= warn_max else 'fail'


def safe_write_text(path, text):
    """Re-export safe_io.safe_write_text for harness scripts.

    Avoids importing scripts/data/safe_io.py path-juggling in each postflight.
    """
    sys.path.insert(0, str(WS / 'scripts' / 'data'))
    from safe_io import safe_write_text as _swt  # type: ignore
    _swt(str(path), text)
