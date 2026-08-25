#!/usr/bin/env python3
"""KCNyu 黄金定投对账：一行命令更新基线，自动累加随即归零重算。

自动累加模式下(见 `clawock-gold-fetch`)，每个 A 股交易日按当日净值自动 +200 估算。
日子久了 T+1 确认 / 跳过日会累积小偏差，所以每隔几周用真实账户数字对一次账：
本脚本把 portfolio.json['gold_dca'] 的三个基线字段
  principal_invested / units_held / reconciled_date
改成你给的真实数字 + 对账当天，自动累加部分即从这天重新算起。

两种输入(二选一)：
  # A) 直接给本金 + 份额（账户里有确切份额时最准）
  clawock-gold-update --principal 17299 --units 4854.55

  # B) 像平时那样报「现值 + 盈亏」，份额用最新净值自动反推
  clawock-gold-update --value 15470 --pnl -1829
  #    可加 --nav 3.1867 指定净值（默认拉最新）

可选：
  --date 2026-06-09   对账日（默认今天 HKT）
  --no-refresh        只改基线，不重建 dashboard
  --publish           改完直接 commit(KCNyu) + safe_push 上线
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from clawock.safe_io import safe_write_json
from clawock.workspace import workspace_root

WS_ROOT = str(workspace_root(Path.cwd()))

PORTFOLIO = os.path.join(WS_ROOT, 'portfolio.json')


def latest_nav(code):
    from clawock.market_data.gold.fetch import fetch_nav_history
    hist = fetch_nav_history(code, pages=1)
    return (hist[-1][0], hist[-1][1]) if hist else (None, None)


def main():
    ap = argparse.ArgumentParser(description='黄金定投对账：更新基线本金/份额')
    ap.add_argument('--principal', type=float, help='累计投入本金（元）')
    ap.add_argument('--units', type=float, help='当前持有份额')
    ap.add_argument('--value', type=float, help='当前现值（元）— 配合 --pnl 反推')
    ap.add_argument('--pnl', type=float, help='当前盈亏（元，亏损为负）')
    ap.add_argument('--nav', type=float, help='反推用净值（默认拉最新）')
    ap.add_argument('--date', help='对账日 YYYY-MM-DD（默认今天 HKT）')
    ap.add_argument('--no-refresh', action='store_true', help='不重建 dashboard')
    ap.add_argument('--publish', action='store_true', help='改完 commit+safe_push 上线')
    a = ap.parse_args()

    pf = json.load(open(PORTFOLIO, encoding='utf-8'))
    g = pf.get('gold_dca')
    if not g:
        print('FATAL: portfolio.json 无 gold_dca，先跑 clawock-gold-fetch 初始化', file=sys.stderr)
        return 1

    # ── 解析输入：A) principal+units  或  B) value+pnl(+nav) ──
    if a.principal is not None and a.units is not None:
        principal, units = a.principal, a.units
        basis = f'直接给定 本金{principal:.0f}/份额{units:.2f}'
    elif a.value is not None and a.pnl is not None:
        nav_date, nav = (None, a.nav) if a.nav else latest_nav(g['fund_code'])
        if not nav:
            print('FATAL: 反推需要净值，--nav 没给且最新净值抓取失败', file=sys.stderr)
            return 1
        principal = a.value - a.pnl            # pnl 亏损为负 → 本金 = 现值 - 盈亏
        units = a.value / nav
        basis = f'由 现值{a.value:.0f}/盈亏{a.pnl:+.0f} 反推（净值{nav:.4f}{"@" + nav_date if nav_date else ""}）→ 本金{principal:.0f}/份额{units:.2f}'
    else:
        print('用法错误：需 (--principal 和 --units) 或 (--value 和 --pnl) 二选一', file=sys.stderr)
        ap.print_usage(sys.stderr)
        return 2

    if principal <= 0 or units <= 0:
        print(f'FATAL: 本金/份额必须为正（principal={principal}, units={units}）', file=sys.stderr)
        return 1

    rdate = a.date or datetime.now(ZoneInfo('Asia/Hong_Kong')).strftime('%Y-%m-%d')
    avg = principal / units

    # ── 改基线（仅这三个字段；其余 fetch_gold_dca 重算）──
    old = (g.get('principal_invested'), g.get('units_held'), g.get('reconciled_date'))
    g['principal_invested'] = round(principal, 2)
    g['units_held'] = round(units, 4)
    g['reconciled_date'] = rdate
    pf['gold_dca'] = g
    safe_write_json(PORTFOLIO, pf)

    print('黄金定投对账完成')
    print(f'  依据：{basis}')
    print(f'  基线：本金 {old[0]}→{principal:,.0f}  份额 {old[1]}→{units:,.2f}  '
          f'对账日 {old[2]}→{rdate}')
    print(f'  平均成本 {avg:.4f}  （自动累加从 {rdate} 之后的交易日重新算起）')

    if not a.no_refresh:
        print('  刷新净值 + 重建 dashboard…')
        subprocess.run(
            [sys.executable, '-m', 'clawock.market_data.gold.fetch'], check=False)
        # Rebuilt so this host's copy is current; NOT staged. The four outputs
        # left the repository in #314 — the scheduled publisher puts them on the
        # data branch, at most 20 minutes behind this commit.
        subprocess.run([sys.executable, '-m', 'clawock', 'dashboard-build'],
                       check=False, stdout=subprocess.DEVNULL)

    if a.publish:
        print('  提交 + 推送上线…')
        os.chdir(WS_ROOT)
        # Each step's exit status is real: a commit or push that fails must
        # surface as a failed DCA reconciliation, not a silent no-op (#848).
        failed = False
        for cmd in (
            ['git', 'add', 'portfolio.json'],
            ['git', 'commit', '-q', '-m', f'gold: 定投对账 {rdate}（本金{principal:.0f}/份额{units:.0f}）'],
            ['bash', os.path.join(WS_ROOT, 'ops/publish/safe_push.sh')],
        ):
            result = subprocess.run(cmd)
            if result.returncode != 0:
                print(f'  ✗ 步骤失败 (exit {result.returncode}): {" ".join(cmd)}',
                      file=sys.stderr)
                failed = True
                break
        if failed:
            return 2
    else:
        print('  未推送。要上线：git add portfolio.json && '
              'git commit + bash ops/publish/safe_push.sh（或加 --publish）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
