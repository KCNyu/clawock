"""The intraday card kcn reads, rendered from structured slot data.

kcn 2026-10-19: the old card was the analyzer's text with sections spliced in
and rewritten pass by pass (变化 lead, ↑ pointer, ▎持续状态, 🛰️ 加仓侧 …); it
answered "what changed" in five places and "what do I do" in none. This card
is built from the slot's structured data, in the order a reader asks:

    title + book line
    ⛔ data health            only when something is degraded
    **⚠️ 待你处理**           P0 questions, unfilled plan orders, broken plan lines,
                              a stop newly broken today, the T+0 order if any
    **本档变化**              each new mover with its underlying and news status,
                              T+0 / observation changes, new primary information
    holdings table            the analyzer's table, byte for byte
    **接下来盯**              setups and candidates; postflight adds 下一触发
    **加仓侧**                only rows that are not a plain 等待
    **我的看法**              the model's judgment (postflight)

WeChat renders markdown bold, tables and lists; Telegram gets the same text.
Everything the card leaves out stays in the context for the model
(`analyzer_block`, `leverage_legs`, `add_side_reads`, …).
"""
from __future__ import annotations

import re

ACTION = '**⚠️ 待你处理**'
CHANGES = '**本档变化**'
WATCH = '**接下来盯**'
ADD_SIDE = '**加仓侧**'
JUDGMENT = '**我的看法**'
SECTION_ORDER = (ACTION, CHANGES, WATCH, ADD_SIDE, JUDGMENT)
# A leveraged leg tracking its underlying within this gap is ordinary
# leverage; only a larger gap is worth a word.
LEVERAGE_GAP_PP = 1.0


def bullet(text: str) -> str:
    return f'• {text}'


def section(header: str, rows) -> list[str]:
    rows = [row for row in rows if row]
    return ['', header, *rows] if rows else []


# ── analyzer pieces ──────────────────────────────────────────────────────────

def split_analyzer(block: str) -> dict:
    """Title, book line and table lines out of the analyzer's text."""
    lines = (block or '').splitlines()
    title = lines[0].strip() if lines else ''
    book = next((line.strip() for line in lines if line.strip().startswith('📊')), '')
    table = [line for line in lines if line.strip().startswith('|') and line.strip().endswith('|')]
    return {'title': title, 'book': book, 'table': table}


def title_line(title: str) -> str:
    """`🇺🇸 美股盯盘 | 10/19 11:04 ET` → `**🇺🇸 美股盯盘 · 10/19 11:04 ET**`."""
    return f"**{title.replace(' | ', ' · ')}**" if title else ''


def book_line(book: str) -> str:
    """The 📊 line in reading order: today's move first (bold), then the totals.

    `📊 市值 $3,318 | 浮盈 $-1,118 (-25.2%) | 今日 +$167 | ✅ 已实现 +$2,376`
    → `今日 **+$167**｜浮亏 -$1,118（-25.2%）｜市值 $3,318｜已实现 +$2,376`
    """
    chunks = re.split(r'\s*\|\s*', book.lstrip('📊').strip())

    def find(key):
        return next((chunk for chunk in chunks if key in chunk), None)

    out = []
    today = find('今日')
    if today:
        out.append(re.sub(r'(今日\s*)(\S+)', r'\1**\2**', today))
    pnl = find('浮盈')
    if pnl:
        match = re.search(r'浮盈\s*\$(-?)([\d,.]+)\s*\(([^)]*)\)', pnl)
        out.append(f"{'浮亏 -' if match.group(1) else '浮盈 +'}${match.group(2)}（{match.group(3)}）"
                   if match else pnl)
    for key in ('市值', '已实现'):
        chunk = find(key)
        if chunk:
            out.append(re.sub(r'^✅\s*', '', chunk))
    return '｜'.join(out) if out else book.lstrip('📊').strip()


# ── sections ─────────────────────────────────────────────────────────────────

