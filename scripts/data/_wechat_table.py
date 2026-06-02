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
W_TODAY_A = 7
W_PNL_P  = 6
W_PNL_A  = 7


def _money(x) -> str:
    return f'{x:+,.0f}'


def render_holdings_table(rows: List[Dict], currency: str = '',
                          today_abs: bool = False) -> List[str]:
    """Render a 7-col WeChat-friendly markdown holdings table.

    Two layouts (both 7-col, fit mobile WeChat without wrapping):
      default  → `代码|股|成本|现价|今日|浮%|浮$`  (63 vw, the 2026-05-21 canonical)
                 used by brief + staged reports (开/午/午后/收盘).
      today_abs=True → `代码|股|现价|今日%|今日$|浮%|浮$`  (64 vw)
                 used ONLY by intraday 盯盘 — it wants the per-holding absolute
                 今日$. Adding 今日$ on TOP of the original 7 cols → 73 vw which
                 wrapped/broke on mobile WeChat (kcn 2026-06-02), so the intraday
                 variant drops the static 成本 column (kcn knows his basis; 浮%
                 already encodes cost-relative P&L) to stay narrow. The Telegram
                 backup renders this same intraday table as a mobile-nice image.

    rows: each dict has code, shares, cost, price, today_pct, today_abs,
          pnl_pct, pnl_abs (unused keys per layout are simply ignored).
    currency: kept for backward-compat. We do NOT emit a unit-note line — WeChat
              不渲染 markdown italic and the currency is implicit in the 市值 line.
    """
    _ = currency  # intentionally unused
    # Column spec: (header, visual_width, align 'l'|'r', value-fn-from-row).
    if today_abs:
        spec = [
            ('代码',  W_CODE,    'l', lambda r: str(r['code'])),
            ('股',    W_SHARES,  'r', lambda r: str(r['shares'])),
            ('现价',  W_PRICE,   'r', lambda r: f"{r['price']:,.2f}"),
            ('今日%', W_TODAY,   'r', lambda r: f"{r.get('today_pct', 0.0):+.1f}%"),
            ('今日$', W_TODAY_A, 'r', lambda r: _money(r.get('today_abs', 0.0))),
            ('浮%',   W_PNL_P,   'r', lambda r: f"{r.get('pnl_pct', 0.0):+.1f}%"),
            ('浮$',   W_PNL_A,   'r', lambda r: _money(r.get('pnl_abs', 0.0))),
        ]
    else:
        spec = [
            ('代码', W_CODE,   'l', lambda r: str(r['code'])),
            ('股',   W_SHARES, 'r', lambda r: str(r['shares'])),
            ('成本', W_COST,   'r', lambda r: f"{r['cost']:,.2f}" if r.get('cost') else '—'),
            ('现价', W_PRICE,  'r', lambda r: f"{r['price']:,.2f}"),
            ('今日', W_TODAY,  'r', lambda r: f"{r.get('today_pct', 0.0):+.1f}%"),
            ('浮%',  W_PNL_P,  'r', lambda r: f"{r.get('pnl_pct', 0.0):+.1f}%"),
            ('浮$',  W_PNL_A,  'r', lambda r: _money(r.get('pnl_abs', 0.0))),
        ]

    def _pad(text, w, a):
        return pad_left(text, w) if a == 'l' else pad_right(text, w)

    out: List[str] = []
    out.append('| ' + ' | '.join(_pad(h, w, a) for h, w, a, _ in spec) + ' |')
    # Separator — dashes per cell width + alignment colon (':' before for left
    # cols, after for right) — matches the original byte-for-byte.
    sep = [(':' + '-' * (w + 1)) if a == 'l' else ('-' * (w + 1) + ':')
           for _, w, a, _ in spec]
    out.append('|' + '|'.join(sep) + '|')
    for r in rows:
        out.append('| ' + ' | '.join(_pad(fn(r), w, a) for _, w, a, fn in spec) + ' |')

    # Self-check: header / separator / each data row must split to the same
    # number of pipe segments. Catches regressions in this builder itself.
    seg_counts = {line.count('|') for line in out}
    if len(seg_counts) != 1:
        raise AssertionError(
            f'_wechat_table: pipe-segment counts diverge across rows ({seg_counts}); '
            f'header/sep/data must be identical column count.'
        )
    return out
