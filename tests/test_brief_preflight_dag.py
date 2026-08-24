"""Runtime DAG contracts for the brief_preflight wave orchestrator (#916).

These tests drive the REAL ``main()`` against a throwaway workspace: every
``clawock`` subprocess is answered by an in-process recorder (no network, no
provider), fresh GH-Action sidecars keep the warn-only loaders silent, and the
extracted node functions are wrapped with a timeline recorder so wave barriers,
the parallelism cap, the NODE_ORDER issue joins and the step_timings ledger
detail are asserted against exactly the code production runs.

The workspace switch works through ``CLAWOCK_WORKSPACE`` plus a reload of every
module that freezes a workspace path at import time; monkeypatch restores both
the env var and the previous module objects afterwards.

Run: python3 -m pytest tests/test_brief_preflight_dag.py -q
"""
import importlib
import json
import subprocess
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Modules that freeze WS-derived paths at import time, dependencies first and
# brief_preflight last, so its `from X import Y` bindings pick up reloaded
# objects.
RELOAD_TARGETS = (
    'clawock.instruments',
    'clawock.decision.risk',
    'clawock.decision.ledger',
    'clawock.decision.plans',
    'clawock.decision.theses',
    'clawock.evidence.research_surface',
    'clawock.portfolio.integrity',
    'clawock.market_data.peer_scan',
    'clawock.harness.brief_preflight',
)

TODAY = '2026-08-25'

# Two boring legs: no guardrail breach, one non-leveraged US single for the
# SEC loop, known total_pnl values for the book arithmetic.
PORTFOLIO = {
    'portfolios': {
        'hk_stocks': {
            'total_pnl': 12345.67,
            'holdings': [
                {'ticker': '0700', 'name': 'Tencent', 'shares': 100,
                 'cost_basis': 300.0, 'current_price': 330.0},
                {'ticker': '9988', 'name': 'Alibaba', 'shares': 200,
                 'cost_basis': 80.0, 'current_price': 90.0},
            ],
        },
        'us_stocks': {
            'total_pnl': 2345.67,
            'holdings': [
                {'ticker': 'PLTR', 'name': 'Palantir', 'shares': 100,
                 'cost_basis': 10.0, 'current_price': 11.0},
                {'ticker': 'MSFT', 'name': 'Microsoft', 'shares': 50,
                 'cost_basis': 30.0, 'current_price': 31.0},
            ],
        },
    },
}

# clawock command -> (returncode, stdout). Anything absent succeeds silently;
# artifacts on disk are absent, so nodes take their "file not written" branch.
DEFAULT_PLAN = {
    'fx': (0, '{"rate": 7.81, "source": "TEST"}'),
    'filings': (0, '{"key_financials": {"Revenues": {}}}'),
    'daily-bars': (0, '3 bars added, 0 revised'),
    'catalysts': (0, '{"summary": {}}'),
}

SIDE_CARS = ('macro.json', 'sentiment.json', 'influencer_feed.json', 'em_news.json')


def _build_workspace(root):
    """Minimal book + config + freshly-stamped sidecars: zero background issues."""
    (root / 'config').mkdir(parents=True, exist_ok=True)
    # Every tracked engine-facing config comes along (the decision packet reads
    # several), EXCEPT watch-list.json: a populated watch list makes
    # watch_list.collect fetch live bars.
    for src in sorted((ROOT / 'config').glob('*.json')):
        if src.name == 'watch-list.json':
            continue
        (root / 'config' / src.name).write_text(src.read_text())
    # slot_for_job validates every contract profile, including message-template
    # paths, so the payloads tree must come along with the contract file.
    payloads = root / 'config' / 'cron-payloads'
    payloads.mkdir(exist_ok=True)
    for src in (ROOT / 'config' / 'cron-payloads').iterdir():
        if src.is_file():
            (payloads / src.name).write_text(src.read_text())
    (root / 'assets' / 'data').mkdir(parents=True, exist_ok=True)
    for name in SIDE_CARS:
        (root / 'assets' / 'data' / name).write_text(
            json.dumps({'generated_at': _fresh_stamp()}))
    (root / 'portfolio.json').write_text(json.dumps(PORTFOLIO))
    return root


