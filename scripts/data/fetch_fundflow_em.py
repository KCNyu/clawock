#!/usr/bin/env python3
"""
fetch_fundflow_em.py - 东财 push2his 日级资金流 (美股 + 港股, 无 key)

Adapted from global-stock-data (https://github.com/simonlin1212/global-stock-data, Apache-2.0).

主力/超大单/大单/中单/小单 净流入 (元) + 主力净占比, 按日。openclaw 此前无资金流数据,
可作个股分析辅助 / 因子层候选信号。

数据源: push2his.eastmoney.com。
⚠️ 可用性: push2his 在 kcn 服务器 IP 上被封 (2026-06-14 实测几次请求后 000)，
   本脚本在该机上会优雅返回空 []。换网络环境 / 别的 IP 可用。故未接入 skill。

Usage:
  python3 fetch_fundflow_em.py AAPL              # 近 20 日资金流
  python3 fetch_fundflow_em.py 00700 --days 10
  python3 fetch_fundflow_em.py BABA --days 30 --json
"""
import json
import os
import sys
import time
from typing import Dict, List

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _em_symbols import resolve  # noqa: E402

FFLOW_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
TIMEOUT = 15


def get_fund_flow(secid: str, days: int = 20, retries: int = 3) -> List[Dict]:
    """近 N 日资金流。空/失败静默返回 []，永不抛。"""
    params = {
        "secid": secid, "klt": 101,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "lmt": days,
    }
    for attempt in range(retries):
        try:
            r = requests.get(FFLOW_URL, params=params,
                             headers={"User-Agent": UA}, timeout=TIMEOUT)
            r.raise_for_status()
            data = (r.json() or {}).get("data") or {}
            klines = data.get("klines") or []
            break
        except (requests.RequestException, ValueError) as e:
            if attempt == retries - 1:
                print(f"  ⚠️  东财 push2his 失败: {e}", file=sys.stderr)
                return []
            time.sleep(0.8 * (attempt + 1))
    else:
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
        if a == "--days":
            days = int(argv[i + 1]); i += 1
        elif a == "--json":
            as_json = True
        elif not a.startswith("-"):
            code = a
        i += 1
    return code, days, as_json


def main():
    code, days, as_json = _parse_args(sys.argv[1:])
    if not code:
        print(__doc__); sys.exit(1)

    sym = resolve(code)
    if not sym:
        print(json.dumps({"error": f"无法解析代码: {code}"}, ensure_ascii=False))
        sys.exit(1)

    flows = get_fund_flow(sym["secid"], days)
    result = {"symbol": sym, "fund_flow": flows}

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"\n  资金流 — {sym['name']} {sym['code']} ({sym['market']})  近 {len(flows)} 日")
    if not flows:
        print("  (无数据)")
        return
    print(f"  {'日期':<12} {'主力净':>14} {'超大单':>14} {'大单':>14} {'主力占比%':>10}")
    for f in flows:
        def _m(v):  # 元 → 万元, 易读
            return f"{v/1e4:,.0f}万" if isinstance(v, (int, float)) else "-"
        print(f"  {f['date']:<12} {_m(f['main_net']):>14} {_m(f['super_big_net']):>14} "
              f"{_m(f['big_net']):>14} {str(f.get('main_pct','-')):>10}")


if __name__ == "__main__":
    main()
