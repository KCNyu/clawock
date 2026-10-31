"""Bounded HK ordinary-share discovery using the desk's Tencent quote route.

Raw fields stay in memory. This adapter makes no claim of a vendor license.
"""
from datetime import datetime
from pathlib import Path
import re

import requests

from clawock.safe_io import to_finite_number
from clawock.sessions import HKT, HK_HALF_DAYS, latest_completed_session
from .hk_discovery import _read, _screen, _text

SOURCE = {"source_id": "tencent_hk", "source_name": "Tencent qt.gtimg.cn",
          "metadata_source": "config/hk-discovery-universe.json"}


def fetch_quotes(codes):
    """One bounded batch on the existing HK quote endpoint; no raw cache."""
    response = requests.get('https://qt.gtimg.cn/q=' + ','.join('r_hk' + c for c in codes),
                            timeout=(5, 12), stream=True)
    with response:
        response.raise_for_status()
        raw = bytearray()
        for chunk in response.iter_content(16384):
            raw.extend(chunk)
            if len(raw) > 1024 * 1024:
                raise ValueError('quote response exceeds byte budget')
    return raw.decode('gbk')


def parse_quotes(text, universe, now):
    """HK wire: 3 price, 32 change %, 37 turnover HKD, 45 cap in HKD 100m."""
    session = latest_completed_session('HK', at=now)
    if session is None:
        raise ValueError('unknown HK session')
    rows, stamps, failed = {}, {}, {}
    close_hour = 12 if session.isoformat() in HK_HALF_DAYS else 16
    for line in text.splitlines():
        match = re.fullmatch(r'v_(?:r_)?hk([0-9]{5})="([^"\n]*)";?', line.strip())
        if not match or match[1] not in universe:
            continue
        ticker = match[1]
        if ticker in rows or ticker in failed:
            rows.pop(ticker, None)
            failed[ticker] = 'duplicate_quote'
            continue
        try:
            cells = match[2].split('~')
            if cells[2] != ticker:
                raise ValueError('identity mismatch')
            observed = datetime.strptime(cells[30], '%Y/%m/%d %H:%M:%S').replace(tzinfo=HKT)
            if observed > now or observed.date() != session or observed.hour < close_hour:
                failed[ticker] = 'missing_latest_completed_close'
                continue
            values = [to_finite_number(cells[i]) for i in (3, 32, 37, 45)]
            if any(v is None for v in values) or any(values[i] <= 0 for i in (0, 3)) or values[2] < 0:
                raise ValueError('invalid screening metrics')
            price, change, turnover, cap = values
            rows[ticker] = {**universe[ticker], 'name': _text({'name': cells[1]}, 'name'),
                            'price_hkd': price, 'change_pct': change,
                            'turnover_hkd': turnover, 'market_cap_hkd': cap * 100_000_000}
            stamps[ticker] = observed.isoformat()
        except (IndexError, ValueError, TypeError):
            failed[ticker] = 'invalid_quote'
    for ticker in universe.keys() - rows.keys() - failed.keys():
        failed[ticker] = 'missing_quote'
    return list(rows.values()), stamps, failed


def collect_live(workspace, *, now):
    from clawock.instruments import load_registry
    from .discovery_common import excluded_exposure

    result = {'schema_version': 1, 'market': 'HK', 'research_only': True,
              'status': 'incomplete', 'candidates': [], 'generated_at': now.isoformat(),
              'source': dict(SOURCE), 'publication': 'derived_candidates_and_security_metadata_only',
              'coverage': 'curated_ordinary_shares_not_full_market'}
    try:
        config, _ = _read(Path(workspace) / 'config/hk-discovery-universe.json')
        if config.get('schema_version') != 1 or not 1 <= len(config['securities']) <= 100:
            raise ValueError('invalid universe')
        universe = {}
        for row in config['securities']:
            ticker = _text(row, 'ticker')
            if not re.fullmatch(r'[0-9]{5}', ticker) or ticker == '00000' or ticker in universe:
                raise ValueError('invalid universe ticker')
            if row.get('security_type') != 'ordinary_share':
                raise ValueError('nonordinary universe entry')
            universe[ticker] = {k: _text(row, k) for k in ('ticker', 'sector', 'industry', 'security_type')}
        portfolio, _ = _read(Path(workspace) / 'portfolio.json')
        registry = load_registry(Path(workspace) / 'config/instruments.json', missing_ok=True)
        excluded_exposure(portfolio, registry)  # Fail closed before network on unknown exposure.
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {**result, 'reason_code': 'invalid_discovery_inputs',
                'degraded': ['港股发现缺少有效股票池、持仓或底层暴露元数据']}
    try:
        rows, stamps, failed = parse_quotes(fetch_quotes(list(universe)), universe, now)
    except (requests.RequestException, ValueError, TypeError):
        return {**result, 'reason_code': 'quote_source_failed',
                'degraded': ['Tencent 港股批量行情失败；未完成筛选']}
    result['missing'] = failed
    result['requested_count'] = len(universe)
    if not rows:
        return {**result, 'reason_code': 'no_usable_closing_quotes', 'scanned_count': 0,
                'degraded': ['Tencent 港股缺少可用收盘报价：' + ', '.join(sorted(failed))]}
    snapshot = {'session_date': latest_completed_session('HK', at=now).isoformat(),
                'observed_at': min(stamps[r['ticker']] for r in rows), 'rows': rows}
    screened = _screen(snapshot, SOURCE, portfolio, registry, now=now)
    result.update(screened)
    for candidate in result['candidates']:
        candidate['evidence']['observed_at'] = stamps[candidate['ticker']]
    # The curated pool is useful but never a complete market scan.
    result['status'] = 'partial'
    result['degraded'] = ['港股仅覆盖配置的跨行业普通股池，非全市场扫描']
    if failed:
        result['degraded'].append('Tencent 港股缺失或无效收盘报价：' + ', '.join(sorted(failed)))
    return result
