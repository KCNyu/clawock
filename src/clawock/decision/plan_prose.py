"""Cross-check explicit remaining-share targets; never infer a sell quantity.

A plan's prose is a consistency reference, not proof of correct sizing. In
particular trim_projection.shares is SOLD shares, whereas 减到 N 股 states a
remaining balance. Comparing those two would manufacture a false authority.
"""
import re

_TARGET = re.compile(r'(?:减|砍|降|压)(?:仓)?到\s*(\d+)\s*股')


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def judgment_plan_share_conflicts(plan, overlay):
    """Compare like-for-like explicit targets, retaining ticker attribution."""
    references = {}
    for row in (plan or {}).get('decisions') or []:
        if not isinstance(row, dict) or not row.get('ticker'):
            continue
        texts = [row.get('rationale'), row.get('thesis_invalidation'),
                 (row.get('condition') or {}).get('description')]
        targets = {int(m[1]) for text in _strings(texts) for m in _TARGET.finditer(text)}
        if targets:
            references.setdefault(str(row['ticker']), set()).update(targets)
    if not references or not isinstance(overlay, dict):
        return []
    names = {str(row.get('ticker')) for row in (plan or {}).get('decisions') or []
             if isinstance(row, dict) and row.get('ticker')}
    names.update(str(row.get('ticker')) for row in overlay.get('ticker_judgments') or []
                 if isinstance(row, dict) and row.get('ticker'))
    names = sorted(names, key=len, reverse=True)
    code = re.compile(r'(?<![A-Za-z0-9])(' + '|'.join(map(re.escape, names))
                      + r')(?![A-Za-z0-9])')
    scoped = [(None, {k: v for k, v in overlay.items() if k != 'ticker_judgments'})]
    scoped.extend((row.get('ticker'), row) for row in overlay.get('ticker_judgments') or []
                  if isinstance(row, dict))
    conflicts = set()
    for default, value in scoped:
        for text in _strings(value):
            for sentence in re.split(r'[。！？!?\n]', text):
                for match in _TARGET.finditer(sentence):
                    prefix = sentence[:match.start()]
                    clause = re.split(r'[，,；;]', prefix)[-1]
                    if re.search(r'不是|并非|不要|不应|不能|无需', clause):
                        continue
                    mentioned = list(code.finditer(prefix))
                    ticker = mentioned[-1][1] if mentioned else default
                    expected = references.get(ticker, set())
                    if len(expected) == 1 and int(match[1]) not in expected:
                        conflicts.add((ticker, next(iter(expected)), int(match[1])))
    return [f'判断与计划股数冲突: {ticker} 计划减到 {expected} 股，判断减到 {actual} 股；'
            '须核对同一场景，不能把卖出股数当剩余股数'
            for ticker, expected, actual in sorted(conflicts)]
