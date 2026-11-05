"""A failed or missing shard must block the required gate; tests are not lost."""
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from ops.ci.pytest_shard import pytest_collection_modifyitems, shard_for

ROOT = Path(__file__).resolve().parents[1]


def test_partition_is_disjoint_and_complete(monkeypatch):
    ids = [f'tests/test_{i // 17}.py::test_{i}[case]' for i in range(1000)]
    partitions = []
    for shard in range(4):
        monkeypatch.setenv('CI_SHARD_INDEX', str(shard))
        monkeypatch.setenv('CI_SHARD_TOTAL', '4')
        removed = []
        config = SimpleNamespace(hook=SimpleNamespace(
            pytest_deselected=lambda items: removed.extend(items)))
        items = [SimpleNamespace(nodeid=n) for n in ids]
        pytest_collection_modifyitems(config, items)
        selected = {i.nodeid for i in items}
        assert selected.isdisjoint(i.nodeid for i in removed)
        assert len(selected) + len(removed) == len(ids)
        partitions.append(selected)
    assert set.union(*partitions) == set(ids)
    assert sum(map(len, partitions)) == len(ids)


@pytest.mark.parametrize('index,total', [('4', '4'), ('0', '0'), ('-1', '4'), ('x', '4')])
def test_bad_shard_fails_instead_of_silently_skipping(monkeypatch, index, total):
    monkeypatch.setenv('CI_SHARD_INDEX', index)
    monkeypatch.setenv('CI_SHARD_TOTAL', total)
    with pytest.raises(pytest.UsageError):
        pytest_collection_modifyitems(None, [])


def test_combined_gate_requires_every_shard_and_original_floors():
    jobs = yaml.safe_load((ROOT / '.github/workflows/ci.yml').read_text())['jobs']
    assert jobs['unit-tests']['strategy']['matrix']['shard'] == [0, 1, 2, 3]
    assert jobs['unit-tests']['strategy']['fail-fast'] is False
    gate = jobs['validate']
    assert set(gate['needs']) == {'scope', 'checks', 'unit-tests'}
    steps = {s.get('name'): s for s in gate['steps']}
    assert 'test "$UNIT" = success' in steps['Require all selected lanes']['run']
    combine = steps['Coverage floors']['run']
    assert '-eq 4' in combine
    assert 'coverage combine' in combine
    assert 'coverage_badge.py --report coverage-report.json --check-only' in combine
    book_step = next(s for s in jobs['checks']['steps'] if s.get('name') == 'Decision v2 unit tests (book-only)')
    assert book_step['if'] == "steps.changes.outputs.book == 'true'"
    assert not any('pytest tests/' in s.get('run', '') and '-m book' not in s['run']
                   for s in jobs['checks']['steps'])


@pytest.mark.parametrize('scope,checks,code,unit,ok', [
    ('success', 'success', 'true', 'success', True),
    ('success', 'success', 'false', 'skipped', True),
    ('failure', 'skipped', 'false', 'skipped', False),
    ('success', 'failure', 'false', 'skipped', False),
    ('success', 'success', 'true', 'failure', False),
    ('success', 'success', 'true', 'skipped', False),
])
def test_required_gate_executes_fail_closed(scope, checks, code, unit, ok):
    jobs = yaml.safe_load((ROOT / '.github/workflows/ci.yml').read_text())['jobs']
    script = jobs['validate']['steps'][0]['run']
    result = subprocess.run(['bash', '-e', '-c', script], env=dict(
        os.environ, SCOPE=scope, CHECKS=checks, CODE=code, UNIT=unit))
    assert (result.returncode == 0) == ok


def test_file_fixtures_are_not_duplicated_between_shards_or_workers():
    ids = ['tests/test_install.py::test_a', 'tests/test_install.py::TestB::test_b[x]']
    assert shard_for(ids[0], 4) == shard_for(ids[1], 4)
    jobs = yaml.safe_load((ROOT / '.github/workflows/ci.yml').read_text())['jobs']
    step = next(s for s in jobs['unit-tests']['steps'] if 'pytest' in s.get('run', ''))
    assert '--dist loadfile' in step['run']
