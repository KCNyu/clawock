#!/usr/bin/env python3
"""
fetch_fundflow_em.py - 东财 push2his 日级资金流 (美股 + 港股, 无 key)

Adapted and modified from global-stock-data
(https://github.com/simonlin1212/global-stock-data, Apache-2.0). See NOTICE.

主力/超大单/大单/中单/小单净流入 (元) + 主力净占比，按日提供给
外部分析流程使用。

数据源: push2his.eastmoney.com。
⚠️ 可用性：push2his 在当前服务器返回 000，本脚本会优雅返回空 []，故未接入 skill。

Usage:
  clawock fundflow AAPL              # 近 20 日资金流
  clawock fundflow 00700 --days 10
  clawock fundflow BABA --days 30 --json
"""
import json
import sys
from typing import Dict, List

from clawock._em_http import em_get
from clawock._em_symbols import resolve

FFLOW_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"


def get_fund_flow(secid: str, days: int = 20) -> List[Dict]:
    """近 N 日资金流。空/失败静默返回 []，永不抛。"""
    params = {
        "secid": secid, "klt": 101,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "lmt": days,
    }
    r = em_get(FFLOW_URL, params=params, label="push2his fflow")
    if r is None:
        return []
    try:
        klines = ((r.json() or {}).get("data") or {}).get("klines") or []
    except ValueError:
        return []

    out = []
    for line in klines:
        p = line.split(",")
        if len(p) < 6:
            continue
        # f51=日期 f52=主力 f53=小单 f54=中单 f55=大单 f56=超大单 (f57=主力净占比%)
        def _f(idx):
            try:
                return float(p[idx])
            except (ValueError, IndexError):
                return None
        out.append({
            "date": p[0],
            "main_net": _f(1),       # 主力净流入(元)
            "small_net": _f(2),
            "mid_net": _f(3),
            "big_net": _f(4),
            "super_big_net": _f(5),
            "main_pct": _f(6),       # 主力净占比%
        })
    return out


def _parse_args(argv):
    code = None
    days = 20
    as_json = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--days" and i + 1 < len(argv):
            try:
                days = max(1, int(argv[i + 1]))
            except ValueError:
                pass
            i += 1
        elif a == "--json":
            as_json = True
        elif not a.startswith("-"):
            code = a
        i += 1
    return code, days, as_json


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    code, days, as_json = _parse_args(argv)
    if not code:
        print(__doc__)
        return 1

    sym = resolve(code)
    if not sym:
        print(json.dumps({"error": f"无法解析代码: {code}"}, ensure_ascii=False))
        return 1

    flows = get_fund_flow(sym["secid"], days)
    result = {"symbol": sym, "fund_flow": flows}

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"\n  资金流 — {sym['name']} {sym['code']} ({sym['market']})  近 {len(flows)} 日")
    if not flows:
        print("  (无数据)")
        return 0
    print(f"  {'日期':<12} {'主力净':>14} {'超大单':>14} {'大单':>14} {'主力占比%':>10}")
    for f in flows:
        def _m(v):  # 元 → 万元, 易读
            return f"{v/1e4:,.0f}万" if isinstance(v, (int, float)) else "-"
        print(f"  {f['date']:<12} {_m(f['main_net']):>14} {_m(f['super_big_net']):>14} "
              f"{_m(f['big_net']):>14} {str(f.get('main_pct','-')):>10}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
