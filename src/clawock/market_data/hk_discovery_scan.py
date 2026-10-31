"""Bounded full-roster quote acquisition; no raw prices leave the screening layer."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import time

from clawock.sessions import HKT
from . import hk_discovery_eastmoney as eastmoney, hk_discovery_live as tencent
from .hk_discovery_quotes import reconcile
from .hk_discovery_universe import fetch_roster, parse_roster

BATCH_SIZE = 100
QUOTE_BUDGET_SECONDS = 35


def _tencent(universe, now, deadline, clock=None):
    codes = list(universe)
    batches = [codes[i:i + BATCH_SIZE] for i in range(0, len(codes), BATCH_SIZE)]
    def batch(codes):
        if time.monotonic() >= deadline:
            return {}, {c: 'request_budget_exhausted' for c in codes}
        subset = {c: universe[c] for c in codes}
        try:
            text = tencent.fetch_quotes(codes)
            rows, _, failed = tencent.parse_quotes(text, subset, clock() if clock else now)
            return {r['ticker']: r for r in rows}, failed
        except Exception:
            return {}, {c: 'tencent_request_failed' for c in codes}
    rows, failed = {}, {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for good, bad in pool.map(batch, batches):
            rows.update(good)
            failed.update(bad)
    return rows, failed


def _eastmoney(universe, now, deadline, clock=None):
    rows, failed = {}, {}
    codes = list(universe)
    reason = None
    for i in range(0, len(codes), BATCH_SIZE):
        batch = codes[i:i + BATCH_SIZE]
        if reason or time.monotonic() >= deadline:
            reason = reason or 'request_budget_exhausted'
            failed.update({c: reason for c in batch})
            continue
        try:
            payload = eastmoney.fetch_quotes(batch)
            good, bad = eastmoney.parse_quotes(payload, {c: universe[c] for c in batch}, clock() if clock else now)
            rows.update(good)
            failed.update(bad)
        except Exception:
            # One transport failure opens the circuit for this run; no retry storm.
            reason = 'eastmoney_request_failed'
            failed.update({c: reason for c in batch})
    return rows, failed


def acquire(overrides, now, *, clock=None):
    degraded = []
    try:
        universe, roster = parse_roster(fetch_roster(), overrides)
        stamp = date.fromisoformat(roster['as_of'])
        today = now.astimezone(HKT).date()
        if stamp < today - timedelta(days=7) or stamp > today + timedelta(days=7):
            raise ValueError('stale or implausibly future roster')
        if stamp > today:
            degraded.append('HKEX 名录为预告版本 ' + roster['as_of'] + '；新增证券须有有效报价才能入选')
    except Exception:
        universe = {t: {**r, 'board': 'unverified'} for t, r in overrides.items()}
        roster = {'source': 'configured_fallback', 'scope': 'curated_fallback_not_full_market',
                  'boards': {'unverified': len(universe)}}
        degraded.append('HKEX 全市场名录读取失败；仅扫描配置的备用股票池，非全市场')
    deadline = time.monotonic() + QUOTE_BUDGET_SECONDS
    with ThreadPoolExecutor(max_workers=3) as pool:
        primary = pool.submit(_tencent, universe, now, deadline, clock)
        secondary = pool.submit(_eastmoney, universe, now, deadline, clock)
        metadata = pool.submit(eastmoney.fetch_classifications, deadline)
        tq, tf = primary.result()
        eq, ef = secondary.result()
        try:
            classifications, classification_receipt = metadata.result()
        except Exception:
            classifications, classification_receipt = {}, {
                "source": "eastmoney_company_profile", "missing": ["classification_request_failed"]}
    if classification_receipt["missing"]:
        degraded.append("东财行业元数据不完整：" + ", ".join(classification_receipt["missing"]))
    rows, missing, discrepancies = [], {}, {}
    for ticker in universe:
        row, disagreement = reconcile(tq.get(ticker), eq.get(ticker))
        if disagreement:
            discrepancies[ticker] = disagreement
        if row:
            row.update(classifications.get(ticker, {}))
            row["quote_evidence"]["classification_source"] = row.get("classification_source",
                "configured_metadata" if row["sector"] != "行业待核验" else "missing")
            rows.append(row)
        else:
            missing[ticker] = disagreement or tf.get(ticker, ef.get(ticker, 'missing_quote'))
    providers = {
        'tencent_hk': {'valid_count': len(tq), 'missing_count': len(tf), 'reasons': dict(Counter(tf.values()))},
        'eastmoney_hk': {'valid_count': len(eq), 'missing_count': len(ef), 'reasons': dict(Counter(ef.values()))},
    }
    for provider, stats in providers.items():
        if stats['missing_count']:
            degraded.append(f"{provider} 缺少有效报价 {stats['missing_count']}/{len(universe)}；" +
                            ', '.join(stats['reasons']))
    if discrepancies:
        degraded.append(f'双源口径或报价分歧 {len(discrepancies)} 票，逐票原因见 discrepancies')
    if missing:
        degraded.append(f'双源合并后 {len(missing)} 票未完成筛选，逐票原因见 missing')
    unknown = sum(r['sector'] == '行业待核验' for r in rows)
    if unknown:
        degraded.append(f'{unknown} 票缺少已核验行业，统一归入待核验组、最多入选一票')
    boards = {board: {'requested': sum(r['board'] == board for r in universe.values()),
                      'scanned': sum(r['board'] == board for r in rows)}
              for board in sorted({r['board'] for r in universe.values()})}
    return rows, {'roster': roster, 'requested_count': len(universe), 'boards': boards,
                  'coverage': 'hkex_hkd_equity_roster' if roster['source'] != 'configured_fallback' else roster['scope'],
                  'sources': providers, 'classifications': classification_receipt, 'missing': missing, 'discrepancies': discrepancies,
                  'unclassified_count': unknown, 'degraded': degraded}
