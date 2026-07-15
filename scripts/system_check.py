#!/usr/bin/env python3
"""
system_check.py — master health gate for clawock.

Run from anywhere (idempotent). Exits 0 if system is healthy enough to push.
Exits 1 on any critical failure; exits 2 on warning-only.

Used by:
  • .githooks/pre-push        (blocks bad pushes from this clone)
  • harness postflight        (calls before git commit/push)
  • CI weekly-health.yml      (full check)
  • Manual: `python3 scripts/system_check.py`
"""
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

WS = Path(__file__).resolve().parent.parent

# Check result severity
CRITICAL = '✗ CRITICAL'
WARNING  = '⚠ WARN'
OK       = '✓ OK'


class Result:
    def __init__(self):
        self.checks = []
    def add(self, name, severity, msg=''):
        self.checks.append((name, severity, msg))
    def critical_count(self):
        return sum(1 for _, s, _ in self.checks if s == CRITICAL)
    def warn_count(self):
        return sum(1 for _, s, _ in self.checks if s == WARNING)
    def ok_count(self):
        return sum(1 for _, s, _ in self.checks if s == OK)


def check_baseline_files(r):
    """All required bootstrap + workspace MD files exist."""
    required = ['SOUL.md', 'IDENTITY.md', 'USER.md', 'MEMORY.md', 'TOOLS.md',
                'AGENTS.md', 'CLAUDE.md', 'BOOTSTRAP.md', 'portfolio.json']
    missing = [f for f in required if not (WS / f).exists()]
    if missing:
        r.add('baseline files', CRITICAL, f'missing: {missing}')
    else:
        r.add('baseline files', OK, f'{len(required)} files present')


def check_scripts_compile(r):
    """All Python scripts compile."""
    failed = []
    for pat in ['scripts/data/*.py', 'scripts/harness/*.py']:
        for f in glob.glob(str(WS / pat)):
            try:
                rr = subprocess.run(['python3', '-m', 'py_compile', f],
                                   capture_output=True, text=True, timeout=10)
                if rr.returncode != 0:
                    failed.append(f'{Path(f).name}: {rr.stderr[-100:]}')
            except Exception as e:
                failed.append(f'{Path(f).name}: {e}')
    if failed:
        r.add('scripts compile', CRITICAL, '; '.join(failed))
    else:
        r.add('scripts compile', OK, 'all scripts compile')


def check_portfolio_schema(r):
    p = WS / 'portfolio.json'
    if not p.exists():
        r.add('portfolio.json', CRITICAL, 'missing')
        return
    try:
        d = json.loads(p.read_text())
    except Exception as e:
        r.add('portfolio.json', CRITICAL, f'parse fail: {e}')
        return
    bad = []
    if 'portfolios' not in d:
        bad.append('missing portfolios key')
    else:
        for region in ('us_stocks', 'hk_stocks'):
            if region not in d['portfolios']:
                bad.append(f'missing {region}')
                continue
            holdings = d['portfolios'][region].get('holdings')
            if not isinstance(holdings, list):
                bad.append(f'{region}.holdings not a list')
                continue
            for h in holdings:
                for f in ('ticker', 'shares', 'cost_basis'):
                    if f not in h:
                        bad.append(f'{region} holding missing {f}: {h.get("ticker")}')
    if bad:
        r.add('portfolio.json schema', CRITICAL, '; '.join(bad[:3]))
    else:
        r.add('portfolio.json schema', OK, 'valid')


def check_plan_json_schema(r):
    """All memory/*-plan.json must satisfy schema."""
    plans = glob.glob(str(WS / 'memory' / '*-plan.json'))
    if not plans:
        r.add('plan.json schema', OK, '0 plans yet')
        return
    bad = []
    sys.path.insert(0, str(WS / 'scripts' / 'data'))
    import decision_v2
    for p in plans:
        try:
            d = json.loads(open(p).read())
        except Exception as e:
            bad.append(f'{Path(p).name}: parse fail'); continue
        errors = decision_v2.validate_plan(d, p)
        bad.extend(f'{Path(p).name}: {e}' for e in errors)
    if bad:
        r.add('plan.json schema', CRITICAL, '; '.join(bad[:3]))
    else:
        r.add('plan.json schema', OK, f'{len(plans)} plans valid')


def check_dashboard_buildable(r):
    """build_dashboard.py produces sub-200KB output.

    Builds to a TEMP file (BUILD_DASHBOARD_OUT) — this is a verification, it
    must not mutate the published assets/data/dashboard.json. Before 2026-06-10
    this check rewrote the real file in place, so every pre-push hook run left
    the working tree dirty with a fresher generated_at.
    """
    import tempfile
    out = Path(tempfile.gettempdir()) / 'system_check_dashboard.json'
    try:
        env = dict(os.environ, BUILD_DASHBOARD_OUT=str(out))
        rr = subprocess.run(
            ['python3', str(WS / 'scripts' / 'data' / 'build_dashboard.py')],
            capture_output=True, text=True, timeout=30, cwd=str(WS), env=env,
        )
        if rr.returncode != 0:
            r.add('dashboard.json build', CRITICAL, rr.stderr[-200:])
            return
    except Exception as e:
        r.add('dashboard.json build', CRITICAL, str(e))
        return
    if not out.exists():
        r.add('dashboard.json build', CRITICAL, 'no output file')
        return
    size = out.stat().st_size
    if size > 200_000:
        r.add('dashboard.json size', WARNING, f'{size:,} > 200KB cap')
    else:
        r.add('dashboard.json build', OK, f'{size:,} bytes')


