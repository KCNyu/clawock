#!/usr/bin/env python3
"""
浏览器侧「切到 Decision Mind tab」基线测量(#702 plan v2 Phase 0.5 归因闸)。

DSH 的 conversation.view ring 没有 keep-alive(`only: active.id`):每次从别的
tab 切回 Decision Mind 都是一次全新 mount(重新 remote 拉取 + 重新渲染)。
本脚本量化这一次切换的成本。

测量定义(审计定稿):
  - 首帧 = click(tab) → 首个 `.dmt .cell` attached + 双 rAF settle;
  - longtask:切换窗口内 >100ms 的长任务(PerformanceObserver);
  - loading 帧:切换窗口内 `.dmt` 出现「正在加载」文本的 DOM 变更次数
    (MutationObserver)——缓存命中路径应恒为 0;
  - cell 数:挂载后 `.dmt .cell` 数量(默认折叠应 ≤ 最近 3 组的量)。

用法:
  python3 tests/bench/measure_tab_switch.py [url] [session-substr] [rounds]

默认 url=http://127.0.0.1:3081/(本机 dsh.service),session 用侧栏首个匹配
行,rounds=5(1 次冷切 + N-1 次「Trajectory→Decision Mind」热切)。
Chromium 用 playwright 缓存 build(executable_path),snap/wrapper 版在本机
沙箱下无法启动。
"""
import json
import os
import sys
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:3081/'
# A session is picked positionally, not by title. Pinning a name here meant
# pinning "hi1h" — the sidebar renders title + relative age, so the string rots
# within the hour and the benchmark the baseline tells you to re-run with just
# times out. Pass an explicit substring only when you need a specific session.
SESSION = sys.argv[2] if len(sys.argv) > 2 else None
ROUNDS = max(1, int(sys.argv[3])) if len(sys.argv) > 3 else 5
CHROMIUM = os.path.expanduser('~/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome')

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROMIUM, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1440, 'height': 1100})
    page.goto(URL, wait_until='domcontentloaded', timeout=30000)
    page.wait_for_timeout(2500)
    rows = page.locator('[class*=sessionRow]')
    if SESSION:
        rows = rows.filter(has_text=SESSION)
    if rows.count() == 0:
        raise SystemExit('no session rows in the sidebar — is dsh serving %s ?' % URL)
    rows.first.click()
    page.wait_for_timeout(3500)

    page.evaluate("""() => {
      window.__perf = { longtasks: [], loadingFrames: 0 };
      new PerformanceObserver((l) => {
        for (const e of l.getEntries()) window.__perf.longtasks.push(Math.round(e.duration));
      }).observe({ type: 'longtask', buffered: true });
      new MutationObserver(() => {
        const el = document.querySelector('.dmt');
        if (el && (el.textContent || '').includes('正在加载')) window.__perf.loadingFrames += 1;
      }).observe(document.body, { childList: true, subtree: true });
    }""")

    def switch_to_dm():
        page.evaluate("""() => {
          window.__perf.longtasks = [];
          window.__perf.loadingFrames = 0;
          performance.clearMarks('dm-switch-start');
          performance.mark('dm-switch-start');
        }""")
        page.get_by_text('Decision Mind', exact=True).first.click()
        page.wait_for_selector('.dmt .cell', state='attached', timeout=20000)
        return page.evaluate("""() => new Promise((r) => {
          requestAnimationFrame(() => requestAnimationFrame(() => {
            const m = performance.getEntriesByName('dm-switch-start')[0];
            r({
              ms: Math.round((performance.now() - m.startTime) * 10) / 10,
              cells: document.querySelectorAll('.dmt .cell').length,
              longtasks: window.__perf.longtasks,
              loadingFrames: window.__perf.loadingFrames,
            });
          }));
        })""")

    results = [{'label': 'cold', **switch_to_dm()}]
    for i in range(1, ROUNDS):
        page.get_by_text('Trajectory', exact=True).first.click()
        page.wait_for_timeout(1200)
        results.append({'label': f'warm{i}', **switch_to_dm()})

    print(json.dumps(results, indent=1, ensure_ascii=False))
    browser.close()
