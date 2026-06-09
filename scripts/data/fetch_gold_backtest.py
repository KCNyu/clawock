#!/usr/bin/env python3
"""fetch_gold_backtest.py — 母 ETF(518880 华安黄金ETF)长期定投回测，给 000217 当参照系。

kcn 的 000217 联接C 从 2026-01-22 起投、踩在金价13年最贵两周 → 现亏 -10%。这卡用母 ETF
518880 的全量历史做"每日定投200持有至今"的多起点回测(总收益 + 资金加权年化 XIRR)，让那 -10%
有个长期对照：历史上长期定投黄金年化普遍 14–26%，短期看运气、时间越长越平滑。

518880 是场内 ETF，但 NAV 历史走 fund-NAV 渠道 `api.fund.eastmoney.com/f10/lsjz` 也能取
(push2his K线接口本机被限流)。全量 ~3100 天缓存在 `.cache/`(gitignored)，每日只增量拉最新几页。

写回 portfolio.json['gold_dca']['parent_backtest']，随 gold_dca 一并进 dashboard。
由 gold_dca_refresh.sh 每日在 fetch_gold_dca.py 之后调用。
"""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

WS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(WS_ROOT, 'scripts', 'data'))
from safe_io import safe_write_json  # noqa: E402

PORTFOLIO = os.path.join(WS_ROOT, 'portfolio.json')
CACHE = os.path.join(WS_ROOT, '.cache', 'gold_etf_518880_nav.json')
FUND_CODE = '518880'
FUND_NAME = '华安黄金ETF'
DAILY = 200.0


def _page(code, p):
    url = (f'https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}'
           f'&pageIndex={p}&pageSize=20')
    for _ in range(3):
        try:
            out = subprocess.run(
                ['curl', '-s', url, '-m', '15', '-H', 'Referer: https://fundf10.eastmoney.com/'],
                capture_output=True, text=True, timeout=20).stdout
            d = json.loads(out)
            if d.get('Data'):
                return d['Data']['LSJZList'], d.get('TotalCount', 0)
        except Exception:
            pass
    return [], 0


def load_cache():
    try:
        d = json.load(open(CACHE, encoding='utf-8'))
        return d.get('nav', {})
    except Exception:
        return {}


def refresh_nav(navmap):
    """有缓存→只拉前3页增量；无缓存→并行拉全量。返回 (navmap, did_seed)。"""
    if len(navmap) > 100:
        for p in (1, 2, 3):
            lst, _ = _page(FUND_CODE, p)
            for x in lst:
                if x.get('DWJZ'):
                    navmap[x['FSRQ']] = float(x['DWJZ'])
        return navmap, False
    # seed: 先取 TotalCount，再并行拉所有页
    _, total = _page(FUND_CODE, 1)
    pages = (total // 20) + 2 if total else 160
    with ThreadPoolExecutor(max_workers=16) as ex:
        for lst, _ in ex.map(lambda p: _page(FUND_CODE, p), range(1, pages + 1)):
            for x in lst:
                if x.get('DWJZ'):
                    navmap[x['FSRQ']] = float(x['DWJZ'])
    return navmap, True


def xirr(flows):
    """flows = [(date, cashflow)]；二分求年化。"""
    d0 = flows[0][0]

    def npv(r):
        return sum(cf / ((1 + r) ** ((d - d0).days / 365.0)) for d, cf in flows)
    lo, hi = -0.99, 5.0
    mid = 0.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(mid) > 0:
            lo = mid
        else:
            hi = mid
    return mid


def backtest(series, start, last_nav):
    """series = [(date_str, nav)] 升序；每个 >=start 的交易日定投 DAILY。"""
    rows = [(d, n) for d, n in series if d >= start]
    if len(rows) < 2:
        return None
    units = sum(DAILY / n for _, n in rows)
    invested = DAILY * len(rows)
    value = units * last_nav
    flows = [(date.fromisoformat(d), -DAILY) for d, _ in rows]
    flows.append((date.fromisoformat(rows[-1][0]), value))
    return {
        'start': rows[0][0],
        'invested': round(invested),
        'value': round(value),
        'ret_pct': round((value / invested - 1) * 100, 1),
        'xirr_pct': round(xirr(flows) * 100, 1),
        'days': len(rows),
    }


def main():
    dry = '--dry-run' in sys.argv
    navmap = load_cache()
    navmap, seeded = refresh_nav(navmap)
    if len(navmap) < 100:
        print('FATAL: 净值抓取失败，缓存不足', file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    safe_write_json(CACHE, {'fundCode': FUND_CODE, 'nav': navmap,
                            'updated': datetime.now(timezone.utc).isoformat()})

    series = sorted(navmap.items())
    last_d, last_nav = series[-1]
    incep = series[0][0]
    today = date.fromisoformat(last_d)
    one_yr = (today - timedelta(days=365)).isoformat()
    targets = [
        (incep, '成立至今'),
        ('2020-01-01', '2020起'),
        ('2022-01-01', '2022起'),
        ('2023-01-01', '2023起'),
        ('2024-01-01', '2024起'),
        ('2025-01-01', '2025起'),
        (one_yr, '近1年'),
    ]
    rows = []
    for start, label in targets:
        bt = backtest(series, start, last_nav)
        if bt:
            bt['label'] = label
            rows.append(bt)

    parent = {
        'fund_code': FUND_CODE,
        'fund_name': FUND_NAME,
        'daily_amount': DAILY,
        'inception': incep,
        'last_nav': round(last_nav, 4),
        'as_of': last_d,
        'rows': rows,
        'note': '每日定投200元买母ETF 518880、持有至今的历史回测；XIRR=资金加权年化。'
                '对照你的 000217 起投点，看长期定投黄金的参照收益。',
        'updated': datetime.now(timezone.utc).isoformat(),
    }
    print(f"{FUND_NAME}({FUND_CODE}) 回测  {incep}→{last_d}  净值{last_nav:.4f}  "
          f"{'[seeded全量]' if seeded else '[增量]'} {len(series)}个交易日")
    for r in rows:
        print(f"  {r['label']:<8} 投入{r['invested']:>8,} 现值{r['value']:>8,} "
              f"收益{r['ret_pct']:>6.1f}% 年化{r['xirr_pct']:>5.1f}%")

    if dry:
        print('  [dry-run] 不写 portfolio.json')
        return 0
    pf = json.load(open(PORTFOLIO, encoding='utf-8'))
    if 'gold_dca' not in pf:
        print('  warn: portfolio.json 无 gold_dca，跳过写回(先跑 fetch_gold_dca.py)', file=sys.stderr)
        return 0
    pf['gold_dca']['parent_backtest'] = parent
    safe_write_json(PORTFOLIO, pf)
    print('  ✓ 已写回 portfolio.json gold_dca.parent_backtest')
    return 0


if __name__ == '__main__':
    sys.exit(main())
