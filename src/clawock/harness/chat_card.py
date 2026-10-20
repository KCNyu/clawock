"""Chat cards kcn reads (intraday, open/close reports), rendered from structured data.

kcn 2026-10-19: the old card was the analyzer's text with sections spliced in
and rewritten pass by pass (变化 lead, ↑ pointer, ▎持续状态, 🛰️ 加仓侧 …); it
answered "what changed" in five places and "what do I do" in none. This card
is built from the slot's structured data, in the order a reader asks:

    title, then today's P&L and the book/risk totals as two short lines
    ⛔ data health            only when something is degraded
    **⚠️ 待你处理**           P0 questions, unfilled plan orders, broken plan lines,
                              a stop newly broken today, the T+0 order if any
    **本档变化**              each new mover with its underlying and news status,
                              T+0 / observation changes, new primary information
    holdings table            the analyzer's table, byte for byte
    **接下来盯**              setups and candidates; postflight adds 下一触发
    **加仓侧**                only rows that are not a plain 等待
    **我的看法**              the model's judgment (postflight)

WeChat renders markdown bold, tables and lists but not headings: `## title`
arrives as literal `## ` in plain weight (kcn 2026-10-20), so every title here
is a whole-line bold. Telegram gets the same text.
Everything the card leaves out stays in the context for the model
(`analyzer_block`, `leverage_legs`, `add_side_reads`, …).
"""
from __future__ import annotations

import re

# Small bold labels, not emoji headings: in a 318px bubble six ### headers and
# their icons were most of what the eye saw (kcn 2026-10-19: 「太丑了」).
ACTION = '**待你处理**'
CHANGES = '**本档变化**'
WATCH = '**接下来盯**'
ADD_SIDE = '**加仓侧**'
JUDGMENT = '**我的看法**'
SECTION_ORDER = (ACTION, CHANGES, WATCH, ADD_SIDE, JUDGMENT)
# A leveraged leg tracking its underlying within this gap is ordinary
# leverage; only a larger gap is worth a word.
LEVERAGE_GAP_PP = 1.0


BULLET = '- '


def bullet(text: str) -> str:
    return f'{BULLET}{text}'


def level(price) -> str:
    """A price the reader acts on, set off as inline code."""
    return f'`{price:g}`' if isinstance(price, (int, float)) else f'`{price}`'


def ticker(name: str) -> str:
    return f'**{name}**'


def section(header: str, rows) -> list[str]:
    rows = [row for row in rows if row]
    return ['', header, *rows] if rows else []


# ── analyzer pieces ──────────────────────────────────────────────────────────

def split_analyzer(block: str) -> dict:
    """Title, index strip, book line and table lines out of the analyzer's text.

    The strip is whatever sits between the title and 📊 — HK's
    `恒指 24,321 ▲1.07%  恒科 4,130 ▲1.70%`; US has none."""
    lines = (block or '').splitlines()
    title = lines[0].strip() if lines else ''
    book = next((line.strip() for line in lines if line.strip().startswith('📊')), '')
    risk = next((line.strip() for line in lines if line.strip().startswith('📉')), '')
    table = [line for line in lines if line.strip().startswith('|') and line.strip().endswith('|')]
    strip = []
    for line in lines[1:]:
        if line.strip().startswith(('📊', '|')):
            break
        if line.strip():
            strip.append(line.strip())
    return {'title': title, 'strip': strip, 'book': book, 'risk': risk, 'table': table}


def title_line(title: str) -> str:
    """`🇺🇸 美股盯盘 | 10/19 11:04 ET` → `**🇺🇸 美股盯盘 · 10/19 11:04 ET**`.

    Shared by every chat card (intraday, reports, brief): a WeChat bubble does
    not render `#` headings, only bold."""
    title = title.replace(' | ', ' · ').replace('｜', ' · ').strip()
    return f'**{title}**' if title else ''


