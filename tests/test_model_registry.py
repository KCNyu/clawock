"""config/models.toml is the one place for models, their parameters and chains."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from clawock.model_registry import Registry, load
from clawock.scheduling import load_contract

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('sync_models', ROOT / 'ops/host/sync_models.py')
sync = importlib.util.module_from_spec(_spec)
sys.modules['sync_models'] = sync
_spec.loader.exec_module(sync)


@pytest.fixture
def registry():
    return load(ROOT / 'config/models.toml')


def test_every_chain_resolves(registry):
    for name in registry.chains:
        chain = registry.chain(name)
        assert chain['model'] and isinstance(chain['fallbacks'], list)


def test_cron_contract_carries_no_model_literal_of_its_own(registry):
    """Rotations and the strategy thinking level come from `chain`; a model id
    typed into the contract would be a second copy."""
    text = (ROOT / 'config/cron-schedules.json').read_text()
    for model in registry.models.values():
        assert model.id not in text
    profiles = load_contract(ROOT / 'config/cron-schedules.json')['payload_profiles']
    for name in ('report', 'intraday', 'brief'):
        assert {k: profiles[name][k] for k in ('model', 'fallbacks', 'thinking')} == {
            k: registry.chain('cron')[k] for k in ('model', 'fallbacks', 'thinking')}


def test_a_profile_cannot_both_name_a_chain_and_list_models(tmp_path):
    contract = json.loads((ROOT / 'config/cron-schedules.json').read_text())
    contract['payload_profiles']['report']['model'] = 'minimax/MiniMax-M3'
    path = tmp_path / 'config/cron-schedules.json'
    path.parent.mkdir()
    path.write_text(json.dumps(contract))
    (tmp_path / 'config/models.toml').write_bytes((ROOT / 'config/models.toml').read_bytes())
    with pytest.raises(ValueError, match='come from chain'):
        load_contract(path, workspace=tmp_path)


def test_clawock_client_follows_the_registry(registry):
    from clawock.automation import llm
    model = registry.model(registry.chains['clawock-llm']['models'][0])
    assert (llm.MINIMAX_MODEL, llm.MINIMAX_BASE, llm.MINIMAX_MAX_TOKENS) == (
        model.id, registry.providers[model.provider]['baseUrl'], model.entry['maxTokens'])


def test_minimax_means_m31_flash_and_its_one_thinking_level(registry):
    """kcn 2026-10-20: MiniMax-M3.1-Flash is the only MiniMax model in use. Its
    Anthropic API reference: thinking cannot be turned off (`disabled` is HTTP
    400), depth is `output_config.effort`. OpenClaw's levels for it are off and
    adaptive, so anything else is clamped with a warning and only claims a depth
    that is not sent (#174 fixed that once; the `high` labels came back)."""
    from clawock.automation import llm
    minimax = [m for m in registry.models.values() if m.provider == 'minimax']
    assert minimax
    for model in minimax:
        assert llm._ADAPTIVE_ONLY.match(model.id), model.id
        assert model.params.get('thinking') == 'adaptive', model.key
    settings = registry.openclaw_settings()
    # Talk consults run the chat chain; a chain made of MiniMax hops alone has
    # no other model to pick a level for.
    if registry.model(registry.chains['chat']['models'][0]).provider == 'minimax':
        assert settings['talk.consultThinkingLevel'] == 'adaptive'
    for name, spec in registry.chains.items():
        if spec.get('thinking') and all(registry.model(item).provider == 'minimax'
                                        for item in spec['models'] + spec.get('also_allowed', [])):
            assert spec['thinking'] == 'adaptive', name


def test_an_alias_must_belong_to_the_models_provider():
    data = {'providers': {'minimax': {'aliases': ['minimax-2']}, 'openai': {}},
            'models': {'luna': {'ref': 'openai/gpt-6-luna'}},
            'chains': {'bad': {'models': ['luna@minimax-2']}}}
    with pytest.raises(ValueError, match='not an alias'):
        Registry(data)


def test_openclaw_sections_are_rendered_and_credentials_kept(registry):
    config = {
        'models': {'mode': 'merge', 'providers': {
            'minimax': {'baseUrl': 'https://old', 'apiKey': 'SECRET', 'models': [{'id': 'old'}]},
            'unmanaged': {'models': [{'id': 'x'}]}}},
        'agents': {'defaults': {'model': {'primary': 'old/old'}, 'models': {'old/old': {}},
                                'heartbeat': {'every': '1h', 'model': 'old/old'}, 'subagents': {}}},
        'plugins': {'entries': {'memory-core': {'enabled': True}}},
        'talk': {'provider': 'minimax', 'consultThinkingLevel': 'medium'},
    }
    out = sync.render_openclaw(config, registry)
    settings = registry.openclaw_settings()
    assert out['talk'] == {'provider': 'minimax',
                           'consultThinkingLevel': settings['talk.consultThinkingLevel']}
    assert out['agents']['defaults']['thinkingDefault'] == settings['agents.defaults.thinkingDefault']
    changed = {name for name, value in sync.openclaw_sections(out, registry).items()
               if sync.openclaw_sections(config, registry).get(name) != value}
    assert {'talk.consultThinkingLevel', 'agents.defaults.thinkingDefault'} <= changed
    minimax = out['models']['providers']['minimax']
    assert minimax['apiKey'] == 'SECRET' and minimax['baseUrl'] == registry.providers['minimax']['baseUrl']
    assert [m['id'] for m in minimax['models']] == [m.id for m in registry.models.values()
                                                     if m.provider == 'minimax']
    assert out['models']['providers']['minimax-2']['models'] == minimax['models']
    assert 'apiKey' not in out['models']['providers']['minimax-2']
    assert out['models']['providers']['unmanaged'] == {'models': [{'id': 'x'}]}
    chat = registry.chain('chat')
    assert out['agents']['defaults']['model'] == {'primary': chat['model'], 'fallbacks': chat['fallbacks']}
    assert out['agents']['defaults']['heartbeat'] == {'every': '1h', 'model': registry.chain('heartbeat')['model']}
    assert 'old/old' not in out['agents']['defaults']['models']
    assert sync.render_openclaw(out, registry) == out


@pytest.mark.parametrize('item_indent', [8, 10])
def test_dsh_minimax_block_is_rendered_in_place(registry, item_indent):
    pad = ' ' * item_indent
    text = '\n'.join([
        'providers:', '      minimax:', '        displayName: MiniMax',
        '        baseURL: https://old', '        models:',
        f'{pad}- id: MiniMax-Old', f'{pad}  name: MiniMax-Old',
        f'{pad}# a stale note about the old id', f'{pad}- id: MiniMax-M3', f'{pad}  name: MiniMax-M3',
        '# outside the block', '- id: llm-deepseek', ''])
    out = sync.render_dsh(text, registry)
    assert 'MiniMax-Old' not in out and 'stale note' not in out
    assert f"baseURL: {registry.providers['minimax']['baseUrl']}" in out
    for model in registry.models.values():
        if model.provider == 'minimax':
            assert f'{pad}- id: {model.id}\n' in out
    assert out.endswith('# outside the block\n- id: llm-deepseek\n')
    assert sync.render_dsh(out, registry) == out


def test_dreaming_keeps_primary_and_renders_a_real_fallback_chain(registry):
    out = sync.render_openclaw({'plugins': {'entries': {'memory-core': {
        'subagent': {'allowModelOverride': True}}}}}, registry)
    memory = out['plugins']['entries']['memory-core']
    assert memory['config']['dreaming'] == {
        'model': 'minimax/MiniMax-M3.1-Flash', 'fallbacks': ['openai/gpt-6-luna']}
    assert memory['subagent'] == {
        'allowModelOverride': True,
        'allowedModels': ['minimax/MiniMax-M3.1-Flash', 'openai/gpt-6-luna']}
    assert out['agents']['defaults']['models']['openai/gpt-6-luna'] == {
        'agentRuntime': {'id': 'codex'}, 'params': {'thinking': 'max'}}
    assert registry.chain('chat')['fallbacks'] == ['minimax/MiniMax-M3.1-Flash']
    assert registry.chain('subagents')['fallbacks'] == []
    # Removing the fallback must clear the rendered chain, too.
    registry.chains['dreaming']['models'] = ['flash']
    cleared = sync.render_openclaw(out, registry)['plugins']['entries']['memory-core']
    assert cleared['config']['dreaming']['fallbacks'] == []
    assert cleared['subagent']['allowedModels'] == ['minimax/MiniMax-M3.1-Flash']
