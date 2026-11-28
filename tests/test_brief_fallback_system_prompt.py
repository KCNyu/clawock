"""The off-host fallback uses the product skill and its single-turn adapter."""
from __future__ import annotations

import json

import pytest

from clawock.automation import brief_fallback


def test_main_loads_the_portable_prompt_without_private_bootstrap(tmp_path, monkeypatch):
    from test_brief_fallback_artifacts import write_generation

    today = '2026-08-25'
    write_generation(tmp_path, today)
    (tmp_path / 'skills/daily-deep-brief/SKILL.md').write_text(
        "skill instructions\n[The proof](references/packet.md)\n")
    reference = tmp_path / 'skills/daily-deep-brief/references'
    reference.mkdir()
    (reference / 'packet.md').write_text("complete rule\n" + ("evidence\n" * 400) + "final boundary")
    captured = {}

    def fake_chat(**kwargs):
        captured.update(kwargs)
        return json.dumps({'plan': {'schema_version': 2, 'date': today, 'decisions': []},
                           'judgment': {}})

    monkeypatch.setenv('TODAY', today)
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(tmp_path))
    monkeypatch.setattr(brief_fallback, 'chat', fake_chat)
    with pytest.raises(SystemExit):
        brief_fallback.main([])

    assert captured['system'] == brief_fallback.SINGLE_TURN_ADAPTER
    assert 'skill instructions' in captured['user']
    assert 'final boundary' in captured['user']


def test_a_plan_dated_another_day_is_refused_before_anything_is_written(
        tmp_path, monkeypatch):
    """#1915: the fallback kept the model's `date` and validated without the
    filename, so a plan dated 09-20 was written as today's plan.json."""
    from test_brief_fallback_artifacts import model_reply, write_generation

    today = '2026-09-26'
    ws = tmp_path
    packet = write_generation(ws, today)
    monkeypatch.setenv('TODAY', today)
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(ws))
    monkeypatch.setattr(brief_fallback, 'chat',
                        lambda **_kw: model_reply(packet, today, date='2026-09-20'))

    with pytest.raises(SystemExit, match='must match filename'):
        brief_fallback.main([])
    assert not (ws / 'memory' / f'{today}-plan.json').exists()