def _fresh_stamp():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class _SpawnRecorder:
    """Stands in for subprocess.run and _run_clawock inside preflight."""

    def __init__(self, plan=None, delays=None):
        self.plan = plan or {}
        self.delays = delays or {}
        self.calls = []
        self.lock = threading.Lock()
        self.running = defaultdict(int)
        self.max_parallel_filings = 0

    def subprocess_run(self, argv, **kwargs):
        command = argv[1] if len(argv) > 1 else argv[0]
        with self.lock:
            self.calls.append(('subprocess', command, list(argv)))
            self.running[command] += 1
            if command == 'filings':
                self.max_parallel_filings = max(
                    self.max_parallel_filings, self.running['filings'])
        try:
            time.sleep(self.delays.get(command, 0))
            rc, out = self.plan.get(command, (0, ''))
            return subprocess.CompletedProcess(argv, rc, stdout=out, stderr='')
        finally:
            with self.lock:
                self.running[command] -= 1

    def clawock(self, command, args=None, timeout=120):
        with self.lock:
            self.calls.append(('clawock', command, [command] + list(args or [])))
        time.sleep(self.delays.get(command, 0))
        rc, out = self.plan.get(command, (0, 'ok'))
        if rc == 0:
            return out, True
        return f'{command}-failed-marker', False


class _Timeline:
    """Per-node start/end monotonic stamps + concurrency tracking."""

    def __init__(self):
        self.lock = threading.Lock()
        self.start = {}
        self.end = {}
        self.count = defaultdict(int)
        self.running = 0
        self.max_parallel = 0

    def wrap(self, fn, name):
        def wrapped(*args, **kwargs):
            with self.lock:
                self.start[name] = time.monotonic()
                self.count[name] += 1
                self.running += 1
                self.max_parallel = max(self.max_parallel, self.running)
            try:
                return fn(*args, **kwargs)
            finally:
                with self.lock:
                    self.end[name] = time.monotonic()
                    self.running -= 1
        return wrapped


def run_stubbed_preflight(tmp_path, monkeypatch, *, plan=None, delays=None):
    """Drive the real brief_preflight.main() against a stubbed workspace."""
    ws = _build_workspace(Path(tmp_path))

    # Workspace switch without reload(): importlib.reload would re-execute the
    # ORIGINAL module object in place, poisoning every other holder of that
    # reference (a test module's collection-time import included). Instead the
    # current object is dropped from sys.modules so a FRESH one is created
    # against CLAWOCK_WORKSPACE, and afterwards the untouched originals are put
    # back — in sys.modules AND as parent-package attributes, because
    # `from clawock.harness import brief_preflight` reads the latter, not the
    # former. Modules first imported inside the window are dropped again.
    saved_modules = {name: sys.modules.get(name) for name in RELOAD_TARGETS}
    saved_keys = frozenset(sys.modules)
    saved_parent_attrs = {}
    for name in RELOAD_TARGETS:
        pname, _, pattr = name.rpartition('.')
        parent = sys.modules.get(pname)
        if parent is not None:
            saved_parent_attrs[name] = (parent, pattr,
                                        vars(parent).get(pattr, _MISSING))
    try:
        for name in RELOAD_TARGETS:
            sys.modules.pop(name, None)
        return _run_with_reloaded_modules(
            ws, monkeypatch, plan=plan, delays=delays)
    finally:
        created = [k for k in sys.modules if k not in saved_keys
                   and (k == 'clawock' or k.startswith('clawock.'))]
        for key in created:
            del sys.modules[key]
        for key in created:
            pname, _, pattr = key.rpartition('.')
            parent = sys.modules.get(pname)
            if parent is not None and pattr in vars(parent):
                delattr(parent, pattr)
        for name, module in saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        for name, (parent, pattr, original) in saved_parent_attrs.items():
            current = vars(parent).get(pattr, _MISSING)
            if original is _MISSING:
                if current is not _MISSING:
                    delattr(parent, pattr)
            elif current is not original:
                setattr(parent, pattr, original)


