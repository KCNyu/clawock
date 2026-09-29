"""#2135: model markdown written straight into a Jekyll page carries no raw HTML.

kramdown passes raw HTML through and the pages have no CSP. #2111 escaped the
harness renderer; these are the two other writers of model markdown into
`memory/*.md`, driven through their own `main()` so the test sees the bytes
that land on disk.
"""
import json

import pytest

from clawock.automation import brief_fallback, weekly_review
from clawock.automation.output_validate import escape_raw_html

TAG = '<img src=x onerror=alert(1)>'


def test_the_off_host_brief_writes_model_tags_as_text(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('TODAY', '2026-09-29')
    (tmp_path / 'memory/.tmp').mkdir(parents=True)
    (tmp_path / 'memory/.tmp/brief-context-2026-09-29.json').write_text('{}')
    (tmp_path / 'skills/daily-deep-brief').mkdir(parents=True)
    for name in ('skills/daily-deep-brief/SKILL.md', 'SOUL.md', 'BOOTSTRAP.md'):
        (tmp_path / name).write_text('x')
    monkeypatch.setattr(brief_fallback, 'prepare_context',
                        lambda raw: {'complete': True, 'serialized': '{}', 'payload': {}})
    plan = {'date': '2026-09-29', 'decisions': []}
    monkeypatch.setattr(brief_fallback, 'chat', lambda **kw: (
        f'## ▎仓位明细\n仓位 < 50%，{TAG}\n```json\n{json.dumps(plan)}\n```'))
    monkeypatch.setattr(brief_fallback.decision_v2, 'normalize_authored_plan', lambda p: p)
    monkeypatch.setattr(brief_fallback.decision_v2, 'validate_plan', lambda p, path: [])
    monkeypatch.setattr(brief_fallback, 'validate_sections', lambda text, **kw: text)

    brief_fallback.main()

    page = (tmp_path / 'memory/2026-09-29-pre-open.md').read_text()
    assert '仓位 &lt; 50%' in page and '&lt;img src=x' in page
    assert '<img' not in page
    assert page.startswith('---\nlayout: default\n')


def test_the_weekly_review_writes_model_tags_as_text(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(weekly_review, 'aggregate_week', lambda as_of: {'week': '2026-W39'})
    monkeypatch.setattr(weekly_review, 'validate_bundle', lambda bundle: None)
    monkeypatch.setattr(weekly_review, 'build_prompt_payload', lambda bundle: {})
    monkeypatch.setattr(weekly_review, 'build_user_prompt', lambda payload: '')
    monkeypatch.setattr(weekly_review, 'generate_review',
                        lambda system, user: f'## 本周\n回撤 < 5%，{TAG}')

    weekly_review.main([])

    page = (tmp_path / 'memory/weekly/2026-W39.md').read_text()
    assert '回撤 &lt; 5%' in page and '&lt;img src=x' in page
    assert '<img' not in page
    assert page.startswith('---\nlayout: default\n')


# #2181: kramdown also writes attributes with no `<` in the input — an
# attribute list lands on the element, and a link target becomes an href
# whatever its scheme. Each form below was rendered through kramdown + GFM (the
# site's parser) with and without the escape; only the escaped one is inert.


ATTRIBUTE_PAYLOADS = [
    ('段落\n{: onclick="alert(1)"}', '{:'),                  # block IAL
    ('*强调*{: onmouseover="alert(1)"}', '{:'),               # span IAL
    ('{::nomarkdown}<b>x</b>{:/nomarkdown}', '{:'),           # raw-HTML extension
    ('[点我](javascript:alert(1))', '](javascript'),
    ('[点我]( JavaScript:alert(1))', ']('),
    ('[点我](jav&#97;script:alert(1))', '](jav'),             # the browser decodes it
    ('[点我](data:text/html,x)', '](data'),
    ('[点我][r]\n\n[r]: javascript:alert(1)', ']: javascript'),
    (TAG, '<'),
]


@pytest.mark.parametrize('payload, live', ATTRIBUTE_PAYLOADS)
def test_model_markdown_cannot_write_an_attribute_or_a_script_href(payload, live):
    assert live not in escape_raw_html(payload)


@pytest.mark.parametrize('payload, live', ATTRIBUTE_PAYLOADS)
def test_the_harness_renderer_escapes_like_the_fallback_writer(payload, live):
    # #2187: `brief_render` writes the same pre-open page every morning with its
    # own escapers, which #2181 left handling `<` only.
    from clawock.harness import brief_render
    for escape in (brief_render.text, brief_render._cell, brief_render._inline):
        assert live not in escape(payload), escape.__name__
    page = brief_render.render_brief(
        {'date': '2026-09-29'},
        {'portfolio_assessment': payload, 'portfolio_counterargument': payload},
        {'date': '2026-09-29', 'decisions': []}, date='2026-09-29')
    assert payload.replace('\n', ' ') not in page
    if live != '<':  # the renderer's own layout carries `<div …>` tags
        assert live not in page


@pytest.mark.parametrize('text', [
    '[公告](https://www1.hkexnews.hk/a.pdf?x=1)',
    '[相对](../2026-09-28-pre-open.html#持仓)',
    '[锚点](#top)',
    '[邮件](mailto:a@b.c)',
    '[r]: https://example.com',
    'USD${-720.35} per concentration.{hk,us}.verdict brief-card-{date}.txt',
])
def test_ordinary_links_and_braces_are_left_alone(text):
    assert escape_raw_html(text) == text
