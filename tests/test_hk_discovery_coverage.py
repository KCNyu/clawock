"""Full-roster identity, failover, price-basis and safe entry-draft contracts."""
from datetime import datetime, timezone
from io import BytesIO
import json
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

from clawock.market_data import hk_discovery_universe as U, hk_discovery_scan as S
from clawock.market_data import hk_discovery_live as T, hk_discovery_eastmoney as E
from clawock.market_data.hk_discovery_quotes import reconcile
from clawock.decision import research_inbox as I, entry

CLASSIFICATIONS = E.fetch_classifications
NOW = datetime(2026, 10, 30, 10, tzinfo=timezone.utc)
META = {'ticker': '01234', 'name': 'Synthetic', 'security_type': 'ordinary_share',
        'sector': '工业', 'industry': '工业', 'board': 'main_board'}


@pytest.fixture(autouse=True)
def offline_classifications(monkeypatch):
    monkeypatch.setattr(E, 'fetch_classifications', lambda deadline: ({}, {'missing': []}))


def workbook():
    strings = ['Updated as at 30/10/2026', 'Stock Code', 'Name of Securities', 'Category',
               'Sub-Category', 'Trading Currency', 'Equity', 'Equity Securities (Main Board)',
               'Equity Securities (GEM)', 'HKD', 'CNY', 'Fund', 'ETF', 'Synthetic']
    rows = [[('A', 0)], [('A', 1), ('B', 2), ('C', 3), ('D', 4), ('Q', 5)]]
    for ticker, category, subtype, currency in [('01234', 6, 7, 9), ('08123', 6, 8, 9),
                                               ('81234', 6, 7, 10), ('03000', 11, 12, 9)]:
        strings.append(ticker)
        rows.append([('A', len(strings)-1), ('B', 13), ('C', category), ('D', subtype), ('Q', currency)])
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    xml = ''.join('<row>' + ''.join(f'<c r="{col}{n}" t="s"><v>{i}</v></c>' for col, i in row)
                  + '</row>' for n, row in enumerate(rows, 1))
    stream = BytesIO()
    with ZipFile(stream, 'w') as z:
        z.writestr('xl/sharedStrings.xml', f'<sst xmlns="{ns}">' + ''.join('<si><t>'+escape(s)+'</t></si>' for s in strings)+'</sst>')
        z.writestr('xl/worksheets/sheet1.xml', f'<worksheet xmlns="{ns}"><sheetData>{xml}</sheetData></worksheet>')
    return stream.getvalue()


def wire(stamp='2026/10/30 16:08:14', price='10'):
    cells = [''] * 46
    for i, v in {1:'Synthetic', 2:'01234', 3:price, 4:'9.9', 30:stamp, 32:'1', 37:'30000000', 45:'200'}.items():
        cells[i] = v
    return 'v_r_hk01234="' + '~'.join(cells) + '";'


def emrow(stamp='2026-10-30T16:08:14+08:00', price=10):
    return {'f12': '01234', 'f124': datetime.fromisoformat(stamp).timestamp(),
            'f2': price, 'f18': 9.9, 'f6': 30000000, 'f20': 20000000000, 'f3': 1}


def test_roster_sparse_columns_boards_and_counter_exclusions():
    rows, receipt = U.parse_roster(workbook(), {'01234': META})
    assert set(rows) == {'01234', '08123'}
    assert rows['08123']['board'] == 'gem' and rows['08123']['sector'] == '行业待核验'
    assert receipt['boards'] == {'main_board': 1, 'gem': 1}
    assert receipt['excluded'] == {'non_hkd_counter': 1, 'non_ordinary_category': 1}
    assert receipt['as_of'] == '2026-10-30'


