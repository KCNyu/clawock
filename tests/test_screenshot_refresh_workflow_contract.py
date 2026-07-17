"""Publication contract for the generated dashboard screenshots workflow."""
import re
from pathlib import Path

from workflow_contract_helpers import step_block, step_run, steps


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'screenshot-refresh.yml'


def _steps():
    return steps(WORKFLOW)


def _step_block(name):
    return step_block(WORKFLOW, name)


def _step_run(name):
    return step_run(WORKFLOW, name)


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
    assert 'assert width >= min_width and height >= min_height' in validator_run

    commit_run = _step_run(commit)
    add_lines = [line.strip() for line in commit_run.splitlines()
                 if re.match(r'^git add(?:\s|$)', line.strip())]
    assert add_lines == [
        'git add -- assets/shadow-backtest.png assets/social-card.png',
        'git add -- assets/dashboard.gif',
    ]
    assert not re.search(r'(?m)^\s*git add\s+(?:--\s+)?assets/?\s*$', commit_run)


def test_gif_is_validated_only_on_manual_dispatch_before_publish():
    names = [name for _, name in _steps()]
    assemble = 'Assemble tab-cycle GIF'
    validate = 'Validate tab-cycle GIF'
    commit = 'Commit if changed'
    assert names.index(assemble) < names.index(validate) < names.index(commit)

    validator_block = _step_block(validate)
    validator_run = _step_run(validate)
    assert "if: github.event_name == 'workflow_dispatch'" in validator_block
    assert 'continue-on-error' not in validator_block
    assert "path = Path('assets/dashboard.gif')" in validator_run
    assert "assert path.is_file(), f'missing GIF: {path}'" in validator_run
    assert 'MIN_GIF_SIZE = 300_000' in validator_run
    assert 'assert size >= MIN_GIF_SIZE' in validator_run
    assert "GIF_MAGICS = (b'GIF89a', b'GIF87a')" in validator_run
    assert 'header = gif.read(10)' in validator_run
    assert 'assert header[:6] in GIF_MAGICS' in validator_run
    assert "struct.unpack('<HH', header[6:10])" in validator_run
    assert 'assert width >= 300 and height >= 500' in validator_run
