"""Code identity has one owner; both provenance consumers keep their wire format."""
import ast
import hashlib
from pathlib import Path
import subprocess

import pytest
from clawock.evidence import run_card
from clawock import scorecard_provenance

ROOT = Path(__file__).resolve().parents[1]
CONSUMERS = (run_card, scorecard_provenance)


def test_one_implementation_of_code_identity():
    owners = {}
    for path in (ROOT / 'src/clawock').rglob('*.py'):
        source = path.read_text()
        if "['git', 'rev-parse', '--short', 'HEAD']" in source:
            owners.setdefault('commit', []).append(str(path.relative_to(ROOT)))
        if "hashlib.sha256(path.read_bytes()).hexdigest()[:16]" in source:
            owners.setdefault('digest', []).append(str(path.relative_to(ROOT)))
    print('code identity owners:', owners)
    assert owners == {key: ['src/clawock/code_identity.py'] for key in ('commit', 'digest')}
    # Consumers may retain compatibility wrappers, but cannot grow a second body.
    for module in CONSUMERS:
        tree = ast.parse(Path(module.__file__).read_text())
        wrapper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_git_commit')
        assert len(wrapper.body) == 1 and isinstance(wrapper.body[0], ast.Return)
        assert ast.unparse(wrapper.body[0].value) == 'git_commit(WS)'


def test_digest_format_and_missing_file(tmp_path):
    path = tmp_path / 'code.py'
    digesters = (run_card.file_digest, scorecard_provenance._file_digest)
    assert all(digest(path) is None for digest in digesters)
    path.write_bytes(b'code\n')
    expected = 'sha256:' + hashlib.sha256(b'code\n').hexdigest()[:16]
    assert [digest(path) for digest in digesters] == [expected, expected]


@pytest.mark.parametrize('result', [subprocess.CompletedProcess([], 0, 'abc123\n'),
                                   subprocess.CompletedProcess([], 1, 'bad\n'), OSError('git absent'),
                                   subprocess.TimeoutExpired('git', 10)])
def test_git_identity_failure_and_workspace(monkeypatch, tmp_path, result):
    from clawock import code_identity
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(code_identity.subprocess, 'run', run)
    for consumer in CONSUMERS:
        monkeypatch.setattr(consumer, 'WS', tmp_path)
        assert consumer._git_commit() == ('abc123' if getattr(result, 'returncode', 1) == 0 else None)
    assert all(args == ['git', 'rev-parse', '--short', 'HEAD'] and kw['cwd'] == tmp_path
               and kw['timeout'] == 10 for args, kw in calls)
