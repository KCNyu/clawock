"""Publication contract for the generated dashboard screenshots workflow."""
import re
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'screenshot-refresh.yml'


def _steps():
    lines = WORKFLOW.read_text().splitlines()
    return [
        (i, line.strip().removeprefix('- name: '))
        for i, line in enumerate(lines)
        if line.lstrip().startswith('- name: ')
    ]


def _step_block(name):
    lines = WORKFLOW.read_text().splitlines()
    start = next(i for i, step_name in _steps() if step_name == name)
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = next(
        (i for i in range(start + 1, len(lines))
         if lines[i].startswith(' ' * indent + '- ')),
        len(lines),
    )
    return '\n'.join(lines[start:end])


def _step_run(name):
    block = _step_block(name).splitlines()
    run_start = next(i for i, line in enumerate(block) if line.strip() == 'run: |')
    return textwrap.dedent('\n'.join(block[run_start + 1:]))


def test_screenshots_are_validated_and_exactly_staged_before_publish():
    names = [name for _, name in _steps()]
    generate = 'Capture win-rate chart + social card'
    validate = 'Validate screenshots'
    commit = 'Commit if changed'
    assert names.index(generate) < names.index(validate) < names.index(commit)

    validator_block = _step_block(validate)
    validator_run = _step_run(validate)
    assert 'continue-on-error' not in validator_block
    assert "('assets/shadow-backtest.png', 20_000, 400, 200)" in validator_run
    assert "('assets/social-card.png', 150_000, 1_000, 500)" in validator_run
    assert "assert path.is_file(), f'missing screenshot: {filename}'" in validator_run
    assert 'assert size >= min_size' in validator_run
    assert "PNG_MAGIC = b'\\x89PNG\\r\\n\\x1a\\n'" in validator_run
    assert 'assert header[:8] == PNG_MAGIC' in validator_run
    assert "assert header[12:16] == b'IHDR'" in validator_run
    assert "struct.unpack('>II', header[16:24])" in validator_run

    commit_run = _step_run(commit)
    add_lines = [line.strip() for line in commit_run.splitlines()
                 if re.match(r'^git add(?:\s|$)', line.strip())]
    assert add_lines == [
        'git add -- assets/shadow-backtest.png assets/social-card.png',
        'git add -- assets/dashboard.gif',
    ]
    assert not re.search(r'(?m)^\s*git add\s+(?:--\s+)?assets/?\s*$', commit_run)
