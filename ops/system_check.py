#!/usr/bin/env python3
"""
system_check.py — master health gate for clawock.

Run from anywhere (idempotent). Exits 0 if system is healthy enough to push.
Exits 1 on any critical failure; exits 2 on warning-only.

Used by:
  • .githooks/pre-push        (blocks bad pushes from this clone)
  • harness postflight        (calls before git commit/push)
  • CI weekly-health.yml      (full check)
  • Manual: `python3 ops/system_check.py`
"""
import glob
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
# Named rather than inlined: this file sits one level below the root, so the
# usual `parents[2]` would land above it. The name is what says "checkout root"
# regardless of depth — and it is the checkout, not WS, because `clawock` ships
# in the tree this file belongs to.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

# Live-box paths for the memory-index check. Still deliberately absolute and not
# derived from WS — the semantic index only ever covers the live runtime
# checkout, so an interactive worktree must judge that one, not its own copy —
# but they are the RUNTIME's layout, so the adapter owns them (#330 step 3).
# This file was the last block of sites that knew which runtime it was on, and
# it migrates last on purpose: it is what proves the earlier steps did not break
# anything. All of these are absent in CI, where the checks skip.
from clawock.providers.openclaw import (  # noqa: E402
    is_installed as openclaw_is_installed,
    read_jobs as openclaw_read_jobs,
    runtime_paths as openclaw_runtime_paths,
)

_OPENCLAW_PATHS = openclaw_runtime_paths()
OPENCLAW_INSTALL = _OPENCLAW_PATHS.install_dir
LIVE_WORKSPACE = _OPENCLAW_PATHS.workspace
MEMORY_INDEX_DB = _OPENCLAW_PATHS.memory_index_db
OPENCLAW_CONFIG = _OPENCLAW_PATHS.config_file

