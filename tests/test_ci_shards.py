"""A failed or missing shard must block the required gate; tests are not lost."""
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
    assert [shard_for(n, 4) for n in ids] == [shard_for(n, 4) for n in ids]


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
