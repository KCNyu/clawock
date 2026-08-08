#!/usr/bin/env python3
"""统一数据体检闸 — 把历史上零散踩过的「数字 bug」固化成一道自动门。

背景（见 MEMORY）：本仓库每次数据事故都靠事后单点补 + 我手动跑「数字体检套路」，
知识散在各 fetcher 和记忆里。本脚本把这些不变量收进一处，每次 preflight / 发布前跑，
硬违规（ERROR）阻止发布、软违规（WARN）标红留痕但不拦。输出 assets/data/integrity_report.json。

完整对账逻辑：portfolio.json 每个「派生数字」都能从源头(shares/current_price/
cost_basis/prev_close/trades[])复原，且都有一道闸守着。计算链：
  current_price → current_value(VALUE_LEG) → TCV(TCV_SUM) → total_pnl(PNL_TOTAL)
  cost_basis(COST_BASIS) → total_cost(COST_TOTAL) ↗        → total_pnl_percent(PNL_PCT)
  prev_close → today_change(TODAY_LEG) → today_total_change(TODAY_TOTAL)
  trades[] → realized_pnl(REALIZED_SUM) / cost_basis(COST_BASIS) / cash(CASH_RECON)

固化的不变量（每条都对应一次真实事故或链上一环）：
  VALUE_LEG      每只 current_value == shares×current_price               ERROR
  TCV_SUM        total_current_value == Σ(活跃持仓 current_value)        ERROR
                 → 手工 T+0 卖出漏重算 TCV → equity 假新高 / 回撤归零（3a68822）
  COST_TOTAL     total_cost == Σ(活跃持仓 shares×cost_basis)             ERROR
  PNL_TOTAL      total_pnl == total_current_value − total_cost           ERROR
  PNL_PCT        total_pnl_percent == total_pnl/total_cost×100           WARN
  PNL_LEG        每只 pnl_abs == shares×(current − cost)                 WARN
  TODAY_LEG      每只 today_change == shares×(current − prev_close)      WARN
  TODAY_TOTAL    today_total_change == Σ(活跃持仓 today_change)          WARN
  CASH_RECON     cash == cash_reconciled基线 + Σ(此后trades现金流) + 存取款 ERROR
                 → 加仓记进仓位漏扣现金 → 双计（6/22-24 SPCH $581；recompute_cash.py）
  PRICE_RANGE    current_price ∈ [day_low, day_high]                     WARN
                 → 03033 坏 tick 4.5 跌破 [4.644,4.696]（e54bc54）
  LEV_DIRECTION  同标的 2x 与 1x 的 today_change_pct 同号                WARN
                 → 杠杆 ETF 反号坏 tick（07226 vs 03033）
  FX_TAG         us 区 currency==USD、hk 区 currency==HKD                 ERROR
                 → HKD+USD 不能直接相加（fetch_fx 铁律）
  STALENESS      data_source / last_updated 不早于上一交易日              WARN
                 → 休市日写 stale 价当新 session（cac6222）
  STALE_PRICE    current_price ≠ 上一交易日 prev_close（四位小数）         WARN
                 → 上面每一条闸校的都是「内部算术自洽」或「时间戳标签」，
                   而 stale 报价是自洽的：Nasdaq lastSalePrice 回退到昨收后
                   today_change==0、TODAY_LEG 精确成立、data_source 戳还是今天
                   → 全绿放行。2026-07-27 PLTU 账面 0.00%（实为 +6.3%）、
                   SKHY 账面 -0.31%（实为 -6.2%）就是这么过闸的。
                   两个独立价格四位小数完全相等 ≈ 不可能，本身即是最强判据。
  REALIZED_SUM   realized_pnl ≈ Σ(trades 里 realized_pnl)                WARN
  COST_BASIS     trades 账本完整(净股==shares)时 cost_basis==移动加权价  ERROR
                 → 算均价漏冲减 T+0 卖出 → 把已卖低价买单留在分母,均价偏低
                   (SPCH 18.07 vs 券商 18.38；只在账本可验证时拦,不误伤半账本)
  US_ASOF        活跃美股共享单一 session 日期（避免跨天双计）            WARN
                 → 同一 US session 落进两个 HK 日期快照（fd86a53）
  TRUE_PRINCIPAL true_principal（峰值净投入）≥ 当前净投入(cost−realized)   WARN
                 → 手填本金常量过期 → 「净本金回报率」分母失真而虚高

用法：
  python3 preflight_integrity.py [portfolio.json]   # 默认仓库根 portfolio.json
  退出码：0=全过或仅 WARN；2=有 ERROR（调用方应阻止发布/投递）
"""
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# The checkout root, so `clawock` resolves from the tree this file ships
# in. Reached through the scripts/data/workspace shim until #267 step 3,
# whose only remaining job was inserting this path as a side effect.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from clawock.workspace import workspace_root  # noqa: E402

