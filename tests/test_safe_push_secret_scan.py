"""The shared bot push path scans data commits even when CI and hooks do not run."""
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'ops/publish/safe_push.sh'


def _git(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def test_hookless_data_push_rejects_a_credential_shaped_added_line(tmp_path):
    origin = tmp_path / 'origin.git'
    subprocess.run(['git', 'init', '--bare', '-b', 'master', str(origin)],
                   check=True, capture_output=True)
    runner = tmp_path / 'runner'
    _git(tmp_path, 'clone', str(origin), str(runner))
    _git(runner, 'config', 'user.name', 'KCNyu')
    _git(runner, 'config', 'user.email', 'shengyu.li.evgeny@gmail.com')
    (runner / 'README.md').write_text('seed\n')
    _git(runner, 'add', 'README.md')
    _git(runner, 'commit', '-qm', 'seed')
    _git(runner, 'push', 'origin', 'master')
    base = _git(runner, 'rev-parse', 'HEAD')
    (runner / 'assets/data').mkdir(parents=True)
    value = 'Q3' * 8  # constructed at runtime; never commit a credential pattern
    (runner / 'assets/data/note.md').write_text(f'- **Finnhub**: {value}\n')
    _git(runner, 'add', 'assets/data/note.md')
    _git(runner, 'commit', '-qm', 'data refresh')
    result = subprocess.run(['bash', str(SCRIPT)], cwd=runner,
                            env={**os.environ, 'PUBLISH_REMOTE': ''},
                            capture_output=True, text=True)
    assert result.returncode == 5, result.stdout + result.stderr
    assert 'added lines failed credential scan' in result.stdout
    assert value not in result.stdout + result.stderr
    assert _git(runner, 'ls-remote', 'origin', 'refs/heads/master').split()[0] == base