def test_intraday_latest_trade_is_separate_from_previous_close():
    now = datetime(2026, 10, 30, 3, tzinfo=timezone.utc)
    rows, _, failed = T.parse_quotes(wire('2026/10/30 10:59:00'), {'01234': META}, now)
    assert not failed
    ev = rows[0]['quote_evidence']
    assert ev['price_basis'] == 'latest_trade' and ev['session_date'] == '2026-10-30'
    assert ev['latest_close'] == {'session_date': '2026-10-29', 'field': 'previous_close'}
    assert rows[0]['previous_close_hkd'] == 9.9
    bad, _, failed = T.parse_quotes(wire('2026/10/29 16:08:00'), {'01234': META}, now)
    assert bad[0]['quote_evidence']['price_basis'] == 'latest_completed_close'
    # Future and stale intraday prices cannot be upgraded to current quotes.
    assert not T.parse_quotes(wire('2026/10/30 11:10:00'), {'01234': META}, now)[0]


def test_dual_source_confirmation_divergence_and_failover():
    tq = T.parse_quotes(wire(), {'01234': META}, NOW)[0][0]
    eq = E.parse_quotes([emrow()], {'01234': META}, NOW)[0]['01234']
    row, reason = reconcile(tq, eq)
    assert reason is None and row['quote_evidence']['cross_check'] == 'confirmed'
    assert row['quote_evidence']['sources'] == ['tencent_hk', 'eastmoney_hk']
    bad = E.parse_quotes([emrow(price=12)], {'01234': META}, NOW)[0]['01234']
    assert reconcile(tq, bad) == (None, 'quote_divergence')
    assert reconcile(None, eq)[0]['quote_evidence']['source'] == 'eastmoney_hk'
    assert not E.parse_quotes([{**emrow(), 'f124': None}], {'01234': META}, NOW)[0]


def test_all_tencent_failure_still_scans_eastmoney_and_preserves_board_counts(monkeypatch):
    monkeypatch.setattr(S, 'fetch_roster', workbook)
    monkeypatch.setattr(T, 'fetch_quotes', lambda codes: '')
    monkeypatch.setattr(E, 'fetch_quotes', lambda codes: [emrow()])
    rows, receipt = S.acquire({'01234': META}, NOW)
    assert [r['ticker'] for r in rows] == ['01234']
    assert rows[0]['quote_evidence']['source'] == 'eastmoney_hk'
    assert receipt['requested_count'] == 2 and receipt['missing'] == {'08123': 'missing_quote'}
    assert receipt['boards']['gem'] == {'requested': 1, 'scanned': 0}
    assert receipt['sources']['tencent_hk']['valid_count'] == 0


def test_failed_eastmoney_opens_circuit_and_budget_is_explicit(monkeypatch):
    calls = []
    def fail(codes):
        calls.append(codes)
        raise ValueError('synthetic transport error')
    monkeypatch.setattr(E, 'fetch_quotes', fail)
    universe = {str(i).zfill(5): META for i in range(1, 205)}
    rows, failed = S._eastmoney(universe, NOW, float('inf'))
    assert len(calls) == 1 and len(failed) == len(universe) and not rows
    calls.clear()
    assert set(S._eastmoney(universe, NOW, 0)[1].values()) == {'request_budget_exhausted'}
    assert not calls


def test_entry_draft_never_fabricates_evidence_or_clears_gate(tmp_path):
    I.ingest(tmp_path, [{**META, 'market': 'HK', 'sector_label': '工业'}], today='2026-10-30')
    before = (tmp_path / '.cache/research-inbox.json').read_bytes()
    doc = I.draft(tmp_path, 'HK', '01234')
    assert doc['quote']['price'] is None and doc['quote']['as_of'] is None
    assert doc['evidence'] == [] and doc['verdict'] == 'gray_needs_evidence'
    assert {r['verdict'] for r in doc['checks']} == {'unknown'}
    assert entry.validate_artifact(doc)
    assert entry.decide(doc)['verdict'] == 'gray_needs_evidence'
    assert not entry.proposal_authorizations(tmp_path, today='2026-10-30')
    assert not (tmp_path / 'memory/entry-gates').exists()
    assert (tmp_path / '.cache/research-inbox.json').read_bytes() == before
    assert json.loads(json.dumps(doc)) == doc


