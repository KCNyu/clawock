#!/usr/bin/env python3
"""fetch_gold_dca.py — 黄金定投盯盘：每日刷 000217 净值 + 重算定投指标。

标的：华安黄金ETF联接C (000217)，场外基金，一天一个净值（约 20:00–23:00 HKT 出）。
跟踪同一份黄金 (母 ETF 518880)，但 C 类有自己的净值刻度 + 销售服务费拖累。

Ground truth = portfolio.json['gold_dca'] 里的两个字段，kcn 按真实账户对账后手填：
  - principal_invested : 累计投入本金（元）
  - units_held         : 当前持有份额
本脚本【绝不】改这两个真值，只：
  1. 拉最新净值 + 近 ~150 交易日历史（api.fund.eastmoney.com/f10/lsjz，稳定渠道）
  2. 拉实时估值（fundgz，净值未出时的当日估算，仅展示用）
  3. 重算 avg_cost / 现值 / 盈亏 / 回本门槛 / 定投摊薄预测 / 区间高低
  4. merge-not-overwrite 写回 portfolio.json

一天刷一次即可，无 LLM、无 API key。延续记忆：
  - openclaw-fetcher-merge-not-overwrite（抓空保留旧值，绝不整文件覆盖真值）
  - openclaw-fx-rule（人民币这笔独立成卡，不并入跨币种总额）

用法：
  python3 scripts/data/fetch_gold_dca.py            # 刷新并写回 portfolio.json
  python3 scripts/data/fetch_gold_dca.py --dry-run  # 只打印，不写盘
"""
import json
import subprocess
import sys
import os
from datetime import date, datetime, timezone

WS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(WS_ROOT, 'scripts', 'data'))
from safe_io import safe_write_json  # noqa: E402

PORTFOLIO = os.path.join(WS_ROOT, 'portfolio.json')

# 真值字段：merge 时永不被派生计算覆盖
GROUND_TRUTH_FIELDS = {
    'fund_code', 'fund_name', 'currency', 'daily_amount', 'start_date',
    'principal_invested', 'units_held', 'principal_note',
}

# 首次运行若 portfolio.json 无 gold_dca，用这套 seed（kcn 2026-06-09 对账）
SEED = {
    'fund_code': '000217',
    'fund_name': '华安黄金ETF联接C',
    'currency': 'CNY',
    'daily_amount': 200,
    'start_date': '2026-01-22',
    'principal_invested': 17299.0,
    'units_held': 4854.55,
    'principal_note': ('真实账户为准。2026-06-09 kcn 对账：现值 15470 + 盈亏 -1829 '
                       '→ 本金 17299，份额 = 15470/净值3.1867 = 4854.55。'
                       '补投/赎回后手动更新 principal_invested + units_held 这两个值即可，'
                       '其余字段 fetch_gold_dca.py 每日自动重算。'),
}

HISTORY_PAGES = 8     # 8×20 = 160 交易日，够画迷你图 + 取区间高低
HISTORY_KEEP = 140    # 写回 portfolio.json 的最大点数（控体积）


def _curl(url, referer):
    for _ in range(4):
        try:
            out = subprocess.run(
                ['curl', '-s', url, '-m', '15', '-H', f'Referer: {referer}'],
                capture_output=True, text=True, timeout=20).stdout
            if out and len(out) > 40:
                return out
        except Exception:
            pass
    return ''


def fetch_nav_history(code, pages=HISTORY_PAGES):
    """返回 [(date, nav, change_pct)] 升序。抓空返回 []（调用方保留旧值）。"""
    rows = {}
    for p in range(1, pages + 1):
        url = (f'https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}'
               f'&pageIndex={p}&pageSize=20')
        raw = _curl(url, 'https://fundf10.eastmoney.com/')
        try:
            d = json.loads(raw)
            lst = (d.get('Data') or {}).get('LSJZList') or []
        except Exception:
            lst = []
        if not lst:
            break
        for x in lst:
            if x.get('DWJZ'):
                rows[x['FSRQ']] = (float(x['DWJZ']),
                                   float(x['JZZZL']) if x.get('JZZZL') not in (None, '') else None)
    return [(dt, v[0], v[1]) for dt, v in sorted(rows.items())]


def fetch_realtime(code):
    """fundgz 实时估值；净值未出时的当日估算，仅展示。返回 dict 或 None。"""
    raw = _curl(f'https://fundgz.1234567.com.cn/js/{code}.js', 'https://fund.eastmoney.com/')
    if 'jsonpgz(' not in raw:
        return None
    try:
        payload = raw[raw.index('(') + 1: raw.rindex(')')]
        d = json.loads(payload)
        return {
            'est_nav': float(d['gsz']),
            'est_change_pct': float(d['gszzl']),
            'est_time': d.get('gztime'),
            'nav_date': d.get('jzrq'),
        }
    except Exception:
        return None


