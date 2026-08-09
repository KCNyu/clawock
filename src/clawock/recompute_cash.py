#!/usr/bin/env python3
"""Derive each portfolio book's cash from its reconciliation ledger.

Cash is a derived value: reconciled baseline + later trade cash flow + later
deposits/withdrawals. The integrity gate verifies the same formula.

  clawock cash            # rewrite portfolio.json
  clawock cash --dry-run  # print differences without writing

Books without a `cash_reconciled` baseline are skipped.
"""
import argparse
import json
from pathlib import Path

from clawock.portfolio_math import derive_cash
from clawock.safe_io import mutate_json
from clawock.workspace import workspace_root

WS = workspace_root(Path.cwd())
PORTFOLIO = WS / 'portfolio.json'
POLICY = WS / 'config' / 'portfolio-derivations.json'


def load_policy(path=POLICY):
    """Load optional book-to-cash-field bindings owned by the workspace."""
    try:
        payload = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    configured = payload.get('cash_field_by_book', {})
    if not isinstance(configured, dict):
        return {}
    return {
        str(book): field
        for book, field in configured.items()
        if isinstance(field, str) and field.startswith('cash_')
    }


def cash_field(book_name, book, configured=None):
    configured = configured or {}
    if book_name in configured:
        return configured[book_name]
    currency = book.get('currency')
    if isinstance(currency, str) and currency.strip():
        return f"cash_{currency.strip().lower()}"
    return None


def recompute(dry_run=False, *, portfolio_path=PORTFOLIO, cash_fields=None):
    changes = []

    def _mut(data):
        for region, port in (data.get('portfolios') or {}).items():
            if not isinstance(port, dict):
                continue
            field = cash_field(region, port, cash_fields)
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
        _mut(json.loads(Path(portfolio_path).read_text()))
    else:
        mutate_json(str(portfolio_path), _mut)
    return changes


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--path', type=Path, default=PORTFOLIO)
    parser.add_argument('--config', type=Path, default=POLICY)
    args = parser.parse_args(argv)
    dry = args.dry_run
    changes = recompute(
        dry_run=dry,
        portfolio_path=args.path,
        cash_fields=load_policy(args.config),
    )
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
    raise SystemExit(main())
