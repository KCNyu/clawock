"""A re-run that rewrites the delivered brief says so, on the page and in the ledger (#3105)."""
from __future__ import annotations

import json
import sys
from datetime import date

import pytest

from clawock.harness import brief_postflight as postflight

from test_brief_projection_publication_gate import _filled_judgment

TODAY = '2026-09-14'
REPORT = ('---\nlayout: default\ntitle: 盘前深度简报\n---\n\n'
          '# 盘前深度简报｜{today}\n\n{body}\n\n## 今天做什么\n\n持有。\n')


@pytest.fixture
def desk(tmp_path, monkeypatch):
    monkeypatch.setattr(postflight.trading_calendar, 'hkt_today',
                        lambda: date.fromisoformat(TODAY))
    tmp = tmp_path / 'memory' / '.tmp'
    tmp.mkdir(parents=True)
    (tmp / f'brief-context-{TODAY}.json').write_text(
        json.dumps({'generation_id': 'generation-fixture'}))
    (tmp / f'brief-judgment-{TODAY}.json').write_text(
        json.dumps(_filled_judgment(), ensure_ascii=False))
    monkeypatch.setattr(postflight, 'WS', tmp_path)
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(tmp_path))
    monkeypatch.setattr(postflight.trading_calendar, 'closed_reason',
                        lambda _market, *_a, **_k: None)
    monkeypatch.setattr(postflight.workflow_outcomes, 'slot_for_job', lambda _job: 'slot')
    stages, degradations, sends, commits = [], [], [], []
    monkeypatch.setattr(postflight.workflow_outcomes, 'record_stage',
                        lambda job, stage, state, **_kw: stages.append((stage, state)))
    monkeypatch.setattr(postflight.workflow_outcomes, 'record_primary_delivery',
                        lambda *_a, **_kw: None)
    monkeypatch.setattr(postflight.workflow_outcomes, 'note_degradation',
                        lambda _ledger, kind, detail, **kw: degradations.append(
                            (kind, detail, kw.get('group'))))
    monkeypatch.setattr(postflight.cron_heartbeat, 'unpushed_commits', lambda **_kw: 0)
    monkeypatch.setattr(postflight.cron_heartbeat, 'unpushed_oldest_hours', lambda: 0)
    monkeypatch.setattr(postflight.brief_context, 'validate_run_bundle', lambda *_a: [])
    monkeypatch.setattr(postflight.brief_decision_packet, 'read_packet',
                        lambda _m: {'_meta': {'generation_id': 'generation-fixture'}})
    monkeypatch.setattr(postflight, 'validate_markdown', lambda *_a, **_k: [])
    monkeypatch.setattr(postflight, 'readability_issues', lambda _r: [])
    monkeypatch.setattr(postflight, 'normalize_plan_json',
                        lambda *_a, **_k: ([], {'decisions': []}))
    monkeypatch.setattr(postflight, 'validate_plan_json', lambda *_a, **_k: [])
    monkeypatch.setattr(postflight, 'record_proposals', lambda *_a, **_k: None)
    monkeypatch.setattr(postflight, 'build_brief_card', lambda *_a, **_k: 'card')
    monkeypatch.setattr(postflight, 'send_per_policy',
                        lambda *a, **_k: sends.append(a) or (True, 'ok', True))
    monkeypatch.setattr(postflight, 'maybe_commit', lambda status, _today, dry_run=False, **_kw:
                        commits.append(status) or (True, 'committed + pushed'))
    monkeypatch.setattr(postflight, 'dashboard_publication_state', lambda _ws: 'published')

    def write_projection(_packet, _judgment, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text('{}')
        return {'judgment_status': 'valid'}, []
    monkeypatch.setattr(postflight.brief_decision_packet, 'write_pages_projection',
                        write_projection)

    md = tmp_path / 'memory' / f'{TODAY}-pre-open.md'
    rendered = {'body': '现金 13.2 亿美元'}

    def render(workspace, today, **kw):
        if kw.get('write', True):
            md.write_text(REPORT.format(today=today, body=rendered['body']), encoding='utf-8')
        return [], None
    monkeypatch.setattr(postflight.brief_render, 'render_from_workspace', render)

    class Desk:
        pass
    d = Desk()
    d.md, d.tmp, d.rendered = md, tmp, rendered
    d.stages, d.degradations, d.sends, d.commits = stages, degradations, sends, commits

    def run(capsys, *argv):
        monkeypatch.setattr(sys, 'argv', ['brief_postflight.py', *argv])
        code = postflight.main(list(argv))
        return code, json.loads(capsys.readouterr().out)
    d.run = run
    return d


def test_the_delivering_run_records_what_the_link_showed(desk, capsys):
    code, result = desk.run(capsys)
    receipt = json.loads((desk.tmp / f'brief-sent-{TODAY}.json').read_text())
    assert code == 0 and len(desk.sends) == 1
    assert receipt['report_sha256'] == postflight.report_sha256(desk.md)
    assert result['content_revised_after_delivery'] is None
    assert desk.degradations == []


def test_a_rerun_that_rewrites_the_delivered_report_is_said_and_counted_once(desk, capsys):
    desk.run(capsys)
    delivered = postflight.report_sha256(desk.md)

    desk.rendered['body'] = 'SK 海力士收 142.87'
    code, result = desk.run(capsys)
    revision = result['content_revised_after_delivery']
    text = desk.md.read_text(encoding='utf-8')

    # Still the designed path: no second card, the revision is committed, exit unchanged.
    assert code == 0 and len(desk.sends) == 1 and desk.commits == ['pass', 'pass']
    assert revision['delivered_report_sha256'] == delivered
    assert revision['report_sha256'] == postflight.report_sha256(desk.md) != delivered
    assert revision['revision'] == 1 and revision['counted'] is True
    assert [kind for kind, _, _ in desk.degradations] == ['content_revised_after_delivery']
    assert desk.degradations[0][2] == '盘前深度简报'
    # The notice sits under the title, and the report itself is the revised one.
    lines = text.split('\n')
    title = next(i for i, line in enumerate(lines) if line.startswith('# '))
    assert lines[title + 2].startswith(postflight.REVISION_NOTICE_PREFIX)
    assert 'SK 海力士收 142.87' in text and '现金 13.2 亿美元' not in text

    # The same revision re-run again is not a new one: notice kept, not re-counted.
    code, result = desk.run(capsys)
    assert code == 0 and len(desk.sends) == 1
    assert result['content_revised_after_delivery']['counted'] is False
    assert len(desk.degradations) == 1
    assert desk.md.read_text(encoding='utf-8') == text

    # A second, different revision is counted as the second one.
    desk.rendered['body'] = '第三版'
    _, result = desk.run(capsys)
    assert result['content_revised_after_delivery']['revision'] == 2
    assert len(desk.degradations) == 2
    assert desk.md.read_text(encoding='utf-8').count(postflight.REVISION_NOTICE_PREFIX) == 1


def test_a_plain_retry_of_the_delivered_report_stays_quiet(desk, capsys):
    desk.run(capsys)
    delivered = desk.md.read_text(encoding='utf-8')
    code, result = desk.run(capsys)
    assert code == 0 and len(desk.sends) == 1
    assert result['content_revised_after_delivery'] is None
    assert desk.degradations == []
    assert desk.md.read_text(encoding='utf-8') == delivered


def test_a_receipt_from_before_the_digest_cannot_tell_and_says_nothing(desk, capsys):
    (desk.tmp / f'brief-sent-{TODAY}.json').write_text(
        json.dumps({'ts': 1, 'sent_ok': True, 'tg_ok': True}))
    code, result = desk.run(capsys)
    assert code == 0 and desk.sends == []
    assert result['content_revised_after_delivery'] is None
    assert desk.degradations == []
    assert postflight.REVISION_NOTICE_PREFIX not in desk.md.read_text(encoding='utf-8')


@pytest.mark.parametrize('claim_won', [False, True])
def test_telegram_only_delivery_revision_precedes_wechat_claim(desk, capsys, monkeypatch, claim_won):
    monkeypatch.setattr(postflight, 'send_per_policy', lambda *a, **k: (False, 'ret=-2', True))
    desk.run(capsys)
    marker = desk.tmp / f'brief-sent-{TODAY}.json'
    original = json.loads(marker.read_text())
    desk.rendered['body'] = '修正后的判断'
    monkeypatch.setattr(postflight, 'claim_send', lambda *_: (claim_won, 'fixture'))
    calls = []
    monkeypatch.setattr(postflight, 'send_per_policy',
                        lambda *a, **k: calls.append(k) or (True, 'ok', True))
    code, result = desk.run(capsys)
    assert code == 0
    assert result['content_revised_after_delivery']['delivered_report_sha256'] == original['report_sha256']
    assert postflight.REVISION_NOTICE_PREFIX in desk.md.read_text()
    assert len(desk.degradations) == 1
    assert len(calls) == int(claim_won)
    if calls:
        assert calls[0]['telegram_done'] is True
    assert json.loads(marker.read_text())['report_sha256'] == original['report_sha256']
    desk.run(capsys)
    assert len(desk.degradations) == 1


def test_no_revision_when_both_channels_failed(desk, capsys, monkeypatch):
    monkeypatch.setattr(postflight, 'send_per_policy', lambda *a, **k: (False, 'failed', False))
    desk.run(capsys)
    desk.rendered['body'] = '尚未送达的修正稿'
    _, result = desk.run(capsys)
    assert result['content_revised_after_delivery'] is None
    assert postflight.REVISION_NOTICE_PREFIX not in desk.md.read_text()
