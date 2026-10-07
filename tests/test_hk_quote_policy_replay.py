"""Freeze the normalized HK writer before policy extraction (#2729).

Expected return values, persisted books and diagnostics were captured from
49797452c before extraction, without network or live portfolio access.
"""
import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

from clawock.market_data import hk_analysis as hk

CASES = json.loads((Path(__file__).parent / 'fixtures' / 'hk_quote_policies.json').read_text())


def run_case(module, case, monkeypatch, path, capsys):
    instant = datetime.fromisoformat(case['now'])

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(module, 'datetime', Clock)
    monkeypatch.setattr(module, 'PORTFOLIO_PATH', str(path))
    monkeypatch.setattr(module, 'fetch_hk_quotes', lambda codes: copy.deepcopy(case['quotes']))

    def indices():
        if case['indices'] == 'failed':
            raise RuntimeError('index provider down')
        return copy.deepcopy(case['indices'])

    monkeypatch.setattr(module, 'fetch_indices', indices)
    path.write_text(json.dumps(case['portfolio']))
    error = None
    try:
        returned = module.update_hk_portfolio(dry_run=case['dry_run'])
    except RuntimeError as exc:
        returned, error = None, str(exc)
    out, err = capsys.readouterr()
    return {'returned': returned, 'written': json.loads(path.read_text()),
            'stdout': out.replace(str(path), '<portfolio>'), 'stderr': err, 'error': error}


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['name'])
def test_writer_replays_pre_extraction_results(case, monkeypatch, tmp_path, capsys):
    assert run_case(hk, case, monkeypatch, tmp_path / 'portfolio.json', capsys) == case['expected']
