"""Eastmoney HK batches through the shared throttled HTTP client."""
from datetime import datetime

from clawock.sessions import HKT
from .eastmoney_http import em_get
from .hk_discovery_quotes import normalize


def fetch_quotes(codes):
    response = em_get('https://push2.eastmoney.com/api/qt/ulist.np/get',
                      params={'secids': ','.join('116.' + c for c in codes), 'fltt': 2, 'invt': 2,
                              'fields': 'f12,f14,f2,f3,f6,f20,f18,f124,f100',
                              'ut': 'bd1d9ddb04089700cf9c27f6f7426281'},
                      headers={'Referer': 'https://quote.eastmoney.com/'},
                      timeout=(3, 6), retries=1, label='HK discovery batch')
    if response is None:
        raise ValueError('eastmoney_request_failed')
    if len(response.content) > 1024 * 1024:
        raise ValueError('eastmoney_response_oversize')
    rows = (response.json().get('data') or {}).get('diff')
    if not isinstance(rows, list) or not rows:
        raise ValueError('eastmoney_empty_response')
    return rows


def parse_quotes(payload, universe, now):
    rows, failed = {}, {}
    for item in payload:
        if not isinstance(item, dict) or item.get('f12') not in universe:
            continue
        ticker = item['f12']
        if ticker in rows or ticker in failed:
            rows.pop(ticker, None)
            failed[ticker] = 'duplicate_quote'
            continue
        try:
            observed = datetime.fromtimestamp(float(item['f124']), HKT)
            row = normalize(universe[ticker], observed=observed, price=item.get('f2'),
                            previous=item.get('f18'), turnover=item.get('f6'), cap=item.get('f20'),
                            change=item.get('f3'), source='eastmoney_hk', now=now)
            # Do not mix the vendor's industry taxonomy with our broad-sector map.
            if isinstance(item.get('f100'), str) and item['f100'] not in ('', '-'):
                row['vendor_industry'] = item['f100'][:160]
            rows[ticker] = row
        except (ValueError, TypeError, KeyError, OverflowError, OSError):
            failed[ticker] = 'invalid_quote_or_timestamp'
    for ticker in universe.keys() - rows.keys() - failed.keys():
        failed[ticker] = 'missing_quote'
    return rows, failed


SECTORS = {'非日常生活消费品': '可选消费', '日常消费品': '必需消费',
           '原材料': '材料', '通讯服务': '通信服务'}


def fetch_classifications(deadline):
    """Page the company metadata service separately from the quote service."""
    import time

    result, seen, missing = {}, set(), []
    expected = None
    for page in range(1, 21):
        if time.monotonic() >= deadline:
            missing.append('classification_budget_exhausted')
            break
        response = em_get('https://datacenter.eastmoney.com/securities/api/data/v1/get',
                          params={'reportName': 'RPT_HKF10_INFO_ORGPROFILE',
                                  'columns': 'SECURITY_CODE,BELONG_INDUSTRY,INDUSTRY_TYPE',
                                  'pageSize': 500, 'pageNumber': page,
                                  'sortColumns': 'SECURITY_CODE', 'sortTypes': '1'},
                          timeout=(3, 6), retries=1, label='HK classifications')
        if response is None or len(response.content) > 1024 * 1024:
            missing.append('classification_request_failed')
            break
        try:
            payload = response.json()['result']
            pages, total, rows = int(payload['pages']), int(payload['count']), payload['data']
            if not 1 <= pages <= 20 or not isinstance(rows, list) or not rows:
                raise ValueError('invalid classification page')
            if expected is not None and expected != (pages, total):
                raise ValueError('classification pagination changed')
            expected = (pages, total)
            for row in rows:
                ticker = row['SECURITY_CODE']
                if ticker in seen:
                    raise ValueError('duplicate classification ticker')
                seen.add(ticker)
                path = row.get('INDUSTRY_TYPE') or ''
                industry = row.get('BELONG_INDUSTRY') or ''
                if not isinstance(path, str) or not path or not isinstance(industry, str) or not industry:
                    continue
                sector = path.split('-')[0].strip()
                if not sector or sector == '-' or industry == '-' or max(len(sector), len(industry)) > 160:
                    continue
                result[ticker] = {'sector': SECTORS.get(sector, sector), 'industry': industry,
                                  'classification_source': 'eastmoney_company_profile'}
            if page == pages:
                if len(seen) != total:
                    raise ValueError('classification row count mismatch')
                break
        except (ValueError, KeyError, TypeError, AttributeError):
            missing.append('invalid_classification_page')
            break
    return result, {'source': 'eastmoney_company_profile', 'classified_count': len(result),
                    'missing': missing, 'pagination_complete': not missing}
