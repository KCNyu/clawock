#!/usr/bin/env python3
"""现金派生：cash_usd / cash_hkd = 对账基线 + 此后 trades 现金流 + 存取款。

现金不再手填。改/补任何 trades 后跑此脚本重算各市场现金，再由 CASH_RECON 闸
(preflight_integrity.py, ERROR) 校验 stated == 派生值，防「加了仓位忘扣钱」双计。

  python3 scripts/data/recompute_cash.py            # 写回 portfolio.json
  python3 scripts/data/recompute_cash.py --dry-run  # 只打印差异不写

存取款：记进对应市场的 cash_adjustments[] = [{date, amount(+存/-取), note}]，
amount 单位同该市场货币；或直接抬高 cash_reconciled + cash_reconciled_date 重新对账。
无 cash_reconciled 基线的市场（如 HK 现金未跟踪）自动跳过。
"""
import sys
from pathlib import Path

# The checkout root, so `clawock` resolves from the tree this file ships
# in. Reached through the scripts/data/workspace shim until #267 step 3,
# whose only remaining job was inserting this path as a side effect.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from clawock.workspace import workspace_root  # noqa: E402

# Code lives in the checkout; only DATA lives in the workspace. `workspace_root`
# is overridable, so resolving our own modules through WS would read them out of
# someone else's data directory — or silently pick up whatever happens to be
# there. Same expression WS is seeded from, kept separate on purpose (#269).
_CHECKOUT = Path(__file__).resolve().parents[2]
WS = workspace_root(Path(__file__).resolve().parents[2])
sys.path.insert(0, str(_CHECKOUT / 'scripts' / 'data'))

from preflight_integrity import derive_cash  # noqa: E402
from safe_io import mutate_json  # noqa: E402

PORTFOLIO = WS / 'portfolio.json'
CASH_FIELD = {'us_stocks': 'cash_usd', 'hk_stocks': 'cash_hkd'}


def recompute(dry_run=False):
    changes = []

    def _mut(data):
        for region, port in (data.get('portfolios') or {}).items():
            if not isinstance(port, dict):
                continue
            field = CASH_FIELD.get(region)
            if not field:
                continue
            der = derive_cash(port)
            if der is None:
                continue  # 无基线，跳过
            derived, baseline, bdate, n_tr = der
            old = port.get(field)
            changes.append((region, field, old, derived, baseline, bdate, n_tr))
            if not dry_run:
                port[field] = derived
        return data

    if dry_run:
        import json
        _mut(json.loads(PORTFOLIO.read_text()))
    else:
        mutate_json(str(PORTFOLIO), _mut)
    return changes


def main(argv):
    dry = '--dry-run' in argv
    changes = recompute(dry_run=dry)
    if not changes:
        print('无可派生现金的市场（缺 cash_reconciled 基线）')
        return 0
    for region, field, old, new, baseline, bdate, n_tr in changes:
        oldf = f'{old:.2f}' if isinstance(old, (int, float)) else str(old)
        mark = '（不变）' if isinstance(old, (int, float)) and abs(old - new) <= 0.01 else f'→ {new:.2f} ⚠'
        print(f'{region:9s} {field}: {oldf} {mark}  '
              f'[基线 {baseline:.2f}@{bdate} + {n_tr} 笔成交]')
    print('（dry-run，未写入）' if dry else '✓ 已写回 portfolio.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
