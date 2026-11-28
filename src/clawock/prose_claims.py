"""Resolve publication claims against the evidence visible in one generation."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from math import isfinite
from urllib.parse import quote as quote_url, urlsplit

from clawock.portfolio.breakeven_claims import validate_drag
from clawock.prose_validation import Advisory, CITATION, MEASUREMENT, check_storytelling

VERSION = 1
FIELD = 'prose_claims_version'
ISSUE = '事实引用'
TOKEN = re.compile(r'\[\[([^\[\]\r\n]+)\]\]')
# Unbound numeric units are editorial diagnostics. Claims authorized for
# publication are detected by the reference grammar, not by this pattern.
_UNBOUND_UNIT = re.compile(
    r'(?<![A-Za-z0-9_.])\d+(?:[.,]\d+)*\s*(?:[%％]|港元|美元|HKD|USD|股(?!票|东))')
_MARKET_TOPIC = re.compile(
    r'南向|港股通|HIBOR|香港银行同业拆息|港元拆息|港[元币]汇[率价]|'
    r'(?:USD/?HKD|HKD/?USD)|(?:美元兑港元|港元兑美元)', re.I)
_MARKET_NUMBER = re.compile(
    r'\d+(?:,\d{3})*(?:\.\d+)?\s*(?:[%％万亿兆]|港元|港币|美元|个基点|基点|bp|HKD|USD)'
    r'|[零〇一二两三四五六七八九十百千万]+(?:点[零〇一二两三四五六七八九]+)?\s*(?:亿元|亿港元|万港元|个基点|基点|个百分点)'
    r'|百分之[零〇一二两三四五六七八九十点]+'
    r'|\d+\.\d+|(?:净买入|净卖出|净流[入出]|报|为|升至|降至)\s*[+-]?\d+(?![\d年月日时周天])', re.I)
_MARKET_CLAUSE = re.compile(r'[。；;！？!?，\n]')
_ACK_FIELDS = {
    'quote_coverage', 'plan_context', 'risk_debts', 'risk_followups', 'session_review',
    'semantic_state', 'semantic_delta', 'signal_count', 'strategy_checks', 'index_direction',
    'bundle_evidence', 'snapshots', 'decision_metrics', 'decision_episodes', 'current_risk', 'plans',
}
_AMOUNT = re.compile(r'[+-]?[0-9]+(?:\.[0-9]+)?')
_ESCAPED_POINTER = re.compile(r'~(?![01])')
_CITE_ROOTS = {
    'active_information_candidates', 'anomaly_search', 'catalysts', 'em_news',
    'information', 'information_full',
    'known_catalysts', 'live_information', 'mover_news', 'news_evidence_graph',
}
_SOURCE_FIELDS = {
    'source', 'source_name', 'provider', 'publisher', 'data_source', 'quote_source',
    'exchange', 'venue', 'time_source', 'source_label', 'primary_source',
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


_MOVER_SOURCES = {
    'exchange_filing': '交易所公告', 'hkexnews_filing': '港交所公告',
    'sec_filing': 'SEC 文件', 'sec_filing_mirror': 'SEC 文件', 'sec_fulltext': 'SEC 文件',
    'finnhub_filing': '公司公告（Finnhub）', 'market_flash': '市场快讯',
}


def _citation(row):
    if not isinstance(row, dict):
        raise ValueError('需要一条来源记录')
    if row.get('cite'):
        return _inline(row['cite'])
    title = _inline(row.get('title') or row.get('headline') or row.get('detail'))
    source = _inline(_MOVER_SOURCES.get(row.get('source_class')) or
                     next((row[key] for key in sorted(_SOURCE_FIELDS)
                           if isinstance(row.get(key), str) and row[key].strip()), None))
    clocks = (
        ('published_at', '发布'), ('publishedAt', '发布'), ('published_date', '发布'),
        ('capturedAt', '采集'), ('captured_at', '采集'), ('observed_at', '观测'),
        ('date', '来源日期'), ('as_of', '截至'), ('asOf', '截至'),
    )
    published = (row.get('publication_time') or {}).get('iso')
    when = next((f'{kind} {row[key]}' for key, kind in clocks
                 if isinstance(row.get(key), str) and _TIME_VALUE.fullmatch(row[key])),
                f'发布 {published}' if isinstance(published, str) and _TIME_VALUE.fullmatch(published)
                else '时间未知')
    return f'《{title[:60]}》（{source}，{when}）'



def _has_market_reading(text):
    return isinstance(text, str) and _MARKET_TOPIC.search(text) and _MARKET_NUMBER.search(text)


def _market_citation(row, citation):
    """Bind an HK liquidity reading to its actual same-generation source title."""
    title = row.get('title') or row.get('headline') or ''
    if not (_has_market_reading(title) or _has_market_reading(citation)):
        return citation
    url = row.get('url') or row.get('source_url')
    try:
        parsed = urlsplit(url) if isinstance(url, str) else None
        good_url = (parsed is not None and parsed.scheme in ('https', 'http')
                    and parsed.hostname and not parsed.username and not any(c.isspace() for c in url))
    except ValueError:
        good_url = False
    source = next((row[key] for key in ('publisher', 'source', 'source_name', 'primary_source', 'provider')
                   if isinstance(row.get(key), str) and row[key].strip()), None)
    timestamp = (row.get('published_at') or row.get('filed_date') or row.get('published_date')
                 or row.get('date') or (row.get('publication_time') or {}).get('iso'))
    if not (good_url and source and isinstance(timestamp, str) and _TIME_VALUE.fullmatch(timestamp)
            and _has_market_reading(title)):
        raise ValueError('外部市场读数需要同代原始标题中的数值、来源、日期和链接')
    target = quote_url(url, safe=":/?#&=+%@,;~")
    freshness = '，旧闻' if row.get('stale') is True else ''
    return f'《{_inline(title)}》（{_inline(source)}，{timestamp}{freshness}，{target}）'


def citation(row, *, market=None):
    value = _citation(row)
    return _market_citation(row, value) if market in ('hk', 'us') else value


def _has_unbound_market_reading(text, measurements):
    for clause in _MARKET_CLAUSE.split(text):
        raw = TOKEN.sub('', clause)
        if not _MARKET_TOPIC.search(raw):
            continue
        if _MARKET_NUMBER.search(raw):
            return True
        if any(match[1] in measurements for match in TOKEN.finditer(clause)):
            return True
    return False


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
        self.advisories = []
        self.references = []
        self.resolved_tokens = set()
        self.measurements_by_scope = {}

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
            return citation(_resolve(roots, path), market=roots['ctx'].get('market')), False
        value = _resolve(roots, path)
        if mode == 'ack' and len(path) == 2 and path[0] == 'ctx' and field in _ACK_FIELDS:
            if value is None or isinstance(value, (dict, list)):
                return '', False
            raise ValueError('确认字段需要本代状态对象或列表')
        if mode == 'count':
            if isinstance(value, list):
                return str(len(value)), True
            raise ValueError('计数需要一个结构化列表')
        if mode == 'status' and field in {'status', 'state', 'delivery_state', 'delivery_mode'}:
            if isinstance(value, str) and value in _STATUS_WORDS:
                return _STATUS_WORDS[value], False
            raise ValueError('缺已登记的状态')
        if mode:
            raise ValueError('未知显示方式')
        if field == 'cite' and any(part in _CITE_ROOTS for part in path[1:-1]):
            if roots['ctx'].get('market') in ('hk', 'us') and _has_market_reading(value):
                raise ValueError('外部市场读数请用原始记录的 |cite')
            return _inline(value), False
        if field in _SOURCE_FIELDS:
            return _inline(value), False
        if isinstance(value, str) and (
                (field == 'decision_id' and _DECISION_ID.fullmatch(value))
                or (field in _ID_FIELDS and _ID_VALUE.fullmatch(value))
                or (field in _TIME_FIELDS and _TIME_VALUE.fullmatch(value))):
            return value, False
        return _numeric_display(value, path, roots), True

    def render(self, text, label, *, decision=None, ticker=None, scope=None, dense_measurements=True):
        if not isinstance(text, str):
            return text
        roots = self.roots if decision is None else {**self.roots, 'decision': decision}

        measurements = {}
        citations = set()
        numerical_keys = []

        def replace(match):
            try:
                value, measurement = self._claim(match[1], roots)
                self.resolved_tokens.add(match[1])
                if measurement:
                    measurements[match.start()] = match[1]
                    numerical_keys.append((match[1], value))
                    if value.endswith('%') and text[match.end():match.end() + 1] in ('%', '％'):
                        value = value[:-1]
                pointer, _, mode = match[1].partition('|')
                if mode == 'cite' or pointer.endswith('/cite'):
                    citations.add(match.start())
                if match[1].startswith(('/decision/trim_at_mark/', '/decision/trim_at_trigger/')):
                    self.references.append(match[1].partition('|')[0])
                return value
            except ValueError as exc:
                self.issues.append(f'{ISSUE} {label} {match[1][:150]}：{exc}')
                return '—'

        raw = TOKEN.sub('', text)
        if bad := _UNBOUND_UNIT.search(raw):
            self.advisories.append(Advisory(f'{label}含未绑定读数「{bad[0]}」，请核同代字段'))
        if '[[' in raw or ']]' in raw:
            self.issues.append(f'{ISSUE} {label} 引用格式不完整')
        result = TOKEN.sub(replace, text)
        if roots['ctx'].get('market') in ('hk', 'us') and _has_unbound_market_reading(
                text, set(measurements.values())):
            self.issues.append(f'{ISSUE} {label} 外部市场读数须使用本代源记录的 |cite，缺资料请说明')
        owner = ticker or (decision or {}).get('ticker')
        if 'breakeven_math' in roots['ctx']:
            pointers = {token.partition('|')[0] for token, _ in numerical_keys}
            self.issues.extend(f'{ISSUE} {label} {issue}' for issue in
                               validate_drag(result, roots['ctx'], ticker=owner, references=pointers))
        repeated = len(set(numerical_keys)) < len(numerical_keys)
        if scope or owner:
            prior = self.measurements_by_scope.setdefault(scope or owner, set())
            repeated |= any(key in prior for key in numerical_keys)
            prior.update(numerical_keys)
        # Strip reference syntax and quoted news from the style check. The
        # pattern sees only the author's words and the positions of measurements.
        draft = TOKEN.sub(lambda match: MEASUREMENT if match.start() in measurements
                          else CITATION if match.start() in citations else ' ', text)
        self.advisories.extend(check_storytelling(
            draft, label, dense_measurements=dense_measurements,
            repeated_measurement=repeated))
        return result

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


def resolved_in(text, renderer):
    """Reference tokens successfully resolved in this authored section."""
    return {match[1] for match in TOKEN.finditer(text) if match[1] in renderer.resolved_tokens}
