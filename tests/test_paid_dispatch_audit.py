"""Paid dispatch regressions: private tasks, fake CLIs, no host services or sessions."""
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / 'ops/host/agent-dispatch'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reader = load('paid_result', RUNNER / 'read-result.py')
ops = load('paid_ops', ROOT / 'ops/host/task_queue_ops.py')


@pytest.fixture
def sandbox(tmp_path):
    task = tmp_path / 'tasks' / 'example'
    task.mkdir(parents=True)
    tools = tmp_path / 'tools'
    tools.mkdir()
    (tools / 'limits.env').write_text('MAX_RUNNING_CODEX=1\n')
    (tools / 'resource-pressure.sh').write_text((RUNNER / 'resource-pressure.sh').read_text())
    for name in ('run-agent.sh', 'dispatch.sh'):
        (tools / name).write_text((RUNNER / name).read_text().replace('/root/tools/agent-dispatch', str(tools))
                                 .replace('/root/logs/agent-dispatch', str(task.parent)))
    for name, text in {
        'systemctl': '#!/bin/sh\necho active\n',
        'openclaw': '#!/bin/sh\nexit 0\n',
        'sleep': '#!/bin/sh\nexec /bin/sleep 0.01\n',
        'codex': '''#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
base=Path(os.environ['TEST_ROOT'])
print(json.dumps({'type':'thread.started','thread_id':'fixture-session'}), flush=True)
while (base/'hold-model').exists(): time.sleep(.01)
if os.environ.get('TEST_QUOTA'):
 print(json.dumps({'type':'turn.failed','error':{'message':"You've hit your usage limit; resets 11pm (Asia/Shanghai)"}}),flush=True)
 sys.exit(1)
Path(sys.argv[sys.argv.index('-o')+1]).write_text('STATUS: DONE')
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'STATUS: DONE'}}),flush=True)
print(json.dumps({'type':'turn.completed'}),flush=True)
''',
        'quota': '''#!/usr/bin/env python3
import os,time
from pathlib import Path
base=Path(os.environ['TEST_ROOT'])
(base/'in-finish').touch()
while (base/'hold-finish').exists(): time.sleep(.01)
''',
    }.items():
        (tools / name).write_text(text)
        (tools / name).chmod(0o755)
    meta = dict(ID='example', NAME='example', AGENT='codex', CWD=str(tmp_path), RESUME='',
                MODEL='fake', EFFORT='low', TIMEOUT='100', NOTIFY='none', DEADLINE='fixture',
                DEADLINE_EPOCH=str(int(time.time()) + 172800), CREATED='2026-01-01 00:00:00')
    (task / 'meta.env').write_text(''.join(f'{k}={shlex.quote(v)}\n' for k, v in meta.items()))
    (task / 'prompt.md').write_text('fixture')
    env = dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}", TEST_ROOT=str(tmp_path),
               AGENT_DISPATCH_PATH_PREFIX=str(tools), AGENT_DISPATCH_LOCKDIR=str(tmp_path / 'locks'),
               AGENT_DISPATCH_OPS=str(tools / 'absent.py'), AGENT_DISPATCH_QUOTA_CMD=str(tools / 'quota'),
               CODEX_HOME=str(tmp_path / 'codex'), DISPATCH_WRAPPED='1', MIN_RUN_SEC='1',
               AGENT_DISPATCH_POLL_SEC='.01')
    env.pop('AGENT_DISPATCH_TASK_ID', None)
    env.pop('MAX_ATTEMPTS', None)
    (tmp_path / 'locks').mkdir()
    procs = []

    def start():
        proc = subprocess.Popen(['bash', str(tools / 'run-agent.sh'), str(task)], env=env)
        procs.append(proc)
        return proc

    def append():
        return subprocess.run(['bash', str(tools / 'dispatch.sh'), 'append', 'example', '--queue'],
                              input='extra instruction', text=True, capture_output=True, env=env, timeout=5)

    yield tmp_path, task, env, start, append
    for proc in procs:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)


def wait_for(predicate):
    end = time.monotonic() + 5
    while not predicate():
        assert time.monotonic() < end, 'fixture barrier timed out'
        time.sleep(.01)


def test_append_before_close_is_consumed_and_during_finish_is_refused(sandbox):
    root, task, _, start, append = sandbox
    (root / 'hold-model').touch()
    (root / 'hold-finish').touch()
    proc = start()
    wait_for(lambda: (task / 'attempt1.jsonl').exists())
    accepted = append()
    assert accepted.returncode == 0, accepted.stderr
    receipt = json.loads(accepted.stdout.splitlines()[0][9:])
    assert receipt['disposition'] == 'accepted'
    (root / 'hold-model').unlink()
    wait_for(lambda: (root / 'in-finish').exists())
    assert (task / 'inbox-state').read_text().strip() == 'finishing'
    assert (task / 'inbox' / 'delivered' / receipt['message_id']).exists()
    assert reader.read_env(task / 'result.env')['APPENDS'] == '1'
    assert reader.read_env(task / 'result.env')['RUN_NO'] == '2'
    refused = append()
    assert refused.returncode == 3
    assert 'nothing queued' in refused.stderr
    assert not list((task / 'inbox').glob('*.md'))
    (root / 'hold-finish').unlink()
    assert proc.wait(timeout=5) == 0
    assert (task / 'inbox-state').read_text().strip() == 'terminal'


def test_append_to_old_runner_does_not_claim_acceptance(sandbox):
    _, task, _, _, append = sandbox
    refused = append()
    assert refused.returncode == 3
    assert not list((task / 'inbox').glob('*.md'))


