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
import re
import shutil
import subprocess
import sys
import time
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


def clawock_argv(*args, env=None):
    """How to spawn the packaged CLI without depending on the caller's PATH.

    The Python half of what `ops/publish/money_checker.sh` does for the two push
    gates, and it exists for the same reason they do: a job started from the
    user crontab runs with PATH=/usr/bin:/bin, and the installed console script
    lives in ~/.local/bin. A bare `clawock` there is not "the CLI is broken" —
    it is FileNotFoundError, which this file reports as CRITICAL, which blocks
    the push. On 2026-08-10 that stranded the 03:20 dreaming commit behind a
    gate that had nothing to say about it.

    Falls back to the package in this checkout, already on `sys.path` above; a
    subprocess does not inherit that, so PYTHONPATH is set explicitly. Same rule
    as the shell resolver: it is `clawock.cli` either way, never a second
    implementation.
    """
    env = dict(os.environ if env is None else env)
    exe = shutil.which('clawock')
    if exe:
        return [exe, *args], env
    src = str(_REPO_ROOT / 'src')
    existing = env.get('PYTHONPATH')
    env['PYTHONPATH'] = f'{src}{os.pathsep}{existing}' if existing else src
    return [sys.executable, '-m', 'clawock.cli', *args], env


OPENCLAW_INSTALL = _OPENCLAW_PATHS.install_dir
LIVE_WORKSPACE = _OPENCLAW_PATHS.workspace
MEMORY_INDEX_DB = _OPENCLAW_PATHS.memory_index_db
OPENCLAW_CONFIG = _OPENCLAW_PATHS.config_file
# Derived, never spelled out: an absolute host path in this file is exactly the
# runtime coupling the ratchet bans, and the host tools directory belongs to
# whoever runs the check, not to this repository.
HOST_TOOLS_DIR = Path.home() / 'tools'
# The pipx-style launcher directory: every watchdog/DST entry point in
# config/cron-schedules.json starts with <home>/.local/bin/clawock-*, so an
# audit that only knows ~/tools skips exactly the commands whose silent death
# matters most (#775 class — the DST syncer died for 8 days while every
# repository-side gate stayed green).
LAUNCHER_BIN_DIR = Path.home() / '.local' / 'bin'

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


# Shipped in the repository: every checkout, worktree and CI runner has them.
# MEMORY.md is back on this list as of #1074 — it is clawock runtime state
# (openclaw's dreaming job writes it, every cron payload gets it, and eight of
# the files beside it name it as the authority), not coding-agent prose. #1072
# swept it out with `memory/*.md`, which forced the two-tier split #1073 had to
# invent; both are gone now that the tracked surface tells the truth again.
#: A publisher that commits every twenty minutes reaches three commits in an
#: hour, so three is "the last hour did not publish" rather than a round number.
#: The hour bound catches the quiet-session version of the same failure, where
#: one commit sits unsent all evening.
BACKLOG_WARN_COMMITS = 3
BACKLOG_WARN_HOURS = 2.0

#: How far back to look for a hop that cannot recover. Wide enough to survive a
#: quiet stretch, short enough that a fixed hop stops being reported the same day.
RUN_SCAN_LIMIT = 40

BASELINE_TRACKED = ['SOUL.md', 'IDENTITY.md', 'USER.md', 'MEMORY.md', 'TOOLS.md',
                    'AGENTS.md', 'CLAUDE.md', 'BOOTSTRAP.md', 'portfolio.json']


def check_baseline_files(r):
    """All required bootstrap + workspace files exist.

    One tier, because they now have one truth: every one of these is tracked, so
    every checkout — live workspace, agent worktree, CI runner — must have it.
    """
    required = list(BASELINE_TRACKED)
    missing = [f for f in required if not (WS / f).exists()]
    if missing:
        r.add('baseline files', CRITICAL, f'missing: {missing}')
    else:
        r.add('baseline files', OK, f'{len(required)} files present')


def check_root_allowlist(r):
    """Every tracked top-level path must have an explicit terminal owner."""
    contract_path = WS / 'config' / 'root-allowlist.json'
    try:
        contract = json.loads(contract_path.read_text())
        entries = contract['entries']
        if contract.get('schema_version') != 1 or not isinstance(entries, dict):
            raise ValueError('unsupported root allowlist schema')
        tracked = subprocess.run(
            ['git', 'ls-files', '-z'], cwd=str(WS), capture_output=True,
            check=True, timeout=20,
        ).stdout.decode().split('\0')
        actual = {path.split('/', 1)[0] for path in tracked if path}
    except Exception as exc:
        r.add('root ownership', CRITICAL, f'cannot read root allowlist: {exc}')
        return
    unexplained = sorted(actual - set(entries))
    missing = sorted(set(entries) - actual)
    incomplete = sorted(
        name for name, meta in entries.items()
        if not isinstance(meta, dict) or not meta.get('owner') or not meta.get('consumer')
    )
    if unexplained or missing or incomplete:
        detail = []
        if unexplained:
            detail.append('unexplained: ' + ', '.join(unexplained))
        if missing:
            detail.append('missing: ' + ', '.join(missing))
        if incomplete:
            detail.append('no owner/consumer: ' + ', '.join(incomplete))
        r.add('root ownership', CRITICAL, '; '.join(detail))
    else:
        r.add('root ownership', OK, f'{len(actual)} tracked paths explicitly owned')