def trading_days_since(history, start):
    return sum(1 for dt, _, _ in history if dt >= start)


def project_dca(units, principal, nav, daily, horizons=(20, 40, 60, 120, 250)):
    """假设金价原地不动、继续每日定投 daily 元，平均成本/回本门槛如何下移。"""
    out = []
    for k in horizons:
        u = units + (daily / nav) * k
        p = principal + daily * k
        avg = p / u
        out.append({
            'days': k,
            'invested': round(p, 2),
            'avg_cost': round(avg, 4),
            'pnl_pct': round((u * nav / p - 1) * 100, 2),
            'breakeven_upside_pct': round((avg / nav - 1) * 100, 2),
        })
    return out


def compute(gold, history, realtime):
    principal = float(gold['principal_invested'])
    units = float(gold['units_held'])
    daily = float(gold.get('daily_amount', 200))
    start = gold.get('start_date', '')

    # 净值：优先用已公布的最新历史净值；历史抓空则沿用 portfolio 里的旧 nav
    if history:
        nav_date, nav, nav_chg = history[-1]
    else:
        nav, nav_date, nav_chg = float(gold.get('nav') or 0), gold.get('nav_date'), gold.get('nav_change_pct')

    avg_cost = principal / units if units else 0
    value = units * nav
    pnl = value - principal
    pnl_pct = (pnl / principal * 100) if principal else 0
    breakeven_upside = ((avg_cost / nav - 1) * 100) if nav else 0

    win = [(d, n, c) for d, n, c in history if d >= start] if start else history
    hi = max(win, key=lambda r: r[1]) if win else None
    lo = min(win, key=lambda r: r[1]) if win else None

    derived = {
        'nav': round(nav, 4),
        'nav_date': nav_date,
        'nav_change_pct': nav_chg,
        'realtime': realtime,
        'avg_cost': round(avg_cost, 4),
        'current_value': round(value, 2),
        'pnl_abs': round(pnl, 2),
        'pnl_percent': round(pnl_pct, 2),
        'breakeven_nav': round(avg_cost, 4),
        'breakeven_upside_pct': round(breakeven_upside, 2),
        'days_invested': trading_days_since(history, start) if start else len(history),
        'installments_est': round(principal / daily) if daily else None,
        'window_high': {'date': hi[0], 'nav': round(hi[1], 4)} if hi else None,
        'window_low': {'date': lo[0], 'nav': round(lo[1], 4)} if lo else None,
        'projection': project_dca(units, principal, nav, daily) if nav else [],
        'nav_history': [[d, round(n, 4)] for d, n, _ in history[-HISTORY_KEEP:]],
        'last_updated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
    }
    return derived


def main():
    dry = '--dry-run' in sys.argv
    pf = json.load(open(PORTFOLIO, encoding='utf-8'))
    gold = pf.get('gold_dca')
    if not gold:
        print('  gold_dca 不存在，seed 初始化', file=sys.stderr)
        gold = dict(SEED)

    code = gold['fund_code']
    history = fetch_nav_history(code)
    realtime = fetch_realtime(code)
    if not history and not gold.get('nav'):
        print('FATAL: 净值历史抓空且无旧值可用，放弃写盘', file=sys.stderr)
        return 1
    if not history:
        print('  warn: 净值历史抓空，沿用 portfolio 里旧 nav（merge-not-overwrite）', file=sys.stderr)

    derived = compute(gold, history, realtime)

    # merge：真值字段原样保留，派生字段更新；nav_history 抓空时不清空
    merged = {k: gold[k] for k in GROUND_TRUTH_FIELDS if k in gold}
    if not history and gold.get('nav_history'):
        derived['nav_history'] = gold['nav_history']
    merged.update(derived)

    g = merged
    print(f"{g['fund_name']} ({g['fund_code']})  净值 {g['nav']} ({g.get('nav_date')})  "
          f"日涨跌 {g.get('nav_change_pct')}%")
    print(f"  投入 {g['principal_invested']:,.0f}  现值 {g['current_value']:,.0f}  "
          f"盈亏 {g['pnl_abs']:+,.0f} ({g['pnl_percent']:+.2f}%)")
    print(f"  平均成本 {g['avg_cost']}  回本需涨 {g['breakeven_upside_pct']:+.2f}%  "
          f"已投 {g['days_invested']} 个交易日 / ~{g['installments_est']} 笔")
    if g.get('realtime'):
        rt = g['realtime']
        print(f"  实时估值 {rt['est_nav']} ({rt['est_change_pct']:+.2f}%) @ {rt.get('est_time')}")

    if dry:
        print('  [dry-run] 不写盘')
        return 0

    pf['gold_dca'] = merged
    safe_write_json(PORTFOLIO, pf)
    print(f"  ✓ 已写回 {PORTFOLIO}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
