"""Session boundaries and evidence ownership for the cross-phase recap."""
import copy
import json
from datetime import datetime

from clawock.decision import session_review as R
from clawock.harness import chat_card
from clawock.harness.report import assemble_message


def fixture(tmp_path, day='2026-10-30'):
    memory = tmp_path / 'memory'
    memory.mkdir()
    (memory / '.tmp').mkdir()
    row = {'decision_id': 'd1', 'plan_date': day, 'ticker': 'ABC', 'leg': 'US',
           'action': 'cut', 'condition': {'type': 'price_below', 'price': 10},
           'size': {'shares': 2}, 'execution': {'status': 'followed'}}
    (memory / f'{day}-plan.json').write_text(json.dumps({'date': day, 'decisions': [row]}))
    current = copy.deepcopy(row)
    current['execution'] = {'status': 'unknown'}
    (memory / 'decisions.jsonl').write_text(json.dumps(current) + '\n')
    (memory / '.tmp/intraday-delivered-state-us.json').write_text(json.dumps({
        'slot': '2026-10-31T01:00:00+08:00',
        'state': {'session': 'us:2026-10-30', 'breaches_seen': [
            {'kind': 'signal', 'ticker': 'ABC', 'level': 'STOP'},
            {'kind': 'signal', 'ticker': 'ABC', 'level': 'STOP'}]}}))
    return memory, row, current


def test_us_midnight_plan_and_delivery_do_not_roll_to_host_day(tmp_path):
    memory, row, _ = fixture(tmp_path)
    (memory / '2026-10-31-plan.json').write_text('{}')
    before = {str(p): p.read_bytes() for p in memory.rglob('*') if p.is_file()}
    out = R.build(tmp_path, 'us', now=datetime.fromisoformat('2026-10-31T04:10:00+08:00'),
                  plan_triggers=[{'ticker': 'ABC', 'action': 'cut', 'condition': 'price_below',
                                  'condition_price': 10}])
    assert out['session'] == 'us:2026-10-30'
    assert out['counts']['unknown'] == 1 and out['counts']['followed'] == 0
    assert out['current_triggers'] == ['ABC']
    assert out['observed_signals'] == [{'ticker': 'ABC', 'level': 'STOP'}]
    assert out['plan_sha256'] and out['execution_status'] == 'ok'
    assert all(p.read_bytes() == before[str(p)] for p in memory.rglob('*') if p.is_file())
    text = '\n'.join(chat_card.review_sections(out))
    assert '触价不等于成交' in text and '待核验 1' in text


def test_execution_is_joined_by_identity_not_ticker_or_authored_status(tmp_path):
    memory, row, current = fixture(tmp_path)
    now = datetime.fromisoformat('2026-10-31T04:10:00+08:00')
    current['execution']['status'] = 'followed'
    (memory / 'decisions.jsonl').write_text(json.dumps(current))
    assert R.build(tmp_path, 'us', now=now)['counts']['followed'] == 1
    current['size']['shares'] = 3
    (memory / 'decisions.jsonl').write_text(json.dumps(current))
    assert R.build(tmp_path, 'us', now=now)['counts']['unknown'] == 1
    (memory / 'decisions.jsonl').write_text('{broken')
    out = R.build(tmp_path, 'us', now=now)
    assert out['execution_status'] == 'unavailable' and out['counts']['followed'] == 0


def test_missing_wrong_session_future_and_stale_are_unknown(tmp_path):
    memory, _, _ = fixture(tmp_path)
    now = datetime.fromisoformat('2026-10-30T23:00:00+08:00')
    out = R.build(tmp_path, 'us', now=now, unrefreshed=['ABC'], plan_triggers=[
        {'ticker': 'ABC', 'action': 'cut', 'condition': 'price_below', 'condition_price': 10}])
    assert out['current_triggers'] == [] and out['intraday_status'] == 'unavailable'
    out = R.build(tmp_path, 'hk', now=now)
    assert out['rows'] == [] and out['intraday_status'] == 'unavailable'
    out = R.build(tmp_path, 'us', now=datetime.fromisoformat('2026-11-02T22:00:00+08:00'))
    assert out['plan_status'] == 'unavailable' and out['intraday_status'] == 'unavailable'
    assert '本交易日盘前计划未读到' in '\n'.join(chat_card.review_sections(out))


def test_passive_not_counted_as_executed_and_bounded_rows(tmp_path):
    memory, row, _ = fixture(tmp_path)
    rows = [{**row, 'decision_id': f'd{i}'} for i in range(15)]
    rows.append({**row, 'decision_id': 'hold', 'action': 'hold_and_watch'})
    (memory / '2026-10-30-plan.json').write_text(json.dumps({'date': '2026-10-30', 'decisions': rows}))
    (memory / 'decisions.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
    out = R.build(tmp_path, 'us', now=datetime.fromisoformat('2026-10-31T04:10:00+08:00'))
    assert out['counts'] == {'followed': 15, 'not_followed': 0, 'unknown': 0, 'passive': 1}
    assert len(out['rows']) == 12 and out['omitted'] == 3
    ctx = {'title': '收盘', 'raw_wechat_block': '行情', 'session_review': out,
           'risk_followups': {'status': 'unavailable'}}
    text = assemble_message(ctx, '')
    assert '**盘前至本档**' in text and '**风险待复查**' in text
    intraday = chat_card.render(analyzer='行情', session_review=out, risk_followups={'status': 'unavailable'})
    assert '**盘前至本档**' in intraday and '**风险待复查**' in intraday


def test_report_watchdog_fallback_preserves_first_line_and_review():
    from clawock.harness.report import fallback_block
    ctx = {'raw_wechat_block': 'original first line\ndata', 'risk_followups': {'status': 'unavailable'}}
    text = fallback_block(ctx)
    assert text.startswith('original first line\n') and '**风险待复查**' in text
    assert fallback_block({'raw_wechat_block': 'old'}) == 'old'
