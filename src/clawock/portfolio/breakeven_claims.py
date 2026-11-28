"""Bind authored monthly leverage-drag claims to the measured position."""
import re
from math import fsum, isclose

from clawock.portfolio.trim_claims import position_fragments, position_subjects
from clawock.safe_io import to_strict_finite_number

DRAG_FIELD = 'chop_drag_pct_per_month'
DRAG_SUM_FIELD = 'priced_chop_drag_sum_pct_per_month'
ISSUE = '横盘衰减与测算不符'
_DRAG = re.compile(r'衰减|耗损|损耗|decay|drag', re.I)
_MONTH = re.compile(r'每个?月|月度|月均|月衰减|月损耗|/\s*月|per month|monthly', re.I)
_SUM = re.compile(r'合计|合付|总计|总共|合起来|加在一起|加总|之和|算术和')
_BOUNDARY = re.compile(r'[。！？；;\n]')
_PERCENT = re.compile(r'([+-]?\d+(?:\.\d+)?)\s*[%％]')


def drag_by_ticker(rows):
    return {row['ticker']: value for row in rows if row.get('ticker')
            and not row.get('vol_unavailable_reason')
            and (value := to_strict_finite_number(row.get(DRAG_FIELD))) is not None}


def priced_drag_total(rows):
    """Arithmetic sum of the measured rows, never a portfolio return."""
    values = drag_by_ticker(rows)
    return round(fsum(values.values()), 2) if values else None


def _claims(text):
    for sentence in _BOUNDARY.split(text):
        if not _MONTH.search(sentence):
            continue
        clauses = re.split(r'[，,]', sentence)
        for index, clause in enumerate(clauses):
            match = _DRAG.search(clause)
            if match is None and re.search(r'两倍腿|杠杆|ETF', sentence, re.I):
                match = re.search(r'合付|白付|付掉|合计', clause)
            if match:
                readings = list(_PERCENT.finditer(clause))
                if not readings and index + 1 < len(clauses) and _MONTH.search(clauses[index + 1]):
                    readings = list(_PERCENT.finditer(clauses[index + 1]))
                    if readings:
                        yield float(readings[0][1]), bool(_SUM.search(sentence))
                        continue
                if readings:
                    nearest = min(readings, key=lambda m: min(abs(m.end() - match.start()),
                                                               abs(m.start() - match.end())))
                    yield float(nearest[1]), bool(_SUM.search(sentence))


def validate_drag(text, context, *, ticker=None, references=None):
    if not isinstance(text, str) or 'breakeven_math' not in context:
        return []
    rows = (context.get('breakeven_math') or {}).get('rows') or []
    values = drag_by_ticker(rows)
    subjects = position_subjects(context, [ticker, *(row.get('ticker') for row in rows)])
    named = {(value, aggregate) for _, fragment in position_fragments(text, subjects, ticker)
             for value, aggregate in _claims(fragment)}
    total = priced_drag_total(rows)
    paths = {row['ticker']: f'/ctx/breakeven_math/rows/{index}/{DRAG_FIELD}'
             for index, row in enumerate(rows) if row.get('ticker')}
    findings = set()
    for subject, fragment in position_fragments(text, subjects, ticker):
        for value, aggregate in _claims(fragment):
            if aggregate:
                continue
            expected = values.get(subject)
            if expected is None:
                findings.add(f'{ISSUE}：{subject} 这只的衰减算不出来')
            elif not isclose(value, expected, abs_tol=1e-9):
                findings.add(f'{ISSUE}：{subject} 每月 {value:g}%，同票测算为 {expected:g}%')
            elif references is not None and paths[subject] not in references:
                findings.add(f'{ISSUE}：{subject} 的衰减须引用同票测算字段')
    for value, aggregate in _claims(text):
        if aggregate:
            if total is None or not isclose(value, total, abs_tol=1e-9):
                expected = '算不出' if total is None else f'{total:g}%'
                findings.add(f'{ISSUE}：已测算标的的月衰减算术和为 {expected}，正文写 {value:g}%')
            elif references is not None and f'/ctx/breakeven_math/{DRAG_SUM_FIELD}' not in references:
                findings.add(f'{ISSUE}：月衰减合计须引用程序的同代合计字段')
        elif (value, aggregate) not in named:
            findings.add(f'{ISSUE}：月衰减 {value:g}% 缺明确标的')
    return sorted(findings)
