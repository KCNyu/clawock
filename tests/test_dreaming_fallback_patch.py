"""Execute the patched upstream loop, including errors at both run and wait."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('dream_patch', ROOT / 'ops/host/patch_dreaming_fallbacks.py')
patch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(patch)
FIXTURE = (ROOT / 'tests/fixtures/openclaw_dreaming_narrative.js').read_text()


def run_loop(outcomes, fallbacks=('openai/gpt-6-luna',)):
    config = {} if fallbacks is None else {'fallbacks': list(fallbacks)}
    script = r'''
const seen = [], deleted = [], written = [], warnings = [];
const NARRATIVE_TIMEOUT_MS = 60000;
const getRuntimeConfig = () => ({plugins:{entries:{'memory-core':{config:{dreaming:CONFIG}}}}});
const formatErrorMessage = e => e.message;
const buildNarrativeSessionKey = () => 'dreaming-narrative-test';
const buildNarrativePrompt = () => 'memory fragments';
const withNarrativeSessionLock = (_, fn) => fn();
const buildNarrativeAttemptSessionKey = (key, i) => `${key}-${i}`;
const isRequestScopedSubagentRuntimeError = () => false;
const scrubDreamingNarrativeArtifacts = async () => {};
let cursor = 0;
const startNarrativeRunOrFallback = async p => {
    seen.push(p.model ?? 'default');
    if (OUTCOMES[cursor].throw) throw new Error(OUTCOMES[cursor++].throw);
    return `run-${cursor}`;
};
const readSettledNarrativeText = async () => 'real diary';
const appendNarrativeEntry = async p => written.push(p.narrative);
const appendFallbackNarrativeEntry = async () => written.push('placeholder');
await generateAndAppendDreamNarrative({
    model:'minimax/MiniMax-M3.1-Flash', workspaceDir:'/isolated',
    data:{phase:'light',snippets:['a quiet library']},
    logger:{info(){},warn(msg){warnings.push(msg)}},
    subagent:{
        deleteSession: async p => deleted.push(p.sessionKey),
        waitForRun: async () => OUTCOMES[cursor++],
    },
});
console.log(JSON.stringify({seen,deleted,written,warnings}));
'''.replace('CONFIG', json.dumps(config)).replace('OUTCOMES', json.dumps(outcomes))
    result = subprocess.run(['node', '--input-type=module'],
                            input=patch.patch_narrative(FIXTURE) + '\n' + script,
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_primary_success_never_calls_luna():
    assert run_loop([{'status': 'ok'}])['seen'] == ['minimax/MiniMax-M3.1-Flash']


@pytest.mark.parametrize('failure', [
    {'status': 'error', 'error': 'HTTP 429 rate_limit_error'},
    {'status': 'error', 'error': 'FailoverError: 已达到 Token Plan 用量上限 (2056)'},
    {'throw': 'HTTP 503 overloaded'},
    {'throw': 'unknown model'},
])
def test_retryable_failure_reaches_luna_and_writes_real_diary(failure):
    result = run_loop([failure, {'status': 'ok'}])
    assert result['seen'] == ['minimax/MiniMax-M3.1-Flash', 'openai/gpt-6-luna']
    assert result['written'] == ['real diary']
    assert any('retrying with openai/gpt-6-luna' in w for w in result['warnings'])
    assert 'dreaming-narrative-test-1' in result['deleted']


@pytest.mark.parametrize('message', ['not trusted for override', 'model is not allowlisted',
                                   'override is not authorized', 'permission denied'])
def test_policy_failure_does_not_retry(message):
    result = run_loop([{'throw': message}])
    assert len(result['seen']) == 1
    assert result['written'] == []
    assert message in result['warnings'][-1]


def test_exhaustion_is_bounded_and_keeps_placeholder():
    failure = {'status': 'error', 'error': '429 quota'}
    result = run_loop([failure, failure])
    assert len(result['seen']) == 2
    assert result['written'] == ['placeholder']


def test_explicit_empty_chain_does_not_retry_default():
    assert len(run_loop([{'status': 'error', 'error': 'unknown model'}], ())['seen']) == 1


def test_legacy_default_retry_remains_when_unconfigured():
    result = run_loop([{'status': 'error', 'error': 'unknown model'}, {'status': 'ok'}], None)
    assert result['seen'][-1] == 'default'


def test_timeout_does_not_start_another_run_while_first_may_be_active():
    result = run_loop([{'status': 'timeout'}])
    assert len(result['seen']) == 1
    assert result['written'] == ['placeholder']


def test_patch_idempotency_and_anchor_drift():
    once = patch.patch_narrative(FIXTURE)
    assert patch.patch_narrative(once) == once
    with pytest.raises(ValueError, match='anchor'):
        patch.patch_narrative(FIXTURE.replace('const attemptModels =', 'const changed ='))


def test_manifest_accepts_fallbacks_and_preserves_other_settings():
    original = {'configSchema': {'properties': {'dreaming': {'properties': {
        'model': {'type': 'string'}, 'enabled': {'type': 'boolean'}}}}}}
    once = patch.patch_manifest(json.dumps(original))
    assert patch.patch_manifest(once) == once
    properties = json.loads(once)['configSchema']['properties']['dreaming']['properties']
    assert properties['fallbacks'] == {'type': 'array', 'items': {'type': 'string'}}
    assert properties['model'] == {'type': 'string'}