def check_peer_map_coverage(r):
    """All active holdings should have a peer-map.json entry."""
    pf_p = WS / 'portfolio.json'
    pm_p = WS / 'memory' / 'peer-map.json'
    if not pm_p.exists():
        r.add('peer-map coverage', WARNING, 'peer-map.json missing')
        return
    try:
        pf = json.loads(pf_p.read_text())
        pm = json.loads(pm_p.read_text()).get('holdings', {})
    except Exception as e:
        r.add('peer-map coverage', CRITICAL, f'parse fail: {e}')
        return
    missing = []
    for region in ('hk_stocks', 'us_stocks'):
        for h in pf['portfolios'].get(region, {}).get('holdings', []):
            if h.get('shares', 0) > 0 and h['ticker'] not in pm:
                missing.append(h['ticker'])
    if missing:
        r.add('peer-map coverage', WARNING, f'active holdings without peers: {missing}')
    else:
        r.add('peer-map coverage', OK, 'all active holdings mapped')


def check_no_leaked_secrets(r):
    """Tracked files must not contain raw API keys."""
    bad = []
    try:
        out = subprocess.check_output(
            ['git', '-C', str(WS), 'grep', '-nE',
             # \b or the prefix matches mid-word: the charset includes '-', so
             # "risk-on-with-trend-conflict" in a plan.json reads as sk- + 21 legal
             # chars and blocked every push on 2026-07-15. A real key's sk-/tp- always
             # starts a word (line start, quote, '=', whitespace).
             r'(\bsk-[a-zA-Z0-9_-]{20,}|\btp-[a-zA-Z0-9_-]{20,}|FINNHUB_API_KEY\s*=\s*[a-zA-Z0-9]+|POLYGON_API_KEY\s*=\s*[a-zA-Z0-9]+)',
             '--', ':!*.md', ':!.gitignore', ':!openclaw.json*', ':!.githooks/*', ':!scripts/system_check.py'],
            text=True, timeout=10, stderr=subprocess.DEVNULL,
        )
        if out.strip():
            bad = out.strip().splitlines()[:3]
    except subprocess.CalledProcessError:
        pass  # git grep returns 1 when no match — that's the OK case
    except Exception:
        pass
    if bad:
        r.add('secret leak scan', CRITICAL, f'{len(bad)} potential leaks: {bad}')
    else:
        r.add('secret leak scan', OK, 'no leaked secrets in tracked files')


def check_openclaw_doctor(r):
    """Cheap config-validity check. Full `openclaw doctor` is too slow for hooks,
    so we just re-validate the JSON config can be parsed + has expected shape."""
    config = Path('/root/.openclaw/openclaw.json')
    if not config.exists():
        r.add('openclaw config', WARNING, 'openclaw.json not found (skipped)')
        return
    try:
        d = json.loads(config.read_text())
    except Exception as e:
        r.add('openclaw config', CRITICAL, f'openclaw.json parse fail: {e}')
        return

    # Sanity checks
    issues = []
    if 'agents' not in d:
        issues.append('missing agents')
    if 'models' not in d or 'providers' not in d.get('models', {}):
        issues.append('missing models.providers')

    # Check primary model is in providers. Native/built-in providers (e.g.
    # claude-cli, registered by openclaw itself reusing ~/.claude login) never
    # appear in the user's models.providers block, so exempt them — otherwise
    # switching the direct-chat backend to claude-cli (2026-06-12) false-positives
    # as "not configured" and blocks every push.
    NATIVE_PROVIDERS = {'claude-cli'}
    primary = d.get('agents', {}).get('defaults', {}).get('model', {}).get('primary', '')
    if primary and '/' in primary:
        prov_name = primary.split('/')[0]
        if prov_name not in d['models']['providers'] and prov_name not in NATIVE_PROVIDERS:
            issues.append(f'primary provider "{prov_name}" not configured')

    # Check meta
    if 'meta' not in d:
        issues.append('missing meta block')

    if issues:
        r.add('openclaw config', CRITICAL, '; '.join(issues))
    else:
        r.add('openclaw config', OK, f'valid; primary={primary}')