# Code lives in the checkout; only DATA lives in the workspace. `workspace_root`
# is overridable, so resolving our own modules through WS would read them out of
# someone else's data directory — or silently pick up whatever happens to be
# there. Same expression WS is seeded from, kept separate on purpose (#269).
_CHECKOUT = Path(__file__).resolve().parents[2]
WS = workspace_root(Path(__file__).resolve().parents[2])
PORTFOLIO = WS / 'portfolio.json'
OUT = WS / 'assets' / 'data' / 'integrity_report.json'

sys.path.insert(0, str(_CHECKOUT / 'scripts' / 'data'))
from clawock.instrument_registry import INSTRUMENTS  # noqa: E402

try:
    from clawock.safe_io import safe_write_json
except Exception:  # pragma: no cover
    def safe_write_json(path, data, indent=2):
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=indent))

try:
    from clawock import trading_calendar as tc
except Exception:
    tc = None

# 同标的 1x/2x 对，用于方向交叉验证（两只都在持仓时才比）。
HSTECH_SIBLINGS = {
    symbol for symbol, meta in INSTRUMENTS.items()
    if meta['region'] == 'HK' and meta['venue'] == 'HKEX' and meta['factor'] == 'HSTECH'
}

# 容差
TCV_TOL = 1.0      # 货币单位（HKD/USD），手工记账小数误差
PCT_TOL = 0.5      # pnl_abs 重算容差（货币单位）
RANGE_TOL = 0.005  # current 越界容忍 0.5%（收盘集合竞价/盘后微动）


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _active(holdings):
    return [h for h in holdings if (_num(h.get('shares')) or 0) > 0]


def _moving_avg_cost(trades):
    """移动加权成本 + 净股数，从 trades[] 推。

    买入按价累加成本；卖出按*当时均价*冲减成本（与券商口径一致：卖出不动均价、
    盈亏落 realized_pnl）。同日 buy/sell 用原始下标稳定排序，保证「先买后卖」的
    T+0 在同一天被正确平掉。返回 (avg_cost 或 None, net_shares)。"""
    sh = 0.0
    cost = 0.0
    for _, t in sorted(enumerate(trades), key=lambda x: (x[1].get('date', ''), x[0])):
        a = t.get('action')
        s = _num(t.get('shares')) or 0
        pr = _num(t.get('price')) or 0
        if a == 'buy':
            sh += s
            cost += s * pr
        elif a == 'sell':
            if sh > 0:
                cost -= s * (cost / sh)   # 按当时均价冲减，均价不变
            sh -= s
    return (cost / sh if sh else None), sh


def _trade_cashflow_after(holdings, after_date):
    """Σ(此日期*之后*所有 trades 的现金流)：sell=+shares×price，buy=−shares×price。

    after_date 为基线对账日 ISO 串；严格大于（基线值已含当日及之前所有成交）。"""
    flow = 0.0
    n = 0
    for h in holdings or []:
        for t in h.get('trades', []) or []:
            d = t.get('date', '')
            if not d or d <= after_date:
                continue
            s = _num(t.get('shares')) or 0
            pr = _num(t.get('price')) or 0
            a = t.get('action')
            if a == 'sell':
                flow += s * pr
            elif a == 'buy':
                flow -= s * pr
            else:
                continue
            n += 1
    return flow, n


