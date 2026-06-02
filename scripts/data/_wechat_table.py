"""
_wechat_table.py — visual-width-aware markdown table renderer.

WeChat 移动端不渲染 markdown table，只显示原始 monospace 文本。CJK 字符
在 monospace 字体下视觉宽度 = 2 个 ASCII 字符。该 helper 用 visual width
做 padding，确保表格在 mobile/desktop WeChat 上每行视觉宽度一致 —— 即使
被强制换行，wrap 出来的子串也对齐。

用法：
    from _wechat_table import render_holdings_table

    rows = [
        {'code': '00100', 'shares': 60, 'cost': 822.83, 'price': 722.00,
         'today_pct': 5.1, 'pnl_pct': -12.2, 'pnl_abs': -6049.8},
        ...
    ]
    print('\\n'.join(render_holdings_table(rows, currency='HKD')))
"""

from typing import Dict, List, Optional


def vw(s: str) -> int:
    """Visual width: CJK = 2, ASCII = 1. Matches WeChat monospace rendering."""
    return sum(2 if ord(c) > 127 else 1 for c in s)


def pad_right(s: str, width: int) -> str:
    """Right-align in visual width (left-pad with spaces)."""
    return ' ' * max(0, width - vw(s)) + s


def pad_left(s: str, width: int) -> str:
    """Left-align in visual width (right-pad with spaces)."""
    return s + ' ' * max(0, width - vw(s))


# Cell content widths (visual). Chosen to fit max expected portfolio values.
# code: 5-char HK / 4-char US tickers
# shares: up to 99999 (current max ~6200 on 07226)
# cost/price: 999.99 fits in 6 chars; numbers ≥ 1000 use compact ',' format
# today/pnl_pct: "+12.3%" 6 vw; "-100.0%" rare 7
# pnl_abs: "-10,050" 7 vw
W_CODE   = 5
W_SHARES = 5
W_COST   = 6
W_PRICE  = 6
W_TODAY  = 6
W_PNL_P  = 6
W_PNL_A  = 7


def render_holdings_table(rows: List[Dict], currency: str = '') -> List[str]:
    """Render a 7-col WeChat-friendly markdown holdings table.

    Returns list of strings (no trailing newline). Caller joins with '\\n'.

    rows: each dict has keys code, shares, cost, price, today_pct, pnl_pct, pnl_abs.
    currency: kept for backward-compat / future use. We do NOT emit a unit-note
              line because: (1) WeChat 不渲染 markdown italic, the raw `_...._`
              looked ugly and LLM verbatim-trimmed it; (2) the currency is already
              implicit via the 市值 line above the table (HK$xxx / $xxx).
    """
    _ = currency  # intentionally unused
    out: List[str] = []
    # Header — left-align code, right-align rest. All widths in visual chars.
    out.append(
        '| ' + pad_left('代码', W_CODE) +
        ' | ' + pad_right('股',   W_SHARES) +
        ' | ' + pad_right('成本', W_COST) +
        ' | ' + pad_right('现价', W_PRICE) +
        ' | ' + pad_right('今日', W_TODAY) +
        ' | ' + pad_right('浮%',  W_PNL_P) +
        ' | ' + pad_right('浮$',  W_PNL_A) + ' |'
    )
    # Separator — dashes per cell width + alignment colon.
    out.append(
        '|:'  + '-' * (W_CODE   + 1) +
        '|'   + '-' * (W_SHARES + 1) + ':' +
        '|'   + '-' * (W_COST   + 1) + ':' +
        '|'   + '-' * (W_PRICE  + 1) + ':' +
        '|'   + '-' * (W_TODAY  + 1) + ':' +
        '|'   + '-' * (W_PNL_P  + 1) + ':' +
        '|'   + '-' * (W_PNL_A  + 1) + ':|'
    )
    for r in rows:
        code      = str(r['code'])
        shares    = r['shares']
        cost      = r.get('cost')
        price     = r['price']
        today_pct = r.get('today_pct', 0.0)
        pnl_pct   = r.get('pnl_pct', 0.0)
        pnl_abs   = r.get('pnl_abs', 0.0)

        cost_s  = f'{cost:,.2f}'   if cost  else '—'
        price_s = f'{price:,.2f}'
        today_s = f'{today_pct:+.1f}%'
        pnlp_s  = f'{pnl_pct:+.1f}%'
        pnla_s  = f'{pnl_abs:+,.0f}'

        out.append(
            '| ' + pad_left(code,        W_CODE) +
            ' | ' + pad_right(str(shares), W_SHARES) +
            ' | ' + pad_right(cost_s,    W_COST) +
            ' | ' + pad_right(price_s,   W_PRICE) +
            ' | ' + pad_right(today_s,   W_TODAY) +
            ' | ' + pad_right(pnlp_s,    W_PNL_P) +
            ' | ' + pad_right(pnla_s,    W_PNL_A) + ' |'
        )
    # Self-check: header / separator / each data row must split to the same
    # number of pipe segments. Catches regressions in this builder itself.
    seg_counts = {line.count('|') for line in out}
    if len(seg_counts) != 1:
        raise AssertionError(
            f'_wechat_table: pipe-segment counts diverge across rows ({seg_counts}); '
            f'header/sep/data must be identical column count.'
        )
    return out
