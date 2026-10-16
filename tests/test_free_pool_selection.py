"""Dynamic candidates take effect without editing the seed; bad evidence cannot pay for inference."""
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import subprocess
import time
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / 'ops/host/agent-dispatch'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


select = module('selection', DIR / 'select-free-models.py')
probe = module('candidate_probe', DIR / 'probe-free-candidates.py')
SEED = 'opencode/space-bunny-free'
NEW = 'opencode/new-free'


@pytest.fixture
def evidence(tmp_path):
    pool = tmp_path / 'pool'
    pool.write_text(SEED + '\n')
    report = {'checked_at': time.time(), 'policy_version': select.audit.POLICY_VERSION,
              'source_errors': {}, 'selection_ready': True, 'status': 'ok',
              'pool_hashes': select.audit.identity([pool, pool]),
              'models': [{'model': m, 'in_catalog': True, 'in_zen': True,
                          'catalog_cost': 'zero', 'metadata_cost': 'zero'} for m in (SEED, NEW)]}
    return pool, report


def test_new_candidate_is_selected_without_seed_write(evidence):
    pool, report = evidence
    before = pool.read_bytes()
    available = select.eligible(report, pool, time.time())
    selected, reasons = select.choose([SEED], available, {'mode': 'automatic', 'max_models': 9, 'exploration_position': 1})
    assert selected == [SEED, NEW]
    assert 'automatic discovery' in reasons[NEW]
    assert pool.read_bytes() == before


@pytest.mark.parametrize('field,value', [('catalog_cost', 'nonzero'), ('catalog_cost', 'unknown'),
                                        ('metadata_cost', 'nonzero'), ('in_zen', False), ('in_catalog', False)])
def test_bad_or_missing_primary_evidence_removes_a_seed(evidence, field, value):
    pool, report = evidence
    report['models'][0][field] = value
    assert select.eligible(report, pool, time.time()) == [NEW]


def test_missing_secondary_price_is_allowed_but_retirement_never_is(evidence):
    pool, report = evidence
    report['models'][0]['metadata_cost'] = 'unknown'
    report['models'][1]['model'] = 'opencode/nemotron-3-ultra-free'
    assert select.eligible(report, pool, time.time()) == [SEED]


@pytest.mark.parametrize('kind', ['stale', 'failure', 'seed_changed', 'old_policy', 'missing'])
def test_invalid_snapshot_blocks_instead_of_reverting_to_static_seed(evidence, kind):
    pool, report = evidence
    if kind == 'stale':
        report['checked_at'] = time.time() - select.audit.STALE - 1
    elif kind == 'failure':
        report['source_errors'] = {'zen': 'HTTP 429'}
    elif kind == 'seed_changed':
        pool.write_text(SEED + '\n# drift')
    elif kind == 'old_policy':
        report['policy_version'] = 1
    else:
        report = {}
    with pytest.raises(ValueError):
        select.eligible(report, pool, time.time())


def test_capacity_rotates_newcomers_and_seed_only_is_safe_rollback():
    seeds = [f'opencode/seed-{i}-free' for i in range(9)]
    available = seeds + [NEW, 'opencode/another-free']
    settings = {'mode': 'automatic', 'max_models': 9, 'exploration_position': 1}
    first, _ = select.choose(seeds, available, settings, 0)
    second, _ = select.choose(seeds, available, settings, 1)
    assert len(first) == len(second) == 9 and first[0] == second[0] == seeds[0]
    assert first[1] != second[1]
    assert select.choose(seeds, available, {**settings, 'mode': 'seed-only'})[0] == seeds
    with pytest.raises(ValueError):
        select.choose(seeds, available, {**settings, 'mode': 'paused'})


