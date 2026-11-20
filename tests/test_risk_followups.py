"""Follow-up projection never rewrites governance or grants an execution."""
import copy
import json

from clawock.decision import risk

NOW = '2026-11-01T08:00:00+00:00'


def record(bid, **extra):
    return {'breach_id': bid, 'leg': 'US', 'ticker': 'ABC', 'type': 'hard_stop',
            'status': 'open', 'last_seen_at': '2026-10-30T00:00:00+00:00', **extra}


def write(tmp_path, rows):
    path = tmp_path / 'risk.json'
    path.write_text(json.dumps({'schema_version': 1, 'updated_at': NOW, 'records': rows}))
    return path


def test_deadlines_rechecked_without_reconcile_or_new_state(tmp_path):
    rows = [record('expired', status='overridden', override={'status': 'active', 'reason': 'wait',
             'expires_at': '2026-11-01T08:00:00+00:00'}),
            record('later', status='overridden', override={'status': 'active', 'reason': 'wait',
             'expires_at': '2026-11-02T08:00:00+00:00'}),
            record('rearm', adaptive={'eligible': True, 'may_stand': True, 'forced_on': '2026-11-01'}),
            record('verify', execution={'status': 'confirmed'}),
            record('ack', acknowledgement={'status': 'acknowledged'}),
            record('new'), record('resolved', status='resolved'), record('hk', leg='HK')]
    path = write(tmp_path, rows)
    before = path.read_bytes()
    view = risk.followups(path, leg='US', now=NOW)
    assert path.read_bytes() == before
    got = {r['breach_id']: r['state'] for r in view['rows']}
    assert got == {'expired': 'due', 'rearm': 'due', 'verify': 'verify', 'new': 'undecided',
                   'later': 'scheduled', 'ack': 'watch'}
    assert view['rows'][0]['state'] == 'due' and view['total'] == 6
    assert view['ledger_updated_at'] == NOW
    small = risk.followups(path, leg='US', now=NOW, limit=2)
    assert small['omitted'] == 4 and len(small['rows']) == 2


def test_invalid_override_and_unknown_dates_do_not_disappear(tmp_path):
    row = record('a', status='overridden', override={'status': 'active', 'reason': '', 'expires_at': 'bad'})
    second = record('b', adaptive={'eligible': True, 'may_stand': True})
    path = write(tmp_path, [row, second])
    assert [r['state'] for r in risk.followups(path, now=NOW)['rows']] == ['due', 'verify']
    path.write_text('{}')
    assert risk.followups(path, now=NOW)['status'] == 'unavailable'
    assert risk.followups(tmp_path / 'absent', now=NOW)['status'] == 'unavailable'
    write(tmp_path, [])
    assert risk.followups(path, now=NOW)['status'] == 'ok'


def test_due_date_uses_ledger_utc_day(tmp_path):
    path = write(tmp_path, [record('a', adaptive={'eligible': True, 'forced_on': '2026-11-02'})])
    assert risk.followups(path, now='2026-11-02T01:00:00+08:00')['rows'][0]['state'] == 'scheduled'


def test_followups_cli_is_read_only(tmp_path, capsys):
    path = write(tmp_path, [record('a')])
    before = copy.deepcopy(json.loads(path.read_text()))
    assert risk.main(['--ledger', str(path), 'followups', '--leg', 'US', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['total'] == 1
    assert json.loads(path.read_text()) == before


def test_card_keeps_deadline_timezone_and_review_distinct_from_orders(tmp_path):
    from clawock.harness.chat_card import review_sections
    path = write(tmp_path, [record('future', status='overridden', override={
        'status': 'active', 'reason': 'wait', 'expires_at': '2026-11-02T08:00:00+00:00'})])
    text = '\n'.join(review_sections(risk_followups=risk.followups(path, now=NOW)))
    assert '11/02 16:00 港时' in text and '不是新的买卖指令' in text
    assert '**待你处理**' not in text


def test_reassessment_request_and_review_leave_the_obligation_and_execution_open(tmp_path):
    path = write(tmp_path, [record('long', age_days=120), record('new', age_days=2)])
    assert risk.followups(path, now=NOW)['rows'][0]['breach_id'] == 'long'
    risk.request_reassessment(path, 'long', 'new company disclosure')
    reread = risk.followups(path)['rows'][0]
    assert reread['state'] == 'due' and reread['decision_overdue']
    assert reread['reassessment']['reason'] == 'new company disclosure'
    risk.request_reassessment(path, 'long', 'risk still open', reviewed=True)
    reread = risk.followups(path)['rows'][0]
    assert reread['state'] == 'undecided' and reread['decision_overdue']
    saved = risk.load_ledger(path)['records'][0]
    assert saved['status'] == 'open'
    assert not any(key in saved for key in ('execution', 'override', 'acknowledgement'))
    assert saved['reassessment']['review_note'] == 'risk still open'


def test_brief_delivery_suppresses_market_repeat_until_risk_changes(tmp_path, monkeypatch):
    from clawock.harness import brief_card, chat_card, report, risk_notices

    memory = tmp_path / 'memory'
    memory.mkdir()
    path = memory / 'risk_breaches.json'

    def save(**fields):
        path.write_text(json.dumps({'schema_version': 1, 'records': [
            {**record('still-open'), **fields},
        ]}))

    def market_card(now=NOW):
        view = risk_notices.review(tmp_path, leg='US', now=now)
        ctx = {'title': '美股报告', 'raw_wechat_block': '行情', 'risk_followups': view,
               'risk_debts': risk.leg_debts('US', path)[0]}
        report_text = report.assemble_message(ctx, '')
        intraday_text = chat_card.render(analyzer='行情', risk_followups=view)
        assert ('**风险待复查**' in report_text) == ('**风险待复查**' in intraday_text)
        assert '欠着的账' not in report_text
        return view, report_text

    save(age_days=9)
    monkeypatch.setattr(brief_card, 'WS', tmp_path)
    brief = risk_notices.review(tmp_path, now=NOW)
    brief_message = brief_card.build_brief_card('2026-11-01', risk_view=brief, footer='usage')
    assert '9 天未结' in brief_message and brief_message.endswith('usage')
    risk_notices.record(tmp_path, brief, '盘前简报')  # A body without the row proves nothing.
    assert '9 天未结' in market_card()[1]
    risk_notices.record(tmp_path, brief, brief_message)
    assert '9 天未结' not in market_card()[1]

    save(age_days=10)
    view, text = market_card('2026-11-02T08:00:00+00:00')
    assert '处置已逾期' in text
    risk_notices.record(tmp_path, view, text)
    save(age_days=11)
    assert '风险待复查' not in market_card('2026-11-03T08:00:00+00:00')[1]

    save(age_days=11, status='overridden', override={'status': 'active', 'reason': 'wait',
                                'expires_at': '2026-11-03T09:00:00+00:00'})
    view, text = market_card('2026-11-03T08:00:00+00:00')
    assert '限时豁免，到期复查' in text
    risk_notices.record(tmp_path, view, text)
    view, text = market_card('2026-11-03T09:00:00+00:00')
    assert '豁免已到期' in text
    risk_notices.record(tmp_path, view, text)
    assert '风险待复查' not in market_card('2026-11-03T09:30:00+00:00')[1]

    save(age_days=11, acknowledgement={'status': 'acknowledged'})
    assert '已确认承担风险' in market_card('2026-11-03T10:00:00+00:00')[1]