def action_rows(*, p0_lines=(), open_orders=(), plan_trigger_rows=(), new_stops=(),
                standing_stops=()):
    """待你处理. `open_orders` are plan_surface order lines (`RKLX 清仓 10股｜开盘｜风控纪律`)."""
    rows = [bullet(line.replace('P0：', '')) for line in p0_lines]
    rows += [bullet(line) for line in plan_trigger_rows]
    ordered = set()
    for line in open_orders:
        ticker, _, rest = line.partition(' ')
        ordered.add(ticker)
        what, *how = rest.split('｜')
        rows.append(bullet(f"{ticker} {what}（{'·'.join(['计划', *how])}，还没成交）"))
    for ticker, detail in new_stops:
        if ticker not in ordered:
            rows.append(bullet(f'{ticker} 跌破止损线{detail}'))
    standing = [t for t in standing_stops if t not in ordered]
    if standing:
        rows.append(bullet('仍在止损线下：' + '、'.join(standing)))
    return rows


def mover_rows(movers, legs, news) -> list[str]:
    """One line per new mover: its move, the underlying, whether there is news."""
    legs = {leg['ticker']: leg for leg in legs or []}
    rows = []
    for ticker, pct in movers:
        bits = [f'{ticker} **{pct:+.1f}%**' if pct is not None else ticker]
        leg = legs.get(ticker)
        if leg:
            under = f"底层 {leg['underlying']} {leg['underlying_pct']:+.{leg.get('decimals', 1)}f}%"
            gap = leg.get('gap_pp')
            if gap is not None and abs(gap) >= LEVERAGE_GAP_PP:
                under += f"，杠杆偏离 {gap:+.1f}pp"
            bits.append(under)
        status = ((news or {}).get(ticker) or {}).get('status')
        if status in ('no_recent_filing', 'no_recent_disclosure'):
            bits.append('无新公告')
        elif status == 'has_recent_filing':
            bits.append('**有新公告**')
        rows.append(bullet('：'.join(bits[:1]) + ('：' + '，'.join(bits[1:]) if bits[1:] else '')))
    return rows


def soft_rows(changes) -> list[str]:
    """T+0 / observation-band changes, without the `（此前 …）` history."""
    out = []
    for text in changes or []:
        text = re.sub(r'（此前[^（）]*(?:（[^（）]*）[^（）]*)*）', '', text)
        text = re.sub(r'，此前报过[^）]*', '', text)
        text = text.replace('T+0 评级变为', 'T+0 转为').strip()
        out.append(bullet(text))
    return out


def setup_rows(setups) -> list[str]:
    rows = []
    for row in (setups or {}).get('rows') or []:
        if row.get('entry_price') is None:
            continue
        name = row.get('label_zh') or row.get('setup_id')
        text = f"{row['label']} 收盘站稳 {row['entry_price']:g} → {name}成立"
        if row.get('invalidation_price') is not None:
            text += f"；跌破 {row['invalidation_price']:g} 作废"
        rows.append(bullet(text))
    return rows


def section_rows(block_text: str) -> list[str]:
    """Rows of an older `◆`-style section (header dropped) as list items."""
    rows = []
    for line in (block_text or '').splitlines()[1:]:
        text = line.strip().lstrip('◆·').strip()
        if text:
            rows.append(bullet(re.sub(r'\s*\|\s*', '｜', text)))
    return rows


def render(*, analyzer: str, health=(), action=(), recommendation='', changes=(),
           watch=(), add_side=()) -> str:
    parts = split_analyzer(analyzer)
    lines = [title_line(parts['title'])]
    if parts['book']:
        lines.append(book_line(parts['book']))
    health = [line for line in health if line]
    if health:
        lines += ['', *health]
    lines += section(ACTION, action)
    if recommendation:
        lines += ['', recommendation]
    lines += section(CHANGES, changes or [bullet('本档无新变化')])
    if parts['table']:
        lines += ['', *parts['table']]
    lines += section(WATCH, watch)
    lines += section(ADD_SIDE, add_side)
    return '\n'.join(lines)


def add_watch_rows(card: str, rows) -> str:
    """Append rows to **接下来盯**, creating it before 加仓侧 / the end."""
    rows = [row for row in rows if row]
    if not rows:
        return card
    lines = card.split('\n')
    if WATCH in lines:
        at = lines.index(WATCH) + 1
        while at < len(lines) and lines[at].startswith('• '):
            at += 1
        lines[at:at] = rows
        return '\n'.join(lines)
    at = lines.index(ADD_SIDE) - 1 if ADD_SIDE in lines else len(lines)
    lines[at:at] = ['', WATCH, *rows]
    return '\n'.join(lines)
