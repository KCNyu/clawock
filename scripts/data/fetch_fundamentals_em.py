#!/usr/bin/env python3
"""
fetch_fundamentals_em.py - 东财 datacenter 基本面 (美股 + 港股, 无 key)

Adapted from global-stock-data (https://github.com/simonlin1212/global-stock-data, Apache-2.0).

补 openclaw 数据空白: 港股财报/关键指标 (analyze_hk_stocks.py 只有价格+技术+新闻)。
美股基本面优先走 fetch_us_filings.py (SEC, 更全); 此处提供中文科目/关键指标作补充。

数据源: datacenter-web.eastmoney.com (实测可达 2026-06-14, kcn 服务器 IP)。

Usage:
  python3 fetch_fundamentals_em.py 00700                      # 关键指标概览(默认)
  python3 fetch_fundamentals_em.py 00700 --indicators         # 同上, 最近4期 ROE/EPS/毛利率...
  python3 fetch_fundamentals_em.py AAPL  --statements income  # 利润表(中文科目行)
  python3 fetch_fundamentals_em.py BABA  --statements balance # 资产负债表
  python3 fetch_fundamentals_em.py 00700 --periods 8 --json   # 取8期 + 机读 JSON
"""
import json
import os
import sys
import time
from typing import Dict, List, Optional

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _em_symbols import resolve  # noqa: E402

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
TIMEOUT = 15
MIN_INTERVAL = 0.25
_last_call = 0.0

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


def _throttle() -> None:
    global _last_call
    gap = time.time() - _last_call
    if gap < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - gap)
    _last_call = time.time()


def _datacenter(report_name: str, secucode: str, page_size: int, retries: int = 3) -> List[Dict]:
    """东财数据中心统一查询。空/失败静默返回 []，永不抛。"""
    params = {
        "reportName": report_name, "columns": "ALL",
        "filter": f'(SECUCODE="{secucode}")', "pageNumber": "1",
        "pageSize": str(page_size), "sortColumns": "REPORT_DATE",
        "sortTypes": "-1", "source": "WEB", "client": "WEB",
    }
    for attempt in range(retries):
        _throttle()
        try:
            r = requests.get(DATACENTER_URL, params=params,
                             headers={"User-Agent": UA}, timeout=TIMEOUT)
            r.raise_for_status()
            d = r.json()
            res = d.get("result")
            if res and res.get("data"):
                return res["data"]
            return []  # 合法空 (该报表无此票)
        except (requests.RequestException, ValueError) as e:
            if attempt == retries - 1:
                print(f"  ⚠️  东财 datacenter 失败 ({report_name}): {e}", file=sys.stderr)
            time.sleep(0.8 * (attempt + 1))
    return []


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
    """财报三表科目行 (中文科目名)。datacenter 按行展开, 每行一个科目。"""
    report = _REPORT_MAP[statement][market]
    rows = _datacenter(report, secucode, periods * 60)  # 每期多科目行, 放宽 page_size
    out = []
    for row in rows:
        out.append({
            "report_date": row.get("REPORT_DATE"),
            "report": row.get("REPORT"),
            "item": row.get("ITEM_NAME"),
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
        elif a == "--periods":
            periods = int(argv[i + 1]); i += 1
        elif a == "--json":
            as_json = True
        elif not a.startswith("-"):
            code = a
        i += 1
    return code, mode, statement, periods, as_json


def main():
    code, mode, statement, periods, as_json = _parse_args(sys.argv[1:])
    if not code:
        print(__doc__); sys.exit(1)
    if statement not in _REPORT_MAP:
        print(f"  ⚠️  未知报表 '{statement}', 可选: balance/income/cashflow", file=sys.stderr)
        sys.exit(1)

    sym = resolve(code)
    if not sym:
        print(json.dumps({"error": f"无法解析代码: {code}"}, ensure_ascii=False))
        sys.exit(1)
    market = "hk" if sym["mkt_num"] == 116 else "us"

    if mode == "indicators":
        data = get_indicators(sym["secucode"], market, periods)
        result = {"symbol": sym, "indicators": data}
    else:
        data = get_statement(sym["secucode"], market, statement, periods)
        result = {"symbol": sym, "statement": statement, "rows": data}

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # 人读输出
    tag = f"{sym['name']} {sym['code']} ({sym['market']}, {sym['secucode']})"
    if mode == "indicators":
        print(f"\n  关键财务指标 — {tag}")
        if not data:
            print("  (无数据)")
        for rec in data:
            print(f"\n  ▎{rec.get('报告期', '?')}")
            for k, v in rec.items():
                if k != "报告期":
                    print(f"    {k}: {v}")
    else:
        print(f"\n  {statement} 财报科目 — {tag}")
        if not data:
            print("  (无数据)")
        cur = None
        for row in data:
            if row["report_date"] != cur:
                cur = row["report_date"]
                print(f"\n  ▎{cur} ({row.get('currency') or ''})")
            print(f"    {row['item']}: {row['amount']}"
                  + (f"  (同比 {row['yoy_pct']}%)" if row.get("yoy_pct") is not None else ""))


if __name__ == "__main__":
    main()
