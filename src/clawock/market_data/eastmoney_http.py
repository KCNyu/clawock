#!/usr/bin/env python3
"""
_em_http.py — 东财 (Eastmoney) 统一 HTTP 出口：串行节流 + 抖动 + Session 复用。

参考 simonlin1212/a-stock-data 的 em_get() 请求节流结构（Apache-2.0），并由
clawock contributors 修改；署名与许可证见仓库 NOTICE。所有东财调用统一走本模块：
  1) 进程内串行 —— 相邻请求间隔 >= MIN_INTERVAL 秒 (线程锁保护, 多线程也安全);
  2) 请求抖动 —— 每次额外 0..JITTER 秒，避免固定时刻形成突发流量;
  3) 单 Session 连接复用 —— 复用 TCP/TLS，减少连接开销。

用法:
    from clawock.market_data.eastmoney_http import em_get
    r = em_get(url, params={...}, label="datacenter")
    if r is None:            # 网络失败 / 重试耗尽 —— 调用方优雅降级 (返回 [] 等)
        ...
    data = r.json()          # 或 r.text (jsonp)

环境变量:
    EM_MIN_INTERVAL   相邻请求最小间隔秒 (默认 1.0)
    EM_JITTER         额外随机抖动上限秒 (默认 0.5)

⚠️ 限速是"进程内"的:每个脚本是独立进程,各自维护自己的节流器。这与源仓库设计一致
   (em_get 是进程内串行器),对我们"一个 fetcher 一个进程"的用法足够;若将来多个东财
   fetcher 并发跑,仍受各自 IP 总频率约束,必要时再上跨进程锁 (flock)。
"""
import os
import random
import sys
import threading
import time
from typing import Optional

import requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
TIMEOUT = 15
MIN_INTERVAL = float(os.environ.get("EM_MIN_INTERVAL", "1.0"))
JITTER = float(os.environ.get("EM_JITTER", "0.5"))
RETRIES = 3

_lock = threading.Lock()
_last_call = 0.0
_session: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA})
        _session = s
    return _session


def _throttle() -> None:
    """确保相邻东财请求间隔 >= MIN_INTERVAL + 随机抖动 (线程锁串行)。"""
    global _last_call
    with _lock:
        gap = time.time() - _last_call
        if gap < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - gap)
        if JITTER > 0:
            time.sleep(random.uniform(0, JITTER))
        _last_call = time.time()


def em_get(url, params=None, headers=None, timeout=TIMEOUT,
           retries=RETRIES, label="eastmoney") -> Optional[requests.Response]:
    """限速 + 重试的东财 GET。全部重试失败返回 None(永不抛),调用方负责降级。"""
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    sess = _get_session()
    for attempt in range(retries):
        _throttle()
        try:
            r = sess.get(url, params=params, headers=h, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if attempt == retries - 1:
                print(f"  ⚠️  东财 {label} 失败 ({retries}次重试耗尽): {e}",
                      file=sys.stderr)
                return None
            time.sleep(0.8 * (attempt + 1))
    return None


if __name__ == "__main__":
    # 冒烟：连打 3 次，确认间隔 >= MIN_INTERVAL + 抖动
    import json as _json
    t0 = time.time()
    for i in range(3):
        r = em_get("https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
                   params={"secid": "116.00700", "klt": 101,
                           "fields1": "f1,f2", "fields2": "f51,f52", "lmt": 3},
                   label="smoke")
        dt = time.time() - t0
        ok = r is not None and (r.json() or {}).get("data") is not None if r else False
        print(f"  call#{i+1}  t+{dt:5.2f}s  status={'OK' if r else 'None'}")
    print(f"  MIN_INTERVAL={MIN_INTERVAL}s JITTER={JITTER}s")