def derive_cash(port):
    """从对账基线 + 此后 trades 现金流 + 存取款派生现金。

    返回 (derived, baseline, baseline_date, n_trades) 或 None（无基线则不可派生，
    调用方应跳过 CASH_RECON 闸——与 COST_BASIS「账本不完整就不校验」同理）。"""
    baseline = _num(port.get('cash_reconciled'))
    bdate = port.get('cash_reconciled_date')
    if baseline is None or not bdate:
        return None
    flow, n = _trade_cashflow_after(port.get('holdings', []), bdate)
    adj = 0.0
    for a in port.get('cash_adjustments', []) or []:
        d = a.get('date', '')
        if d and d > bdate:
            adj += _num(a.get('amount')) or 0
    return round(baseline + flow + adj, 2), baseline, bdate, n


def _last_session(market):
    """上一个（含今天）交易日 ISO 字符串；trading_calendar 不可用时返回 None。"""
    if tc is None:
        return None
    d = date.today()
    for _ in range(10):
        try:
            if tc.is_trading_day(market, d):
                return d.isoformat()
        except Exception:
            return None
        d -= timedelta(days=1)
    return None


def _extract_iso(s):
    """从 data_source / last_updated 文本里抠出 YYYY-MM-DD 或 Mon D 之类的日期。"""
    if not s:
        return None
    import re
    m = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', str(s))
    if m:
        y, mo, d = (int(g) for g in m.groups())
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None
    # "May 8, 2026" / "Jun 18"
    for fmt in ('%b %d, %Y', '%b %d %Y', '%B %d, %Y'):
        m = re.search(r'[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}', str(s))
        if m:
            try:
                return datetime.strptime(m.group(0), fmt).date().isoformat()
            except ValueError:
                continue
    return None


def _prev_snapshot_cash(region, field):
    """Most recent prior snapshot's cash for <region>.<field> as (value, snap_date),
    or None. Used to fat-finger-check manual cash edits (a digit typo shows up as a
    big jump vs. the last published snapshot). The date lets CASH_SANITY subtract any
    deposits/withdrawals logged *after* that snapshot so a confirmed cash move isn't
    misread as a typo."""
    snaps = sorted((WS / 'memory' / 'snapshots').glob('*.json'))
    today = date.today().isoformat()
    for f in reversed(snaps):
        if f.stem >= today:          # skip a snapshot already written for today
            continue
        try:
            d = json.loads(f.read_text())
            v = (d.get('portfolios', {}).get(region, {}) or {}).get(field)
            n = _num(v)
            if n is not None:
                return n, f.stem
        except Exception:
            continue
    return None