_MISSING = object()


def _run_with_reloaded_modules(ws, monkeypatch, *, plan, delays):
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(ws))
    monkeypatch.setenv('TODAY', TODAY)
    for name in RELOAD_TARGETS:
        importlib.import_module(name)

    from clawock import sessions as trading_calendar
    from clawock.automation import workflow_outcomes

    pf = sys.modules['clawock.harness.brief_preflight']

    recorder = _SpawnRecorder(plan=dict(plan or DEFAULT_PLAN), delays=delays or {})
    monkeypatch.setattr(pf.subprocess, 'run', recorder.subprocess_run)
    monkeypatch.setattr(pf, '_run_clawock', recorder.clawock)
    # Both markets open: the holiday gate must not skip the run.
    monkeypatch.setattr(trading_calendar, 'closed_reason', lambda market, d=None: None)
    # research_surface's HK results probe would otherwise hit Tencent.
    monkeypatch.setattr(pf, '_fetch_hk_results_notices', lambda ticker: [])

    timeline = _Timeline()
    for name in pf.NODE_ORDER:
        monkeypatch.setattr(pf, name, timeline.wrap(getattr(pf, name), name))
    monkeypatch.setattr(
        pf, 'compute_decision_metrics',
        timeline.wrap(pf.compute_decision_metrics, '_decision_metrics'))

    stage_calls = []

    def _stage_spy(job_name, stage, status, **kwargs):
        stage_calls.append({'job': job_name, 'stage': stage,
                            'status': status, 'kwargs': kwargs})
        return {}

    monkeypatch.setattr(workflow_outcomes, 'record_stage', _stage_spy)

    exit_code = pf.main([])
    ctx_path = ws / 'memory' / '.tmp' / f'brief-context-{TODAY}.json'
    context = json.loads(ctx_path.read_text())
    return SimpleNamespace(exit_code=exit_code, context=context,
                           issues=context['issues'], stage_calls=stage_calls,
                           timeline=timeline, recorder=recorder, workspace=ws,
                           pf=pf)


def _final_preflight_stage(run):
    finals = [s for s in run.stage_calls
              if s['stage'] == 'preflight' and s['status'] in ('success', 'warning')]
    assert finals, f'no final preflight stage recorded: {run.stage_calls}'
    return finals[-1]


def test_wave_nodes_execute_exactly_once_and_respect_edges(tmp_path, monkeypatch):
    run = run_stubbed_preflight(tmp_path, monkeypatch, delays=_stagger_delays())
    tl, pf = run.timeline, run.pf

    wanted = set(pf.NODE_ORDER) | {'_decision_metrics'}
    assert set(tl.count) == wanted, 'every node must run exactly once'
    assert all(v == 1 for v in tl.count.values()), dict(tl.count)

    # quant → t0 (ATR), quant → quant-review/cross-factor (history/artifacts)
    assert tl.start['t0_node'] >= tl.end['quant_node']
    assert tl.start['quant_review_node'] >= tl.end['quant_node']
    assert tl.start['cross_factor_node'] >= tl.end['quant_node']
    # em-news + catalysts complete before news-evidence builds its graph,
    # and cross-factor's rewrite of cross_sectional_factor.json lands before
    # news-evidence reads it for the confirmation gate (J-P1-1)
    assert tl.start['news_evidence_node'] >= tl.end['cross_factor_node']
    assert tl.start['news_evidence_node'] >= max(tl.end['em_news_node'],
                                                 tl.end['catalysts_node'])
    # evidence page rebuilds only after quant-review + cross-factor finalize
    assert tl.start['evidence_node'] >= max(tl.end['quant_review_node'],
                                            tl.end['cross_factor_node'])
    # t0-review reconciles t0's history jsonl
    assert tl.start['t0_review_node'] >= tl.end['t0_node']
    # determinism edge: regime FINISHES before benchmark STARTS (#916 §1.2)
    assert tl.start['benchmark_node'] >= tl.end['regime_node']
    # settle reads the canonical bar store, so bars finish first
    assert tl.start['_decision_metrics'] >= tl.end['daily_bars_node']

    # SEC filings stay strictly serial inside collect_us_fundamentals
    assert run.recorder.max_parallel_filings == 1

    assert run.exit_code == 0
    assert run.issues == []


