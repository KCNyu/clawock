"""The patch kit never publishes an unverified prefix of a multi-file patch run."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / 'ops/host'
spec = importlib.util.spec_from_file_location('patch_kit', HOST / 'manage_openclaw_patches.py')
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)


@pytest.fixture
def installation(tmp_path):
    install = tmp_path / 'openclaw'
    dist = install / 'dist'
    dist.mkdir(parents=True)
    (install / 'package.json').write_text('{"version":"fixture","type":"module"}')
    (dist / 'embedding.js').write_text('''function createLocalEmbeddingProviderInProcess() {
    const contextSize = 10;
    return createEmbeddingContext({ contextSize, });
}
function createEmbeddingContext(options) { return options; }
console.log(JSON.stringify(createLocalEmbeddingProviderInProcess()));
''')
    (dist / 'memory.js').write_text('const MEMORY_SEARCH_TOOL_TIMEOUT_MS = 15000;\n')
    (dist / 'hook.js').write_text('''function buildNativeHookRelayCommand(params) {
\treturn shellQuoteArgs([params.command]);
}
function shellQuoteArgs(args) { return args.join(" "); }
console.log(buildNativeHookRelayCommand({command: "relay"}));
''')
    (dist / 'usage.js').write_text('''function buildUsageContract(cacheRead, promptTotal) {
\tconst cacheHitPct = promptTotal > 0 ? Math.round((cacheRead ?? 0) / promptTotal * 100) : void 0;
    return { usage: {
\t\t\tcache_hit_pct: cacheHitPct,
    }};
}
console.log(JSON.stringify(buildUsageContract(997, 1000)));
''')
    (dist / 'anthropic.js').write_text('''function applyAnthropicSonnet5Cost(params) {
\tif (!isAnthropicSonnet5Model(params.modelId)) return;
\tconst cost = resolveAnthropicSonnet5Cost();
\tif (params.model.cost.input === cost.input && params.model.cost.output === cost.output && params.model.cost.cacheRead === cost.cacheRead && params.model.cost.cacheWrite === cost.cacheWrite) return;
\treturn {
\t\t...params.model,
\t\tcost
\t};
}
function isAnthropicSonnet5Model(modelId) { return modelId === "claude-sonnet-5"; }
function resolveAnthropicSonnet5Cost() { return { input: 2, output: 10, cacheRead: 0.2, cacheWrite: 2.5 }; }
const cost = applyAnthropicSonnet5Cost({
\tmodelId: "claude-sonnet-5",
\tmodel: { id: "claude-sonnet-5", provider: "anthropic", input: ["text"] }
}).cost;
console.log(JSON.stringify(cost));
''')
    (dist / 'loader.js').write_text('''function buildCliPluginApi(validatedConfig, cfg) {
\treturn {
\t\t\tregistrationMode: "cli-metadata",
\t\t\tconfig: cfg,
\t\t\tpluginConfig: validatedConfig.value,
\t\t\truntime: {},
\t};
}
const api = buildCliPluginApi({ value: {} }, {});
const store = api.runtime.state.openSyncKeyedStore({ namespace: "fixture" });
let threw = false;
try {
\tstore.read;
} catch (error) {
\tthrew = error.message.includes("CLI metadata registration");
}
console.log(JSON.stringify({ registered: true, threw }));
''')
    return install


def manifest(tmp_path, ids):
    data = kit.load_manifest(kit.DEFAULT_MANIFEST)
    data['patches'] = [p for p in data['patches'] if p['id'] in ids]
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(data))
    return path


def plan(tmp_path, installation, ids):
    stage = tmp_path / 'stage'
    stage.mkdir()
    return kit.prepare(installation, manifest(tmp_path, ids), stage)


def test_real_adapters_plan_apply_replay_and_guarded_rollback(tmp_path, installation):
    ids = ['embedding-threads1', 'memory-search-timeout', 'hook-relay-exec', 'cache-hit-pct-exact']
    report, old, new = plan(tmp_path, installation, ids)
    dist = installation / 'dist'
    assert len(report['changes']) == 4
    assert all((dist / name).read_bytes() == data for name, data in old.items())
    result = kit.commit(installation, report, old, new, tmp_path / 'state')
    assert result['status'] == 'applied'
    assert subprocess.check_output(['node', str(dist / 'hook.js')], text=True).strip() == 'exec relay'
    embedding = json.loads(subprocess.check_output(['node', str(dist / 'embedding.js')]))
    assert embedding == {'threads': 1, 'batchSize': 512, 'contextSize': 10}
    usage = json.loads(subprocess.check_output(['node', str(dist / 'usage.js')]))['usage']
    assert usage == {'cache_hit_pct': 100, 'cache_hit_pct_exact': 99.7}
    stage2 = tmp_path / 'stage2'
    stage2.mkdir()
    replay, _, _ = kit.prepare(installation, tmp_path / 'manifest.json', stage2)
    assert replay['changes'] == []
    restored = kit.rollback(Path(result['receipt']))
    assert restored['status'] == 'rolled_back'
    assert all((dist / name).read_bytes() == data for name, data in old.items())


def test_later_adapter_failure_leaves_every_installed_byte_unchanged(tmp_path, installation):
    dist = installation / 'dist'
    # Selector exists, but the hook's edit anchor has drifted.
    (dist / 'hook.js').write_text('function buildNativeHookRelayCommand(params) { return "changed"; }')
    before = {p.name: p.read_bytes() for p in dist.iterdir()}
    with pytest.raises(ValueError, match='staging failed'):
        plan(tmp_path, installation, ['memory-search-timeout', 'hook-relay-exec'])
    assert {p.name: p.read_bytes() for p in dist.iterdir()} == before


def test_ambiguous_selector_refuses_before_patching(tmp_path, installation):
    dist = installation / 'dist'
    (dist / 'duplicate.js').write_bytes((dist / 'memory.js').read_bytes())
    with pytest.raises(ValueError, match='matched 2 bundles'):
        plan(tmp_path, installation, ['memory-search-timeout'])


def test_partial_marker_is_not_a_success(tmp_path, installation):
    # The old adapter accepts its marker alone. The kit requires the output field too.
    (installation / 'dist/usage.js').write_text(
        'function buildUsageContract() {} // clawock-cache-hit-pct-exact-v1\n')
    with pytest.raises(ValueError, match='incomplete postconditions'):
        plan(tmp_path, installation, ['cache-hit-pct-exact'])


def test_native_hook_fix_is_accepted_without_reapplying(tmp_path, installation):
    (installation / 'dist/hook.js').write_text('''function buildNativeHookRelayCommand(params) {
const command = params.command;
return `exec ${command}`;
}
''')
    report, _, _ = plan(tmp_path, installation, ['hook-relay-exec'])
    assert report['changes'] == []


def test_anthropic_costless_and_codex_cli_runtime_adapters(tmp_path, installation):
    dist = installation / 'dist'
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.run(['node', str(dist / 'anthropic.js')], check=True, capture_output=True)
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.run(['node', str(dist / 'loader.js')], check=True, capture_output=True)

    report, old, new = plan(
        tmp_path, installation, ['anthropic-sonnet5-costless', 'codex-cli-runtime-state'])
    assert len(report['changes']) == 2
    result = kit.commit(installation, report, old, new, tmp_path / 'state')
    assert result['status'] == 'applied'

    cost = json.loads(subprocess.check_output(['node', str(dist / 'anthropic.js')], text=True))
    assert cost == {'input': 2, 'output': 10, 'cacheRead': 0.2, 'cacheWrite': 2.5}
    loader = json.loads(subprocess.check_output(['node', str(dist / 'loader.js')], text=True))
    assert loader == {'registered': True, 'threw': True}

    stage2 = tmp_path / 'stage2'
    stage2.mkdir()
    replay, _, _ = kit.prepare(installation, tmp_path / 'manifest.json', stage2)
    assert replay['changes'] == []


def test_concurrent_live_edit_refuses_entire_commit(tmp_path, installation):
    report, old, new = plan(tmp_path, installation, ['memory-search-timeout'])
    path = installation / 'dist/memory.js'
    path.write_text('concurrent edit')
    with pytest.raises(ValueError, match='changed during staging'):
        kit.commit(installation, report, old, new, tmp_path / 'state')
    assert path.read_text() == 'concurrent edit'
    assert not (tmp_path / 'state').exists()


def test_write_failure_rolls_back_earlier_replacements(tmp_path, installation, monkeypatch):
    report, old, new = plan(tmp_path, installation, ['memory-search-timeout', 'hook-relay-exec'])
    original = kit.atomic_write

    def write(path, data, mode=0o600):
        if path == installation / 'dist/hook.js' and data == new['hook.js']:
            raise OSError('injected install failure')
        return original(path, data, mode)

    monkeypatch.setattr(kit, 'atomic_write', write)
    with pytest.raises(OSError, match='injected'):
        kit.commit(installation, report, old, new, tmp_path / 'state')
    assert all((installation / 'dist' / name).read_bytes() == data for name, data in old.items())
    receipt = next((tmp_path / 'state').glob('*/receipt.json'))
    assert json.loads(receipt.read_text())['status'] == 'rolled_back'


def test_rollback_refuses_to_overwrite_later_edits(tmp_path, installation):
    report, old, new = plan(tmp_path, installation, ['memory-search-timeout', 'hook-relay-exec'])
    result = kit.commit(installation, report, old, new, tmp_path / 'state')
    (installation / 'dist/hook.js').write_text('later operator edit')
    with pytest.raises(ValueError, match='rollback refused'):
        kit.rollback(Path(result['receipt']))
    assert (installation / 'dist/memory.js').read_bytes() == new['memory.js']


def test_all_adapters_are_tracked_and_cannot_default_to_the_live_package():
    data = kit.load_manifest(kit.DEFAULT_MANIFEST)
    assert len(data['patches']) == 12
    for patch in data['patches']:
        source = HOST / patch['script']
        assert source.is_file()
        if source.suffix == '.sh':
            assert '${CLAWOCK_PATCH_STAGE:?' in source.read_text()
            subprocess.run(['bash', '-n', str(source)], check=True)


def test_invalid_javascript_never_reaches_the_installation(tmp_path, installation):
    path = installation / 'dist/memory.js'
    path.write_text('const MEMORY_SEARCH_TOOL_TIMEOUT_MS = 15000;\nconst = invalid;\n')
    before = path.read_bytes()
    with pytest.raises(subprocess.CalledProcessError):
        plan(tmp_path, installation, ['memory-search-timeout'])
    assert path.read_bytes() == before


def test_manifest_cannot_select_outside_the_package(tmp_path, installation):
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps({'schema': 1, 'patches': [
        {'id': 'escape', 'targets': [{'path': '../package.json'}]}]}))
    with pytest.raises(ValueError, match='unsafe patch path'):
        kit.resolve_targets(installation / 'dist', kit.load_manifest(path))
