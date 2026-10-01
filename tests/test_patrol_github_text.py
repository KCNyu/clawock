"""Public patrol text must never create third-party GitHub backlinks or mentions."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ops/host/clawock-patrol'))
from github_text import sanitize, validate


@pytest.mark.parametrize('text', [
    'https://github.com/example/project/issues/123',
    '<https://github.com/example/project/pull/42>',
    '[borrowed example](https://github.com/example/project/commit/abcdef)',
    'example/project#123 example/project@abcdef @someone',
    'https://github.com/example/project/blob/main/README.md',
    'https://raw.githubusercontent.com/example/project/main/README.md',
    'https://api.github.com/repos/example/project/issues/1',
    '[example/project#5](https://github.com/example/project/issues/5)',
    'www.github.com/example/project/issues/1',
])
def test_external_references_become_plain_text(text):
    with pytest.raises(ValueError):
        validate(text)
    clean = sanitize(text)
    assert 'github.com' not in clean and 'githubusercontent.com' not in clean
    assert 'example/project#' not in clean and '@' not in clean
    assert validate(clean) == clean and sanitize(clean) == clean


def test_own_repository_and_local_evidence_remain_intact():
    text = 'Closes #2251 KCNyu/clawock#2251 https://github.com/KCNyu/clawock/issues/2251 src/clawock/a.py:12'
    assert validate(text) == text