def test_max_parallelism_never_exceeds_two(tmp_path, monkeypatch):
    run = run_stubbed_preflight(tmp_path, monkeypatch, delays=_stagger_delays())

    assert run.timeline.max_parallel <= 2, '_run_wave must cap workers at 2'
    assert run.timeline.max_parallel >= 2, (
        'waves never actually ran two nodes concurrently — the schedule '
        'degenerated to serial')


def test_issues_order_is_deterministic_regardless_of_completion_order(tmp_path, monkeypatch):
    expected = [
        'US refresh failed: analyze-us-failed-marker',
        'SEC EDGAR PLTR failed',
        'SEC EDGAR MSFT failed',
        'FX fallback used: provider down',
        'daily bar refresh failed',
        'catalysts fetch failed',
        'benchmark history fetch failed',
        'news evidence graph failed',
    ]
    failures = {
        'analyze-us': (1, ''),
        'fx': (1, 'provider down'),
        'filings': (1, 'sec down'),
        'daily-bars': (1, ''),
        'catalysts': (1, 'cat down'),
        'news-evidence': (1, 'graph down'),
        'benchmark': (1, ''),
    }
    # Two opposite delay profiles scramble completion order within each wave;
    # the context issues must come out in NODE_ORDER both times (#916).
    fast_first = {'analyze-us': 0.01, 'filings': 0.02, 'fx': 0.30,
                  'daily-bars': 0.25, 'catalysts': 0.01,
                  'news-evidence': 0.20, 'benchmark': 0.01}
    slow_first = {'analyze-us': 0.05, 'filings': 0.01, 'fx': 0.01,
                  'daily-bars': 0.03, 'catalysts': 0.30,
                  'news-evidence': 0.25, 'benchmark': 0.20}

    seen = []
    for delays in (fast_first, slow_first):
        run = run_stubbed_preflight(tmp_path, monkeypatch,
                                    plan=failures, delays=delays)
        assert run.exit_code == 1
        assert run.issues == expected, run.issues
        assert _final_preflight_stage(run)['status'] == 'warning'
        seen.append(run.context['issues'])

    assert seen[0] == seen[1]


def test_step_timings_recorded_in_preflight_stage(tmp_path, monkeypatch):
    run = run_stubbed_preflight(tmp_path, monkeypatch)
    final = _final_preflight_stage(run)

    timings = final['kwargs']['step_timings']
    assert set(timings) == set(run.pf.NODE_ORDER), (
        'step_timings must carry exactly one entry per node')
    for name, entry in timings.items():
        assert set(entry) == {'ok', 'wall_s'}, (name, entry)
        assert entry['ok'] is True, name
        assert isinstance(entry['wall_s'], float) and entry['wall_s'] >= 0.0
    # earlier pending/skipped stages carry no step_timings detail
    pendings = [s for s in run.stage_calls if s['status'] == 'pending']
    assert pendings and all('step_timings' not in s['kwargs'] for s in pendings)


def _stagger_delays():
    """Long enough to force overlap inside waves; short enough to stay fast."""
    return {
        'analyze-us': 0.02, 'analyze-hk': 0.02, 'filings': 0.03,
        'fx': 0.18, 'peer-scan': 0.05, 'daily-bars': 0.15,
        'portfolio-risk': 0.20, 'regime': 0.12, 'quant': 0.25,
        'em-news': 0.08, 'catalysts': 0.06, 'peer-residual': 0.10,
        'quant-review': 0.10, 'cross-factor': 0.12, 't0': 0.08,
        'news-evidence': 0.10, 'benchmark': 0.05,
        't0-review': 0.06, 'evidence': 0.05,
    }
