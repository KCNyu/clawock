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
from datetime import datetime, timezone
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


def check_instrument_registry(r):
    """Canonical metadata must cover every active holding."""
    sys.path.insert(0, str(WS / 'scripts' / 'data'))
    try:
        import instrument_registry
        portfolio = json.loads((WS / 'portfolio.json').read_text())
        errors = instrument_registry.validate_active_holdings(portfolio)
    except Exception as e:
        r.add('instrument registry', CRITICAL, f'load/validate failed: {e}')
        return
    if errors:
        r.add('instrument registry', CRITICAL, '; '.join(errors[:3]))
    else:
        active = sum(
            1
            for bucket in ('us_stocks', 'hk_stocks')
            for h in portfolio['portfolios'][bucket]['holdings']
            if (h.get('shares') or 0) > 0
        )
        r.add('instrument registry', OK, f'{active} active holdings mapped')


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


# Loose key-ish shapes: vendor prefixes and named assignments.
SECRET_PATTERNS_LOOSE = (
    # \b is not a usable left anchor here: the charset includes '-', which is
    # itself a non-word char, so \b sits inside every hyphenated slug.
    # "risk-on-with-trend-conflict" in a plan.json read as sk- + 21 legal chars
    # and blocked every push on 2026-07-15, and a news URL slug
    # (".../update-5-sk-hynix-plunges-after-…") does the same inside *.md.
    # A real key's prefix always opens a token: line start, whitespace, quote,
    # '=', ':' or an opening bracket. Anchoring there is what lets this tier
    # scan *.md at all — see the 2026-07-22 note on check_no_leaked_secrets.
    r'(^|\s|["\'=:,({[])(sk|tp)-[a-zA-Z0-9_-]{20,}'   # OpenAI/MiniMax sk-, Xiaomi tp-
    # Vendors whose keys carry no distinguishing prefix (Alpha Vantage, Mistral)
    # can only be caught by the variable they are assigned to. Bound to '=' so a
    # bare mention of the variable name in prose or a `${{ secrets.X }}` reference
    # does not fire. The optional quote matters: FINNHUB_API_KEY="…" in a .env,
    # a JS config or a YAML value is the common shape, and without it the value
    # started at a quote and never matched.
    r'|(FINNHUB|POLYGON|ALPHA_VANTAGE|MISTRAL|TAVILY|MINIMAX|XIAOMI)_API_KEY\s*=\s*["\']?[A-Za-z0-9_-]{8,}'
    # Nostr accepts a bare 64-hex private key. Raw 64-hex is far too common
    # (sha256 sums, lockfiles) to match on its own, so require the variable name.
    r'|NOSTR_PRIVATE_KEY\s*=\s*["\']?[0-9a-fA-F]{64}'
)

# Structurally unambiguous credential markers. A PEM header or a vendor key with a
# fixed prefix + fixed length cannot plausibly occur in prose, so these also scan
# *.md — which is exactly where the memory-promotion cron writes, and where a
# credential pasted into a session could otherwise land in the public repo.
SECRET_PATTERNS_STRICT = (
    r'-----BEGIN [A-Z ]*PRIVATE KEY-----'          # any PEM private key
    # GCP service-account JSON. Keyed on private_key_id, not on
    # "type": "service_account": that field is plain metadata that any setup doc
    # or fixture may legitimately quote, while a real key file always carries a
    # 40-hex private_key_id (and a PEM the line above catches anyway).
    r'|"private_key_id"\s*:\s*"[0-9a-f]{40}"'
    # No trailing \b on the two below: their charsets include '-' and '_', so a
    # key ending in one had no word boundary after it and silently never matched.
    r'|\bAIza[0-9A-Za-z_-]{35}'                     # Google/Gemini API key
    r'|\b[0-9]{8,10}:AA[A-Za-z0-9_-]{33}'           # Telegram bot token
    r'|\bgh[pousr]_[A-Za-z0-9]{36}\b'               # GitHub PAT
    r'|\bAKIA[0-9A-Z]{16}\b'                        # AWS access key id
    r'|\bxox[baprs]-[A-Za-z0-9-]{10,}'              # Slack token
    r'|\btvly-[A-Za-z0-9_-]{20,}'                   # Tavily search key
    # Nostr nsec (bech32: fixed prefix, fixed length, no b/i/o/1 in the charset).
    # nostr_publish.js signs with this — a leak lets anyone post as Rick.
    r'|\bnsec1[02-9ac-hj-np-z]{58}\b'
)