def summary_lines(book: str, risk: str = '') -> list[str]:
    """The 📊 and 📉 lines as two short lines: today's P&L first and bold, then
    the standing totals and risk (318px bubble: one long line wrapped mid-word).

    `📊 市值 $3,318 | 浮盈 $-1,118 (-25.2%) | 今日 +$167 | ✅ 已实现 +$2,376`
    + `📉 亏损持仓 3/4  |  杠杆ETF敞口 90%`
    → `**今日 +$167** · 浮亏 -$1,118（-25.2%）`
      `市值 $3,318 · 已实现 +$2,376 · 亏损持仓 3/4 · 杠杆ETF敞口 90%`
    """
    chunks = [c for c in re.split(r'\s*\|\s*', (book or '').lstrip('📊').strip()) if c]

    def find(key):
        return next((chunk for chunk in chunks if key in chunk), None)

    first, second = [], []
    today = find('今日')
    if today:
        first.append(f'**{today.strip()}**')
    pnl = find('浮盈')
    if pnl:
        # US: `浮盈 $-1,118 (-25.2%)`; HK: `浮盈 -61,313 (-53.5%)` (HK$ is in 市值).
        match = re.search(r'浮盈\s*(\$?)(-?)\$?([\d,.]+)\s*\(([^)]*)\)', pnl)
        first.append(f"{'浮亏 -' if match.group(2) else '浮盈 +'}{match.group(1)}{match.group(3)}"
                     f"（{match.group(4)}）" if match else pnl)
    for key in ('市值', '已实现'):
        chunk = find(key)
        if chunk:
            second.append(re.sub(r'^✅\s*', '', chunk))
    second += [c.replace('亏损持仓', '亏损').replace('杠杆ETF敞口', '杠杆')
               for c in re.split(r'\s*\|\s*', (risk or '').lstrip('📉').strip()) if c]
    known = {c for c in (today, pnl, find('市值'), find('已实现')) if c}
    second += [c for c in chunks if c not in known]
    return [' · '.join(part) for part in (first, second) if part]


# ── sections ─────────────────────────────────────────────────────────────────

def action_rows(*, p0_lines=(), open_orders=(), plan_trigger_rows=(), new_stops=(),
                standing_stops=()):
    """待你处理. `open_orders` are plan_surface order lines (`RKLX 清仓 10股｜开盘｜风控纪律`)."""
    rows = [bullet(line.replace('P0：', '')) for line in p0_lines]
    rows += [bullet(line) for line in plan_trigger_rows]
    ordered = set()
    for line in open_orders:
        name, _, rest = line.partition(' ')
        ordered.add(name)
        what, *how = rest.split('｜')
        how = [f'{h}单' if h in ('开盘', '收盘', '盘中') else h for h in how]
        # Everything under 待你处理 is unfilled by definition: no status chip.
        rows.append(bullet(f"{ticker(name)} {what} · {' · '.join(how or ['计划单'])}"))
    for name, detail in new_stops:
        if name not in ordered:
            rows.append(bullet(f"{ticker(name)} 跌破止损线{(' · ' + detail.strip('（）')) if detail else ''}"))
    standing = [t for t in standing_stops if t not in ordered]
    if standing:
        rows.append(bullet('仍在止损线下：' + '、'.join(ticker(t) for t in standing)))
    return rows


def mover_rows(movers, legs, news) -> list[str]:
    """One line per new mover: its move, the underlying, whether there is news."""
    legs = {leg['ticker']: leg for leg in legs or []}
    rows = []
    for name, pct in movers:
        bits = [f'**{name} {pct:+.1f}%**' if pct is not None else ticker(name)]
        leg = legs.get(name)
        if leg:
            if leg.get('underlying_pct') is None:
                under = f"{leg['underlying']} 今日涨跌本档未取到"
            else:
                under = f"{leg['underlying']} {leg['underlying_pct']:+.{leg.get('decimals', 1)}f}%"
                gap = leg.get('gap_pp')
                if gap is not None and abs(gap) >= LEVERAGE_GAP_PP:
                    under += f"（偏离 {gap:+.1f}pp）"
            bits.append(under)
        status = ((news or {}).get(name) or {}).get('status')
        if status in ('no_recent_filing', 'no_recent_disclosure'):
            bits.append('无公告')
        elif status == 'has_recent_filing':
            bits.append('**有公告**')
        rows.append(bullet(' · '.join(bits)))
    return rows


