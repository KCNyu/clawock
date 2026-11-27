"""Resolve publication claims against the evidence visible in one generation."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from math import isfinite

VERSION = 1
FIELD = 'prose_claims_version'
ISSUE = '事实引用'
TOKEN = re.compile(r'\[\[([^\[\]\r\n]+)\]\]')
# These are vocabulary, rather than measurements (P0 policy, T+1 horizon,
# MA200 indicator, 7×24 feed). Tickers containing digits use a ticker ref.
_VOCABULARY = re.compile(
    r'(?<![A-Za-z0-9])(?:P0|T[+-](?:0|1|2|3|5|10|20)|MA(?:5|10|20|50|60|100|120|200|250)'
    r'|MACD|RSI(?:14)?|7[×x]24)(?![A-Za-z0-9])', re.I)
_LITERAL = re.compile(
    r'\d+(?:[.,:：]\d+)*'
    r'|[零〇一二两三四五六七八九十百千万亿]+(?:点[零一二三四五六七八九]+)?'
    r'(?=\s*(?:股(?!东|权|价|票|指|息)|手(?!段|续)|倍|个?百分点|元|美元|港元|港币'
    r'|个交易日|个基点|年|月|日|点钟|时[整分]|分钟|小时|条|宗|份|个(?!股|人|性|体|别)|只(?!有|是|因|看|要)|次|%|％|成(?!交|本|熟|长|员|立|功|果)))'
    r'|百分之[零〇一二两三四五六七八九十百千万亿点]+'
)
_AMOUNT = re.compile(r'[+-]?[0-9]+(?:\.[0-9]+)?')
_ESCAPED_POINTER = re.compile(r'~(?![01])')
_CITE_ROOTS = {
    'active_information_candidates', 'anomaly_search', 'catalysts', 'em_news',
    'information', 'information_full',
    'known_catalysts', 'live_information', 'mover_news', 'news_evidence_graph',
}
_SOURCE_FIELDS = {
    'source', 'source_name', 'provider', 'publisher', 'data_source', 'quote_source',
    'exchange', 'venue', 'time_source', 'source_label',
}
_TIME_FIELDS = {
    'asof', 'as_of', 'asofdate', 'capturedat', 'captured_at', 'date', 'fetched_at',
    'generated_at', 'last_update', 'observed_at', 'published_at', 'publishedat',
    'session', 'session_date', 'timestamp', 'used_at', 'time',
}
_ID_FIELDS = {'ticker', 'symbol', 'index_code', 'proxy_label', 'label'}
_STATUS_WORDS = {
    'active': '生效', 'available': '可用', 'clear': '未触发', 'closed': '已关闭',
    'empty': '未查到条目', 'fresh': '本场已更新', 'incomplete': '不完整',
    'complete': '完整', 'delivered': '已送达', 'degraded': '降级', 'error': '失败',
    'failed': '失败', 'missing': '缺失', 'no_change': '无变化', 'ok': '正常',
    'partial': '部分可用', 'pending': '待定', 'published': '已发布',
    'stale': '已过时', 'success': '成功', 'triggered': '已触发',
    'unavailable': '不可用', 'unknown': '未知', 'warning': '警告',
}
_TIME_VALUE = re.compile(
    r'\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?'
    r'(?:Z|[+-]\d{2}:?\d{2}| HKT| ET)?)?|\d{2}:\d{2}')
_DECISION_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}')
_ID_VALUE = re.compile(r'[A-Za-z0-9^][A-Za-z0-9.^-]{0,15}')


def enabled(context):
    return (context or {}).get(FIELD) == VERSION


def _segments(pointer):
    if not pointer.startswith('/') or _ESCAPED_POINTER.search(pointer):
        raise ValueError('需要 JSON Pointer（/ctx/…）')
    return [part.replace('~1', '/').replace('~0', '~') for part in pointer[1:].split('/')]


def _resolve(roots, segments):
    node = roots
    for part in segments:
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif (isinstance(node, list) and re.fullmatch(r'0|[1-9][0-9]{0,8}', part)
              and int(part) < len(node)):
            node = node[int(part)]
        else:
            raise ValueError('本代没有该字段')
    return node


def _inline(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('缺可显示的文字')
    return ' '.join(value.split()).replace('|', '｜')


def _number(value):
    if type(value) not in (int, float) or isinstance(value, float) and not isfinite(value):
        raise ValueError('缺有限数值')
    return str(value)


def _numeric_display(value, path, roots):
    text = _number(value)
    name = next((part.lower() for part in reversed(path) if not part.isdecimal()), '')
    if name == 'shares' or name.endswith('_shares') or name.startswith('shares_'):
        return text + ' 股'
    if name == 'pct' or name.endswith('_pct') or '_pct_' in name or name.startswith('pct_'):
        return text + '%'
    if name in {'pp', 'value_pp'} or name.endswith('_pp'):
        return text + ' 个百分点'
    if name in {'value_multiple', 'range_used_atr', 'leverage_multiple'}:
        return text + ' 倍'
    for currency in ('HKD', 'USD'):
        if currency.lower() in name.split('_'):
            return text + ' ' + currency
    if name in {'market_value', 'total_pnl', 'today_pnl', 'cost_value'}:
        market = (roots.get('ctx') or {}).get('market')
        if market == 'hk' or 'hk_stocks' in path:
            return text + ' HKD'
        if market == 'us' or 'us_stocks' in path:
            return text + ' USD'
    return text


def _citation(row):
    if not isinstance(row, dict):
        raise ValueError('需要一条来源记录')
    if row.get('cite'):
        return _inline(row['cite'])
    title = _inline(row.get('title') or row.get('headline'))
    source = _inline(next((row[key] for key in sorted(_SOURCE_FIELDS)
                           if isinstance(row.get(key), str) and row[key].strip()), None))
    clocks = (
        ('published_at', '发布'), ('publishedAt', '发布'), ('published_date', '发布'),
        ('capturedAt', '采集'), ('captured_at', '采集'), ('observed_at', '观测'),
        ('date', '来源日期'), ('as_of', '截至'), ('asOf', '截至'),
    )
    when = next((f'{kind} {row[key]}' for key, kind in clocks
                 if isinstance(row.get(key), str) and _TIME_VALUE.fullmatch(row[key])), '时间未知')
    return f'《{title[:60]}》（{source}，{when}）'



def _trigger(roots, path, spec):
    if len(path) != 4 or path[:2] != ['ctx', 'trigger_prices']:
        raise ValueError('触发位需要指定标的及其 trigger_prices 行')
    row = _resolve(roots, path)
    direction, _, proposed = spec.partition('=')
    if direction not in ('above', 'below'):
        raise ValueError('触发方向须为 above 或 below')
    try:
        price = Decimal(str(row['price']))
    except (InvalidOperation, KeyError, TypeError):
        raise ValueError('触发位缺有效价格') from None
    if not price.is_finite() or price <= 0:
        raise ValueError('触发位缺有效价格')
    result = str(row['price'])
    if '=' in spec:
        if not _AMOUNT.fullmatch(proposed) or len(proposed) > 24 or row.get('current') is not True:
            raise ValueError('前瞻位需要本档同标的现价')
        if abs(Decimal(proposed) - price) > price * Decimal('0.05'):
            raise ValueError('前瞻位超过同标的现价 ±5%')
        result = proposed
    verb = '站上' if direction == 'above' else '跌破'
    return f'{path[2]} {verb}{result}'


class ClaimRenderer:
    """Read exact paths from trusted inputs and collect authoring errors."""

    def __init__(self, context, *, packet=None, receipts=()):
        self.roots = {'ctx': context, 'packet': packet or {}, 'compute': {
            row['receipt_id']: row for row in receipts if isinstance(row.get('receipt_id'), str)
        }}
        self.issues = []
        self.references = []

    def _claim(self, token, roots):
        pointer, _, mode = token.partition('|')
        path = _segments(pointer)
        if len(path) < 2:
            raise ValueError('需要具体字段')
        field = path[-1].lower()
        if mode == 'cite':
            allowed = (any(part in _CITE_ROOTS for part in path[1:-1])
                       or path[0] == 'packet' and 'evidence' in path[1:-1])
            if not allowed:
                raise ValueError('需要资讯来源字段')
            return _citation(_resolve(roots, path))
        value = _resolve(roots, path)
        if mode == 'count':
            if isinstance(value, list):
                return str(len(value))
            raise ValueError('计数需要一个结构化列表')
        if mode == 'status' and field in {'status', 'state', 'delivery_state', 'delivery_mode'}:
            if isinstance(value, str) and value in _STATUS_WORDS:
                return _STATUS_WORDS[value]
            raise ValueError('缺已登记的状态')
        if mode:
            raise ValueError('未知显示方式')
        if field == 'cite' and any(part in _CITE_ROOTS for part in path[1:-1]):
            return _inline(value)
        if field in _SOURCE_FIELDS:
            return _inline(value)
        if isinstance(value, str) and (
                (field == 'decision_id' and _DECISION_ID.fullmatch(value))
                or (field in _ID_FIELDS and _ID_VALUE.fullmatch(value))
                or (field in _TIME_FIELDS and _TIME_VALUE.fullmatch(value))):
            return value
        return _numeric_display(value, path, roots)

    def render(self, text, label, *, decision=None):
        if not isinstance(text, str):
            return text
        roots = self.roots if decision is None else {**self.roots, 'decision': decision}

        def replace(match):
            try:
                value = self._claim(match[1], roots)
                if match[1].startswith(('/decision/trim_at_mark/', '/decision/trim_at_trigger/')):
                    self.references.append(match[1].partition('|')[0])
                return value
            except ValueError as exc:
                self.issues.append(f'{ISSUE} {label} {match[1][:150]}：{exc}')
                return '—'

        raw = TOKEN.sub('', text)
        bad = _LITERAL.search(_VOCABULARY.sub('', raw))
        if bad:
            self.issues.append(f'{ISSUE} {label} 手写数值「{bad[0]}」，请引用同代字段')
        if '[[' in raw or ']]' in raw:
            self.issues.append(f'{ISSUE} {label} 引用格式不完整')
        return TOKEN.sub(replace, text)

    def triggers(self, line, prefix):
        if not line:
            self.issues.append(f'{ISSUE} 下一触发：缺少结构化触发位')
            return ''
        rows = []
        for item in line.removeprefix(prefix).split('；'):
            try:
                match = TOKEN.fullmatch(item.strip())
                if not match:
                    raise ValueError('每项需要一个 trigger_prices 引用')
                pointer, _, spec = match[1].partition('|')
                rows.append(_trigger(self.roots, _segments(pointer), spec))
            except ValueError as exc:
                self.issues.append(f'{ISSUE} 下一触发：{exc}')
        return prefix + '；'.join(rows) if rows else ''
