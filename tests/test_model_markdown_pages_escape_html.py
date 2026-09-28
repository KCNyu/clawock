"""#2135: model markdown written straight into a Jekyll page carries no raw HTML.

kramdown passes raw HTML through and the pages have no CSP. #2111 escaped the
harness renderer; these are the two other writers of model markdown into
`memory/*.md`, driven through their own `main()` so the test sees the bytes
that land on disk.
"""
import json

from clawock.automation import brief_fallback, weekly_review

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
