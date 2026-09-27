"""Isolated runner admission/quota tests: fake CLIs, private locks, no real sessions."""
import fcntl
import os
import shlex
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER_LIMITS = '/root/tools/agent-dispatch/limits.env'  # the path the runner sources
PATROL = Path(os.environ.get('PATROL_SCRIPT', '/root/tools/clawock-patrol/patrol.sh'))  # override: an uninstalled copy


class LimitsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.task = self.base / 'task'
        self.task.mkdir()
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.locks = self.base / 'locks'
        self.locks.mkdir()
        self.limits = self.base / 'limits.env'
        self.limits.write_text('MAX_RUNNING_CLAUDE=1\nMAX_RUNNING_CODEX=1\nMAX_RUNNING_OPENCODE=1\nMAX_RUNNING=3\n'
                               'PATROL_MIN_AVAILABLE_KB=196608\nPATROL_MAX_MEMORY_FULL_AVG60=10\n')
        self.runner = self.base / 'runner.sh'
        self.runner.write_text((ROOT / 'run-agent.sh').read_text().replace(RUNNER_LIMITS, str(self.limits)))
        # patrol.sh sources "$DISPATCH_DIR/limits.env" through a variable, so replacing an absolute
        # path in its text patches nothing (that made this test's supervisor half a no-op until
        # 2026-09-23). Point it at a private dispatch dir holding the same one-slot limit file.
        self.dispatch_dir = self.base / 'dispatch'
        self.dispatch_dir.mkdir()
        (self.dispatch_dir / 'limits.env').write_text(self.limits.read_text())
        (self.dispatch_dir / 'resource-pressure.sh').write_text(
            (ROOT / 'resource-pressure.sh').read_text())
        self.patrol = self.base / 'patrol.sh'
        self.patrol.write_text(PATROL.read_text())
        self.mem = self.base / 'meminfo'
        self.mem.write_text('MemAvailable: 700000 kB\n')
        self.psi = self.base / 'pressure'
        self.psi.write_text('full avg60=0.00\n')
        for name, code in {
            'openclaw': '#!/bin/sh\nexit 0\n',
            'sleep': '#!/bin/sh\nexec /bin/sleep 0.02\n',
            'codex': '''#!/usr/bin/python3
import json,os,sys
from pathlib import Path
p=Path(os.environ['TEST_BASE'])
with (p/'calls').open('a') as f: f.write(json.dumps(sys.argv)+'\\n')
print(json.dumps({'type':'thread.started','thread_id':'isolated-test-session'},separators=(',',':')),flush=True)
if os.environ.get('TEST_QUOTA') == '1':
 print(json.dumps({'type':'turn.failed','error':{'message':"You've hit your usage limit; resets 11pm (Asia/Shanghai)"}}),flush=True)
 sys.exit(1)
Path(sys.argv[sys.argv.index('-o')+1]).write_text('STATUS: DONE\\n')
''',
        }.items():
            p = self.bin / name
            p.write_text(code)
            p.chmod(0o755)
        self.env = dict(os.environ, TEST_BASE=str(self.base), AGENT_DISPATCH_PATH_PREFIX=str(self.bin),
                        AGENT_DISPATCH_LOCKDIR=str(self.locks), AGENT_DISPATCH_QUOTA_CMD='/bin/true',
                        AGENT_DISPATCH_MEMINFO=str(self.mem), AGENT_DISPATCH_MEMORY_PSI=str(self.psi),
                        CODEX_HOME=str(self.base / 'codex'), DISPATCH_WRAPPED='1',
                        MIN_RUN_SEC='1', MAX_ATTEMPTS='5', AGENT_DISPATCH_POLL_SEC='0.02')
        for agent in ('CLAUDE', 'CODEX', 'OPENCODE'):
            self.env.pop(f'AGENT_DISPATCH_MAX_RUNNING_{agent}', None)

    def setup_task(self, quota_resumes=None, patrol=False):
        data = dict(ID='patrol-test' if patrol else 'foreground-test', AGENT='codex', NAME='test',
                    CWD='/root', RESUME='', MODEL='fake', EFFORT='low', TIMEOUT='100',
                    DEADLINE='test', DEADLINE_EPOCH=str(int(time.time())+172800), NOTIFY='none')
        if quota_resumes is not None:
            data['QUOTA_RESUMES'] = str(quota_resumes)
        (self.task / 'meta.env').write_text(''.join(f'{k}={shlex.quote(v)}\n' for k,v in data.items()))
        (self.task / 'prompt.md').write_text('Isolated test. No real task.')

    def fields(self):
        p = self.task / 'result.env'
        return dict(line.split('=', 1) for line in p.read_text().splitlines()) if p.exists() else {}

    def wait_field(self, name, value):
        end = time.monotonic()+5
        while time.monotonic() < end:
            if self.fields().get(name) == value:
                return
            time.sleep(0.02)
        self.fail(f'{name} != {value}: {self.fields()}')

    def run_runner(self):
        return subprocess.run(['bash', str(self.runner), str(self.task)], env=self.env,
                              capture_output=True, text=True, timeout=8)

    def start_runner(self):
        proc = subprocess.Popen(['bash', str(self.runner), str(self.task)], env=self.env)
        self.addCleanup(lambda: (proc.terminate(), proc.wait(timeout=5)) if proc.poll() is None else None)
        return proc

    def check_quota(self, cap, expected):
        self.setup_task(cap)
        self.env['TEST_QUOTA'] = '1'
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 75, proc.stderr)
        calls = (self.base / 'calls').read_text().splitlines()
        self.assertEqual(len(calls), expected)
        self.assertNotIn('resume', __import__('json').loads(calls[0]))
        for c in calls[1:]:
            self.assertIn('resume', __import__('json').loads(c))
        fields = self.fields()
        self.assertEqual(fields['STATE'], 'quota')
        self.assertEqual(fields['SLOT'], "''")
        self.assertEqual(fields['WAITING'], "''")
        self.assertEqual(fields['QUOTA_RESUMES_USED'], str(expected-1))
        self.assertIn('quota resume budget exhausted', (self.task/'run.log').read_text())

    def test_meta_without_a_budget_uses_the_runner_fallback(self):
        # dispatch.sh writes QUOTA_RESUMES (default 3 since 2026-09-23, same as the runner)
        # into every new task's meta.env; the runner's fallback only covers a meta without it.
        self.check_quota(None, 4)

    def test_explicit_one_quota_resume(self):
        self.check_quota(1, 2)

    def test_zero_disables_auto_quota_resume(self):
        self.check_quota(0, 1)

    def test_explicit_budget_is_honoured(self):
        self.check_quota(2, 3)

    def hold(self, name):
        lock = open(self.locks / f'{name}.lock', 'w')
        self.addCleanup(lock.close)
        fcntl.flock(lock, fcntl.LOCK_EX)
        return lock

    def supervisor(self, call, **env):
        (self.bin/'systemctl').write_text('#!/bin/sh\nexit 0\n')
        (self.bin/'systemctl').chmod(0o755)
        env = dict(self.env, PATH=f'{self.bin}:/usr/bin:/bin', PATROL_TASKS_DIR=str(self.locks),
                   PATROL_STATE_DIR=str(self.base/'state'), PATROL_DISPATCH_DIR=str(self.dispatch_dir), **env)
        return subprocess.check_output(['bash','-c',f'source "$1"; {call}','test',str(self.patrol)],
                                       env=env, text=True).strip()

    def test_runner_and_supervisor_agree_on_the_slot_locks(self):
        # The runner takes slot-<agent>-<n>.lock; the supervisor probes the same files, and only
        # the opencode ones (the round's own agent) gate a new round.
        self.setup_task()
        lock = self.hold('slot-codex-1')
        proc = self.start_runner()
        self.wait_field('WAITING', 'slot')
        self.assertFalse((self.base/'calls').exists())
        self.assertEqual(self.supervisor('others_need_slot'), '')
        self.hold('slot-opencode-1')
        self.assertEqual(self.supervisor('others_need_slot'), 'the opencode run slot is busy')
        fcntl.flock(lock, fcntl.LOCK_UN)
        self.assertEqual(proc.wait(timeout=5),0)
        self.assertIn('agent_slots=1', (self.task/'run.log').read_text())
        self.assertIn('got run slot codex-1', (self.task/'run.log').read_text())
        self.assertEqual(self.fields()['SLOT'], "''")

    def test_shared_slots_of_old_runners_block_nobody_new(self):
        self.setup_task()
        self.hold('slot-1'); self.hold('slot-2')
        self.assertEqual(self.run_runner().returncode, 0)
        self.assertIn('got run slot codex-1', (self.task/'run.log').read_text())

    def test_environment_override_reaches_both_consumers(self):
        self.setup_task()
        self.env['AGENT_DISPATCH_MAX_RUNNING_CODEX']='2'
        self.hold('slot-codex-1')
        self.assertEqual(self.run_runner().returncode,0)
        self.assertIn('got run slot codex-2',(self.task/'run.log').read_text())
        self.assertEqual(self.supervisor('echo "$AGENT_SLOTS"', AGENT_DISPATCH_MAX_RUNNING_OPENCODE='2'), '2')

    def test_patrol_memory_wait_uses_no_slot_or_attempt(self):
        self.setup_task(patrol=True)
        self.mem.write_text('MemAvailable: 1000 kB\n')
        proc=self.start_runner()
        self.wait_field('WAITING','memory')
        self.assertEqual(self.fields()['ATTEMPTS'],'0')
        self.assertEqual(self.fields()['SLOT'],"''")
        self.assertFalse((self.base/'calls').exists())
        self.mem.write_text('MemAvailable: 700000 kB\n')
        self.assertEqual(proc.wait(timeout=5),0)
        self.assertEqual(self.fields()['ATTEMPTS'],'1')

    def memory_reason(self, available, full_avg60):
        self.mem.write_text(f'MemAvailable: {available} kB\n')
        self.psi.write_text(f'full avg10=0.00 avg60={full_avg60} avg300=0.00 total=0\n')
        return subprocess.check_output(
            ['bash', '-c', '. "$1"; . "$2"; memory_pressure_reason', 'test',
             str(ROOT / 'limits.env'), str(ROOT / 'resource-pressure.sh')],
            env=self.env, text=True).strip()

    def test_production_memory_thresholds(self):
        # Moved from clawock-patrol/tests/test_supervisor.py: the thresholds live here, the
        # supervisor's admission-only use of them is covered in the repo's test_patrol_supervisor.
        self.assertIn('headroom low', self.memory_reason(190000, '0.00'))
        self.assertEqual(self.memory_reason(196608, '0.00'), '')
        self.assertIn('memory pressure', self.memory_reason(700000, '10.00'))
        self.assertEqual(self.memory_reason(700000, '9.99'), '')
        self.psi.write_text('')
        self.assertIn('telemetry unavailable', subprocess.check_output(
            ['bash', '-c', '. "$1"; . "$2"; memory_pressure_reason', 'test',
             str(ROOT / 'limits.env'), str(ROOT / 'resource-pressure.sh')], env=self.env, text=True))

    def test_memory_gate_never_blocks_foreground(self):
        self.setup_task()
        self.mem.write_text('MemAvailable: 1000 kB\n')
        self.assertEqual(self.run_runner().returncode,0)


if __name__ == '__main__':
    unittest.main()
