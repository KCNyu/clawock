"""The fallback reads and writes the selected book from an unrelated cwd."""
import json

import pytest

from clawock.automation import brief_fallback as bf

TODAY = '2026-08-25'


@pytest.mark.parametrize('complete', [False, True])
def test_explicit_workspace_owns_inputs_and_artifacts(tmp_path, monkeypatch, complete):
    from test_brief_fallback_artifacts import model_reply, write_generation

    root, away = tmp_path / 'book', tmp_path / 'elsewhere'
    for directory in [root, away]:
        (directory / 'memory' / '.tmp').mkdir(parents=True)
        (directory / 'skills' / 'daily-deep-brief').mkdir(parents=True)
    packet = write_generation(root, TODAY) if complete else None
    if not complete:
        (root / 'memory' / '.tmp' / f'brief-context-{TODAY}.json').write_text(
            json.dumps({'date': TODAY}))
    for directory in [root, away]:
        for name in ['SOUL.md', 'BOOTSTRAP.md', 'skills/daily-deep-brief/SKILL.md']:
            (directory / name).write_text('chosen-book' if directory == root else 'wrong-cwd')
    # A tempting cwd context must not override the selected book.
    (away / 'memory' / '.tmp' / f'brief-context-{TODAY}.json').write_text(json.dumps({
        'status': 'market_closed'}))
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(root))
    monkeypatch.setenv('TODAY', TODAY)
    monkeypatch.chdir(away)

    def chat(**kwargs):
        assert complete, 'incomplete context must not call a provider'
        assert 'chosen-book' in kwargs['system'] and 'chosen-book' in kwargs['user']
        assert 'wrong-cwd' not in kwargs['system'] + kwargs['user']
        return model_reply(packet, TODAY)

    monkeypatch.setattr(bf, 'chat', chat)
    bf.main([])
    plan = json.loads((root / 'memory' / f'{TODAY}-plan.json').read_text())
    assert bool(plan['decisions']) == complete
    # Fail-closed still writes its own notice; a real brief leaves the page to postflight.
    assert (root / 'memory' / f'{TODAY}-pre-open.md').exists() != complete
    assert (root / 'memory' / '.tmp' / f'brief-judgment-{TODAY}.json').exists() == complete
    assert not (away / 'memory' / f'{TODAY}-pre-open.md').exists()
    assert not (away / 'memory' / f'{TODAY}-plan.json').exists()
    assert not (away / 'memory' / '.tmp' / f'brief-judgment-{TODAY}.json').exists()


def test_only_the_selected_workspace_needs_a_context(tmp_path, monkeypatch):
    root, away = tmp_path / 'book', tmp_path / 'elsewhere'
    (root / 'memory' / '.tmp').mkdir(parents=True)
    (root / 'memory' / '.tmp' / f'brief-context-{TODAY}.json').write_text('{}')
    away.mkdir()
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(root))
    monkeypatch.setenv('TODAY', TODAY)
    monkeypatch.chdir(away)
    monkeypatch.setattr(bf, 'chat', lambda **kwargs: pytest.fail('broken context called provider'))
    bf.main([])
    assert (root / 'memory' / f'{TODAY}-plan.json').exists()
    assert not (away / 'memory').exists()
