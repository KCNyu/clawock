"""HKEX security identity roster, with explicit board/currency exclusions."""
from collections import Counter
from datetime import datetime
from io import BytesIO
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import requests

URL = 'https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx'
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
BOARDS = {'Equity Securities (Main Board)': 'main_board', 'Equity Securities (GEM)': 'gem'}


def fetch_roster():
    with requests.get(URL, timeout=(5, 12), stream=True) as response:
        response.raise_for_status()
        raw = bytearray()
        for chunk in response.iter_content(65536):
            raw.extend(chunk)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError('HKEX roster exceeds byte budget')
    return bytes(raw)


def parse_roster(raw, overrides):
    """Read cells by column reference, never assume sparse rows are dense."""
    with ZipFile(BytesIO(raw)) as book:
        if sum(f.file_size for f in book.infolist()) > 32 * 1024 * 1024:
            raise ValueError('HKEX workbook exceeds expanded budget')
        shared = [''.join(si.itertext()) for si in ET.fromstring(book.read('xl/sharedStrings.xml'))]
        sheet = ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
    universe, excluded, counts = {}, Counter(), Counter()
    as_of = None
    header = None
    for row in sheet.findall('.//s:row', NS):
        cells = {}
        for cell in row.findall('s:c', NS):
            val = cell.find('s:v', NS)
            value = val.text if val is not None else ''
            if cell.get('t') == 's' and value:
                value = shared[int(value)]
            cells[re.sub(r'[0-9]', '', cell.get('r', ''))] = (value or '').strip()
        if cells.get('A', '').startswith('Updated as at '):
            as_of = datetime.strptime(cells['A'][14:], '%d/%m/%Y').date().isoformat()
        if cells.get('A') == 'Stock Code':
            header = {v: k for k, v in cells.items() if v}
            continue
        if not header or not re.fullmatch(r'[0-9]{5}', cells.get('A', '')):
            continue
        def field(name):
            return cells.get(header[name], '')
        board = BOARDS.get(field('Sub-Category'))
        if field('Category') != 'Equity' or not board:
            excluded['non_ordinary_category'] += 1
            continue
        if field('Trading Currency') != 'HKD':
            excluded['non_hkd_counter'] += 1
            continue
        ticker = field('Stock Code')
        if ticker in universe:
            raise ValueError('duplicate HKEX security')
        meta = overrides.get(ticker, {})
        universe[ticker] = {'ticker': ticker, 'name': field('Name of Securities'),
                            'board': board, 'security_type': 'ordinary_share',
                            'sector': meta.get('sector', '行业待核验'),
                            'industry': meta.get('industry', '行业待核验')}
        counts[board] += 1
    if not as_of or not universe or len(universe) > 6000:
        raise ValueError('invalid HKEX roster')
    return universe, {'source': 'HKEX ListOfSecurities', 'url': URL, 'as_of': as_of,
                      'scope': 'HKD ordinary equity, Main Board and GEM',
                      'boards': dict(counts), 'excluded': dict(excluded)}
