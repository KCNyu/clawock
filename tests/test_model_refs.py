"""config/models.json is the one place model ids and the MiniMax endpoint are set."""
import copy
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('sync_model_refs', ROOT / 'ops/host/sync_model_refs.py')
refs = importlib.util.module_from_spec(_spec)
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
    """A copy of the bound repo files plus fake host files, and a truth that
    points its host bindings at them."""
    truth = refs.load_truth()
    for name in {b['file'] for b in truth['bindings'] if not b.get('host')}:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, tmp_path / name)
    host = tmp_path / 'host'
    host.mkdir()
    (host / 'openclaw.json').write_text(json.dumps(OPENCLAW, indent=2) + '\n')
    for profile in ('web', 'headless'):
        (host / f'{profile}.yml').write_text(DSH)
    for binding in truth['bindings']:
        if 'openclaw.json' in binding['file']:
            binding['file'] = str(host / 'openclaw.json')
        elif '/profiles/' in binding['file']:
            binding['file'] = str(host / ('web.yml' if '/web/' in binding['file'] else 'headless.yml'))
    return tmp_path, truth


def test_repo_copies_match_the_truth():
    """Hand-editing one copy of an id turns this red; edit config/models.json
    and run `ops/host/sync_model_refs.py --apply` instead."""
    rows = refs.inspect(refs.load_truth(), include_host=False)
    assert rows and [r for r in rows if r['ok'] is not True] == []


def test_every_binding_resolves_in_the_sandbox(sandbox):
    root, truth = sandbox
    rows = refs.inspect(truth, root)
    assert len(rows) > len(truth['bindings'])  # wildcards expand per cron profile
    assert [r for r in rows if r['ok'] is not True] == []


def test_one_edit_reaches_every_copy_and_is_idempotent(sandbox):
    root, truth = sandbox
    truth['values']['minimax_model'] = 'MiniMax-M3.2-Flash'
    truth['values']['minimax_model_name'] = 'MiniMax M3.2 Flash'
    changed = refs.apply(truth, root)
    assert len(changed) == 5  # cron contract, llm.py, openclaw.json, two dsh profiles
    assert all(r['ok'] for r in refs.inspect(truth, root))
    assert refs.apply(truth, root) == []
    config = json.loads((root / 'host/openclaw.json').read_text())
    # The id hidden in a JSON key moved too; the rollback id did not.
    assert list(config['agents']['defaults']['models']) == ['minimax/MiniMax-M3.2-Flash', 'minimax/MiniMax-M3']
    assert config['models']['providers']['minimax']['models'][1]['id'] == 'MiniMax-M3'
    dsh = (root / 'host/web.yml').read_text()
    assert '- id: MiniMax-M3.2-Flash' in dsh and '- id: MiniMax-M3\n' in dsh
    cron = json.loads((root / 'config/cron-schedules.json').read_text())
    assert {p['model'] for p in cron['payload_profiles'].values()} == {'minimax/MiniMax-M3.2-Flash'}
    assert "MINIMAX_MODEL = 'MiniMax-M3.2-Flash'" in (root / 'src/clawock/automation/llm.py').read_text()


def test_an_unbound_copy_blocks_the_rewrite(sandbox):
    root, truth = sandbox
    config = copy.deepcopy(OPENCLAW)
    config['agents']['defaults']['imageModel'] = 'minimax/MiniMax-M3.1-Flash'
    (root / 'host/openclaw.json').write_text(json.dumps(config, indent=2) + '\n')
    before = (root / 'config/cron-schedules.json').read_text()
    truth['values']['minimax_model'] = 'MiniMax-M3.2-Flash'
    with pytest.raises(ValueError, match='unbound copy'):
        refs.apply(truth, root)
    # Validation runs before any write: nothing was half-applied.
    assert (root / 'config/cron-schedules.json').read_text() == before
