"""A same-cycle re-scan that only moved generated_at must not commit.

Every scan stamps `generated_at` with its own run time, so the commit helper's
"no change" exit could never fire and a retry that found nothing new still
committed and redeployed Pages (sentiment 2026-10-12 `d7edf1f58`, 2026-10-14
`46fcfc92c`). `ops/ci/hold_unchanged_sidecar.py` writes the committed bytes
back in that case, but only inside one scheduled cycle, so a confirmed
sidecar never starts reading as stale.
"""
import importlib.util
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from clawock.publish import dashboard
from workflow_contract_helpers import step_run, steps

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hold = _load('hold_unchanged_sidecar', ROOT / 'ops' / 'ci' / 'hold_unchanged_sidecar.py')
snap = _load('snapshot_factor_sidecar', ROOT / 'ops' / 'ci' / 'snapshot_factor_sidecar.py')

CYCLE = datetime(2026, 10, 18, 21, 45, tzinfo=timezone.utc)


def _macro(generated_at, dxy=101.862):
    return (json.dumps({'generated_at': generated_at,
                        'dxy': {'price': dxy, 'as_of': 1792366196}}, indent=2) + '\n').encode()


def test_a_retry_that_only_moved_generated_at_keeps_the_committed_copy():
    old = _macro('2026-10-18T23:20:21+00:00')
    new = _macro('2026-10-18T23:44:33+00:00')

    verdict, reason = hold.decide(new, old, CYCLE)

    assert verdict == 'hold'
    assert '2026-10-18T23:20:21+00:00' in reason


def test_a_fresher_reading_is_committed():
    old = _macro('2026-10-18T23:20:21+00:00')
    new = _macro('2026-10-18T23:44:33+00:00', dxy=101.871)

    assert hold.decide(new, old, CYCLE)[0] == 'commit'


def test_the_first_scan_after_a_fire_commits_even_when_the_readings_repeat():
    # A holiday can repeat every reading; holding yesterday's copy would leave
    # the health card's mtime and the brief's 36h age on yesterday.
    old = _macro('2026-10-17T23:20:21+00:00')
    new = _macro('2026-10-18T23:20:21+00:00')

    assert hold.decide(new, old, CYCLE)[0] == 'commit'


@pytest.mark.parametrize('old, cycle', [
    (None, CYCLE),
    (b'not json', CYCLE),
    (json.dumps({'dxy': {'price': 101.862, 'as_of': 1792366196}}).encode(), CYCLE),
    (_macro('2026-10-18T23:20:21+00:00'), None),
])
def test_anything_it_cannot_prove_is_the_same_cycle_is_committed(old, cycle):
    new = _macro('2026-10-18T23:44:33+00:00')

    assert hold.decide(new, old, cycle)[0] == 'commit'


@pytest.mark.parametrize('name, at, expected', [
    # Sunday UTC evening: the 21:45 fire has started, its grace has not run out.
    ('macro.json', '2026-10-18T23:44:00+00:00', '2026-10-18T21:45:00+00:00'),
    ('macro.json', '2026-10-19T03:00:00+00:00', '2026-10-18T21:45:00+00:00'),
    # No Friday or Saturday fire: the weekend still belongs to Thursday's.
    ('macro.json', '2026-10-17T12:00:00+00:00', '2026-10-15T21:45:00+00:00'),
    ('sentiment.json', '2026-10-18T21:31:00+00:00', '2026-10-18T21:30:00+00:00'),
    # Two fires a day; the later one that has started wins.
    ('influencer_feed.json', '2026-10-19T13:00:00+00:00', '2026-10-19T12:50:00+00:00'),
    ('influencer_feed.json', '2026-10-19T12:00:00+00:00', '2026-10-18T21:40:00+00:00'),
])
def test_the_cycle_starts_at_the_health_cards_latest_fire(name, at, expected):
    got = dashboard.latest_scheduled_fire(name, datetime.fromisoformat(at))

    assert got == datetime.fromisoformat(expected)


def test_a_file_without_a_schedule_has_no_cycle():
    at = datetime(2026, 10, 19, tzinfo=timezone.utc)

    assert dashboard.latest_scheduled_fire('portfolio.json', at) is None


def _git(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout


def test_a_held_retry_reaches_the_commit_helper_as_no_change(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    data = repo / 'assets' / 'data'
    data.mkdir(parents=True)
    _git(repo, 'init', '-q', '-b', 'master')
    first = _macro('2026-10-18T23:20:21+00:00')
    (data / 'macro.json').write_bytes(first)
    snap.snapshot(data / 'macro.json', 'macro', '2026-10-19', root=data / 'factor-snapshots')
    _git(repo, 'add', '.')
    _git(repo, '-c', 'user.name=t', '-c', 'user.email=t@example.invalid',
         'commit', '-qm', 'host-dispatched scan')
    head = _git(repo, 'rev-parse', 'HEAD')

    # The scheduled retry lands 24 minutes later with the same readings.
    (data / 'macro.json').write_bytes(_macro('2026-10-18T23:44:33+00:00'))
    monkeypatch.chdir(repo)
    monkeypatch.setattr(dashboard, 'latest_scheduled_fire', lambda name, at: CYCLE)
    assert hold.main(['--source', 'assets/data/macro.json']) == 0
    assert snap.snapshot(data / 'macro.json', 'macro', '2026-10-19',
                         root=data / 'factor-snapshots') == 'unchanged'
    pushed = subprocess.run(
        ['bash', str(ROOT / 'ops' / 'publish' / 'gha_commit_push.sh'), 'macro: retry',
         'assets/data/macro.json', 'assets/data/factor-snapshots/macro'],
        cwd=repo, capture_output=True, text=True)

    assert pushed.returncode == 0, pushed.stderr
    assert 'no change' in pushed.stdout
    assert _git(repo, 'rev-parse', 'HEAD') == head
    assert (data / 'macro.json').read_bytes() == first


@pytest.mark.parametrize('workflow, source, before', [
    ('macro-scan.yml', 'assets/data/macro.json', 'Snapshot point-in-time copy'),
    ('sentiment-scan.yml', 'assets/data/sentiment.json', 'Snapshot point-in-time copy'),
    ('influencer-scan.yml', 'assets/data/influencer_feed.json', 'Commit + push'),
])
def test_each_scan_holds_its_own_sidecar_after_validation_and_before_publishing(
        workflow, source, before):
    path = ROOT / '.github' / 'workflows' / workflow
    names = [name for _, name in steps(path)]
    step = 'Keep the committed copy when only generated_at moved'
    validate = next(n for n in names if n.startswith('Validate '))

    # After validation so the fresh scan is what gets validated; before the
    # snapshot so the dated copy is taken from the bytes that will be committed.
    assert names.index(validate) < names.index(step) < names.index(before)
    assert step_run(path, step).split() == [
        'python3', 'ops/ci/hold_unchanged_sidecar.py', '--source', source]