def test_explicit_model_cannot_bypass_and_filter_observes_changed_evidence(evidence, tmp_path):
    pool, report = evidence
    report_path = tmp_path / 'report.json'
    report_path.write_text(json.dumps(report))
    command = ['python3', str(DIR / 'select-free-models.py'), '--pool', str(pool), '--report', str(report_path)]
    r = subprocess.run(command, capture_output=True, text=True, timeout=5)
    assert r.returncode == 0 and json.loads(r.stdout)['models'] == [SEED, NEW]
    assert (tmp_path / 'free-pool-selection.json').exists()
    report['models'][0]['catalog_cost'] = 'nonzero'
    report_path.write_text(json.dumps(report))
    r = subprocess.run(command + ['--filter', SEED + ',' + NEW], capture_output=True, text=True, timeout=5)
    assert r.returncode == 0 and r.stdout.strip() == NEW
    r = subprocess.run(command + ['--prefer', SEED], capture_output=True, text=True, timeout=5)
    assert r.returncode == 2 and not r.stdout


def test_big_pickle_is_the_only_non_suffixed_exception():
    assert select.CHECKER.validate(['opencode/big-pickle'])
    for bad in ('opencode/big-pickle-paid', 'opencode/gpt-paid', 'other/big-pickle', *select.CHECKER.RETIRED):
        with pytest.raises(ValueError):
            select.CHECKER.validate([bad])


def test_tool_proof_rejects_a_string_and_failed_tool():
    text = {'type': 'text', 'part': {'text': 'PROBE-OK'}}
    fake = {'type': 'text', 'part': {'text': 'TOOL-PROBE-OK'}}
    tool = {'type': 'tool_use', 'part': {'tool': 'bash', 'state': {'status': 'completed',
            'input': {'command': 'echo TOOL-PROBE-OK'}, 'output': 'TOOL-PROBE-OK\n'}}}
    assert probe.verdict([text, fake], 0) == 'unverified'
    assert probe.verdict([tool, text], 0) == 'verified_tool'
    assert probe.verdict([tool, text], 1) == 'unverified'
    tool['part']['state']['status'] = 'error'
    assert probe.verdict([tool, text], 0) == 'unverified'
    assert probe.verdict([], 124) == 'timeout_unknown'
    assert probe.verdict([{'type': 'error', 'error': {'message': 'FreeUsageLimitError 429'}}], 0) == 'rate_limited'


def test_completed_tool_with_provider_thinking_terminator_is_verified():
    # Observed in the first scheduled big-pickle probe; no new inference needed.
    text = {'type': 'text', 'part': {'text': '</think>PROBE-OK'}}
    tool = {'type': 'tool_use', 'part': {'tool': 'bash', 'state': {'status': 'completed',
            'input': {'command': 'echo TOOL-PROBE-OK'}, 'output': 'TOOL-PROBE-OK\n'}}}
    assert probe.verdict([tool, text], 0) == 'verified_tool'
    assert probe.verdict([text], 0) == 'unverified'
    assert probe.verdict([tool, text], 1) == 'unverified'
    tool['part']['state']['status'] = 'error'
    assert probe.verdict([tool, text], 0) == 'unverified'


def test_probe_window_frequency_and_failure_backoff_leave_other_candidates_a_turn():
    now = datetime.now(ZoneInfo('Asia/Shanghai')).replace(hour=4, minute=0, second=0).timestamp()
    assert probe.next_model([SEED, NEW], {}, now) is None
    day = datetime.fromtimestamp(now, ZoneInfo('Asia/Shanghai')).replace(hour=10).timestamp()
    assert probe.next_model([SEED, NEW], {'last_run': day - 30}, day) is None
    state = {'models': {SEED: {'next_at': day + 86400, 'checked_at': day - 86400}}}
    assert probe.next_model([SEED, NEW], state, day) == NEW


def test_dispatch_and_runner_use_selector_for_real_inference():
    dispatch = (DIR / 'dispatch.sh').read_text()
    runner = (DIR / 'run-agent.sh').read_text()
    assert 'POOL_SELECTION=$(python3 "$helper_dir/select-free-models.py"' in dispatch
    assert '>"$DIR/free-pool-selection.json"' in dispatch
    assert 'FREE_POOL_REPORT=$(printf %q "$FREE_POOL_REPORT")' in dispatch
    attempt_loop = runner.split('# ---- attempts ', 1)[1]
    assert attempt_loop.index('--filter "$pool_csv"') < attempt_loop.index('  run_attempt "$cap"')
