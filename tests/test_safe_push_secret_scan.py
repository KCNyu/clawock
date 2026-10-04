"""The shared bot push path scans data commits even when CI and hooks do not run."""
import os
import subprocess
from pathlib import Path

import pytest


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


@pytest.mark.parametrize("url_remote", [False, True])
@pytest.mark.parametrize("diverged", [False, True])
def test_concurrent_fetch_head_replacement_does_not_break_push_checks(tmp_path, url_remote, diverged):
    import shutil

    origin = tmp_path / 'origin.git'
    subprocess.run(['git', 'init', '--bare', '-b', 'master', str(origin)],
                   check=True, capture_output=True)
    runner = tmp_path / 'runner'
    _git(tmp_path, 'clone', str(origin), str(runner))
    _git(runner, 'config', 'user.name', 'test')
    _git(runner, 'config', 'user.email', 'test@example.invalid')
    (runner / 'README.md').write_text('seed\n')
    _git(runner, 'add', 'README.md')
    _git(runner, 'commit', '-qm', 'seed')
    _git(runner, 'push', 'origin', 'master')
    (runner / 'note.txt').write_text('runtime refresh\n')
    _git(runner, 'add', 'note.txt')
    _git(runner, 'commit', '-qm', 'refresh')
    head = _git(runner, 'rev-parse', 'HEAD')
    if diverged:
        rival = tmp_path / 'rival'
        _git(tmp_path, 'clone', str(origin), str(rival))
        _git(rival, 'config', 'user.name', 'test')
        _git(rival, 'config', 'user.email', 'test@example.invalid')
        (rival / 'README.md').write_text('remote update\n')
        _git(rival, 'add', 'README.md')
        _git(rival, 'commit', '-qm', 'remote update')
        _git(rival, 'push', 'origin', 'master')
    tools = tmp_path / 'bin'
    tools.mkdir()
    real_git = shutil.which('git')
    wrapper = tools / 'git'
    wrapper.write_text('#!/bin/sh\n'
                       'if [ "$1" = diff ] || [ "$1" = fetch ]; then\n'
                       '  : > "$(' + real_git + ' rev-parse --git-path FETCH_HEAD)"\n'
                       'fi\nexec ' + real_git + ' "$@"\n')
    wrapper.chmod(0o755)
    checker = tools / 'clawock'
    checker.write_text('#!/bin/sh\nexit 0\n')
    checker.chmod(0o755)
    env = {**os.environ, 'PATH': f"{tools}:{os.environ['PATH']}", 'PUBLISH_REMOTE': ''}
    remote = origin.as_uri() if url_remote else 'origin'
    result = subprocess.run(['bash', str(SCRIPT), remote], cwd=runner, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    published = _git(runner, 'ls-remote', 'origin', 'refs/heads/master').split()[0]
    assert published == _git(runner, 'rev-parse', 'HEAD')
    assert (runner / 'note.txt').read_text() == 'runtime refresh\n'
    assert not _git(runner, 'for-each-ref', 'refs/clawock/')
    if diverged:
        assert (runner / 'README.md').read_text() == 'remote update\n'
    else:
        assert published == head