def soft_rows(changes) -> list[str]:
    """T+0 / observation-band changes, without the `（此前 …）` history."""
    out = []
    for text in changes or []:
        text = re.sub(r'（此前[^（）]*(?:（[^（）]*）[^（）]*)*）', '', text)
        text = re.sub(r'，此前报过[^）]*', '', text)
        text = text.replace('T+0 评级变为', 'T+0 转为').strip()
        out.append(bullet(re.sub(r'^([A-Z0-9]{2,6})(?=\s)', r'**\1**', text)))
    return out


def setup_rows(setups) -> list[str]:
    rows = []
    for row in (setups or {}).get('rows') or []:
        if row.get('entry_price') is None:
            continue
        name = row.get('label_zh') or row.get('setup_id')
        text = f"{ticker(row['label'])} {name} · 收盘站稳 {level(row['entry_price'])}"
        if row.get('invalidation_price') is not None:
            text += f" · 破 {level(row['invalidation_price'])} 作废"
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
    lines += summary_lines(parts['book'], parts['risk'])
    if parts['strip']:
        lines += ['', *parts['strip']]
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


def trigger_text(item: str) -> str:
    """A checked 下一触发 item in card style: leading ticker bold, levels as code."""
    item = re.sub(r'^([A-Z0-9]{2,6})(?=\s)', r'**\1**', item.strip())
    return re.sub(r'(?<![A-Za-z0-9_.`+*-])(\d+(?:,\d{3})*(?:\.\d+)?)(?![A-Za-z0-9_.%`*])', r'`\1`', item)


def quote(text: str) -> str:
    """Every line of `text` inside one blockquote (blank lines kept as `>`)."""
    return '\n'.join(f'> {line}' if line.strip() else '>' for line in text.strip().split('\n'))


def add_watch_rows(card: str, rows) -> str:
    """Append rows to **接下来盯**, creating it before 加仓侧 / the end."""
    rows = [row for row in rows if row]
    if not rows:
        return card
    lines = card.split('\n')
    if WATCH in lines:
        at = lines.index(WATCH) + 1
        while at < len(lines) and lines[at].startswith(BULLET):
            at += 1
        lines[at:at] = rows
        return '\n'.join(lines)
    at = lines.index(ADD_SIDE) - 1 if ADD_SIDE in lines else len(lines)
    lines[at:at] = ['', WATCH, *rows]
    return '\n'.join(lines)


# ── open / close reports ─────────────────────────────────────────────────────

SIGNALS = '**信号**'
NEWS = '**新闻**'
# Any leading glyph: US writes `▼ STOP-LOSS` / `△ WATCH` / `▽ TRIM`, HK
# `✋ STOP?` / `⚠️ ALERT` / `▲ HOLD+` (hk_analysis.signal, us_analysis.SIGNAL_COLOR).
_SIGNAL_LINE = re.compile(r'^[^\w\s]*\s*(STOP-LOSS|STOP\?|TAKE-PROFIT|TRIM|WATCH|ADD|[A-Z?+-]+)\s+(\S+)\s*\|?\s*(.*)$')


_NEWS_LINE = re.compile(r'📰(✅|⚠\ufe0f?)?\s*(\S+)\s*\((\d+)条\)')


