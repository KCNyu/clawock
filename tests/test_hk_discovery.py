"""Licensed HK adapter contract; fixtures are synthetic, never live recommendations."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from clawock.market_data import hk_discovery as H, stock_discovery as D
from clawock.decision import research_inbox

NOW = datetime(2026, 10, 30, 10, tzinfo=timezone.utc)
AUTH = {"schema_version": 1, "source_id": "synthetic_test", "source_name": "Synthetic test only",
        "terms_url": "https://example.test/agreement", "clause": "Synthetic clause for tests only",
        "reviewed_by": "test operator", "reviewed_on": "2026-10-29", "valid_until": "2026-11-01",
        "automated_acquisition": True, "public_derived_candidates": True, "public_security_metadata": True}
ROW = {"ticker": "01234", "name": "Synthetic Ordinary", "security_type": "ordinary_share",
       "sector": "工业", "industry": "设备", "market_cap_hkd": 20_000_000_000,
       "price_hkd": 10, "turnover_hkd": 30_000_000, "change_pct": 1}
SNAPSHOT = {"schema_version": 1, "source_id": "synthetic_test", "session_date": "2026-10-30",
            "observed_at": "2026-10-30T16:10:00+08:00", "rows": [ROW]}
BOOK = {"portfolios": {}}


def install(tmp_path):
    base = tmp_path / '.cache/hk-discovery'
    base.mkdir(parents=True)
    (base / 'authorization.json').write_text(json.dumps(AUTH))
    (base / 'snapshot.json').write_text(json.dumps(SNAPSHOT))
    (tmp_path / 'portfolio.json').write_text(json.dumps(BOOK))
    return base


def screen(snapshot=None, auth=None, book=None, registry=None):
    return H.screen_snapshot(snapshot or SNAPSHOT, auth or AUTH, book or BOOK, registry or {},
                             now=NOW, receipt_hash='fixture')


def test_screen_excludes_holdings_underlying_nonordinary_and_sector_caps():
    snap = deepcopy(SNAPSHOT)
    snap['rows'] = [{**ROW, 'ticker': ticker, **extra} for ticker, extra in [
        ('01234', {}), ('02345', {}), ('03456', {'sector': '科技'}),
        ('04567', {'security_type': 'etf'}), ('05678', {}), ('06789', {})]]
    book = {'portfolios': {'HK': {'holdings': [{'ticker': '05678', 'shares': 10}]}}}
    result = screen(snap, book=book, registry={'05678': {'underlying': '06789'}})
    assert [r['ticker'] for r in result['candidates']] == ['01234', '03456']
    assert result['rejections'] == {'security_type': 1, 'held_or_underlying': 2}
    assert all(r['allowed'] is False for r in result['candidates'])
    encoded = json.dumps(result)
    assert 'snapshot_metrics' not in encoded and '30000000' not in encoded
    assert result['source']['clause'] == AUTH['clause']


@pytest.mark.parametrize('key,value', [('automated_acquisition', False), ('public_derived_candidates', False),
                                      ('public_security_metadata', False), ('valid_until', '2026-10-29'),
                                      ('reviewed_on', '2026-11-01'), ('clause', '')])
def test_permission_failure_does_not_read_snapshot(tmp_path, key, value):
    base = install(tmp_path)
    (base / 'authorization.json').write_text(json.dumps({**AUTH, key: value}))
    (base / 'snapshot.json').write_text('{broken')
    assert H.collect(tmp_path, now=NOW)['reason_code'] == 'redistribution_permission_missing'


@pytest.mark.parametrize('patch', [{'session_date': '2026-10-29'}, {'source_id': 'other'}, {'rows': []},
                                  {'observed_at': '2026-10-30T15:00:00+08:00'},
                                  {'observed_at': '2026-10-30T19:00:00+08:00'},
                                  {'rows': [{**ROW, 'turnover_hkd': None}]}])
def test_invalid_feed_is_unavailable_not_empty_screen(tmp_path, patch):
    base = install(tmp_path)
    (base / 'snapshot.json').write_text(json.dumps({**SNAPSHOT, **patch}))
    assert H.collect(tmp_path, now=NOW)['reason_code'] == 'authorized_snapshot_invalid'


def test_valid_empty_screen_distinct_from_missing_permission():
    result = screen({**SNAPSHOT, 'rows': [{**ROW, 'turnover_hkd': 1}]})
    assert result['status'] == 'no_candidates'
    assert not result['candidates']


def test_combined_us_failure_still_delivers_hk_to_inbox_and_render(tmp_path, monkeypatch):
    install(tmp_path)
    original = H.collect
    monkeypatch.setattr(H, 'collect', lambda workspace: original(workspace, now=NOW))
    # Unconfigured US still permits HK to flow through the actual combined entry.
    combined = D.collect(tmp_path, market='all')
    assert combined['status'] == 'ok' and combined['market'] == 'all'
    assert combined['markets']['HK']['status'] == 'ok'
    attached = research_inbox.attach(tmp_path, combined, today='2026-10-30')
    assert attached['inbox']['rows'][0]['market'] == 'HK'
    assert '01234' in '\n'.join(D.candidate_lines(attached))
    assert '01234' in '\n'.join(D.candidate_lines(combined['markets']['HK']))
    assert '原始行情' in '\n'.join(D.candidate_lines(attached))
    # An actual US request failure must not mask a healthy HK result.
    config = tmp_path / 'config'
    config.mkdir()
    from pathlib import Path
    (config / 'stock-discovery.json').write_text((Path(__file__).parents[1] / 'config/stock-discovery.json').read_text())
    def fail():
        raise TimeoutError()
    combined = D.collect(tmp_path, market='all', fetcher=fail)
    assert combined['status'] == 'ok'
    assert combined['markets']['US']['status'] == 'unavailable'
    assert '未取到' in '\n'.join(D.candidate_lines(combined))


def test_hk_candidate_survives_packet_and_report_projection():
    from clawock.decision import packet
    from clawock.harness import brief_render
    result = screen()
    compiled = packet.compile_packet({'date': '2026-10-30', 'portfolio': BOOK,
                                      'stock_discovery': result}, generation_id='hk-test')
    candidate = compiled['stock_discovery']['candidates'][0]
    assert candidate['market'] == 'HK' and candidate['allowed'] is False
    assert candidate['proposal_availability']['status'] == 'unavailable'
    assert '01234' in brief_render.stock_discovery_section(compiled)
