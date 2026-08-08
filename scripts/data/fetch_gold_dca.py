#!/usr/bin/env python3
"""fetch_gold_dca.py — 黄金定投盯盘：每日刷 000217 净值 + 重算定投指标。

标的：华安黄金ETF联接C (000217)，场外基金，一天一个净值（约 20:00–23:00 HKT 出）。
跟踪同一份黄金 (母 ETF 518880)，但 C 类有自己的净值刻度 + 销售服务费拖累。

对账基线 = portfolio.json['gold_dca'] 里 kcn 按真实账户填的三个字段：
  - principal_invested : 对账日的累计投入本金（元）
  - units_held         : 对账日的持有份额
  - reconciled_date    : 这两个数字截止到哪天（含当天）
之后每个 A 股交易日，本脚本【自动】按当日净值 +daily_amount（默认200）累加估算
（principal_effective / units_effective），所以你天天定投也能自动跟上。每隔几周用真实
账户报一次新数字 + 更新 reconciled_date，自动累加部分即归零重算（消除 T+1/跳过的累积偏差）。
本脚本【绝不】改这三个基线字段，只：
  1. 拉最新净值 + 近 ~150 交易日历史（api.fund.eastmoney.com/f10/lsjz，稳定渠道）
  2. 拉实时估值（fundgz，净值未出时的当日估算，仅展示用）
  3. 拉上金所 Au99.99 同日收盘，映射真持仓的国内金/伦敦金回本价
  4. 重算 avg_cost / 现值 / 盈亏 / 回本门槛 / 定投摊薄预测 / 区间高低
  5. merge-not-overwrite 写回 portfolio.json

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
import bisect
from datetime import date, datetime, timezone
from pathlib import Path

GRAMS_PER_OZ = 31.1035  # 1 金衡盎司(troy oz) = 31.1035 克

WS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(WS_ROOT, 'scripts', 'data'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from clawock.safe_io import safe_write_json  # noqa: E402
from _em_http import em_get  # noqa: E402  东财统一请求节流出口

PORTFOLIO = os.path.join(WS_ROOT, 'portfolio.json')

# 对账基线字段：merge 时永不被派生计算覆盖
GROUND_TRUTH_FIELDS = {
    'fund_code', 'fund_name', 'currency', 'daily_amount', 'start_date',
    'principal_invested', 'units_held', 'reconciled_date', 'principal_note',
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
    'reconciled_date': '2026-06-09',
    'principal_note': ('对账基线（自动累加模式）。2026-06-09 kcn 对账：现值 15470 + 盈亏 -1829 '
                       '→ 本金 17299，份额 = 15470/净值3.1867 = 4854.55。此后每个 A 股交易日'
                       '自动 +200@当日净值。补投对账：把 principal_invested/units_held 改成新的'
                       '真实数字、reconciled_date 改成对账当天即可，自动累加归零重算。'),
}

HISTORY_PAGES = 8     # 8×20 = 160 交易日，够画迷你图 + 取区间高低
HISTORY_KEEP = 140    # 写回 portfolio.json 的最大点数（控体积）
XAU_SETTLEMENT_DAYS = 5
XAU_SETTLED_DRIFT_PCT = 0.3
XAU_PRIMARY_SOURCE = 'sina_global_futures_xau'
XAU_FALLBACK_SOURCE = 'eastmoney_gc00y_fallback'


def _curl(url, referer):
    for _ in range(4):
        try:
            # errors='replace'：gtimg 等源名字段是 GBK，UTF-8 严格解码会抛异常被吞成空串；
            # 数值字段全是 ASCII，replace 不影响解析（只有中文名变成替换符）。
            out = subprocess.run(
                ['curl', '-sL', url, '-m', '15', '-H', f'Referer: {referer}'],
                capture_output=True, text=True, errors='replace', timeout=20).stdout
            if out and len(out) > 40:
                return out
        except Exception:
            pass
    return ''


def _em_text(url, referer, *, params=None, label='gold DCA'):
    """Eastmoney text response through the shared serialized anti-ban client."""
    r = em_get(url, params=params, headers={'Referer': referer}, timeout=15,
               label=label)
    return r.text if r is not None else ''


def fetch_nav_history(code, pages=HISTORY_PAGES):
    """返回 [(date, nav, change_pct)] 升序。抓空返回 []（调用方保留旧值）。"""
    rows = {}
    for p in range(1, pages + 1):
        raw = _em_text(
            'https://api.fund.eastmoney.com/f10/lsjz',
            'https://fundf10.eastmoney.com/',
            params={'fundCode': code, 'pageIndex': p, 'pageSize': 20},
            label=f'gold NAV page {p}',
        )
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
    raw = _em_text(f'https://fundgz.1234567.com.cn/js/{code}.js',
                   'https://fund.eastmoney.com/', label='gold realtime estimate')
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


def _market_number(value):
    text = str(value or '').strip().replace(',', '').replace('%', '')
    if text in ('', '-'):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fetch_au9999_daily(day):
    """上金所 Au99.99 每日交易行情，元/克。

    用基金最新净值日查同一交易日，避免周末或净值晚发时把
    不同日的国内金价与基金净值硬对齐。抓空返回 None，调用方
    merge-not-overwrite 保留上次有效值。
    """
    if not day:
        return None
    url = ('https://www.sge.com.cn/sjzx/quotation_daily_new'
           f'?start_date={day}&end_date={day}')
    raw = _curl(url, 'https://www.sge.com.cn/')
    if 'Au99.99' not in raw:
        return None
    try:
        import re
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', raw, flags=re.I | re.S)
        row = next(r for r in rows if re.search(r'>\s*Au99\.99\s*<', r))
        cells = [re.sub(r'<[^>]+>', '', cell).strip()
                 for cell in re.findall(r'<td[^>]*>(.*?)</td>', row, flags=re.I | re.S)]
        # 页面把旧「序号」td 放在 HTML 注释里，宽松 HTML 解析仍可能读到；
        # 以合约列为锚点，不假设序号是否出现。
        symbol_idx = cells.index('Au99.99')
        if symbol_idx < 1 or len(cells) < symbol_idx + 8:
            return None
        close = _market_number(cells[symbol_idx + 4])
        if close is None or close <= 0:
            return None
        return {
            'symbol': 'Au99.99',
            'price_cny_g': close,
            'date': cells[symbol_idx - 1],
            'open_cny_g': _market_number(cells[symbol_idx + 1]),
            'high_cny_g': _market_number(cells[symbol_idx + 2]),
            'low_cny_g': _market_number(cells[symbol_idx + 3]),
            'change_pct': _market_number(cells[symbol_idx + 6]),
            'weighted_avg_cny_g': _market_number(cells[symbol_idx + 7]),
            'source': 'sge_quotation_daily_new',
            'fetched_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
        }
    except (StopIteration, IndexError, ValueError):
        return None


# ───────────────────────── 伦敦金（XAU）类比口径 ─────────────────────────
# kcn 日常看的是伦敦金现货趋势 → 把这笔人民币基金折算成「等于多少克/盎司黄金」+
# 「伦敦金 vs 你的基金」起投归一对比线。国内真基准另取上金所
# Au99.99 每日行情。国际口径三个源（都无 key）：
#   · 现价/涨跌/高低 = 腾讯 hf_XAU（真·伦敦金现货，稳）
#   · USDCNY        = frankfurter（ECB 日频，带历史）
#   · 历史日线      = 新浪 GlobalFutures XAU（真·伦敦金现货日线，回溯 2006）；东财 GC00Y 兜底
# 任一抓空 → compute_london 返回旧 london（merge-not-overwrite，绝不清空真值/旧线）。

def fetch_london_spot():
    """腾讯 hf_XAU 伦敦金现货。返回 dict 或 None。
    字段: v_hf_XAU="现价,涨跌%,_,_,高,低,时间,昨收,...,日期,名称" """
    raw = _curl('https://qt.gtimg.cn/q=hf_XAU', 'https://gu.qq.com')
    if 'hf_XAU=' not in raw:
        return None
    try:
        body = raw[raw.index('"') + 1: raw.rindex('"')]
        f = body.split(',')
        return {
            'xau_usd': float(f[0]),
            'change_pct': float(f[1]) if f[1] not in ('', None) else None,
            'high': float(f[4]) if len(f) > 4 and f[4] else None,
            'low': float(f[5]) if len(f) > 5 and f[5] else None,
            'prev_close': float(f[7]) if len(f) > 7 and f[7] else None,
            'date': f[12] if len(f) > 12 else None,
        }
    except Exception:
        return None


def fetch_usdcny(start):
    """frankfurter USD→CNY：当前值 + start..今天 历史。返回 (cur, {date: rate}) 或 (None, {})。"""
    today = date.today().isoformat()
    cur, hist = None, {}
    raw = _curl('https://api.frankfurter.app/latest?from=USD&to=CNY',
                'https://www.frankfurter.app/')
    try:
        cur = float(json.loads(raw)['rates']['CNY'])
    except Exception:
        cur = None
    if start:
        rawh = _curl(f'https://api.frankfurter.app/{start}..{today}?from=USD&to=CNY',
                     'https://www.frankfurter.app/')
        try:
            for d, r in json.loads(rawh).get('rates', {}).items():
                if r.get('CNY'):
                    hist[d] = float(r['CNY'])
        except Exception:
            pass
    if cur is None and hist:
        cur = hist[max(hist)]
    return cur, hist


def fetch_xau_history(start):
    """伦敦金现货 XAU 日线收盘，返回 ([(date, usd)], source metadata)。

    主源 = 新浪全球期货（真·伦敦金现货，回溯 2006，稳）；兜底 = 东财 101.GC00Y（COMEX 连续，会限流）。"""
    s = start or ''
    # ① 新浪 GlobalFutures XAU
    raw = _curl('https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var_=/'
                'GlobalFuturesService.getGlobalFuturesDailyKLine?symbol=XAU',
                'https://finance.sina.com.cn')
    try:
        import re
        m = re.search(r'(\[.*\])', raw, re.S)
        arr = json.loads(m.group(1)) if m else []
        out = [(x['date'], float(x['close'])) for x in arr
               if x.get('date', '') >= s and x.get('close')]
        if out:
            out = sorted(out)
            return out, {'name': XAU_PRIMARY_SOURCE, 'points': len(out)}
    except Exception:
        pass
    # ② 兜底 东财 GC00Y（限流时退避重试）
    raw = _em_text(
        'https://push2his.eastmoney.com/api/qt/stock/kline/get',
        'https://quote.eastmoney.com/',
        params={'secid': '101.GC00Y', 'fields1': 'f1', 'fields2': 'f51,f53',
                'klt': 101, 'fqt': 1, 'end': '20991231', 'lmt': 200},
        label='gold XAU history fallback',
    )
    try:
        kl = (json.loads(raw).get('data') or {}).get('klines') or []
    except Exception:
        kl = []
    if kl:
        out = sorted((p[0], float(p[1])) for p in (r.split(',') for r in kl)
                     if len(p) >= 2 and p[0] >= s and p[1])
        return out, {'name': XAU_FALLBACK_SOURCE, 'points': len(out)}
    return [], {'name': 'unavailable', 'points': 0}


def _london_history_coverage_start(nav_history, start):
    """Oldest date whose XAU/FX coverage may be consumed by London metrics."""
    nav_dates = [
        str(row[0]) for row in (nav_history or [])
        if row and len(row) > 1 and row[0] and row[1] is not None
    ]
    candidates = [str(start)] if start else []
    if nav_dates:
        candidates.append(min(nav_dates))
    return max(candidates) if candidates else None


def _bounded_london_history(rows, coverage_start=None):
    normalized = {
        str(day): float(value)
        for day, value in (rows or [])
        if day and value is not None
    }
    ordered = sorted(normalized.items())
    if not coverage_start:
        return ordered
    dates = [day for day, _ in ordered]
    first_required = bisect.bisect_left(dates, str(coverage_start))
    first_retained = max(0, first_required - XAU_SETTLEMENT_DAYS)
    return ordered[first_retained:]


def stabilize_history(fresh, previous, fresh_source, previous_source=None,
                      label='伦敦金历史', coverage_start=None):
    """Accept revisions in the latest settlement window; quarantine old outliers.

    A current close can legitimately settle on the next day, so the newest five
    trading dates always win. Older points may revise normally up to 0.3%; a
    larger move keeps the prior value and emits an advisory instead of silently
    changing every historical DCA purchase. When the authoritative Sina XAU feed
    returns after a GC00Y fallback, it replaces the fallback reference outright.
    """
    fresh_map = dict(_bounded_london_history(fresh, coverage_start))
    prior_map = dict(_bounded_london_history(previous, coverage_start))
    source_name = (fresh_source or {}).get('name', 'unavailable')
    prior_name = (previous_source or {}).get('name')
    if not prior_map:
        advisory = None if fresh_map else f'{label}抓取失败，暂无可用参考点'
        return _bounded_london_history(fresh_map.items(), coverage_start), advisory
    if not fresh_map:
        retained = _bounded_london_history(prior_map.items(), coverage_start)
        return (
            retained,
            f'{label}抓取失败，沿用上次 {len(retained)} 个参考点',
        )
    if source_name == XAU_PRIMARY_SOURCE and prior_name == XAU_FALLBACK_SOURCE:
        return _bounded_london_history(fresh_map.items(), coverage_start), None

    recent = set(sorted(fresh_map)[-XAU_SETTLEMENT_DAYS:])
    merged = dict(prior_map)
    quarantined = []
    for day, value in fresh_map.items():
        old = prior_map.get(day)
        drift_pct = abs(value / old - 1) * 100 if old else 0
        if day in recent or old is None or drift_pct <= XAU_SETTLED_DRIFT_PCT:
            merged[day] = value
        else:
            quarantined.append((day, drift_pct))
    advisory = None
    if quarantined:
        worst_day, worst_pct = max(quarantined, key=lambda item: item[1])
        advisory = (
            f'{label}校验：沿用 {len(quarantined)} 个已结算点；'
            f'最大新旧偏差 {worst_pct:.2f}%（{worst_day}，源 {source_name}）'
        )
    return _bounded_london_history(merged.items(), coverage_start), advisory


def _xau_at(xau_sorted_dates, xau_vals, d):
    """forward-fill：返回 <= d 的最近一个 XAU 值（对齐 A 股/COMEX 不同交易日历）。"""
    i = bisect.bisect_right(xau_sorted_dates, d) - 1
    return xau_vals[i] if i >= 0 else None


def build_compare_series(nav_history, xau_hist, start, keep=90):
    """[[date, fund_index, london_index]]，起投锚点=100。fund 用 CNY 净值、london 用 USD，
    两条线发散 = 汇率 + 销售费 + C 类拖累（kcn 要的「差因」叙事）。"""
    fund = [(d, n) for d, n in nav_history if n is not None]
    if start:
        fund = [(d, n) for d, n in fund if d >= start] or fund
    if len(fund) < 2 or not xau_hist:
        return []
    xs = sorted(xau_hist)
    xd = [d for d, _ in xs]
    xv = [v for _, v in xs]
    base_fund = base_xau = None
    for d, n in fund:
        x = _xau_at(xd, xv, d)
        if x:
            base_fund, base_xau = n, x
            break
    if not base_xau:
        return []
    series = []
    for d, n in fund:
        x = _xau_at(xd, xv, d)
        if not x:
            continue
        series.append([d, round(n / base_fund * 100, 2), round(x / base_xau * 100, 2)])
    return series[-keep:]


def build_london_dca(nav_history, xau_hist, usdcny_hist, xau_cur, usdcny_cur, start, daily):
    """反事实「对应现值」：同样的钱、同样的定投日子，改买伦敦金现货（CNY 计价）现在值多少。

    直接对标你的基金 current_value —— 两边都是 DCA、同一节奏，唯一变量是标的（基金 vs 伦敦金）。
    每个 A 股交易日投 daily 元，按当日伦敦金 CNY 价（xau_usd×USDCNY）买入盎司，累加后用当前
    现价×汇率算现值。历史 XAU / USDCNY 缺天 → forward-fill（对齐不同交易日历）。
    关键源缺失 → 返回 None（调用方沿用旧值，绝不清空）。"""
    if not xau_hist or not xau_cur or not usdcny_cur:
        return None
    dates = sorted({d for d, n in nav_history if n is not None and (not start or d >= start)})
    if len(dates) < 2:
        return None
    xs = sorted(xau_hist)
    xd, xv = [d for d, _ in xs], [v for _, v in xs]
    fx = sorted(usdcny_hist.items()) if usdcny_hist else []
    fxd, fxv = [d for d, _ in fx], [v for _, v in fx]
    oz, principal_cny, usd_spent = 0.0, 0.0, 0.0
    for d in dates:
        x = _xau_at(xd, xv, d)
        if not x:
            continue
        r = _xau_at(fxd, fxv, d) or usdcny_cur  # 汇率缺天 → forward-fill，再兜底当前
        oz += daily / (x * r)                    # daily 元 ÷ 每盎司人民币价 = 买到的盎司
        principal_cny += daily
        usd_spent += daily / r                    # 当日 daily 元折算的美元（算 USD/oz 均价）
    if principal_cny <= 0 or oz <= 0:
        return None
    grams = oz * GRAMS_PER_OZ
    value = oz * xau_cur * usdcny_cur
    # 平均成本：blended 买入价。USD/oz 对标现货报价，CNY/克对标人民币直觉。
    avg_usd_oz = usd_spent / oz
    # 摊薄轨迹：假设现货+汇率冻结在今天，继续每日投 daily 元按现货买入，
    # 均成本 $/oz 往下移多少、回本门槛降到哪。回本涨幅与基金口径线性一致。
    daily_usd = daily / usdcny_cur
    oz_per_day = daily / (xau_cur * usdcny_cur)
    def _avg_after(n):
        return (usd_spent + daily_usd * n) / (oz + oz_per_day * n)
    projection = [{
        'days': k,
        'avg_cost_usd_oz': round(_avg_after(k), 2),
        'breakeven_upside_pct': round((_avg_after(k) / xau_cur - 1) * 100, 2),
    } for k in (20, 40, 60, 120, 250)]
    return {
        'principal_cny': round(principal_cny, 2),
        'oz_held': round(oz, 4),
        'grams_held': round(grams, 1),
        'avg_cost_usd_oz': round(avg_usd_oz, 2),
        'avg_cost_cny_g': round(principal_cny / grams, 2),
        'spot_usd_oz': round(xau_cur, 2),
        'breakeven_upside_pct': round((avg_usd_oz / xau_cur - 1) * 100, 2),
        'current_value_cny': round(value, 2),
        'pnl_abs': round(value - principal_cny, 2),
        'pnl_pct': round((value / principal_cny - 1) * 100, 2),
        'days': len(dates),
        'daily_grams': round(oz_per_day * GRAMS_PER_OZ, 3),
        'projection': projection,
    }


def compute_london(derived, gold, spot, usdcny, usdcny_hist, xau_hist,
                   hist_source=None, fx_hist_source=None, hist_advisory=None):
    """折算 + 对比线 + DCA 对应现值。任一关键源缺失 → 保留旧 london（merge-not-overwrite）。"""
    if not spot or not spot.get('xau_usd') or not usdcny:
        return gold.get('london')  # 抓空：沿用旧值，绝不清空
    xau = spot['xau_usd']
    cur_value_cny = derived.get('current_value') or 0
    intl_usd = cur_value_cny / usdcny if usdcny else None
    oz = intl_usd / xau if (intl_usd and xau) else None
    grams = oz * GRAMS_PER_OZ if oz else None
    compare = build_compare_series(derived.get('nav_history') or [], xau_hist,
                                   gold.get('start_date', ''))
    # 抓到现价/汇率但历史限流 → 折算照出，对比线沿用旧线
    if not compare and gold.get('london', {}).get('compare_series'):
        compare = gold['london']['compare_series']
    dca_equiv = build_london_dca(derived.get('nav_history') or [], xau_hist, usdcny_hist,
                                 xau, usdcny, gold.get('start_date', ''),
                                 float(gold.get('daily_amount', 200)))
    if not dca_equiv and gold.get('london', {}).get('dca_equiv'):
        dca_equiv = gold['london']['dca_equiv']  # 历史限流 → 沿用旧值
    coverage_start = _london_history_coverage_start(
        derived.get('nav_history') or [],
        gold.get('start_date', ''),
    )
    nav = float(derived.get('nav') or 0)
    avg_cost = float(derived.get('avg_cost') or 0)
    breakeven_ratio = (avg_cost / nav) if nav and avg_cost else None
    return {
        'xau_usd': round(xau, 2),
        'xau_change_pct': spot.get('change_pct'),
        'xau_high': spot.get('high'),
        'xau_low': spot.get('low'),
        'xau_prev_close': spot.get('prev_close'),
        'xau_date': spot.get('date'),
        'usdcny': round(usdcny, 4),
        'oz_equiv': round(oz, 3) if oz else None,
        'grams_equiv': round(grams, 1) if grams else None,
        'intl_value_usd': round(intl_usd, 2) if intl_usd else None,
        # 真基金持仓的映射回本线：假设 USD/CNY 与内外盘价差不变。
        # 与下方 dca_equiv（假设每日直接买伦敦金）必须分开。
        'fund_breakeven_usd_oz': round(xau * breakeven_ratio, 2) if breakeven_ratio else None,
        'fund_breakeven_upside_pct': derived.get('breakeven_upside_pct'),
        'compare_series': compare,
        'dca_equiv': dca_equiv,
        'hist_source': hist_source or {'name': 'unavailable', 'points': 0},
        'hist_series': [
            [d, round(v, 4)]
            for d, v in _bounded_london_history(xau_hist, coverage_start)
        ],
        'fx_hist_source': fx_hist_source or {'name': 'unavailable', 'points': 0},
        'fx_hist_series': [
            [d, round(v, 6)]
            for d, v in _bounded_london_history(
                (usdcny_hist or {}).items(),
                coverage_start,
            )
        ],
        'hist_advisory': hist_advisory,
        'last_updated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
    }


def compute_domestic_gold(derived, gold, quote):
    """上金所现价 → 真基金持仓回本价。

    quote 抓空时沿用旧 domestic_gold，但用最新基金成本/净值重算
    回本映射；这样不会把旧行情冒充新日期，也不会清空最后一个有效值。
    """
    reference = quote or gold.get('domestic_gold')
    if not isinstance(reference, dict):
        return None
    price = _market_number(reference.get('price_cny_g'))
    nav = float(derived.get('nav') or 0)
    avg_cost = float(derived.get('avg_cost') or 0)
    if not price or not nav or not avg_cost:
        return None
    out = dict(reference)
    out['price_cny_g'] = round(price, 2)
    out['breakeven_cny_g'] = round(price * avg_cost / nav, 2)
    out['breakeven_upside_pct'] = derived.get('breakeven_upside_pct')
    out['quote_status'] = 'fresh' if quote else 'retained'
    return out


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


def compute(gold, history, realtime, spot=None, usdcny=None, usdcny_hist=None,
            xau_hist=None, xau_hist_source=None, fx_hist_source=None,
            hist_advisory=None, domestic_quote=None):
    base_principal = float(gold['principal_invested'])
    base_units = float(gold['units_held'])
    daily = float(gold.get('daily_amount', 200))
    start = gold.get('start_date', '')

    # 净值：优先用已公布的最新历史净值；历史抓空则沿用 portfolio 里的旧 nav
    if history:
        nav_date, nav, nav_chg = history[-1]
    else:
        nav, nav_date, nav_chg = float(gold.get('nav') or 0), gold.get('nav_date'), gold.get('nav_change_pct')

    # 自动累加：对账日【之后】的每个 A 股交易日 +daily@当日净值（基线已含对账日当天）。
    # reconciled_date 缺失时默认取最新净值日 → auto=0（安全失败：宁可不加，也绝不从起投日双计）。
    reconciled = gold.get('reconciled_date') or nav_date or start
    auto = [(d, n) for d, n, _ in history if d > reconciled and n]
    auto_amount = daily * len(auto)
    auto_units = sum(daily / n for _, n in auto)
    principal = base_principal + auto_amount
    units = base_units + auto_units

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
        # 自动累加后的实际投入/份额（卡片显示这个，而非对账基线）
        'principal_effective': round(principal, 2),
        'units_effective': round(units, 2),
        'auto_added_days': len(auto),
        'auto_added_amount': round(auto_amount, 2),
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
    derived['domestic_gold'] = compute_domestic_gold(derived, gold, domestic_quote)
    derived['london'] = compute_london(
        derived, gold, spot, usdcny, usdcny_hist, xau_hist,
        xau_hist_source, fx_hist_source, hist_advisory,
    )
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

    quote_day = history[-1][0] if history else gold.get('nav_date')
    domestic_quote = fetch_au9999_daily(quote_day)
    if not domestic_quote:
        print(f'  warn: 上金所 Au99.99({quote_day or "unknown"})抓空，沿用上次有效值',
              file=sys.stderr)

    # 伦敦金类比口径（best-effort，抓空各自沿用旧值）
    spot = fetch_london_spot()
    usdcny, usdcny_hist = fetch_usdcny(gold.get('start_date', ''))
    if spot and usdcny:
        xau_fresh, xau_source = fetch_xau_history(gold.get('start_date', ''))
    else:
        xau_fresh, xau_source = [], {'name': 'not_attempted', 'points': 0}
    old_london = gold.get('london') or {}
    london_coverage_start = _london_history_coverage_start(
        history[-HISTORY_KEEP:] if history else gold.get('nav_history') or [],
        gold.get('start_date', ''),
    )
    xau_hist, xau_advisory = stabilize_history(
        xau_fresh,
        old_london.get('hist_series') or [],
        xau_source,
        old_london.get('hist_source') or {},
        coverage_start=london_coverage_start,
    )
    fx_source = {
        'name': 'frankfurter_usdcny',
        'points': len(usdcny_hist or {}),
    }
    fx_hist, fx_advisory = stabilize_history(
        sorted((usdcny_hist or {}).items()),
        old_london.get('fx_hist_series') or [],
        fx_source,
        old_london.get('fx_hist_source') or {},
        label='USDCNY 历史',
        coverage_start=london_coverage_start,
    )
    usdcny_hist = dict(fx_hist)
    history_advisory = '；'.join(
        advisory for advisory in (xau_advisory, fx_advisory) if advisory
    ) or None
    if not spot:
        print('  warn: 伦敦金现货(hf_XAU)抓空，沿用旧 london', file=sys.stderr)
    elif not xau_fresh:
        print('  warn: 伦敦金历史(GC00Y)限流抓空，对比线沿用旧线', file=sys.stderr)
    if history_advisory:
        print(f'  advisory: {history_advisory}', file=sys.stderr)

    derived = compute(
        gold, history, realtime, spot, usdcny, usdcny_hist, xau_hist,
        xau_source, fx_source, history_advisory, domestic_quote,
    )

    # merge：真值字段原样保留，派生字段更新；nav_history 抓空时不清空
    merged = {k: gold[k] for k in GROUND_TRUTH_FIELDS if k in gold}
    if not history and gold.get('nav_history'):
        derived['nav_history'] = gold['nav_history']
    merged.update(derived)

    g = merged
    print(f"{g['fund_name']} ({g['fund_code']})  净值 {g['nav']} ({g.get('nav_date')})  "
          f"日涨跌 {g.get('nav_change_pct')}%")
    print(f"  投入 {g['principal_effective']:,.0f}  现值 {g['current_value']:,.0f}  "
          f"盈亏 {g['pnl_abs']:+,.0f} ({g['pnl_percent']:+.2f}%)")
    print(f"  平均成本 {g['avg_cost']}  回本需涨 {g['breakeven_upside_pct']:+.2f}%  "
          f"已投 {g['days_invested']} 个交易日 / ~{g['installments_est']} 笔")
    print(f"  对账基线 {g['principal_invested']:,.0f}@{g.get('reconciled_date')} "
          f"+ 自动累加 {g['auto_added_days']} 个交易日 ¥{g['auto_added_amount']:,.0f}")
    if g.get('realtime'):
        rt = g['realtime']
        print(f"  实时估值 {rt['est_nav']} ({rt['est_change_pct']:+.2f}%) @ {rt.get('est_time')}")
    if g.get('domestic_gold'):
        dg = g['domestic_gold']
        print(f"  上金所 Au99.99 ¥{dg['price_cny_g']:,.2f}/克 @ {dg.get('date')} "
              f"→ 真持仓回本 ¥{dg['breakeven_cny_g']:,.2f}/克 "
              f"({dg.get('breakeven_upside_pct', 0):+.2f}%, {dg.get('quote_status')})")
    if g.get('london'):
        ld = g['london']
        print(f"  伦敦金 ${ld.get('xau_usd')}/oz ({(ld.get('xau_change_pct') or 0):+.2f}%) "
              f"USDCNY {ld.get('usdcny')} → 折 {ld.get('grams_equiv')} 克 / {ld.get('oz_equiv')} oz "
              f"(国际口径 ${ld.get('intl_value_usd'):,.0f})  对比线 {len(ld.get('compare_series') or [])} 点")
        print(f"  ↳ 真持仓伦敦金回本 ${ld.get('fund_breakeven_usd_oz'):,.2f}/oz "
              f"(假设汇率/内外盘价差不变)")
        hs = ld.get('hist_source') or {}
        print(f"  ↳ 历史源 {hs.get('name', 'unknown')} · {hs.get('points', 0)} 点")
        if ld.get('hist_advisory'):
            print(f"  ℹ️ {ld['hist_advisory']}")
        de = ld.get('dca_equiv')
        if de:
            print(f"  ↳ 同额定投伦敦金：平均成本 ${de['avg_cost_usd_oz']:,.2f}/oz "
                  f"(¥{de['avg_cost_cny_g']:,.2f}/克) vs 现货 ${de['spot_usd_oz']:,.2f}/oz "
                  f"→ 回本需涨 {de['breakeven_upside_pct']:+.2f}%")
            print(f"     现值 ¥{de['current_value_cny']:,.0f} (投入 ¥{de['principal_cny']:,.0f}, "
                  f"{de['pnl_pct']:+.2f}%) vs 你的基金 {g['pnl_percent']:+.2f}%")

    if dry:
        print('  [dry-run] 不写盘')
        return 0

    # 锁内重读当前 portfolio，只覆盖自己拥有的 gold_dca key —— 防与 market/intraday
    # 写者的 load-modify-write 竞态（旧内存整块覆盖刚写的 gold 字段）。[cut #2]
    from clawock.safe_io import mutate_json
    mutate_json(PORTFOLIO, lambda d: {**d, 'gold_dca': merged})
    print(f"  ✓ 已写回 {PORTFOLIO}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