# Never scan the pattern definitions themselves or the ignore list. The local
# runtime config (/root/.openclaw/openclaw.json) legitimately holds live keys but
# is not in the repo, so git grep cannot see it anyway — it is deliberately NOT
# excluded here: an exclusion would only ever take effect on the one day someone
# accidentally commits that file, which is precisely the day it must be caught.
_SCAN_EXCLUDES = [':!.gitignore', ':!.githooks/*', ':!scripts/system_check.py']


def _grep_tracked(pattern, extra_excludes=(), rev=None):
    """Run `git grep -nE` over tracked files, or over `rev` when given.

    Returns (lines, failure). `failure` is None on a real answer; on anything that
    stops the scan from running it carries a reason. The distinction matters: a
    security check that swallows its own errors reports OK while scanning nothing.
    That is not hypothetical — the strict tier's PEM pattern starts with '-', which
    git parsed as an option flag until `-e` was added below, and the old blanket
    `except` turned that into a silent pass.
    """
    try:
        p = subprocess.run(
            # -e is required: a pattern starting with '-' is otherwise read as a flag.
            ['git', '-C', str(WS), 'grep', '-nE', '-e', pattern,
             *([rev] if rev else []),
             '--', *_SCAN_EXCLUDES, *extra_excludes],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as e:  # timeout, git missing, …
        return [], f'{type(e).__name__}: {e}'
    if p.returncode == 0:
        return p.stdout.strip().splitlines(), None
    if p.returncode == 1:
        return [], None  # git grep returns 1 when no match — that's the OK case
    return [], f'git grep rc={p.returncode}: {p.stderr.strip()[:160]}'


def _head_exists():
    """False in a repo with no commits — nothing committed can leak there.

    Also False if git itself is unusable; that path is not swallowed, because the
    worktree scans below then fail on the same cause and report CRITICAL.
    """
    try:
        p = subprocess.run(['git', '-C', str(WS), 'rev-parse', '--verify', '-q', 'HEAD'],
                           capture_output=True, text=True, timeout=10)
    except Exception:
        return False
    return p.returncode == 0


def check_no_leaked_secrets(r):
    """Tracked files must not contain raw API keys or private credentials.

    Scans both tiers over *.md too (2026-07-22). Markdown was previously exempt
    from the loose tier because of hyphen-slug collisions, but memory/*.md is the
    dreaming-write path straight into a public repo — the single most likely place
    for a pasted credential to land. The prefix anchor in SECRET_PATTERNS_LOOSE
    replaces the exemption: it is what makes slugs and URLs stop matching.

    Scans the working tree *and* HEAD. `git grep` without a revision only sees the
    working tree, so a credential that was committed and then edited out locally
    would be pushed while the scan reported clean.
    """
    # The two tiers now cover the same files, so one grep per revision does the
    # work of two. They stay separate constants because they are reasoned about
    # and tested separately — only the scan is merged.
    pattern = f'{SECRET_PATTERNS_LOOSE}|{SECRET_PATTERNS_STRICT}'
    revs = [None] + (['HEAD'] if _head_exists() else [])

    bad, failures = [], []
    for rev in revs:
        lines, err = _grep_tracked(pattern, rev=rev)
        bad += lines
        if err:
            failures.append(err)

    if bad:
        r.add('secret leak scan', CRITICAL,
              f'{len(bad)} potential leaks: {bad[:3]}')
    elif failures:
        # Fail closed: an unusable scanner must never read as "no secrets found".
        r.add('secret leak scan', CRITICAL,
              f'scan did not run, cannot certify: {failures}')
    else:
        r.add('secret leak scan', OK,
              'no leaked secrets in tracked files (worktree + HEAD)')


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
    direct file reads silently return nothing. Read via _watchdog_common.load_jobs:
    CLI first, then the live SQLite DB read-only, with pre-migration files kept
    only as an explicitly rejected last-resort fossil.
    """
    import re
    sys.path.insert(0, str(WS / 'scripts' / 'harness'))
    try:
        import _watchdog_common as wc  # type: ignore
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
    if getattr(wc, 'LAST_LOAD_SOURCE', None) == 'fossil':
        # Both live sources were unreadable and load_jobs() served a pre-6.1
        # fossil that is STALE for model/delivery/message. Refuse validation:
        # passing or failing the payload contract against this view is a lie.
        r.add('cron runtime contract', CRITICAL,
              'live CLI + SQLite unreadable — jobs came from a stale pre-6.1 fossil; '
              'contract validation refused')
        return

    try:
        sys.path.insert(0, str(WS / 'scripts' / 'data'))
        from cron_contract import (  # type: ignore
            load_contract, next_us_dst_transition, us_season,
            validate_live_jobs, validate_watchdogs,
        )
        contract = load_contract()
        errors = validate_live_jobs(contract, jobs)
        if errors:
            r.add('cron runtime contract', CRITICAL, '; '.join(errors[:8]))
        else:
            transition = next_us_dst_transition()
            next_label = transition.date().isoformat() if transition else 'unknown'
            r.add('cron runtime contract', OK,
                  f'{len(jobs)} jobs · schedule+payload match · US={us_season()} next={next_label}')
        crontab = subprocess.run(
            ['crontab', '-l'], capture_output=True, text=True, timeout=10,
        )
        if crontab.returncode != 0:
            r.add('watchdog cron contract', CRITICAL, 'crontab -l failed')
        else:
            watchdog_errors = validate_watchdogs(contract, crontab.stdout)
            if watchdog_errors:
                r.add('watchdog cron contract', CRITICAL, '; '.join(watchdog_errors[:8]))
            else:
                n_watchdogs = sum(bool(j.get('watchdog')) for j in contract['jobs'])
                r.add('watchdog cron contract', OK,
                      f'{n_watchdogs} watchdogs + daily DST sync match tracked config')
    except Exception as e:
        r.add('cron runtime contract', CRITICAL, f'cannot validate: {e}')

    refs = set()
    for j in jobs:
        msg = ((j.get('payload') or {}).get('message')) or j.get('message') or ''
        refs.update(re.findall(r'/root/\.openclaw/workspace/scripts/[a-z/_]+\.py', msg))
    missing = [p for p in sorted(refs) if not os.path.exists(p)]
    if missing:
        r.add('cron paths', CRITICAL, f'missing: {missing}')
    else:
        r.add('cron paths', OK, f'{len(jobs)} jobs · {len(refs)} referenced scripts present')


def check_generated_cron_docs(r):
    """Generated schedule documentation must exactly match the contract."""
    result = subprocess.run(
        ['python3', str(WS / 'scripts' / 'data' / 'generate_cron_docs.py'), '--check'],
        capture_output=True, text=True, timeout=15, cwd=str(WS),
    )
    if result.returncode == 0:
        r.add('generated cron docs', OK, 'CRON_SCHEDULES.md matches contract')
    else:
        r.add('generated cron docs', CRITICAL,
              (result.stdout + result.stderr).strip()[-300:])


def main():
    r = Result()
    checks = [
        check_baseline_files,
        check_scripts_compile,
        check_portfolio_schema,
        check_instrument_registry,
        check_plan_json_schema,
        check_dashboard_buildable,
        check_peer_map_coverage,
        check_no_leaked_secrets,
        check_openclaw_doctor,
        check_decision_ledger,
        check_cron_paths_exist,
        check_generated_cron_docs,
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
