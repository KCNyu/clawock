#!/usr/bin/env python3
"""
fetch_fundamentals_em.py - 东财 datacenter 基本面 (美股 + 港股, 无 key)

Adapted and modified from global-stock-data
(https://github.com/simonlin1212/global-stock-data, Apache-2.0). See NOTICE.

补齐港股财报/关键指标数据；美股基本面优先走 SEC filings，此处提供中文
科目和关键指标作为补充。

数据源: datacenter-web.eastmoney.com (实测可达 2026-06-14, kcn 服务器 IP)。

Usage:
  clawock fundamentals 00700                      # 关键指标概览(默认)
  clawock fundamentals 00700 --indicators         # 同上, 最近4期 ROE/EPS/毛利率...
  clawock fundamentals AAPL  --statements income  # 利润表(中文科目行)
  clawock fundamentals BABA  --statements balance # 资产负债表
  clawock fundamentals 00700 --periods 8 --json   # 取8期 + 机读 JSON
"""
import json
import sys
from typing import Dict, List

from clawock._em_http import em_get
from clawock._em_symbols import resolve

DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# statement → {market: reportName}  (命名不统一: balance/income 用 F10, cashflow 用 SK)
_REPORT_MAP = {
    "balance": {"us": "RPT_USF10_FN_BALANCE", "hk": "RPT_HKF10_FN_BALANCE"},
    "income":  {"us": "RPT_USF10_FN_INCOME",  "hk": "RPT_HKF10_FN_INCOME"},
    "cashflow": {"us": "RPT_USSK_FN_CASHFLOW", "hk": "RPT_HKSK_FN_CASHFLOW"},
}

# 关键指标里挑给人看的核心字段 (美/港字段集不同, 取并集, 缺省跳过)
_INDICATOR_FIELDS = [
    ("REPORT_DATE", "报告期"), ("CURRENCY", "币种"),
    ("OPERATE_INCOME", "营收"), ("OPERATE_INCOME_YOY", "营收同比%"),
    ("GROSS_PROFIT_RATIO", "毛利率%"), ("NET_PROFIT_RATIO", "净利率%"),
    ("PARENT_HOLDER_NETPROFIT", "归母净利"), ("HOLDER_PROFIT", "股东应占溢利"),
    ("BASIC_EPS", "每股收益"), ("DILUTED_EPS", "稀释EPS"),
    ("ROE_AVG", "平均ROE%"), ("ROA", "ROA%"), ("ROIC", "ROIC%"),
    ("DEBT_ASSET_RATIO", "资产负债率%"), ("CURRENT_RATIO", "流动比率"),
    ("BPS", "每股净资产"), ("DIVI_RATIO", "股息率%"),
]


def _fmt(v, is_pct: bool = False) -> str:
    """人读格式化(仅用于 print, JSON 保留原始精度)。大额→亿/万, 比率→2位。"""
    if not isinstance(v, (int, float)):
        return str(v)
    if is_pct:
        return f"{v:.2f}%"
    a = abs(v)
    if a >= 1e8:
        return f"{v / 1e8:,.2f}亿"
    if a >= 1e4:
        return f"{v / 1e4:,.2f}万"
    return f"{v:.4g}"


def _datacenter(report_name: str, secucode: str, page_size: int) -> List[Dict]:
    """东财数据中心统一查询。空/失败静默返回 []，永不抛。"""
    params = {
        "reportName": report_name, "columns": "ALL",
        "filter": f'(SECUCODE="{secucode}")', "pageNumber": "1",
        "pageSize": str(page_size), "sortColumns": "REPORT_DATE",
        "sortTypes": "-1", "source": "WEB", "client": "WEB",
    }
    r = em_get(DATACENTER_URL, params=params, label=f"datacenter {report_name}")
    if r is None:
        return []
    try:
        res = (r.json() or {}).get("result")
    except ValueError:
        return []
    if res and res.get("data"):
        return res["data"]
    return []  # 合法空 (该报表无此票)


def get_indicators(secucode: str, market: str, periods: int = 4) -> List[Dict]:
    """GMAININDICATOR 关键财务指标, 最近 N 期。"""
    report = f"RPT_{'HK' if market == 'hk' else 'US'}F10_FN_GMAININDICATOR"
    rows = _datacenter(report, secucode, periods)
    out = []
    for row in rows:
        rec = {}
        for key, label in _INDICATOR_FIELDS:
            if key in row and row[key] is not None:
                rec[label] = row[key]
        out.append(rec)
    return out


