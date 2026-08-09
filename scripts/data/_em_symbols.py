#!/usr/bin/env python3
"""
_em_symbols.py - 东财 (Eastmoney) ticker/代码 → secid / SECUCODE 解析

Shared helper for fetch_fundamentals_em.py + fetch_fundflow_em.py.
Adapted and modified from global-stock-data
(https://github.com/simonlin1212/global-stock-data, Apache-2.0). See NOTICE.

Resolution priority:
  1. 显式后缀直接解析: "AAPL.O" / "BABA.N" / "00700.HK"
  2. searchapi.eastmoney.com — 拿 QuoteID(=secid) + MktNum, 最可靠
  3. 启发式回退(search 失败时): 5位数字→港股116, 纯字母→美股(NASDAQ优先)

MktNum / secid 前缀:
  105 = 美股 NASDAQ (SECUCODE 后缀 .O)
  106 = 美股 NYSE   (SECUCODE 后缀 .N)
  107 = 美股 ETF/其他 (后缀 .O 尝试)
  116 = 港股        (SECUCODE 后缀 .HK)

零鉴权。endpoint 实测可达 (2026-06-14, kcn 服务器 IP)。
"""
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

_CHECKOUT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CHECKOUT))
sys.path.insert(0, str(_CHECKOUT / "src"))
from clawock._em_http import em_get  # noqa: E402  统一请求节流出口

SEARCH_URL = "https://searchapi.eastmoney.com/api/suggest/get"
# 公开 token(满网皆是,非密钥); 若失效会自动回退到启发式
SEARCH_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"

# MktNum → (市场名, SECUCODE 后缀)
_MKT = {
    "105": ("NASDAQ", ".O"),
    "106": ("NYSE", ".N"),
    "107": ("US_OTHER", ".O"),
    "116": ("HK", ".HK"),
}
# 显式后缀 → (mkt_num, 市场名)
_SUFFIX = {
    ".O": ("105", "NASDAQ"),
    ".N": ("106", "NYSE"),
    ".HK": ("116", "HK"),
}


def _make(code: str, mkt_num: str, name: str = "") -> Dict:
    market, suffix = _MKT.get(mkt_num, ("US_OTHER", ".O"))
    return {
        "code": code,
        "name": name,
        "mkt_num": int(mkt_num),
        "market": market,
        "secid": f"{mkt_num}.{code}",
        "secucode": f"{code}{suffix}",
    }


def search(keyword: str, count: int = 10) -> List[Dict]:
    """东财股票搜索 — 返回美股/港股候选。失败返回 []。"""
    r = em_get(SEARCH_URL, params={
        "input": keyword, "type": 14, "token": SEARCH_TOKEN, "count": count,
    }, label="search")
    if r is None:
        return []
    try:
        rows = (r.json().get("QuotationCodeTable") or {}).get("Data") or []
    except ValueError:
        return []

    out = []
    for s in rows:
        mkt = str(s.get("MktNum", ""))
        if mkt not in _MKT:
            continue
        out.append(_make(s.get("Code", ""), mkt, s.get("Name", "")))
    return out


def resolve(code: str, prefer: Optional[str] = None) -> Optional[Dict]:
    """ticker / 代码 → {code, name, mkt_num, market, secid, secucode}。

    prefer: "us" 或 "hk" — 多市场同名时的偏好(如 BABA 美股 vs 09988 港股)。
    解析不出返回 None(调用方自行报错)。
    """
    code = code.strip()

    # 1) 显式后缀
    for suffix, (mkt_num, _name) in _SUFFIX.items():
        if code.upper().endswith(suffix):
            base = code[: -len(suffix)]
            return _make(base, mkt_num)

    # 2) searchapi 精确匹配
    cands = search(code)
    if cands:
        exact = [c for c in cands if c["code"].upper() == code.upper()]
        pool = exact or cands
        if prefer == "hk":
            pool.sort(key=lambda c: c["mkt_num"] != 116)
        elif prefer == "us":
            pool.sort(key=lambda c: c["mkt_num"] == 116)
        return pool[0]

    # 3) 启发式回退
    if re.fullmatch(r"\d{4,5}", code):
        return _make(code.zfill(5), "116")
    if re.fullmatch(r"[A-Za-z.]{1,6}", code):
        return _make(code.upper(), "106" if prefer == "us_nyse" else "105")
    return None


if __name__ == "__main__":
    import json
    for q in sys.argv[1:] or ["00700", "AAPL", "BABA", "09988", "BABA.N"]:
        print(q, "→", json.dumps(resolve(q), ensure_ascii=False))
