"""Bind authored monthly leverage-drag claims to the measured position."""
from math import fsum, isclose

from clawock.portfolio.trim_claims import position_fragments, position_subjects
from clawock.safe_io import to_strict_finite_number

DRAG_FIELD = 'chop_drag_pct_per_month'
DRAG_SUM_FIELD = 'priced_chop_drag_sum_pct_per_month'
ISSUE = '横盘衰减与测算不符'
_DRAG = ('衰减', '耗损', '损耗', 'decay', 'drag')
_MONTH = ('每月', '每个月', '月度', '月均', '月衰减', '月损耗', '/月', '/ 月', 'per month', 'monthly')
_DAILY = ('当日衰减', '日内衰减', '每日衰减', '每天衰减', 'daily drag', 'daily decay')
_SUM = ('合计', '合付', '总计', '总共', '合起来', '加在一起', '加总', '之和', '算术和')
_BOUNDARY = str.maketrans({char: '\n' for char in '。！？；;'})
_DECIMAL_CHARS = frozenset('0123456789.+-')


def _find(text, words):
    return min((pos for word in words if (pos := text.find(word)) >= 0), default=None)


def _percentages(clause):
    for end, char in enumerate(clause):
        if char not in '%％':
            continue
        prefix = clause[:end].rstrip()
        start = len(prefix)
        while start and prefix[start - 1] in _DECIMAL_CHARS:
            start -= 1
        try:
            yield start, end, float(prefix[start:])
        except ValueError:
            continue


def drag_by_ticker(rows):
    return {row['ticker']: value for row in rows if row.get('ticker')
            and not row.get('vol_unavailable_reason')
            and (value := to_strict_finite_number(row.get(DRAG_FIELD))) is not None}


def priced_drag_total(rows):
    """Arithmetic sum of the measured rows, never a portfolio return."""
    values = drag_by_ticker(rows)
    return round(fsum(values.values()), 2) if values else None


def _claims(text):
    for sentence in text.casefold().translate(_BOUNDARY).splitlines():
        if _find(sentence, _MONTH) is None:
            continue
        clauses = sentence.replace('，', ',').split(',')
        aggregate = _find(sentence, _SUM) is not None
        for index, clause in enumerate(clauses):
            if _find(clause, _DAILY) is not None and _find(clause, _MONTH) is None:
                continue
            position = _find(clause, _DRAG)
            if position is None and _find(sentence, ('两倍腿', '杠杆', 'etf')) is not None:
                position = _find(clause, ('合付', '白付', '付掉', '合计'))
            if position is None:
                continue
            readings = list(_percentages(clause))
            if readings:
                _, _, value = min(
                    readings, key=lambda reading: min(abs(reading[0] - position),
                                                      abs(reading[1] - position)))
                yield value, aggregate
            elif index + 1 < len(clauses):
                adjacent = clauses[index + 1]
                month = _find(adjacent, _MONTH)
                other_readings = list(_percentages(adjacent)) if month is not None else []
                if other_readings:
                    _, _, value = min(
                        other_readings, key=lambda reading: min(abs(reading[0] - month),
                                                               abs(reading[1] - month)))
                    yield value, aggregate


def validate_drag(text, context, *, ticker=None, references=None):
    if not isinstance(text, str) or 'breakeven_math' not in context:
        return []
    claims = list(_claims(text))
    if not claims:
        return []
    rows = (context.get('breakeven_math') or {}).get('rows') or []
    values = drag_by_ticker(rows)
    subjects = position_subjects(context, [ticker, *(row.get('ticker') for row in rows)])
    total = priced_drag_total(rows)
    paths = {row['ticker']: f'/ctx/breakeven_math/rows/{index}/{DRAG_FIELD}'
             for index, row in enumerate(rows) if row.get('ticker')}
    findings = set()
    named = set()
    for subject, fragment in position_fragments(text, subjects, ticker):
        for value, aggregate in _claims(fragment):
            if aggregate:
                continue
            named.add(value)
            expected = values.get(subject)
            if expected is None:
                findings.add(f'{ISSUE}：{subject} 这只的衰减算不出来')
            elif not isclose(value, expected, abs_tol=1e-9):
                findings.add(f'{ISSUE}：{subject} 每月 {value:g}%，同票测算为 {expected:g}%')
            elif references is not None and paths[subject] not in references:
                findings.add(f'{ISSUE}：{subject} 的衰减须引用同票测算字段')
    for value, aggregate in claims:
        if aggregate:
            if total is None or not isclose(value, total, abs_tol=1e-9):
                expected = '算不出' if total is None else f'{total:g}%'
                findings.add(f'{ISSUE}：已测算标的的月衰减算术和为 {expected}，正文写 {value:g}%')
            elif references is not None and f'/ctx/breakeven_math/{DRAG_SUM_FIELD}' not in references:
                findings.add(f'{ISSUE}：月衰减合计须引用程序的同代合计字段')
        elif value not in named:
            findings.add(f'{ISSUE}：月衰减 {value:g}% 缺明确标的')
    return sorted(findings)