def test_default_quota_and_attempt_budgets_remain_three(sandbox):
    _, task, env, start, _ = sandbox
    env['TEST_QUOTA'] = '1'
    assert start().wait(timeout=8) == 75
    fields = reader.read_env(task / 'result.env')
    assert (fields['ATTEMPTS'], fields['QUOTA_RESUMES_USED'], fields['QUOTA_RESUMES']) == ('3', '2', '3')
    assert fields['STOP_REASON'] == 'attempt_budget'
    assert fields['FINISHED_EPOCH']


def test_zero_attempt_terminal_and_latest_incomplete_report(tmp_path):
    (tmp_path / 'meta.env').write_text('NOTIFY=weixin,telegram\n')
    (tmp_path / 'result.env').write_text('STATE=blocked\nSTOP_REASON=session_busy\nATTEMPTS=0\nNOTIFY_FAILED=weixin,telegram\n')
    (tmp_path / 'runner-summary.txt').write_text('session occupied')
    text = reader.report(tmp_path)
    assert 'stop_reason: session_busy' in text
    assert 'notification: failed' in text
    assert 'session occupied' in text
    (tmp_path / 'attempt1.json').write_text('{"result":"old success"}')
    (tmp_path / 'attempt2.json').write_text('')
    assert 'old success' not in reader.report(tmp_path)
    assert 'old success' in reader.report(tmp_path, 1)


@pytest.mark.parametrize('agent', ['claude', 'codex'])
def test_usage_old_task_excludes_later_session_work(tmp_path, monkeypatch, agent):
    task = tmp_path / 'task'
    task.mkdir()
    (task / 'meta.env').write_text(f'AGENT={agent}\nMODEL=fixture\n')
    # A queued task's creation precedes unrelated work; only its actual run is ours.
    (task / 'result.env').write_text('STATE=ok\nSESSION=fixture\nUSAGE_START_EPOCH=150.2\nFINISHED_EPOCH=150.6\n')
    events = [(150.1, 50), (150.3, 100), (150.7, 200)]
    if agent == 'claude':
        home = tmp_path / 'claude'
        monkeypatch.setattr(ops, 'CLAUDE_HOME', home)
        path = home / 'projects' / 'fixture' / 'fixture.jsonl'
        records = [{'type': 'assistant', 'timestamp': datetime.fromtimestamp(t, timezone.utc).isoformat(),
                    'message': {'id': str(t), 'model': 'fixture', 'usage': {'input_tokens': n}}} for t, n in events]
    else:
        monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'codex'))
        path = tmp_path / 'codex' / 'sessions' / 'rollout-test-fixture.jsonl'
        total = 0
        records = []
        for t, n in events:
            total += n
            records.append({'timestamp': datetime.fromtimestamp(t, timezone.utc).isoformat(), 'payload': {
                'type': 'token_count', 'info': {'total_token_usage': {'input_tokens': total}}}})
    path.parent.mkdir(parents=True)
    path.write_text(''.join(json.dumps(e)+'\n' for e in records))
    assert ops.task_usage(task)['tokens']['in'] == 100
    # Legacy terminal results are not recomputed without an upper bound.
    (task / 'result.env').write_text('STATE=ok\nSESSION=fixture\n')
    assert ops.task_usage(task)['tokens'] is None
    with (task / 'result.env').open('a') as f:
        f.write('TOKENS_IN=100\nTOKENS_CACHE_W=0\nTOKENS_CACHE_R=0\nTOKENS_OUT=0\nTOKENS_TOTAL=100\n')
    assert ops.task_usage(task)['tokens']['in'] == 100


def test_session_busy_has_zero_attempt_reason_and_no_usage(sandbox, monkeypatch):
    root, task, _, start, _ = sandbox
    with (task / 'meta.env').open('a') as meta:
        meta.write('RESUME=fixture-session\n')
    with (root / 'locks' / 'session-fixture-session.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert start().wait(timeout=5) == 75
    fields = reader.read_env(task / 'result.env')
    assert fields['ATTEMPTS'] == '0'
    assert fields['STOP_REASON'] == fields['FAILURE_REASON'] == 'session_busy'
    assert 'session_busy' in reader.report(task)
    monkeypatch.setenv('CODEX_HOME', str(root / 'no-real-sessions'))
    assert ops.task_usage(task)['tokens'] is None


def test_no_timestamp_usage_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(ops, 'CLAUDE_HOME', tmp_path)
    path = tmp_path / 'projects' / 'fixture' / 'fixture.jsonl'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'type': 'assistant', 'message': {'usage': {'input_tokens': 100}}})+'\n')
    assert ops.claude_usage('fixture', 100, 200) is None
    monkeypatch.setenv('CODEX_HOME', str(tmp_path))
    path = tmp_path / 'sessions' / 'rollout-test-fixture.jsonl'
    path.parent.mkdir()
    path.write_text(json.dumps({'payload': {'type': 'token_count', 'info': {
        'total_token_usage': {'input_tokens': 100}}}})+'\n')
    assert ops.codex_usage('fixture', 100, 'fake', 200) is None


def test_missing_state_never_promotes_an_old_report_to_current(tmp_path):
    (tmp_path / 'attempt1.json').write_text('{"result":"old success"}')
    with pytest.raises(ValueError, match='no terminal result'):
        reader.report(tmp_path)
    (tmp_path / 'result.env').write_text("STATE='running'\n")
    with pytest.raises(ValueError, match='no terminal result'):
        reader.report(tmp_path)
    assert 'old success' in reader.report(tmp_path, 1)
