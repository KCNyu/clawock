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