def check(portfolio_path=PORTFOLIO):
    data = json.loads(Path(portfolio_path).read_text())
    P = data.get('portfolios', {})
    findings = []  # {code, level, region, ticker, msg}

    def add(code, level, msg, region=None, ticker=None):
        findings.append({'code': code, 'level': level, 'region': region,
                         'ticker': ticker, 'msg': msg})

    region_market = {'us_stocks': 'us', 'hk_stocks': 'hk'}
    region_ccy = {'us_stocks': 'USD', 'hk_stocks': 'HKD'}

    for region, port in P.items():
        if not isinstance(port, dict):
            continue
        market = region_market.get(region)
        holdings = port.get('holdings', []) or []
        active = _active(holdings)

        # FX_TAG ---------------------------------------------------------
        ccy = port.get('currency')
        want = region_ccy.get(region)
        if want and ccy != want:
            add('FX_TAG', 'ERROR', f'{region} currency={ccy} 应为 {want}（HKD/USD 不能混加）', region)

        # TCV_SUM --------------------------------------------------------
        tcv = _num(port.get('total_current_value'))
        sum_cv = sum(_num(h.get('current_value')) or 0 for h in active)
        if tcv is not None and abs(tcv - sum_cv) > TCV_TOL:
            add('TCV_SUM', 'ERROR',
                f'total_current_value={tcv:.2f} ≠ Σ活跃持仓 current_value={sum_cv:.2f} '
                f'(差 {tcv - sum_cv:+.2f})；疑似手工卖出漏重算聚合 → equity 假新高', region)

        # COST_TOTAL：total_cost == Σ(活跃持仓 shares×cost_basis)（喂 total_pnl）
        tcost = _num(port.get('total_cost'))
        sum_cost = sum((_num(h.get('shares')) or 0) * (_num(h.get('cost_basis')) or 0)
                       for h in active if _num(h.get('cost_basis')) is not None)
        if tcost is not None and abs(tcost - sum_cost) > TCV_TOL:
            add('COST_TOTAL', 'ERROR',
                f'total_cost={tcost:.2f} ≠ Σ活跃持仓 shares×cost_basis={sum_cost:.2f} '
                f'(差 {tcost - sum_cost:+.2f})；手工记仓漏重算成本 → total_pnl 失真', region)

        # PNL_TOTAL ------------------------------------------------------
        tpnl = _num(port.get('total_pnl'))
        if tcv is not None and tcost is not None and tpnl is not None:
            if abs(tpnl - (tcv - tcost)) > TCV_TOL:
                add('PNL_TOTAL', 'ERROR',
                    f'total_pnl={tpnl:.2f} ≠ TCV−cost={tcv - tcost:.2f}', region)

        # PNL_PCT：total_pnl_percent == total_pnl/total_cost×100（口径=未实现/当前成本）
        tpct = _num(port.get('total_pnl_percent'))
        if tpct is not None and tpnl is not None and tcost:
            want_pct = tpnl / tcost * 100
            if abs(tpct - want_pct) > 0.5:
                add('PNL_PCT', 'WARN',
                    f'total_pnl_percent={tpct:.2f} ≠ total_pnl/total_cost={want_pct:.2f}', region)

        # TODAY_TOTAL：today_total_change == Σ(活跃持仓 today_change)
        ttc = _num(port.get('today_total_change'))
        sum_tc = sum(_num(h.get('today_change')) or 0 for h in active)
        if ttc is not None and abs(ttc - sum_tc) > TCV_TOL:
            add('TODAY_TOTAL', 'WARN',
                f'today_total_change={ttc:.2f} ≠ Σ活跃持仓 today_change={sum_tc:.2f} '
                f'(差 {ttc - sum_tc:+.2f})', region)

        # REALIZED_SUM ---------------------------------------------------
        rp = _num(port.get('realized_pnl'))
        if rp is not None:
            tally = 0.0
            for h in holdings:
                for tr in h.get('trades', []) or []:
                    if tr.get('action') == 'sell':
                        tally += _num(tr.get('realized_pnl')) or 0
            if abs(rp - tally) > 1.0:
                add('REALIZED_SUM', 'WARN',
                    f'realized_pnl={rp:.2f} ≠ trades 汇总={tally:.2f}（差 {rp - tally:+.2f}）；'
                    f'禁止手写 realized_pnl，应跑 recompute_realized', region)

        # 逐只 -----------------------------------------------------------
        sib_dirs = {}
        asofs = set()
        for h in active:
            t = h.get('ticker')
            cur = _num(h.get('current_price'))
            lo = _num(h.get('day_low'))
            hi = _num(h.get('day_high'))
            sh = _num(h.get('shares'))
            cost = _num(h.get('cost_basis'))
            pnl = _num(h.get('pnl_abs'))
            chg = _num(h.get('today_change_pct'))

            # PRICE_RANGE
            if cur and lo and hi and lo > 0 and hi > 0:
                if cur < lo * (1 - RANGE_TOL) or cur > hi * (1 + RANGE_TOL):
                    add('PRICE_RANGE', 'WARN',
                        f'{t} current={cur} 越出当日区间[{lo}, {hi}]；疑似坏 tick，'
                        f'用同标的 2x/1x 兄弟验向', region, t)

            # VALUE_LEG：current_value == shares×current_price（喂 TCV→equity 的源；
            # TCV_SUM 只验「总额==Σcv」，若每只 cv 本身算错则一起错也发现不了）
            cv = _num(h.get('current_value'))
            if cur is not None and sh and cv is not None:
                want_cv = sh * cur
                if abs(cv - want_cv) > max(PCT_TOL, abs(want_cv) * 0.01):
                    add('VALUE_LEG', 'ERROR',
                        f'{t} current_value={cv:.2f} ≠ shares×current_price={want_cv:.2f}'
                        f'（差 {cv - want_cv:+.2f}）；手工记仓漏重算市值 → equity 失真', region, t)

            # PNL_LEG
            if cur is not None and sh and cost is not None and pnl is not None:
                want_pnl = sh * (cur - cost)
                if abs(pnl - want_pnl) > max(PCT_TOL, abs(want_pnl) * 0.01):
                    add('PNL_LEG', 'WARN',
                        f'{t} pnl_abs={pnl:.2f} ≠ shares×(cur−cost)={want_pnl:.2f}', region, t)

            # TODAY_LEG：today_change == shares×(current−prev_close)（日内 P&L 的源）
            # 例外：本 session 内建仓的持仓——prev_close 时未持有，其当日 P&L 基准是
            # 成本价而非前收(today_change==current−cost==pnl_abs 才对)，prev_close 对它
            # 无意义(IPO 首日更是连真实前收都没有)。跳过前收公式，免 IPO/新建仓假警报。
            prev = _num(h.get('prev_close'))
            tchg = _num(h.get('today_change'))
            sess_date = h.get('day_session_date')
            trade_dates = [tr.get('date') for tr in (h.get('trades') or []) if tr.get('date')]
            opened_this_session = bool(sess_date) and (
                h.get('prev_close_date') == sess_date               # 前收日==会话日 → 非真实前收
                or (trade_dates and min(trade_dates) >= sess_date)  # 首笔买入在本会话 → 前收时未持有
            )
            if (cur is not None and sh and prev is not None and tchg is not None
                    and not opened_this_session):
                want_tc = sh * (cur - prev)
                if abs(tchg - want_tc) > max(PCT_TOL, abs(want_tc) * 0.02):
                    add('TODAY_LEG', 'WARN',
                        f'{t} today_change={tchg:.2f} ≠ shares×(cur−prev_close)={want_tc:.2f}'
                        f'（差 {tchg - want_tc:+.2f}）；prev_close 陈旧或漏重算', region, t)

            # COST_BASIS：仅当 trades 账本完整(净股==当前 shares)时才校验，
            # 半账本(只记近期 T+0、缺建仓买入)净股对不上 → cost_basis 是手填的、跳过
            trades = h.get('trades') or []
            if trades and cost is not None and sh:
                mavg, net = _moving_avg_cost(trades)
                if mavg is not None and abs(net - sh) < 1e-6 and cost > 0:
                    if abs(mavg - cost) / cost > 0.005:   # 偏离 >0.5%
                        add('COST_BASIS', 'ERROR',
                            f'{t} cost_basis={cost:.4f} ≠ trades 移动加权={mavg:.4f}'
                            f'（差 {cost - mavg:+.4f}）；算均价疑漏冲减 T+0 卖出/重复计已卖买单',
                            region, t)

            # 收集方向用于 LEV_DIRECTION（恒科同标的族）
            if t in HSTECH_SIBLINGS and chg is not None:
                sib_dirs[t] = chg

            # 收集 us_asof
            if market == 'us':
                src = h.get('data_source') or ''
                iso = _extract_iso(src)
                if iso:
                    asofs.add(iso)

            # STALENESS（逐只 data_source）
            if market:
                last = _last_session(market)
                iso = _extract_iso(h.get('data_source'))
                if last and iso and iso < last:
                    add('STALENESS', 'WARN',
                        f'{t} data_source 日期 {iso} 早于上一交易日 {last}；可能 stale 价当新 session',
                        region, t)

            # STALE_PRICE：现价与上一交易日前收四位小数完全相等
            # 刻意不复用 opened_this_session 豁免：那条豁免的判据之一是
            # prev_close_date == day_session_date，而写坏 prev_close_date 恰恰是同一个
            # bug 的产物 → 会把这道闸对着「正需要拦的行」关掉。这里只认
            # prev_close_date < day_session_date（真·上一交易日）这一种情况。
            if (cur is not None and prev is not None and sh
                    and h.get('prev_close_date') and sess_date
                    and h['prev_close_date'] < sess_date
                    and abs(cur - prev) < 1e-4):
                add('STALE_PRICE', 'WARN',
                    f'{t} current_price={cur:.4f} 与上一交易日前收 {prev:.4f}'
                    f'（{h["prev_close_date"]}）四位小数完全相等；报价源大概率停在昨收，'
                    f'当日涨跌被算成 0（today_change_pct={h.get("today_change_pct")}）',
                    region, t)

            # 数据源自己声明的质量降级，别让它只留在 stdout 里
            if h.get('stale_price_repair'):
                rp = h['stale_price_repair']
                add('STALE_PRICE', 'WARN',
                    f'{t} 报价源返回 {rp.get("reported")} == 昨收，已按 {rp.get("basis")} '
                    f'重建为 {rp.get("repaired")}（{rp.get("source")} @ {rp.get("at")}）',
                    region, t)
            if h.get('quote_incomplete'):
                add('STALE_PRICE', 'WARN',
                    f'{t} 报价不完整（缺前收/日内区间），所有 provider 都没给全；'
                    f'day_high/day_low 仅由本地累积器推得，别当真实区间读',
                    region, t)

        # LEV_DIRECTION：恒科族两只以上且方向不一致
        nz = {k: v for k, v in sib_dirs.items() if abs(v) > 0.05}
        if len(nz) >= 2:
            signs = {1 if v > 0 else -1 for v in nz.values()}
            if len(signs) > 1:
                detail = ', '.join(f'{k} {v:+.2f}%' for k, v in nz.items())
                add('LEV_DIRECTION', 'WARN',
                    f'恒科同标的族方向矛盾（{detail}）；疑似某只坏 tick', region)

        # US_ASOF：活跃美股多个 session 日期
        if market == 'us' and len(asofs) > 1:
            add('US_ASOF', 'WARN',
                f'活跃美股横跨多个 session 日期 {sorted(asofs)}；当心每日 P&L 跨天双计', region)

        # TRUE_PRINCIPAL：手填的「峰值净投入」常量是「净本金回报率」的分母，改仓忘
        # 重算会让回报率失真。不变量：true_principal（历史峰值净投入）≥ 当前净投入
        # net_principal(total_cost − realized_pnl)。反超 = 常量过期需按现金流账本重算。
        tp = _num(port.get('true_principal'))
        if tp is not None and tp > 0:
            tcost_tp = _num(port.get('total_cost'))
            real_tp = _num(port.get('realized_pnl'))
            if tcost_tp is not None and real_tp is not None:
                net_principal = tcost_tp - real_tp
                if net_principal > tp + 1:
                    add('TRUE_PRINCIPAL', 'WARN',
                        f'true_principal={tp:.2f} < 当前净投入 cost−realized={net_principal:.2f}'
                        f'（差 {net_principal - tp:+.2f}）；峰值净投入常量疑过期，改仓后须按'
                        f'现金流账本重算（它是「净本金回报率」分母，过期则回报率虚高）', region)

        # CASH_SANITY：手填现金 fat-finger 闸（既有 ERROR 校验只看持仓，抓不到现金笔误）
        cash_field = {'us_stocks': 'cash_usd', 'hk_stocks': 'cash_hkd'}.get(region)
        if cash_field and port.get(cash_field) is not None:
            raw = port.get(cash_field)
            cash = _num(raw)
            if cash is None:
                add('CASH_SANITY', 'WARN', f'{cash_field}={raw!r} 非数值；手填现金损坏', region)
            else:
                if cash < 0:
                    add('CASH_SANITY', 'WARN',
                        f'{cash_field}={cash:.2f} 为负；手填现金异常需核对', region)
                prev_info = _prev_snapshot_cash(region, cash_field)
                if prev_info and prev_info[0] > 0 and cash > 0:
                    prev, prev_date = prev_info
                    # A logged deposit/withdrawal after the last snapshot legitimately
                    # moves cash — subtract it so a *confirmed* move doesn't read as a
                    # fat-finger. An unlogged digit typo still trips the ratio gate.
                    adj_since = sum(
                        _num(a.get('amount')) or 0
                        for a in port.get('cash_adjustments', []) or []
                        if a.get('date', '') > (prev_date or ''))
                    base = cash - adj_since
                    if base > 0:
                        ratio = base / prev
                        if ratio >= 5 or ratio <= 0.2:
                            explained = f'（已扣登记存取款 {adj_since:+.0f} 后仍 {ratio:.1f}×）' \
                                if adj_since else f'跳变 {ratio:.1f}×'
                            add('CASH_SANITY', 'WARN',
                                f'{cash_field}={cash:.2f} 较上一快照 {prev:.2f} {explained}；'
                                f'疑似手填多/少一位（总资产 = 持仓 + 现金，会被静默污染）', region)

        # CASH_RECON：现金可复原闸。有对账基线时，cash 必须 == 基线 + 此后 trades
        # 现金流 + 存取款。抓「加了 trades 没重算现金」（如 6/22-24 漏扣 SPCH $581
        # 双计）——这是 CASH_SANITY 抓不到的「该降没降」。无基线则跳过（同 COST_BASIS）。
        if cash_field and port.get(cash_field) is not None:
            der = derive_cash(port)
            stated = _num(port.get(cash_field))
            if der is not None and stated is not None:
                derived, baseline, bdate, n_tr = der
                if abs(stated - derived) > TCV_TOL:
                    add('CASH_RECON', 'ERROR',
                        f'{cash_field}={stated:.2f} ≠ 派生值 {derived:.2f}'
                        f'（基线 {baseline:.2f}@{bdate} + 此后 {n_tr} 笔成交现金流，差 '
                        f'{stated - derived:+.2f}）；改/补 trades 后须跑 recompute_cash.py', region)

    # GOLD_RECON：黄金定投手填对账值闸（隐含均价 vs NAV，抓填错/单位反）
    g = data.get('gold_dca') or {}
    pi, uh, nav = _num(g.get('principal_invested')), _num(g.get('units_held')), _num(g.get('nav'))
    if pi is not None and uh is not None:
        if pi <= 0 or uh <= 0:
            add('GOLD_RECON', 'WARN',
                f'gold_dca principal_invested/units_held 非正（{pi}/{uh}）；对账值疑误', region='gold')
        elif nav and nav > 0:
            implied = pi / uh
            if not (0.3 <= implied / nav <= 3):
                add('GOLD_RECON', 'WARN',
                    f'gold_dca 手填隐含均价 {implied:.3f} 与 NAV {nav:.3f} 偏离 {implied / nav:.2f}×；'
                    f'疑 principal/units 填错或单位反', region='gold')

    errors = [f for f in findings if f['level'] == 'ERROR']
    warns = [f for f in findings if f['level'] == 'WARN']
    report = {
        'generated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'ok': not errors,
        'error_count': len(errors),
        'warn_count': len(warns),
        'findings': findings,
    }
    return report


def main(argv):
    path = Path(argv[0]) if argv else PORTFOLIO
    report = check(path)
    safe_write_json(str(OUT), report)

    icon = {'ERROR': '🔴', 'WARN': '🟡'}
    if not report['findings']:
        print('✅ 数据体检全过，无异常')
    else:
        for f in report['findings']:
            loc = f"[{f.get('region') or '-'}]"
            print(f"{icon.get(f['level'], '·')} {f['code']:14s} {loc:12s} {f['msg']}")
    print(f"\n体检结论：{report['error_count']} ERROR / {report['warn_count']} WARN → "
          f"{'❌ 阻止发布' if not report['ok'] else '✅ 可发布'}")
    return 2 if not report['ok'] else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