def check_scripts_compile(r):
    """All Python scripts compile."""
    failed = []
    for pat in [
        'src/clawock/**/*.py',
        'ops/**/*.py',
    ]:
        for f in glob.glob(str(WS / pat), recursive=True):
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
    try:
        from clawock import instruments as instrument_registry
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
    from clawock.decision import ledger as decision_v2
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
    """The installed dashboard builder produces sub-200KB output.

    Builds to a TEMP file (BUILD_DASHBOARD_OUT) — this is a verification, it
    must not mutate the published assets/data/dashboard.json. Before 2026-06-10
    this check rewrote the real file in place, so every pre-push hook run left
    the working tree dirty with a fresher generated_at.
    """
    import tempfile
    out = Path(tempfile.gettempdir()) / 'system_check_dashboard.json'
    try:
        env = dict(os.environ, BUILD_DASHBOARD_OUT=str(out))
        argv, env = clawock_argv('dashboard-build', env=env)
        rr = subprocess.run(
            argv,
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
    r'|(FINNHUB|POLYGON|ALPHA_VANTAGE|MISTRAL|TAVILY|MINIMAX|XIAOMI|OPENCODE)_API_KEY\s*=\s*["\']?[A-Za-z0-9_-]{8,}'
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
    # An nsec is the account's signing key — a leak lets anyone post as its owner.
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
        from clawock.decision import ledger as decision_v2
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


def _cron_jobs_without_prompt_report(sessions):
    """Enabled cron jobs whose newest session carries no `systemPromptReport`.

    The gate below verifies the newest session per *profile*, which is the right
    question for "is context still being assembled correctly" and the wrong one
    for "is every job covered". On 2026-08-11 ten market jobs reported a uniform
    5 files / 29 skills / 34 tools while `Memory Dreaming Promotion` produced no
    report at all, and the profile-level check averaged it away.

    A per-job session entry is replaced when a run starts, before the runtime
    attaches its prompt report. It also stays report-less when the provider
    fails before responding. Both states are explicit in the authoritative cron
    listing; neither is evidence of capability loss. Successful jobs, jobs with
    no history, and jobs with an unknown outcome still have to be named.

    Returns names rather than a count, and returns empty when the job list
    cannot be read — an unreadable schedule is not evidence that every job is
    covered, but it is also not this check's failure to report.
    """
    try:
        from clawock.providers.openclaw import cron_cli_json

        listing = cron_cli_json(['list', '--json']) or {}
    except Exception:
        return []

    reported = {
        key.split(':cron:', 1)[1].split(':')[0]
        for key, entry in (sessions or {}).items()
        if ':cron:' in key and isinstance(entry, dict)
        and isinstance(entry.get('systemPromptReport'), dict)
    }
    missing = []
    for job in listing.get('jobs', []) or []:
        if not job.get('enabled'):
            continue
        if str(job.get('id')) in reported:
            continue
        state = job.get('state') if isinstance(job.get('state'), dict) else {}
        if job.get('status') == 'running' or state.get('runningAtMs') is not None:
            continue
        last_status = str(
            state.get('lastStatus') or state.get('lastRunStatus') or '').lower()
        if last_status in {
                'error', 'failed', 'failure', 'timeout', 'timed_out',
                'cancelled', 'canceled', 'skipped'}:
            continue
        missing.append(str(job.get('name') or job.get('id'))[:28])
    return sorted(missing)


def check_context_capability(r):
    """A run that came out with no skills or no tools has to fail somewhere.

    `clawock context audit` answers a different question — it verifies the
    workspace has the documents and capability roots — so a loss that happens
    at *assembly* time leaves it green. That is the exact failure #380 exists to
    prevent, and until this check existed nothing looked at a realized run.

    Warning rather than critical on purpose: a narrowed context is visible in
    the daily health output, but it says nothing about whether the book
    reconciles, and this gate blocks pre-push.
    """
    from clawock.context.assembly import verify_prompt_report

    store = _OPENCLAW_PATHS.sessions_dir / 'sessions.json'
    if not store.exists():
        r.add('context capability', OK, 'no runtime session store (skipped)')
        return
    try:
        sessions = json.loads(store.read_text())
    except Exception as e:
        r.add('context capability', WARNING, f'session store unreadable: {e}')
        return

    newest, profiles_seen = {}, set()
    for key, entry in (sessions or {}).items():
        if not isinstance(entry, dict):
            continue
        profile = 'isolated-cron' if ':cron:' in key else 'interactive'
        profiles_seen.add(profile)
        report = entry.get('systemPromptReport')
        if not isinstance(report, dict):
            continue
        try:
            stamp = int(entry.get('updatedAt') or entry.get('lastInteractionAt') or 0)
        except (TypeError, ValueError):
            stamp = 0
        if stamp >= newest.get(profile, (-1,))[0]:
            newest[profile] = (stamp, key, report)

    # "Nothing to check" and "the thing I check stopped being produced" are not
    # the same answer, and merging them is how this gate would go quiet without
    # going red — the exact silent capability loss #380 exists to prevent, and
    # the same shape as #452/#453/#460.
    #
    # A workspace with no sessions at all is a foreign or fresh machine and has
    # nothing to say. A profile that HAS sessions but carries no prompt report
    # anywhere is different: the runtime used to record what this gate reads and
    # has stopped, so every later run goes unverified behind a green check.
    # Coverage is counted against the jobs that are actually scheduled, not
    # against whatever sessions happen to exist. Nine healthy cron reports
    # otherwise average away a tenth enabled job that produces none — the gate
    # reads OK while one live job is unverifiable (#473). Names, not a count, so
    # the finding says which job to go look at.
    unreported_jobs = _cron_jobs_without_prompt_report(sessions)
    if unreported_jobs:
        r.add('context capability', WARNING,
              f'{len(unreported_jobs)} enabled cron job(s) produce no prompt '
              f'report, so this gate cannot see them: '
              f'{", ".join(unreported_jobs)}')

    silent = sorted(profiles_seen - set(newest))
    if silent:
        r.add('context capability', WARNING,
              f'{", ".join(silent)}: sessions exist but none carries a prompt '
              f'report — the runtime stopped recording what this gate reads, so '
              f'a narrowed context would now pass unseen')
        return
    if not newest:
        r.add('context capability', OK, 'no sessions recorded yet')
        return

    failures, checked = [], []
    for profile, (_stamp, key, report) in sorted(newest.items()):
        try:
            result = verify_prompt_report(report, profile=profile)
        except ValueError as e:
            failures.append(f'{profile}: unreadable report ({e})')
            continue
        failed = [name for name, ok in result['checks'].items() if ok is False]
        if failed:
            failures.append(f'{profile} {key[-24:]}: {", ".join(failed)}')
        else:
            seen = result['observed']
            checked.append(
                f'{profile} {len(seen["files"])}f/{seen["skills"]}s/{seen["tools"]}t')
    if failures:
        r.add('context capability', WARNING, '; '.join(failures))
    else:
        r.add('context capability', OK, ' · '.join(checked))


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
        from clawock.scheduling import (  # type: ignore
            load_contract, next_us_dst_transition, us_season,
            validate_live_jobs, validate_watchdogs,
        )
        contract = load_contract()
        errors = validate_live_jobs(contract, jobs)
        if errors:
            # Naming the fix in the message is not decoration: on 2026-08-31
            # this exact CRITICAL blocked every master push for eight hours,
            # and the reconciler that repairs it in one command
            # (`sync_cron_payloads.py`) had to be found by reading the tree.
            r.add('cron runtime contract', CRITICAL,
                  '; '.join(errors[:8])
                  + '  → fix: python3 ops/host/sync_cron_payloads.py --apply')
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


def _host_crontab_target_audit(crontab_text):
    """(rows, missing) — absolute host crontab command paths that do not exist.

    A cron line whose script was deleted still fires on schedule and fails only
    inside cron's own mail, which nobody reads — the #592 cleanup deleted
    `indexnow_submit.py` and `rick_broadcast_nostr.sh` while the host crontab
    kept scheduling them (#663). Every absolute path in the command part that
    sits under the live workspace or the host tools directory must therefore
    resolve, or the line is a silent no-op.

    Both roots are derived, not spelled out: the workspace comes from the
    provider adapter and the tools directory from the operator's home, so this
    file stays free of the host-path coupling the ratchet bans. Tokens are read
    until the first shell operator (`>`, `|`, `;`): a redirect target like
    `>> logs/watchdog.cron.log` is created by cron, so a not-yet-written log is
    not a missing file.
    """
    import re
    import shlex

    from clawock.scheduling import parse_crontab_lines

    missing = []
    rows = parse_crontab_lines(crontab_text)
    for row in rows:
        for token in shlex.split(row['command']):
            if '=' in token:  # env assignment prefixing the command (PATH=…)
                continue
            if re.search(r'[>|;]', token):
                break
            if not token.startswith('/'):
                continue
            target = Path(token)
            if not any(target.is_relative_to(root)
                       for root in (LIVE_WORKSPACE, HOST_TOOLS_DIR,
                                    LAUNCHER_BIN_DIR)):
                continue
            if not os.path.exists(target):
                missing.append(token)
    return rows, missing


def check_host_crontab_targets(r):
    """Host crontab lines must not point at files that no longer exist.

    Skip-safe by design: CI runners and fresh hosts have no crontab, and an
    unreadable or empty one is not a finding. The check exists because deleting
    an ops script without touching the host crontab turns the scheduled line
    into a silent no-op that no repository-side gate can see (#663).
    """
    try:
        out = subprocess.run(
            ['crontab', '-l'], capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return  # no crontab on this host — nothing to check
    if out.returncode != 0 or not out.stdout.strip():
        return
    rows, missing = _host_crontab_target_audit(out.stdout)
    if missing:
        for path in missing:
            r.add('host crontab targets', CRITICAL,
                  f'crontab points at missing file: {path}')
    else:
        r.add('host crontab targets', OK, f'{len(rows)} lines · no missing targets')


# A cron job that dies writes its traceback to the log the crontab line
# redirects into, and its exit code into cron's mail — which this host has no
# MTA for. Both are unread, so "crashes on every run" is as invisible as the
# deleted-script case #663 already gates. These are the shapes a crashed run
# leaves at the end of such a log.
HOST_CRON_LOG_CRASH_MARKERS = (
    re.compile(r'^Traceback \(most recent call last\):'),
    re.compile(r'^[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Interrupt)\b'),
    re.compile(r'command not found'),
    re.compile(r'No such file or directory'),
    re.compile(r'Permission denied'),
)
# Only the tail is read: these logs are append-only for months (the dashboard
# publisher's is already several MB) and the question is about the last run.
HOST_CRON_LOG_TAIL_BYTES = 8192


def _host_cron_log_targets(crontab_text):
    """Log files the host crontab appends job output into, under the workspace.

    Derived from the crontab rather than listed here, for the same reason
    `_host_crontab_target_audit` derives its roots: an absolute host path in
    this file is the coupling the ratchet bans, and the set of host jobs is the
    operator's, not this repository's.
    """
    from clawock.scheduling import parse_crontab_lines

    targets = set()
    for row in parse_crontab_lines(crontab_text):
        for match in re.finditer(r'>>?\s*(\S+)', row['command']):
            target = Path(match.group(1))
            if target.is_absolute() and target.is_relative_to(LIVE_WORKSPACE):
                targets.add(target)
    return targets


def _last_meaningful_line(path):
    """The final non-blank line of a file's tail, or None."""
    with path.open('rb') as fh:
        try:
            fh.seek(-HOST_CRON_LOG_TAIL_BYTES, os.SEEK_END)
        except OSError:
            fh.seek(0)
        tail = fh.read().decode('utf-8', 'replace')
    lines = [line.strip() for line in tail.splitlines() if line.strip()]
    return lines[-1] if lines else None


def check_publish_backlog(r):
    """Commits that were made and never left the machine.

    #1241 is the case this exists for. On 2026-08-31 a CRITICAL from
    `cron runtime contract` made `.githooks/pre-push` refuse every push to
    master. The publisher kept committing on schedule, the `data-plane` branch
    kept publishing successfully, the dashboard looked completely alive — and
    six commits sat unpushed for **eight hours** with nothing measuring it. It
    was found because someone asked whether the checkout was clean.

    What makes it findable now is that the backlog is a *state*, not an event.
    An event ("push failed") can be missed if nobody reads the line it was
    written on, and that is exactly what happened: the refusal went to the
    stderr of a cron step. A state is still true on the next run, and this
    reports it every twenty minutes for as long as it lasts.

    **WARN, never CRITICAL, and not by timidity.** This check runs inside the
    pre-push hook, so a CRITICAL here would refuse the very push that clears the
    backlog — the measurement would become the thing keeping the number up.
    Same reasoning as `check_host_cron_logs` above, one step more literal.

    No network: `origin/master` is read at whatever the last fetch left it,
    which for the publisher is seconds ago because `safe_push.sh` fetches before
    it pushes. A stale ref can only *under*-report, and under-reporting a
    backlog is the safe direction for a check that must not block.
    """
    if os.environ.get('GITHUB_ACTIONS'):
        return  # a PR checkout's distance from origin/master is not a backlog
    try:
        branch = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            capture_output=True, text=True, timeout=10)
        if branch.returncode != 0 or branch.stdout.strip() != 'master':
            return  # only the live checkout publishes from master
        ahead = subprocess.run(
            ['git', 'rev-list', '--count', 'origin/master..HEAD'],
            capture_output=True, text=True, timeout=10)
        if ahead.returncode != 0:
            return  # no origin/master ref here — a fresh clone or a worktree
        count = int((ahead.stdout or '0').strip() or 0)
    except Exception:
        return
    if not count:
        r.add('publish backlog', OK, 'nothing unpushed')
        return
    oldest = subprocess.run(
        ['git', 'log', '-1', '--format=%ct', 'origin/master..HEAD'],
        capture_output=True, text=True, timeout=10)
    hours = None
    try:
        hours = (time.time() - int(oldest.stdout.strip())) / 3600
    except Exception:
        pass
    age = f'{hours:.1f}h' if hours is not None else 'unknown age'
    detail = f'{count} commit(s) unpushed, oldest {age}'
    if count >= BACKLOG_WARN_COMMITS or (hours is not None and hours >= BACKLOG_WARN_HOURS):
        r.add('publish backlog', WARNING,
              f'{detail} — the desk is committing but not publishing; '
              f'check what pre-push is refusing')
    else:
        r.add('publish backlog', OK, detail)


def check_fallback_chain_shape(r):
    """How many independent legs the scheduled model chain actually has.

    #1242. `check_model_chain_health` below answers "is a hop dead"; this one
    answers the question that was never asked anywhere: **how long is the chain
    when you stop counting hops and start counting the things that can fail
    independently.** A chain of three hops behind one account is one hop with
    two extra round trips, and it reads as three everywhere — in the contract,
    in the error string (`All models failed (3)`), and in the run table.

    The number that matters is not the hop count but the count of distinct
    credentials behind it, because a rate limit, an expired key and an empty
    balance all hit every hop that shares the credential at the same instant.
    `minimax` and `minimax-2` are two providers in the contract and one API key
    in `openclaw.json`; that is the fact this check exists to say out loud.

    Off the live box there is no `openclaw.json`, so credentials cannot be
    counted and the check reports what the contract alone can prove.
    """
    contract = WS / 'config' / 'cron-schedules.json'
    try:
        profiles = json.loads(contract.read_text()).get('payload_profiles') or {}
    except Exception as e:  # noqa: BLE001
        r.add('fallback chain', CRITICAL, f'cannot read cron contract: {e}')
        return
    rotations = {}
    for name, profile in sorted(profiles.items()):
        fallbacks = profile.get('fallbacks')
        if not fallbacks:
            continue  # a single-model profile declares no chain to measure
        rotations.setdefault(tuple([profile.get('model'), *fallbacks]), []).append(name)
    if not rotations:
        r.add('fallback chain', OK, 'no profile declares a fallback chain')
        return

    keys = _provider_api_keys()
    worst = None
    for rotation, names in sorted(rotations.items(), key=lambda kv: kv[1]):
        providers = {hop.split('/')[0] for hop in rotation}
        # An unknown provider is counted as its own credential rather than
        # folded in with the others: guessing the optimistic direction here
        # would be the exact overcount this check exists to prevent.
        creds = {keys.get(p, f'unknown:{p}') for p in providers} if keys else None
        legs = len(creds) if creds is not None else len(providers)
        unit = 'credential' if creds is not None else 'provider'
        detail = (f'{"/".join(names)}: {len(rotation)} hops · '
                  f'{legs} independent {unit}{"s" if legs != 1 else ""} '
                  f'({" → ".join(rotation)})')
        if worst is None or legs < worst[0]:
            worst = (legs, unit, detail)
    legs, unit, detail = worst
    if legs < 2:
        r.add('fallback chain', WARNING,
              f'{detail} — every hop fails together; the chain is one leg long')
    else:
        r.add('fallback chain', OK, detail)


def _provider_api_keys():
    """provider name → an opaque label for the account behind it. Live box only.

    The caller's only question is whether two providers are the same account,
    so the credential itself never leaves this function: providers sharing one
    are handed the same anonymous label (`account-1`, `account-2`, …) and the
    secrets are dropped on return. Nothing here hashes or stores a key — a
    fingerprint would be a second copy of the secret for no added answer.
    """
    try:
        config = json.loads(OPENCLAW_CONFIG.read_text())
    except Exception:  # noqa: BLE001
        return {}
    providers = ((config.get('models') or {}).get('providers') or {})
    accounts, labels = {}, {}
    for name, provider in providers.items():
        # baseUrl, then the name: a provider that carries no key of its own is
        # its own account rather than a silent match with someone else's.
        identity = str(provider.get('apiKey')
                       or provider.get('baseUrl') or name)
        labels[name] = accounts.setdefault(identity, f'account-{len(accounts) + 1}')
    accounts.clear()
    return labels


def check_model_chain_health(r):
    """A hop that will never recover, told apart from one that just timed out.

    #1242. The scheduled jobs run a three-model fallback chain for their run
    summary. Two hops are the same MiniMax account and time out at the top of
    the hour; the third, added precisely so there would be a non-MiniMax leg,
    now answers `401 Insufficient balance`. All three land in one
    `FallbackSummaryError: All models failed (3)`, so a permanent billing
    failure and a transient timeout are indistinguishable — and the chain's
    real length is 2, from one provider, while it reports as 3.

    Only billing-class failures are reported, and only as a WARN. A timeout is
    the chain working as designed (the retry succeeds and the report is
    delivered); a `401 Insufficient balance` never fixes itself, and no amount
    of retrying it does anything except spend a round trip per slot.
    """
    try:
        sys.path.insert(0, str(_REPO_ROOT / 'ops' / 'host'))
        import cron_runs  # noqa: PLC0415 - host-only, imported lazily on purpose
        job_map, _ = cron_runs.load_job_map()
        if not job_map:
            return  # no openclaw on this host
        entries, _ = cron_runs.load_entries('cron', None, None, job_map)
    except Exception:
        return
    dead = {}
    for entry in entries[:RUN_SCAN_LIMIT]:
        for hop in re.findall(r'([\w./-]+):\s*([^|]*?)\s*\((billing|auth)\)',
                              str(entry.get('error') or '')):
            dead.setdefault(hop[0], hop[1][:60])
    if dead:
        named = '; '.join(f'{hop} — {why}' for hop, why in sorted(dead.items()))
        r.add('model chain', WARNING,
              f'{len(dead)} hop(s) failing for a reason retrying cannot fix: {named}')
    else:
        r.add('model chain', OK, f'no billing-class hop failures in the last '
                                 f'{RUN_SCAN_LIMIT} runs')


DELIVERY_DEGRADED_FAILURE_RATE = 0.20
DELIVERY_HEALTHY_SUCCESS_RATE = 0.95


def check_delivery_channel_health(r):
    """A delivery leg that is quietly rotting, told apart from one bad slot.

    Sibling of :func:`check_model_chain_health`, for the other chain. Every
    report co-sends to WeChat and Telegram and the slot counts as delivered if
    either lands, which is the right design — WeChat cannot confirm a cold-session
    drop, so gating on it would suppress real reports. The cost of that design is
    that **one leg can fail a third of the time and nothing says so**: the
    postflight prints a warning to stderr, the watchdog correctly stays quiet
    because Telegram carried the slot, and no gate or view ever adds the failures
    up. Measured 2026-09-06 over the ledger's own four-day window: Telegram
    98/100, WeChat 67/100, and WeChat trending 84% -> 76% -> 68% across three
    consecutive days without a single alert anywhere.

    Two different things get reported, because they need different answers:

    * a slot where **every** channel failed is a report that did not reach a
      human, and the watchdog's re-send is the only thing that saved it;
    * a channel far below its sibling is a leg degrading behind a working
      fallback — nothing is lost today, and that is exactly why it goes unseen.

    Channels are enumerated from the `*_ok` fields the ledger actually carries
    rather than from a hardcoded pair, so a third channel is covered the day it
    starts writing its result (the same reason the packaging and argparse gates
    read their real source instead of a list someone has to remember to
    update).

    WARNING, never CRITICAL: a push is not the thing to block over a delivery
    statistic, and `check_model_chain_health` set that precedent for the chain
    next door.
    """
    try:
        sys.path.insert(0, str(_REPO_ROOT / 'src'))
        from clawock.automation import workflow_outcomes  # noqa: PLC0415
        ledger = json.loads(workflow_outcomes.public_path().read_text(encoding='utf-8'))
    except Exception:
        return  # no ledger on this host yet
    records = ledger.get('records') or []

    slots = []
    for rec in records:
        delivery = ((rec.get('stages') or {}).get('primary_delivery') or {})
        channels = {k[:-3]: bool(v) for k, v in delivery.items()
                    if k.endswith('_ok') and isinstance(v, bool)}
        if channels:
            slots.append((rec.get('slot') or '', channels))
    if not slots:
        return
    slots.sort(key=lambda s: s[0])
    slots = slots[-RUN_SCAN_LIMIT:]

    names = sorted({name for _, ch in slots for name in ch})
    totals = {n: [0, 0] for n in names}  # name -> [ok, seen]
    silent = []
    for slot, ch in slots:
        for name, ok in ch.items():
            totals[name][1] += 1
            totals[name][0] += 1 if ok else 0
        if ch and not any(ch.values()):
            silent.append(slot)

    def rate(name):
        ok, seen = totals[name]
        return ok / seen if seen else 1.0

    tally = ' · '.join(f'{n} {totals[n][0]}/{totals[n][1]}' for n in names)
    if silent:
        shown = ', '.join(silent[-4:])
        r.add('delivery channels', WARNING,
              f'{len(silent)} slot(s) where every channel failed — only the '
              f'watchdog re-send stood between these and a missed report: {shown} '
              f'({tally} over the last {len(slots)} slots)')
        return
    healthy = [n for n in names if rate(n) >= DELIVERY_HEALTHY_SUCCESS_RATE]
    rotting = [n for n in names
               if (1 - rate(n)) >= DELIVERY_DEGRADED_FAILURE_RATE and n not in healthy]
    if rotting and healthy:
        named = '; '.join(f'{n} {rate(n) * 100:.0f}%' for n in rotting)
        r.add('delivery channels', WARNING,
              f'{named} while {"/".join(healthy)} carries every slot — nothing is '
              f'lost today, which is why this leg can rot unnoticed '
              f'({tally} over the last {len(slots)} slots)')
    else:
        r.add('delivery channels', OK,
              f'{tally} over the last {len(slots)} slots')


def check_host_cron_logs(r):
    """A host cron job whose log ends in a crash has been failing unnoticed.

    #775 is the case this exists for: the DST synchroniser died on the same
    `FileNotFoundError` eight days running and every repository-side gate stayed
    green, because they all ask different questions — `check_host_crontab_targets`
    asks whether the script still exists (it did), the GitHub cron-health job
    only sees the eleven agent slots, and the outcome ledger does not carry host
    maintenance jobs at all.

    The criterion is deliberately modest and stated as what it is: **the last
    thing this job wrote looks like a crash.** Host cron does not hand anyone an
    exit code, so any design claiming to report one would be inventing it. Two
    honest limits follow: a job that dies without writing anything is invisible
    here, and one crash keeps reporting until a later run pushes it off the tail
    (at most one schedule period for a job that runs at all).

    WARN, not CRITICAL: `.githooks/pre-push` runs this file before every push to
    master, and a stalled maintenance job must not wedge the market-data
    publisher. WARN still surfaces on every run of the 20-minute publisher.
    """
    try:
        out = subprocess.run(
            ['crontab', '-l'], capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return  # no crontab on this host — nothing to check
    if out.returncode != 0 or not out.stdout.strip():
        return
    targets = _host_cron_log_targets(out.stdout)
    if not targets:
        return

    crashed, checked = [], 0
    for path in sorted(targets):
        if not path.is_file() or path.stat().st_size == 0:
            continue  # never written, or written and then rotated away
        checked += 1
        last = _last_meaningful_line(path)
        if last and any(m.search(last) for m in HOST_CRON_LOG_CRASH_MARKERS):
            crashed.append((path.name, last))
    if not checked:
        return
    for name, last in crashed:
        r.add('host cron logs', WARNING, f'{name} ends on a crash: {last[:140]}')
    if not crashed:
        r.add('host cron logs', OK, f'{checked} host cron logs · none end on a crash')


def check_delivered_but_unarchived(r):
    """A product that reached kcn but never reached git.

    2026-09-01 is the case this exists for. The 08:00 brief was delivered to
    WeChat and Telegram (`brief-sent-2026-09-01.json`, `sent_ok`/`tg_ok` both
    true) and `memory/2026-09-01-pre-open.md` was never committed, so the link
    printed on the card kcn actually received 404'd all day, `briefs.html` stopped
    at 08-31, and `memory/decisions.jsonl` — whose *only* carrier is the daily
    brief commit — did not move for a whole trading day. The same thing cost the
    HK open report its commit on 08-31 and 09-01.

    The mechanism is the postflights' own ordering: deliver first, commit second
    (#765). Anything that kills the process in between leaves a state where
    **every existing gate reads success** — the send marker is written, the
    ledger's `primary_delivery` is `success`, the watchdog sees a fresh marker
    with `tg_ok`, and the model's own wrap-up reads the marker and stops. On
    2026-09-01 the killer was the agent's own `timeout 90` wrapper; the payloads
    now carve postflight out of that rule, but the wrapper is not the only way to
    die between the two halves, so the *state* needs a gate rather than the cause.

    Criterion, stated as exactly what it is: **today's brief was delivered and its
    markdown is not tracked by git.** `git ls-files --error-unmatch` answers
    "tracked", which is the property that matters — a file staged but uncommitted
    still has not left the desk, and one that is neither is the 09-01 case.

    WARN, not CRITICAL, for the reason `check_publish_backlog` gives one function
    up: this runs inside `.githooks/pre-push`, and the fix for the state it
    reports is *a push*. A CRITICAL would refuse the very commit that clears it.

    Weekends, holidays and any day before the brief has been delivered are
    silent: no send marker, nothing to say.
    """
    # 主机 TZ 是 Asia/Shanghai(+0800)，与 HKT 同偏移，所以本地日期就是场次日；
    # 不引 zoneinfo 是为了让这个文件在任何 checkout 上都零依赖地跑起来。
    today = date.today().strftime('%Y-%m-%d')
    marker = WS / 'memory' / '.tmp' / f'brief-sent-{today}.json'
    if not marker.is_file():
        return  # not delivered (yet) — nothing is owed to git
    try:
        sent = json.loads(marker.read_text())
    except Exception:
        return
    if not (sent.get('sent_ok') or sent.get('tg_ok')):
        return  # marker exists but nothing went out; a different failure owns it
    unarchived = []
    for rel in (f'memory/{today}-pre-open.md', f'memory/{today}-plan.json'):
        if not (WS / rel).exists():
            continue  # absent is the miss detector's business, not this one
        tracked = subprocess.run(
            ['git', 'ls-files', '--error-unmatch', rel],
            capture_output=True, text=True, timeout=10, cwd=str(WS))
        if tracked.returncode != 0:
            unarchived.append(rel)
    if unarchived:
        r.add('delivered but unarchived', WARNING,
              f'{today} brief was delivered but {", ".join(unarchived)} '
              f'is not tracked — postflight died between delivery and commit; '
              f'the public brief page will 404 until it is committed')
    else:
        r.add('delivered but unarchived', OK,
              f'{today} brief delivered and archived')


def check_generated_cron_docs(r):
    """Generated schedule documentation must exactly match the contract."""
    result = subprocess.run(
        ['python3', str(_REPO_ROOT / 'ops' / 'host' / 'generate_cron_docs.py'), '--check'],
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
    try:
        from clawock import sessions as trading_calendar
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
    if OPENCLAW_INSTALL is None:
        return ['openclaw install root unresolved; set CLAWOCK_OPENCLAW_INSTALL_DIR']
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


def _memory_curation_gaps():
    """Compare the memory index against the topic files on disk.

    Returns (orphans, dangling): topic files nothing links to, and links that
    resolve to nothing. Both are read from the LIVE workspace: the index is
    tracked (#1074) but the topic files it points at are host-local, so only
    the live box can see both halves at once.
    """
    index = LIVE_WORKSPACE / 'MEMORY.md'
    if not index.is_file():
        return None, None
    text = index.read_text(encoding='utf-8', errors='ignore')

    linked = set()
    for match in re.finditer(r'(?:\(|`|\[\[|\s)(memory/[^\s`)\]]+\.md)', text):
        linked.add(match.group(1))
    for match in re.finditer(r'\[\[([^\]]+)\]\]', text):     # shared-memory wiki links
        linked.add(f'memory/{match.group(1)}.md')

    on_disk = set()
    for path in sorted((LIVE_WORKSPACE / 'memory').glob('*.md')):
        # Product surfaces, not memory: the published brief is indexed by the
        # site, not by MEMORY.md.
        if path.name.endswith('-pre-open.md'):
            continue
        on_disk.add(f'memory/{path.name}')

    orphans = sorted(on_disk - linked)
    dangling = sorted(name for name in linked
                      if not (LIVE_WORKSPACE / name).is_file())
    return orphans, dangling


def check_memory_curation(r):
    """The memory is an index plus topic files; drift shows up as both halves.

    kcn's shape (2026-08-26): 「类似于我们 shared memory 那种 index+md 形式的维护，
    然后对照清理」. `MEMORY.md` is the index; `memory/*.md` are the topic files.
    A topic file nothing links to is a note that will never be recalled — the
    pile that has to be cleaned. A link pointing at a file that is gone is the
    same drift from the other side.

    Deliberately a REPORT, not a deletion, and deliberately not on a timer:
    which note is finished is a judgement, and a job that decides it by mtime
    would delete the one durable note somebody wrote three months ago and never
    had to touch again. WARN so it surfaces on every push without blocking one.
    """
    if not LIVE_WORKSPACE.is_dir():
        r.add('memory curation', OK, 'no live workspace on this host (skipped)')
        return
    orphans, dangling = _memory_curation_gaps()
    if orphans is None:
        r.add('memory curation', WARNING,
              'MEMORY.md is missing from the live workspace — the index is the '
              'entry point every session reads')
        return
    problems = []
    if orphans:
        problems.append(f'{len(orphans)} topic file(s) not in the index '
                        f'(e.g. {orphans[0]})')
    if dangling:
        problems.append(f'{len(dangling)} index link(s) resolve to nothing '
                        f'(e.g. {dangling[0]})')
    if problems:
        r.add('memory curation', WARNING, '; '.join(problems))
    else:
        r.add('memory curation', OK, 'index and topic files agree')


def check_benchmark_freshness(r):
    """The benchmark overlay must say how old its last point is.

    Retaining previous bars when a fetch returns empty is correct and silent.
    On 2026-08-26 the file was written at 00:03Z with HSI/HSTECH through 08-25
    and SPY still at 08-21 — two completed US sessions behind — and nothing
    said so anywhere: the equity curve drew today's book against a two-day-old
    benchmark and `regime.py` derived the US leverage regime from the same
    series.

    Read from the value stored AT WRITE TIME, not recomputed now. Recomputing
    would flag every HK evening between the 16:00 close and the next morning's
    fetch, which is not staleness — it is the schedule. A job that stops running
    altogether is a different failure and `check_host_cron_logs` owns it.
    """
    path = WS / 'assets' / 'data' / 'benchmark.json'
    if not path.is_file():
        r.add('benchmark freshness', WARNING, 'assets/data/benchmark.json missing')
        return
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:  # noqa: BLE001
        r.add('benchmark freshness', WARNING, f'unreadable: {e}')
        return
    freshness = data.get('freshness')
    if not freshness:
        r.add('benchmark freshness', WARNING,
              'no freshness block — the writer predates it, so how stale the '
              'overlay is cannot be answered from the file')
        return
    stale = []
    for key, row in sorted(freshness.items()):
        behind = row.get('sessions_behind')
        expected = row.get('expected_lag_sessions') or 0
        if behind is None or behind <= expected:
            continue
        stale.append(f"{key} {behind} session(s) behind "
                     f"(last {row.get('last_session')}, normal {expected})")
    if stale:
        r.add('benchmark freshness', WARNING, '; '.join(stale))
    else:
        r.add('benchmark freshness', OK,
              ' · '.join(f"{k} @ {v.get('last_session')}"
                         for k, v in sorted(freshness.items())))


def _unthesised_holdings():
    """Active holdings with no canonical thesis document, by ticker."""
    try:
        from clawock.decision import theses as thesis_registry
        docs, _ = thesis_registry.load_registry(WS / 'memory' / 'theses')
        have = {str(doc.get('ticker')) for doc in docs}
        book = json.loads((WS / 'portfolio.json').read_text(encoding='utf-8'))
    except Exception:      # noqa: BLE001 — a broken probe must not fail closed
        return []
    out = []
    for port in (book.get('portfolios') or {}).values():
        for holding in (port or {}).get('holdings') or []:
            ticker = str(holding.get('ticker') or '')
            shares = holding.get('shares') or 0
            if ticker and shares > 0 and ticker not in have:
                out.append(ticker)
    return sorted(out)


def check_research_artifacts(r):
    """Thesis, earnings and entry-gate artifacts must stay valid.

    An artifact whose stated verdict no longer matches the computed one, or whose
    schema broke, is an integrity failure. A due earnings review or an ungated
    position is the human's work queue, so it warns and never blocks a publish.
    """
    try:
        from clawock.evidence import research_surface
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
    elif not counts['theses'] and _unthesised_holdings():
        # "Zero valid artifacts" and "no open work" are the same sentence to a
        # validator and opposite facts to a reader — but say the RIGHT thing
        # about it. The first version of this branch claimed an empty research
        # layer held the add side shut; it does not, and the wrong text shipped
        # for one evening (#1075 → corrected same night).
        #
        # What is actually true: the canonical thesis registry is a KILL SWITCH.
        # Only `state ∈ {broken, damaged, weakening}` changes a number — it
        # zeroes the tranche. `intact` and "no document at all" size identically.
        # So an empty registry does not block anything; it means the switch has
        # never been armed, and the day a holding's story breaks there is nothing
        # to trip. Named per holding because that is the unit somebody would act
        # on.
        #
        # Entry gates and earnings artifacts are deliberately NOT part of this
        # condition: `research-governance.json` requires a gate only for
        # positions opened on or after `gate_required_from` (2026-07-27), and
        # every current holding predates it. Zero gates is the policy working,
        # not a gap — `ungated_positions` already warns about the real case.
        names = _unthesised_holdings()
        r.add('research artifacts', WARNING,
              f'{tally} valid; the thesis kill-switch is unarmed for '
              f'{len(names)} active holding(s) ({", ".join(names[:4])}'
              f'{"…" if len(names) > 4 else ""}) — nothing can trip when a '
              f'story breaks')
    else:
        r.add('research artifacts', OK, f'{tally} valid · no open research work')


def main():
    r = Result()
    # GitHub Secret Scanning + Push Protection own repository-wide credential
    # detection. The pre-commit hook still scans staged additions locally; do
    # not put the old full-tree git-grep back into this latency-sensitive hook.
    checks = [
        check_baseline_files,
        check_root_allowlist,
        check_scripts_compile,
        check_portfolio_schema,
        check_instrument_registry,
        check_plan_json_schema,
        check_dashboard_buildable,
        check_peer_map_coverage,
        check_openclaw_doctor,
        check_decision_ledger,
        check_context_capability,
        check_cron_paths_exist,
        check_host_crontab_targets,
        check_host_cron_logs,
        check_publish_backlog,
        check_delivered_but_unarchived,
        check_fallback_chain_shape,
        check_model_chain_health,
        check_delivery_channel_health,
        check_generated_cron_docs,
        check_research_artifacts,
        check_trading_calendar_horizon,
        check_memory_index,
        check_memory_curation,
        check_benchmark_freshness,
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
