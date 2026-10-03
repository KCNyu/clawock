"""Policy transport and upgrade recovery, without starting a gateway."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'ops/host/skillhub/index.ts'
INSTALLER = ROOT / 'ops/host/install_skillhub_plugin.sh'
POLICY = ROOT / 'docs/operations/skills-store-policy.md'


def node(script):
    return subprocess.run(['node', '--experimental-strip-types', '--input-type=module', '-e',
                           f'import register, {{renderPolicy}} from {json.dumps(PLUGIN.as_uri())};\n' + script],
                          capture_output=True, text=True)


def test_system_context_survives_followups_resume_and_compaction():
    result = node(f'''
const handlers = {{}};
register({{
  pluginConfig: {{primaryCli:'skillhub', fallbackCli:'clawhub', primaryLabel:'cn-optimized', fallbackLabel:'public-registry'}},
  config: {{agents:{{defaults:{{workspace:{json.dumps(str(ROOT))}}}}}}},
  on: (name, handler) => {{ handlers[name] = handler; }},
}});
const outputs = [];
for (const messages of [[], [{{role:'user'}}], [{{role:'assistant'}}], []]) {{
  outputs.push(await handlers.before_prompt_build({{prompt:'你好',messages}}, {{sessionKey:'same-thread'}}));
}}
console.log(JSON.stringify(outputs));
''')
    assert result.returncode == 0, result.stderr
    outputs = json.loads(result.stdout)
    assert len(outputs) == 4
    assert outputs == [outputs[0]] * 4
    for output in outputs:
        assert set(output) == {'prependSystemContext'}
        text = output['prependSystemContext']
        assert text.count('Skills store policy (operator configured):') == 1
        assert len([line for line in text.splitlines() if line[:1].isdigit()]) == 6
        assert '1. For skills discovery/install/update, try `skillhub` first (cn-optimized).' in text
        assert '2. If unavailable, rate-limited, or no match, fallback to `clawhub` (public-registry).' in text
        assert '3. Do not claim exclusivity. Public and private registries are both allowed.' in text
        assert '4. Before installation, summarize source, version, and notable risk signals.' in text
        assert '5. For search requests, execute `exec` with `skillhub search <keywords>` first and report the command output.' in text
        assert '6. In the current session, reply directly. Do NOT call `message` tool just to send progress updates.' in text


def test_config_substitution_and_optional_note():
    doc = json.dumps(POLICY.read_text())
    result = node(f'console.log(renderPolicy({doc}, {{primaryCli:"private-cli", fallbackCli:"public-cli", primaryLabel:"private", fallbackLabel:"public", extraNote:"Operator note"}}));')
    assert result.returncode == 0, result.stderr
    assert '`private-cli` first (private)' in result.stdout
    assert '`public-cli` (public)' in result.stdout
    assert '`private-cli search <keywords>`' in result.stdout
    assert '7. Operator note' in result.stdout
    assert 'skillhub`' not in result.stdout


@pytest.mark.parametrize('document', ['1. incomplete', POLICY.read_text().replace('6. In', '8. In'),
                                       POLICY.read_text().replace('{{primaryCli}}', '{{unknown}}')])
def test_invalid_policy_is_rejected(document):
    result = node(f'renderPolicy({json.dumps(document)}, {{}});')
    assert result.returncode != 0


def test_install_replay_check_and_rollback(tmp_path):
    target = tmp_path / 'extensions/skillhub'
    target.mkdir(parents=True)
    original = {'index.ts': 'previous hook', 'openclaw.plugin.json': '{"id":"skillhub"}'}
    for name, content in original.items():
        (target / name).write_text(content)
    env = {**os.environ, 'SKILLHUB_PLUGIN_DIR': str(target)}

    def run(*args):
        return subprocess.run(['bash', str(INSTALLER), *args], env=env, capture_output=True, text=True)

    assert run('--check').returncode != 0
    assert run().returncode == 0
    assert run('--check').returncode == 0
    assert run().returncode == 0  # Idempotence must preserve the recovery pair.
    for name, content in original.items():
        assert (target / (name + '.before-update')).read_text() == content
    (target / 'index.ts').write_text('upgrade accidentally replaced the hook')
    assert run('--check').returncode != 0
    assert run().returncode == 0
    assert run('--check').returncode == 0
    assert run('--rollback').returncode == 0
    assert (target / 'index.ts').read_text() == 'upgrade accidentally replaced the hook'
    assert 'prependSystemContext' not in (target / 'index.ts').read_text()
