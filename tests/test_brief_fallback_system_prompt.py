"""The fallback's system prompt must carry SOUL.md and BOOTSTRAP.md whole.

Regression guard for #962: the prompt used to embed `{soul[:1000]}\\n\\n
{bootstrap[:2000]}`. On committed 2026-08 text the SOUL cut landed right before
`## Operating mode (this workspace)` — the analyst disposition for exactly this
writing job — and kept 39% of the file; the BOOTSTRAP cut landed mid-sentence
and dropped C. 输出约束, the constraint list postflight validates the fallback
output against. Same defect class as #959/#961: never slice a whole document
into a prompt.
"""
from __future__ import annotations

import json

import pytest

from clawock.automation import brief_fallback


SOUL_TEXT = (
    "# SOUL.md - Who You Are\n\n"
    "intro text that fills up the first chunk of the file.\n"
    + ("filler sentence.\n" * 120)
    + "## Operating mode (this workspace)\n\nHave a view, name the trade.\n"
)

BOOTSTRAP_TEXT = (
    "# BOOTSTRAP.md\n\nhard rules live here first.\n"
    + ("more filler.\n" * 250)
    + "### C. 输出约束\n\n禁止敷衍词；禁止 hedging 免责声明。\n"
)


def test_system_prompt_carries_both_files_whole():
    prompt = brief_fallback.build_system_prompt(SOUL_TEXT, BOOTSTRAP_TEXT)

    # Markers deliberately placed past both old cut points (char 1000 / 2000):
    # under the slices these assertions failed, which is the exact data loss.
    assert "## Operating mode (this workspace)" in prompt
    assert "### C. 输出约束" in prompt
    assert "禁止敷衍词" in prompt


def test_system_prompt_preserves_the_final_lines_of_each_file():
    """Nothing after either file's last line may go missing again."""
    prompt = brief_fallback.build_system_prompt(SOUL_TEXT, BOOTSTRAP_TEXT)

    assert prompt.endswith(BOOTSTRAP_TEXT.strip())
    assert SOUL_TEXT.strip() in prompt


def test_main_passes_the_untruncated_prompt_to_chat(tmp_path, monkeypatch):
    """Wiring test: whatever main() sends as `system` must be the whole-file
    build, proven end-to-end through the real file reads."""
    today = '2026-08-25'
    ws = tmp_path
    (ws / 'memory' / '.tmp').mkdir(parents=True)
    (ws / 'skills' / 'daily-deep-brief').mkdir(parents=True)
    (ws / 'SOUL.md').write_text(SOUL_TEXT, encoding='utf-8')
    (ws / 'BOOTSTRAP.md').write_text(BOOTSTRAP_TEXT, encoding='utf-8')
    (ws / 'skills' / 'daily-deep-brief' / 'SKILL.md').write_text(
        '# skill\n', encoding='utf-8')
    context = {'portfolio': {'portfolios': {'hk_stocks': {}, 'us_stocks': {}}}}
    (ws / 'memory' / '.tmp' / f'brief-context-{today}.json').write_text(
        json.dumps(context), encoding='utf-8')

    captured = {}

    def fake_chat(**kwargs):
        captured.update(kwargs)
        return ('prose\n```json\n'
                + json.dumps({'schema_version': 2, 'date': today,
                              'decisions': []})
                + '\n```')

    monkeypatch.setenv('TODAY', today)
    monkeypatch.chdir(ws)
    monkeypatch.setattr(brief_fallback, 'chat', fake_chat)
    # An empty decisions list fails schema validation by design; chat() has
    # already been called by then, which is the moment under test.
    with pytest.raises(SystemExit):
        brief_fallback.main()

    system = captured['system']
    assert "## Operating mode (this workspace)" in system
    assert "禁止敷衍词" in system