MEMORY_INDEX_LOG = LIVE_WORKSPACE / 'logs' / 'memory_index.log'
# Nightly reindex is 05:10 HKT; 30h lets one run slip into the next daily review
# rather than firing on the normal gap between two runs.
MEMORY_REINDEX_MAX_AGE_HOURS = 30

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
    for pat in ['scripts/data/*.py',
                'instances/kcnyu/src/clawock_kcnyu/harness/*.py']:
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
    sys.path.insert(0, str(_REPO_ROOT / 'scripts' / 'data'))
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
    sys.path.insert(0, str(_REPO_ROOT / 'scripts' / 'data'))
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
            ['python3', str(_REPO_ROOT / 'scripts' / 'data' / 'build_dashboard.py')],
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
    # The payload only grows (snapshots, decisions, outcome rows), so the cap is
    # reached between one publish and the next with no warning: on 2026-07-28 it
    # crossed 200KB and every push turned red on a test, not here. Warn while
    # there is still room to trim something.
    cap, near = 200_000, 180_000
    if size > cap:
        r.add('dashboard.json size', WARNING, f'{size:,} > 200KB cap')
    elif size > near:
        r.add('dashboard.json size', WARNING,
              f'{size:,} — {cap - size:,} bytes left under the 200KB cap')
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
_SCAN_EXCLUDES = [':!.gitignore', ':!.githooks/*', ':!ops/system_check.py']


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
    config = OPENCLAW_CONFIG
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
        sys.path.insert(0, str(_REPO_ROOT / 'scripts' / 'data'))
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
    direct file reads silently return nothing. Read through the core runtime
    provider: CLI first, then the live SQLite DB read-only, with pre-migration
    files kept only as an explicitly rejected last-resort fossil.
    """
    import re
    try:
        cron_read = openclaw_read_jobs()
        jobs = cron_read.entries
    except Exception as e:
        r.add('cron paths', WARNING, f'cron jobs unreadable: {e}')
        return
    if not jobs:
        if not openclaw_is_installed():
            # CI runner / dev clone without the openclaw install — nothing to check.
            r.add('cron paths', OK, 'skipped (no openclaw CLI on this host)')
        else:
            r.add('cron paths', WARNING, 'openclaw CLI returned 0 cron jobs (storage regression? run doctor --fix)')
        return
    if cron_read.source == 'fossil':
        # Both live sources were unreadable and the provider served a pre-6.1
        # fossil that is STALE for model/delivery/message. Refuse validation:
        # passing or failing the payload contract against this view is a lie.
        r.add('cron runtime contract', CRITICAL,
              'live CLI + SQLite unreadable — jobs came from a stale pre-6.1 fossil; '
              'contract validation refused')
        return

    try:
        sys.path.insert(0, str(_REPO_ROOT / 'scripts' / 'data'))
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
                n_watchdogs = sum(
                    bool(job.get('watchdog')) + len(job.get('extra_watchdogs') or [])
                    for job in contract['jobs']
                )
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
        ['python3', str(_REPO_ROOT / 'scripts' / 'data' / 'generate_cron_docs.py'), '--check'],
        capture_output=True, text=True, timeout=15, cwd=str(WS),
    )
    if result.returncode == 0:
        r.add('generated cron docs', OK, 'docs/operations/cron-schedules.md matches contract')
    else:
        r.add('generated cron docs', CRITICAL,
              (result.stdout + result.stderr).strip()[-300:])


def check_trading_calendar_horizon(r):
    """The holiday table is hand-extended each December; warn before it lapses.

    Past its horizon the calendar deliberately fails OPEN so a real trading day is
    never skipped — which means an unextended table quietly turns every 2027 public
    holiday into a session. The table cannot be auto-generated (HK dates are
    gazetted, US ones move), so the only safe mechanism is a loud deadline.
    """
    sys.path.insert(0, str(_REPO_ROOT / 'scripts' / 'data'))
    try:
        import trading_calendar
        coverage = trading_calendar.coverage()
    except Exception as e:  # noqa: BLE001
        r.add('trading calendar', CRITICAL, f'cannot read coverage: {e}')
        return
    today = date.today()
    missing_now = sorted(m for m, c in coverage.items() if not c['covers_current_year'])
    missing_next = sorted(m for m, c in coverage.items() if not c['covers_next_year'])
    horizon = f"through {trading_calendar.LATEST_YEAR}"
    if missing_now:
        r.add('trading calendar', CRITICAL,
              f"no holiday data for {today.year} ({', '.join(missing_now)}) — "
              "every public holiday now reads as a trading day")
    elif missing_next and today.month >= 10:
        r.add('trading calendar', WARNING,
              f"{', '.join(missing_next)} table stops {horizon}; extend it before "
              f"{today.year + 1} begins")
    else:
        r.add('trading calendar', OK, f'{horizon} · both markets')


def _memory_index_backlog():
    """(missing, stale, indexed) — what openclaw embeds vs what its index holds.

    Measured from `memory_index_sources` rather than `openclaw memory status`,
    for two reasons: the CLI call costs ~16s, which is too much for a pre-push
    hook, and its `Dirty:` line clears after the cheap chunk/FTS pass and before
    the expensive embed pass — so it reads healthy while vectors are missing.
    Comparing the recorded size against the file on disk also catches a source
    that was indexed once and has changed since, which the ratio cannot show.
    """
    import sqlite3
    conn = sqlite3.connect(f'file:{MEMORY_INDEX_DB}?mode=ro', uri=True, timeout=10)
    try:
        indexed = {row[0]: int(row[1]) for row in
                   conn.execute('select path, size from memory_index_sources')}
    finally:
        conn.close()

    # openclaw's scope is `MEMORY.md` + every .md under memory/, including the
    # gitignored .tmp and .dreams trees (verified against a clean 472/472 index).
    on_disk = {}
    root_doc = LIVE_WORKSPACE / 'MEMORY.md'
    if root_doc.exists():
        on_disk['MEMORY.md'] = root_doc.stat().st_size
    for path in (LIVE_WORKSPACE / 'memory').rglob('*.md'):
        try:
            on_disk[path.relative_to(LIVE_WORKSPACE).as_posix()] = path.stat().st_size
        except OSError:
            continue  # written and removed underneath us; not a backlog

    missing = sorted(p for p in on_disk if p not in indexed)
    stale = sorted(p for p, size in on_disk.items() if p in indexed and indexed[p] != size)
    return missing, stale, len(indexed)


def _memory_index_patch_gaps():
    """Local dist patches openclaw upgrades wipe, both silent at the point of use."""
    try:
        dist = OPENCLAW_INSTALL.resolve() / 'dist'
    except OSError as e:  # noqa: BLE001
        return [f'cannot resolve openclaw install: {e}']
    if not dist.is_dir():
        return [f'openclaw dist not found at {dist}']

    def contains(pattern, needle):
        for path in dist.glob(pattern):
            try:
                if needle in path.read_text(encoding='utf-8', errors='replace'):
                    return True
            except OSError:
                continue
        return False

    gaps = []
    if not contains('embeddings-*.js', 'threads: 1, batchSize: 512'):
        gaps.append('threads:1 embedding patch missing (local embedding can deadlock)')
    if contains('tools-*.js', 'MEMORY_SEARCH_TOOL_TIMEOUT_MS = 15e3;'):
        gaps.append('memory_search deadline back to stock 15s (this box needs ~27s cold)')
    return gaps


def _memory_reindex_age_hours():
    """Hours since the nightly reindex last finished, or None if it never has."""
    if not MEMORY_INDEX_LOG.exists():
        return None
    last = None
    for line in MEMORY_INDEX_LOG.read_text(errors='replace').splitlines():
        # The */15 reaper writes to the same log, so its mtime proves nothing.
        if 'reindex done' in line:
            last = line.split(' ', 1)[0]
    if not last:
        return None
    try:
        when = datetime.fromisoformat(last)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.astimezone()
    return (datetime.now(timezone.utc) - when).total_seconds() / 3600


def check_memory_index(r):
    """Semantic recall degrades silently; nothing else reports it.

    On 2026-07-27 the index had been 23 files behind for five days — every
    dreaming note since 07-23 and both recent weekly reviews were invisible to
    recall — and it surfaced only because someone read `openclaw memory status`
    by hand while chasing an unrelated bug. Warn, never block: a stale index
    costs recall quality, and holding a publish over it would be the worse
    trade.
    """
    if not MEMORY_INDEX_DB.exists() or not LIVE_WORKSPACE.is_dir():
        r.add('memory index', OK, 'no live index on this host (skipped)')
        return
    try:
        missing, stale, indexed = _memory_index_backlog()
    except Exception as e:  # noqa: BLE001 — an unreadable index is the warning
        r.add('memory index', WARNING, f'cannot read index: {e}')
        return

    problems = []
    if missing:
        problems.append(f'{len(missing)} file(s) never embedded (e.g. {missing[0]})')
    if stale:
        problems.append(f'{len(stale)} file(s) changed since indexing (e.g. {stale[0]})')
    problems += _memory_index_patch_gaps()

    age = _memory_reindex_age_hours()
    if age is None:
        problems.append('nightly reindex has never completed')
    elif age > MEMORY_REINDEX_MAX_AGE_HOURS:
        problems.append(f'nightly reindex last completed {age:.0f}h ago')

    if problems:
        r.add('memory index', WARNING, '; '.join(problems))
    else:
        r.add('memory index', OK,
              f'{indexed} files embedded · patches applied · reindex {age:.0f}h ago')


def check_research_artifacts(r):
    """Thesis, earnings and entry-gate artifacts must stay valid.

    An artifact whose stated verdict no longer matches the computed one, or whose
    schema broke, is an integrity failure. A due earnings review or an ungated
    position is the human's work queue, so it warns and never blocks a publish.
    """
    sys.path.insert(0, str(_REPO_ROOT / 'scripts' / 'data'))
    try:
        import research_surface
        result = research_surface.check()
    except Exception as e:  # noqa: BLE001 — a broken checker must not fail open
        r.add('research artifacts', CRITICAL, f'cannot validate: {e}')
        return
    counts = result['counts']
    tally = (f"{counts['theses']} theses · {counts['earnings_artifacts']} earnings · "
             f"{counts['entry_gates']} gates")
    if result['status'] == 'fail':
        r.add('research artifacts', CRITICAL, '; '.join(result['errors'][:4]))
    elif result['status'] == 'warn':
        r.add('research artifacts', WARNING,
              f"{tally} valid; open work: " + '; '.join(result['warnings'][:4]))
    else:
        r.add('research artifacts', OK, f'{tally} valid · no open research work')


def main():
    r = Result()
    # GitHub Secret Scanning + Push Protection own repository-wide credential
    # detection. The pre-commit hook still scans staged additions locally; do
    # not put the old full-tree git-grep back into this latency-sensitive hook.
    checks = [
        check_baseline_files,
        check_scripts_compile,
        check_portfolio_schema,
        check_instrument_registry,
        check_plan_json_schema,
        check_dashboard_buildable,
        check_peer_map_coverage,
        check_openclaw_doctor,
        check_decision_ledger,
        check_cron_paths_exist,
        check_generated_cron_docs,
        check_research_artifacts,
        check_trading_calendar_horizon,
        check_memory_index,
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
