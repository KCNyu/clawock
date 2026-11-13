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
    cards = []
    monkeypatch.setattr(postflight, 'build_brief_card',
                        lambda *_a, **_k: cards.append(_k) or 'card')
    monkeypatch.setattr(postflight, 'send_per_policy',
                        lambda *_a, **kw: sends.append(kw) or (True, 'ok', True))
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
    d.cards = cards
    d.versions = tmp_path / 'memory' / 'brief-versions' / TODAY

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


def test_the_delivered_card_binds_a_version_and_a_rerun_keeps_it(desk, capsys):
    code, result = desk.run(capsys)
    first_id = result['brief_version']
    receipt = json.loads((desk.tmp / f'brief-sent-{TODAY}.json').read_text())
    index = json.loads((desk.versions / 'index.json').read_text())

    assert code == 0 and len(desk.sends) == 1
    assert first_id.startswith('v1-')
    assert receipt['brief_version'] == first_id
    assert receipt['brief_version_path'] == index['versions'][0]['path']
    assert receipt['brief_version_sha256'] == receipt['report_sha256']
    assert index['current'] == first_id
    assert index['versions'][0]['delivery']['channels'] == {
        'wechat': True, 'telegram': True}
    assert desk.cards[0]['version']['id'] == first_id

    archived_v1 = (desk.versions / index['versions'][0]['file']).read_text()
    assert '现金 13.2 亿美元' in archived_v1
    desk.rendered['body'] = 'SK 海力士收 142.87'
    code, result = desk.run(capsys)
    second_id = result['brief_version']
    receipt = json.loads((desk.tmp / f'brief-sent-{TODAY}.json').read_text())
    index = json.loads((desk.versions / 'index.json').read_text())
    page = desk.md.read_text(encoding='utf-8')

    # No second card; the delivered version stays bound to the first card.
    assert code == 0 and len(desk.sends) == 1
    assert second_id != first_id and index['current'] == second_id
    assert receipt['brief_version'] == first_id
    assert (desk.versions / index['versions'][0]['file']).read_text() == archived_v1
    assert len(index['versions']) == 2
    assert result['content_revised_after_delivery']['delivered_version'] == first_id
    assert result['content_revised_after_delivery']['current_version'] == second_id
    # The live page is current and names both sides; the archive link is absent
    # because this fixture's workspace declares no repository.
    assert 'SK 海力士收 142.87' in page
    assert first_id in page and second_id in page


def test_a_legacy_receipt_binds_the_archived_digest_it_still_names(desk, capsys):
    desk.run(capsys)
    marker = desk.tmp / f'brief-sent-{TODAY}.json'
    receipt = json.loads(marker.read_text())
    first_id = receipt['brief_version']
    for key in ('brief_version', 'brief_version_path', 'brief_version_sha256'):
        receipt.pop(key)
    marker.write_text(json.dumps(receipt))

    code, result = desk.run(capsys)
    rebound = json.loads(marker.read_text())
    index = json.loads((desk.versions / 'index.json').read_text())

    assert code == 0 and len(desk.sends) == 1
    assert rebound['brief_version'] == first_id
    assert index['versions'][0]['delivery']['channels'] == {
        'wechat': True, 'telegram': True}
    assert index['versions'][0]['delivery']['receipt'] == marker.name
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
    rewritten = json.loads(marker.read_text())
    assert rewritten['report_sha256'] == original['report_sha256']
    # The first delivered card keeps the version binding; a later WeChat
    # recovery may carry a newer page, but it must not relabel the delivery.
    assert rewritten['brief_version'] == original['brief_version']
    desk.run(capsys)
    assert len(desk.degradations) == 1


def test_no_revision_when_both_channels_failed(desk, capsys, monkeypatch):
    monkeypatch.setattr(postflight, 'send_per_policy', lambda *a, **k: (False, 'failed', False))
    desk.run(capsys)
    desk.rendered['body'] = '尚未送达的修正稿'
    _, result = desk.run(capsys)
    assert result['content_revised_after_delivery'] is None
    assert postflight.REVISION_NOTICE_PREFIX not in desk.md.read_text()


def test_dry_run_does_not_create_a_version(desk, capsys):
    code, result = desk.run(capsys, '--dry-run')

    assert code == 0
    assert result['brief_version'] is None
    assert not desk.versions.exists()
    assert len(desk.sends) == 1 and desk.sends[0].get('dry_run') is True


def test_a_version_store_failure_does_not_block_the_card(desk, capsys, monkeypatch):
    def broken(*_a, **_k):
        raise OSError('disk full while archiving')

    monkeypatch.setattr(postflight.brief_versions, 'capture', broken)
    code, result = desk.run(capsys)

    assert code == 0 and len(desk.sends) == 1
    assert result['brief_version'] is None
    assert 'disk full while archiving' in result['brief_version_error']
    receipt = json.loads((desk.tmp / f'brief-sent-{TODAY}.json').read_text())
    assert 'brief_version' not in receipt
    assert receipt['sent_ok'] is True and receipt['tg_ok'] is True
