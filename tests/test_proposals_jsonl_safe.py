import json

from clawock.decision import proposals


def test_nonfinite_proposal_fields_are_strict_json_and_reported(tmp_path, capsys):
    plan = {'date': '2026-10-21', 'decisions': [{'ticker': 'TEST', 'action': 'watch',
            'forecast': {'up': float('nan')}, 'size': {'shares': float('inf')}}]}
    proposals.record(tmp_path, plan, [], plan_status='pass', author={})
    assert proposals.record(tmp_path, plan, [], plan_status='pass', author={}) == []
    lines = proposals.log_path(tmp_path).read_text().splitlines()
    def reject(token):
        raise AssertionError(token)
    rows = [json.loads(line, parse_constant=reject) for line in lines]
    assert len(rows) == len(proposals.load(tmp_path)) == 1
    assert rows[0]['forecast']['up'] is None
    assert rows[0]['size']['shares'] is None
    assert 'non-finite' in capsys.readouterr().err