def test_entry_draft_can_use_current_discovery_without_mutation(tmp_path, monkeypatch):
    from clawock.market_data import stock_discovery
    monkeypatch.setattr(stock_discovery, 'collect', lambda *a, **kw: {'status': 'partial', 'candidates': [{**META, 'market': 'HK'}]})
    assert I.draft(tmp_path, 'HK', '01234')['ticker'] == '01234'
    assert not (tmp_path / '.cache').exists()
    with pytest.raises(ValueError, match='not a stored or current candidate'):
        I.draft(tmp_path, 'HK', '02345')


@pytest.mark.parametrize('duplicate', [False, True])
def test_classification_pagination_and_taxonomy(monkeypatch, duplicate):
    from types import SimpleNamespace
    calls = []
    def get(url, **kwargs):
        page = kwargs['params']['pageNumber']
        calls.append(page)
        payload = {'result': {'pages': 2, 'count': 2, 'data': [{
            'SECURITY_CODE': '01234' if page == 1 or duplicate else '02345',
            'INDUSTRY_TYPE': '非日常生活消费品-零售', 'BELONG_INDUSTRY': '零售'}]}}
        return SimpleNamespace(content=b'{}', json=lambda: payload)
    monkeypatch.setattr(E, 'em_get', get)
    rows, receipt = CLASSIFICATIONS(float('inf'))
    assert calls == [1, 2]
    assert rows['01234']['sector'] == '可选消费'
    assert receipt['pagination_complete'] is not duplicate
    assert bool(receipt['missing']) is duplicate


def test_quote_timestamp_is_checked_after_network_returns(monkeypatch):
    from datetime import timedelta
    start = datetime(2026, 10, 30, 3, tzinfo=timezone.utc)
    monkeypatch.setattr(T, 'fetch_quotes', lambda codes: wire('2026/10/30 11:00:01'))
    rows, failed = S._tencent({'01234': META}, start, float('inf'), clock=lambda: start + timedelta(seconds=2))
    assert set(rows) == {'01234'} and not failed


def test_classifier_enriches_scanned_rows_before_sector_screen(monkeypatch):
    monkeypatch.setattr(S, 'fetch_roster', workbook)
    monkeypatch.setattr(T, 'fetch_quotes', lambda codes: wire())
    monkeypatch.setattr(E, 'fetch_quotes', lambda codes: [emrow()])
    monkeypatch.setattr(E, 'fetch_classifications', lambda deadline: (
        {'01234': {'sector': '信息技术', 'industry': '软件', 'classification_source': 'eastmoney_company_profile'}},
        {'missing': []}))
    rows, receipt = S.acquire({}, NOW)
    assert rows[0]['sector'] == '信息技术' and receipt['unclassified_count'] == 0
    assert rows[0]['quote_evidence']['cross_check'] == 'confirmed'


def test_more_recent_valid_secondary_basis_wins_without_false_confirmation():
    now = datetime(2026, 10, 30, 3, tzinfo=timezone.utc)
    old = T.parse_quotes(wire('2026/10/29 16:08:00'), {'01234': META}, now)[0][0]
    current = E.parse_quotes([emrow('2026-10-30T10:59:00+08:00')], {'01234': META}, now)[0]['01234']
    selected, reason = reconcile(old, current)
    assert reason == 'different_price_basis'
    assert selected['quote_evidence']['price_basis'] == 'latest_trade'
    assert selected['quote_evidence']['source'] == 'eastmoney_hk'


def test_full_source_failure_does_not_overflow_brief_context():
    from clawock.market_data.stock_discovery import compact_coverage
    full = {'market': 'all', 'candidates': [{'ticker': '01234'}], 'markets': {'HK': {
        'missing': {str(i).zfill(5): 'missing_current_session_quote' for i in range(3000)},
        'sources': {'tencent_hk': {'missing_count': 3000}}}}}
    compact = compact_coverage(full)
    assert len(json.dumps(compact).encode()) < 2000
    assert compact['markets']['HK']['missing_omitted_count'] == 2980
    assert compact['candidates'] == full['candidates']
    assert len(full['markets']['HK']['missing']) == 3000
