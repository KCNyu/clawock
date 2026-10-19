"""config/models.json is the one place model ids and the MiniMax endpoint are set."""
import copy
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('sync_model_refs', ROOT / 'ops/host/sync_model_refs.py')
refs = importlib.util.module_from_spec(_spec)
sys.modules['sync_model_refs'] = refs  # dataclasses resolve their module
_spec.loader.exec_module(refs)

OPENCLAW = {
    'models': {'providers': {
        name: {'baseUrl': 'https://api.minimaxi.com/anthropic', 'models': [
            {'id': 'MiniMax-M3.1-Flash', 'name': 'MiniMax M3.1 Flash'},
            {'id': 'MiniMax-M3', 'name': 'MiniMax M3'}]}
        for name in ('minimax', 'minimax-2')}},
    'agents': {'defaults': {
        'model': {'primary': 'minimax/MiniMax-M3.1-Flash', 'fallbacks': ['deepseek/deepseek-flash']},
        'models': {'minimax/MiniMax-M3.1-Flash': {}, 'minimax/MiniMax-M3': {}},
        'heartbeat': {'model': 'minimax/MiniMax-M3.1-Flash'},
        'subagents': {'model': 'minimax/MiniMax-M3.1-Flash'}}},
    'plugins': {'entries': {'memory-core': {
        'config': {'dreaming': {'model': 'minimax/MiniMax-M3.1-Flash'}},
        'subagent': {'allowedModels': ['minimax/MiniMax-M3.1-Flash']}}}},
}
DSH = ('      minimax:\n        baseURL: https://api.minimaxi.com/anthropic\n        models:\n'
       '        - id: MiniMax-M3\n          name: MiniMax-M3\n'
       '        - id: MiniMax-M3.1-Flash\n          name: MiniMax-M3.1-Flash\n')


@pytest.fixture
def sandbox(tmp_path):
    """Copies of the bound repo files plus fake host files."""
    for name in ('config/cron-schedules.json', 'src/clawock/automation/llm.py'):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, tmp_path / name)
    (tmp_path / 'openclaw.json').write_text(json.dumps(OPENCLAW, indent=2) + '\n')
    for profile in ('web', 'headless'):
        (tmp_path / 'dsh' / profile).mkdir(parents=True)
        (tmp_path / 'dsh' / profile / 'cordis.patch.yml').write_text(DSH)
    truth = refs.load_truth()

    def bound(value=truth):
        return list(refs.targets(value, root=tmp_path, openclaw_config=tmp_path / 'openclaw.json',
                                 dsh_profiles=tmp_path / 'dsh'))
    return tmp_path, truth, bound


def _drift(all_targets):
    return [(t.path.name, row) for t in all_targets for row in refs.inspect(t) if row[1] != row[2]]


def test_repo_copies_match_the_truth():
    """Hand-editing one copy of an id turns this red: edit config/models.json
    and run `ops/host/sync_model_refs.py --apply` instead."""
    repo = [t for t in refs.targets(refs.load_truth()) if not t.host]
    assert all(refs.inspect(t) for t in repo) and _drift(repo) == []


def test_every_copy_is_found_in_the_sandbox(sandbox):
    _, _, bound = sandbox
    counts = {t.path.name: len(refs.inspect(t)) for t in bound()}
    # cron: 7 paths x 3 strategy profiles + the memory profile's model
    assert counts == {'cron-schedules.json': 22, 'llm.py': 2, 'openclaw.json': 13,
                      'cordis.patch.yml': 3}
    assert _drift(bound()) == []


def test_one_edit_reaches_every_copy_and_is_idempotent(sandbox):
    root, truth, bound = sandbox
    new = copy.deepcopy(truth)
    new['minimax'].update(model='MiniMax-M3.2-Flash', display_name='MiniMax M3.2 Flash')
    assert len(refs.apply(bound(new))) == 5  # cron, llm.py, openclaw.json, two dsh profiles
    assert _drift(bound(new)) == []
    assert refs.apply(bound(new)) == []
    config = json.loads((root / 'openclaw.json').read_text())
    # The id kept in a JSON key moved too; the rollback id did not.
    assert list(config['agents']['defaults']['models']) == ['minimax/MiniMax-M3.2-Flash',
                                                            'minimax/MiniMax-M3']
    assert config['models']['providers']['minimax']['models'][1]['id'] == 'MiniMax-M3'
    dsh = (root / 'dsh/web/cordis.patch.yml').read_text()
    assert '- id: MiniMax-M3.2-Flash' in dsh and '- id: MiniMax-M3\n' in dsh
    cron = json.loads((root / 'config/cron-schedules.json').read_text())
    assert {p['model'] for p in cron['payload_profiles'].values()} == {'minimax/MiniMax-M3.2-Flash'}
    assert "MINIMAX_MODEL = 'MiniMax-M3.2-Flash'" in (root / 'src/clawock/automation/llm.py').read_text()


def test_an_unbound_copy_blocks_the_rewrite_before_anything_is_written(sandbox):
    root, truth, bound = sandbox
    config = copy.deepcopy(OPENCLAW)
    config['agents']['defaults']['imageModel'] = 'minimax/MiniMax-M3.1-Flash'
    (root / 'openclaw.json').write_text(json.dumps(config, indent=2) + '\n')
    before = (root / 'config/cron-schedules.json').read_text()
    new = copy.deepcopy(truth)
    new['minimax']['model'] = 'MiniMax-M3.2-Flash'
    with pytest.raises(ValueError, match='unbound copy'):
        refs.apply(bound(new))
    assert (root / 'config/cron-schedules.json').read_text() == before
