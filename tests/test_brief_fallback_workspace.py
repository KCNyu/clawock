"""The fallback reads and writes the selected book from an unrelated cwd."""
import json
from pathlib import Path

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


def test_single_turn_fallback_inlines_the_same_skill_references():
    from clawock.automation.brief_fallback import _read_brief_skill

    root = Path(__file__).resolve().parents[1]
    skill = root / 'skills/daily-deep-brief'
    prompt = _read_brief_skill(root)
    for name in ('packet', 'swarm', 'style', 'plan-schema'):
        reference = (skill / 'references' / f'{name}.md').read_text(encoding='utf-8').strip()
        assert reference in prompt


def test_brief_skill_exposes_small_runtime_entry_and_indexed_references():
    import re

    root = Path(__file__).resolve().parents[1]
    skill = root / 'skills/daily-deep-brief'
    entry = (skill / 'SKILL.md').read_text(encoding='utf-8')
    assert len(entry.splitlines()) < 500
    assert 'manual' in entry.lower() or '手动复盘' in entry
    assert '工作日简报任务是正例' in entry
    paths = re.findall(r'\]\((references/[^/)]+\.md)\)', entry)
    assert set(paths) == {
        'references/packet.md', 'references/swarm.md', 'references/style.md',
        'references/plan-schema.md', 'references/technical-playbooks.md',
    }
    for relative in paths:
        reference = (skill / relative).read_text(encoding='utf-8')
        if len(reference.splitlines()) > 100:
            assert '## 目录' in reference
        assert '](references/' not in reference