def check_decision_ledger(r):
    """V2 decision ledger is parseable, unique and schema-valid."""
    p = WS / 'memory' / 'decisions.jsonl'
    if not p.exists():
        r.add('decisions.jsonl', OK, 'no ledger yet (first runs)')
        return
    try:
        sys.path.insert(0, str(WS / 'scripts' / 'data'))
        import decision_v2
        rows = decision_v2.load_decisions(p)
    except Exception as e:
        r.add('decisions.jsonl', CRITICAL, f'parse fail: {e}')
        return
    errors = []
    seen = set()
    for row in rows:
        errors.extend(decision_v2.validate_decision(row))
        did = row.get('decision_id')
        if did in seen: errors.append(f'duplicate decision_id {did}')
        seen.add(did)
    if errors:
        r.add('decisions.jsonl', CRITICAL, '; '.join(errors[:3]))
    else:
        r.add('decisions.jsonl', OK, f'{len(rows)} decisions · {len({x.get("episode_id") for x in rows})} episodes')


def check_cron_paths_exist(r):
    """Live cron schedules match the tracked contract and payload scripts exist.

    6.1 migrated cron storage from cron/jobs.json into state/openclaw.sqlite, so
    direct file reads silently return nothing. Read via _watchdog_common.load_jobs
    (storage-agnostic: CLI `cron list --json` primary, pre-migration files fallback)
    — the same path the watchdogs were fixed to use on 2026-06-04.
    """
    import re
    sys.path.insert(0, str(WS / 'scripts' / 'harness'))
    try:
        from _watchdog_common import OPENCLAW_BIN, load_jobs  # type: ignore
        jobs = load_jobs()
    except Exception as e:
        r.add('cron paths', WARNING, f'cron jobs unreadable: {e}')
        return
    if not jobs:
        if not os.path.exists(OPENCLAW_BIN):
            # CI runner / dev clone without the openclaw install — nothing to check.
            r.add('cron paths', OK, 'skipped (no openclaw CLI on this host)')
        else:
            r.add('cron paths', WARNING, 'openclaw CLI returned 0 cron jobs (storage regression? run doctor --fix)')
        return

    contract_path = WS / 'config' / 'cron-schedules.json'
    try:
        contract = json.loads(contract_path.read_text()).get('jobs', [])
        expected = {
            j['name']: (
                (j.get('schedule') or {}).get('expr'),
                (j.get('schedule') or {}).get('tz'),
                j.get('enabled', True),
            )
            for j in contract
        }
        actual = {
            j['name']: (
                (j.get('schedule') or {}).get('expr'),
                (j.get('schedule') or {}).get('tz'),
                j.get('enabled', True),
            )
            for j in jobs
        }
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(
            name for name in set(expected) & set(actual)
            if expected[name] != actual[name]
        )
        if missing or extra or changed:
            detail = []
            if missing:
                detail.append(f'missing={missing}')
            if extra:
                detail.append(f'extra={extra}')
            if changed:
                detail.append(
                    'changed=' + str({n: {'expected': expected[n], 'actual': actual[n]}
                                      for n in changed})
                )
            r.add('cron schedule contract', CRITICAL, '; '.join(detail))
        else:
            r.add('cron schedule contract', OK, f'{len(actual)} live jobs match tracked config')
    except Exception as e:
        r.add('cron schedule contract', CRITICAL, f'cannot validate: {e}')

    refs = set()
    for j in jobs:
        msg = ((j.get('payload') or {}).get('message')) or j.get('message') or ''
        refs.update(re.findall(r'/root/\.openclaw/workspace/scripts/[a-z/_]+\.py', msg))
    missing = [p for p in sorted(refs) if not os.path.exists(p)]
    if missing:
        r.add('cron paths', CRITICAL, f'missing: {missing}')
    else:
        r.add('cron paths', OK, f'{len(jobs)} jobs · {len(refs)} referenced scripts present')


def main():
    r = Result()
    checks = [
        check_baseline_files,
        check_scripts_compile,
        check_portfolio_schema,
        check_plan_json_schema,
        check_dashboard_buildable,
        check_peer_map_coverage,
        check_no_leaked_secrets,
        check_openclaw_doctor,
        check_decision_ledger,
        check_cron_paths_exist,
    ]
    for c in checks:
        try:
            c(r)
        except Exception as e:
            r.add(c.__name__, CRITICAL, f'check itself crashed: {e}')

    # Print report
    print('═' * 64)
    print(f'  clawock system check  · {r.ok_count()} ok · {r.warn_count()} warn · {r.critical_count()} critical')
    print('═' * 64)
    for name, severity, msg in r.checks:
        line = f'  {severity:14s}  {name:25s}'
        if msg:
            line += f'  {msg}'
        print(line)
    print('═' * 64)

    if r.critical_count() > 0:
        print(f'\n🚫 {r.critical_count()} critical failure(s) — push/commit BLOCKED')
        return 1
    if r.warn_count() > 0:
        print(f'\n⚠️  {r.warn_count()} warning(s) — push allowed but please review')
        return 2
    print('\n✅ all checks passed — system OK to publish')
    return 0


if __name__ == '__main__':
    sys.exit(main())