def get_statement(secucode: str, market: str, statement: str, periods: int = 4) -> List[Dict]:
    """财报三表科目行 (中文科目名)。datacenter 按行展开, 每行一个科目。

    datacenter 一页混多期、每期约数十科目行、行数不定 —— 故 over-fetch 后按
    REPORT_DATE 精确截到最近 N 期, 并对 (期, 科目) 去重 (REPORT_TYPE 变体会重复)。
    """
    report = _REPORT_MAP[statement][market]
    rows = _datacenter(report, secucode, max(periods * 80, 200))
    out, seen, kept_dates = [], set(), []
    for row in rows:
        rd = row.get("REPORT_DATE")
        if rd not in kept_dates:
            if len(kept_dates) >= periods:
                continue  # 已收满 N 期, 跳过更早的
            kept_dates.append(rd)
        item = row.get("ITEM_NAME")
        key = (rd, item)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "report_date": rd,
            "report": row.get("REPORT"),
            "item": item,
            "amount": row.get("AMOUNT"),
            "yoy_pct": row.get("YOY_RATIO"),
            "currency": row.get("CURRENCY"),
            "standard": row.get("ACCOUNT_STANDARD") or row.get("ACCOUNTING_STANDARDS"),
        })
    return out


def _parse_args(argv):
    code = None
    mode = "indicators"
    statement = "income"
    periods = 4
    as_json = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--indicators":
            mode = "indicators"
        elif a == "--statements":
            mode = "statements"
            if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                statement = argv[i + 1]; i += 1
        elif a == "--periods" and i + 1 < len(argv):
            try:
                periods = max(1, int(argv[i + 1]))
            except ValueError:
                pass
            i += 1
        elif a == "--json":
            as_json = True
        elif not a.startswith("-"):
            code = a
        i += 1
    return code, mode, statement, periods, as_json


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    code, mode, statement, periods, as_json = _parse_args(argv)
    if not code:
        print(__doc__)
        return 1
    if statement not in _REPORT_MAP:
        print(f"  ⚠️  未知报表 '{statement}', 可选: balance/income/cashflow", file=sys.stderr)
        return 1

    sym = resolve(code)
    if not sym:
        print(json.dumps({"error": f"无法解析代码: {code}"}, ensure_ascii=False))
        return 1
    market = "hk" if sym["mkt_num"] == 116 else "us"

    def _fetch(secucode):
        if mode == "indicators":
            return get_indicators(secucode, market, periods)
        return get_statement(secucode, market, statement, periods)

    data = _fetch(sym["secucode"])
    # US 启发式回退可能把 NASDAQ(.O)/NYSE(.N) 猜反 → 空结果时换后缀再试一次
    if not data and market == "us":
        alt = sym["secucode"][:-2] + (".N" if sym["secucode"].endswith(".O") else ".O")
        alt_data = _fetch(alt)
        if alt_data:
            sym = {**sym, "secucode": alt,
                   "mkt_num": 106 if alt.endswith(".N") else 105,
                   "market": "NYSE" if alt.endswith(".N") else "NASDAQ",
                   "secid": f"{106 if alt.endswith('.N') else 105}.{sym['code']}"}
            data = alt_data

    if mode == "indicators":
        result = {"symbol": sym, "indicators": data}
    else:
        result = {"symbol": sym, "statement": statement, "rows": data}

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    # 人读输出
    tag = f"{sym['name']} {sym['code']} ({sym['market']}, {sym['secucode']})"
    if mode == "indicators":
        print(f"\n  关键财务指标 — {tag}")
        if not data:
            print("  (无数据)")
        for rec in data:
            rd = str(rec.get("报告期", "?"))[:10]
            print(f"\n  ▎{rd}")
            for k, v in rec.items():
                if k in ("报告期", "币种"):
                    continue
                print(f"    {k}: {_fmt(v, is_pct='%' in k)}")
    else:
        print(f"\n  {statement} 财报科目 — {tag}")
        if not data:
            print("  (无数据)")
        cur = None
        for row in data:
            if row["report_date"] != cur:
                cur = row["report_date"]
                print(f"\n  ▎{str(cur)[:10]} ({row.get('currency') or ''})")
            yoy = row.get("yoy_pct")
            print(f"    {row['item']}: {_fmt(row['amount'])}"
                  + (f"  (同比 {_fmt(yoy, is_pct=True)})" if yoy is not None else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