def parse_report_block(block: str) -> dict:
    """The analyzer's report block, grouped. Lines it does not recognise are
    kept, in order, in `other` — the card reorganises, it never drops a line."""
    out = {'book': '', 'risk': '', 'table': [], 'signals': [], 'news': [], 'orders': [], 'other': []}
    lines = (block or '').splitlines()
    # The analyzer's own title (`🇺🇸 美股盯盘 | 10/19 09:34 ET`) repeats the
    # report title; any other first line (an index strip) is data and stays.
    if lines and re.search(r'盯盘\s*\|', lines[0]):
        lines = lines[1:]
    mode = None
    for raw in lines:
        line = raw.strip()
        if not line:
            mode = None if mode != 'news' else mode
            continue
        if line.startswith('|') and line.endswith('|'):
            out['table'].append(raw)
            continue
        if line.startswith('📊'):
            out['book'] = line
        elif line.startswith('📉'):
            out['risk'] = line
        elif line == '⚠️ 信号':
            mode = 'signals'
        elif line == '📰 新闻':
            mode = 'news'
        elif line.startswith('📋 未成交计划'):
            mode = 'orders'
        elif mode == 'signals' and line.startswith('·'):
            if out['signals']:
                out['signals'][-1]['reasons'].append(line.lstrip('·').strip())
        elif mode == 'signals':
            match = _SIGNAL_LINE.match(line)
            kind, name, detail = (match.groups() if match else ('', '', line))
            out['signals'].append({'kind': kind, 'ticker': name, 'detail': detail, 'reasons': []})
        elif mode == 'news' and line.startswith('📰'):
            # The analyzer marks a ticker's news sentiment: 📰✅ positive,
            # 📰⚠️ negative, bare 📰 neutral (us_analysis / hk_analysis).
            match = _NEWS_LINE.match(line)
            if match:
                out['news'].append({'ticker': match.group(2), 'mark': match.group(1) or '',
                                    'count': int(match.group(3)), 'titles': []})
            else:
                out['other'].append(raw)
        elif mode == 'news' and line.startswith('·') and out['news']:
            out['news'][-1]['titles'].append(line.lstrip('·').strip())
        elif mode == 'orders' and line.startswith('◆'):
            out['orders'].append(line.lstrip('◆').strip())
        else:
            mode = None
            out['other'].append(line)
    return out


# `▎情绪面｜正文…` (US) or `▎情绪面` alone on its line (HK).
_PROSE_LABEL = re.compile(r'▎\s*([^｜|：:\s]+)[｜|：:\s]*(.*)$')


def prose_markdown(prose: str) -> str:
    """The model's report prose: each ▎ marker becomes a small bold label on
    its own line with the paragraph under it plain, and `1)` lists become `1.`.

    kcn 2026-10-20 「太多加粗了」: bolding the whole ▎ line turned four
    paragraphs of the close report into solid bold."""
    out = []
    for line in (prose or '').strip().split('\n'):
        stripped = line.strip()
        if stripped.startswith('▎'):
            match = _PROSE_LABEL.match(stripped)
            if match:
                out += ['', f'**{match.group(1)}**'] + ([match.group(2)] if match.group(2) else [])
            continue
        out.append(re.sub(r'^(\s*)(\d+)\)\s*', r'\1\2. ', line))
    return '\n'.join(out).strip()


def render_report(title: str, block: str, prose: str) -> str:
    parts = parse_report_block(block)
    title = re.sub(r'\b20\d\d-(\d\d)-(\d\d)\b', r'\1/\2', title or '')
    lines = [title_line(title)] if title else []
    lines += summary_lines(parts['book'], parts['risk'])
    if parts['other']:
        lines += ['', *parts['other']]
    stops = [sig for sig in parts['signals'] if sig['kind'].startswith('STOP')]
    action = action_rows(open_orders=[order.replace(' | ', '｜') for order in parts['orders']])
    ordered = {order.partition(' ')[0] for order in parts['orders']}
    # As in the intraday card: a stop whose ticker already has an order is that order.
    for sig in (sig for sig in stops if sig['ticker'] not in ordered):
        why = '；'.join(sig['reasons'])
        action.append(bullet(f"{ticker(sig['ticker'])} 止损线已破 · {sig['detail']}"
                             + (f' · {why}' if why else '')))
    lines += section(ACTION, action)
    if parts['table']:
        lines += ['', *parts['table']]
    lines += section(SIGNALS, [
        bullet(f"{ticker(sig['ticker'])} {sig['kind']} · {sig['detail']}"
               + (' · ' + '；'.join(sig['reasons']) if sig['reasons'] else ''))
        for sig in parts['signals'] if sig not in stops])
    lines += section(NEWS, [
        bullet(f"{ticker(item['ticker'])}{' ' + item['mark'] if item['mark'] else ''} · {item['count']} 条"
               + (' · ' + '；'.join(item['titles']) if item['titles'] else ''))
        for item in parts['news']])
    body = prose_markdown(prose)
    if body:
        lines += ['', body]
    return '\n'.join(lines)
