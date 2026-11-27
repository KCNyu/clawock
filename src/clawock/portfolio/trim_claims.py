"""Extract explicit concentration claims and reconcile them with book scenarios.

A number gets its meaning from the field it describes, the position being
discussed, and the stated price basis. Free-form market commentary still uses
the harness's advisory numeric provenance check.
"""
import re
from dataclasses import dataclass
from enum import Enum, auto


class _Field(Enum):
    REVIEW_SALE = auto()
    REVIEW_REMAINDER = auto()
    ENOUGH_TO_REACH_LINE = auto()
    POST_SALE_WEIGHT = auto()
    CONCENTRATION = auto()
    ABOVE_LINE = auto()
    AT_OR_BELOW_LINE = auto()


@dataclass(frozen=True, slots=True)
class _Claim:
    field: _Field
    raw: str = ''

    @property
    def value(self):
        return float(self.raw.replace(',', ''))


_NUMBER = r'[+-]?(?:\d{1,3}(?:,\d{3})+(?!\d)|\d+)(?:\.\d+)?'
_SENTENCE = re.compile(r'[。；;！？!?\n]')
# A thousands separator is part of the value, even when adjacent to other clauses.
_CLAUSE = re.compile(r'[，、]|,(?!\d{3}(?!\d))')
_NEGATED = re.compile(r'不能|无法|未能|不再声称|不会|并非|不是|不应|不该|是否|无需|不用|不足以|不够|到不了|达不到')
_AFTER_SIZE_NEGATION = re.compile(r'^\s*(?:也|仍|还|尚)?(?:不能|无法|不足以|不够|到不了|达不到|不会|未能|并非)')
_SHARE = re.compile(rf'({_NUMBER})\s*股')
_REVIEW_CONTEXT = re.compile(r'复核线|支配度|集中度|占比')
_LINE_REQUIREMENT = re.compile(r'复核线\s*(?:所?需|要求|最低|最少|必须)')
_SIZE_AS_SUBJECT = re.compile(r'^\s*(?:[A-Z0-9.-]+\s+)?(?:只要|仅|只)?\s*$')
# Goal forms carry meaning even if a new verb is used to describe sufficiency.
# An observation such as "目前仍高于复核线" is not a sale goal.
_GOAL = re.compile(
    rf'(?:回[到归落]|到达|达到|达标|触及|守住|跌破|压[到回下]|[低小]于|不高于|到)'
    rf'[^，,。；;%％股]{{0,8}}(?:{_NUMBER}\s*[%％]\s*(?:的\s*)?)?(?:单名)?复核线'
    r'|复核线(?:之内|内|以下|下方)')
_MARKER = r'(?:当前价|现价|账面价|简报时现价|(?:计划)?触发价)'
_PRICE_BASIS = re.compile(
    rf'按\s*(?:(?P<label>{_MARKER})\s*(?:(?P<label_price>{_NUMBER})\s*'
    rf'(?:港元|美元|HKD|USD)?)?\s*(?:计)?算'
    rf'|(?P<price>{_NUMBER})\s*(?:港元|美元|HKD|USD)\s*(?:计)?算)', re.I)
_REVIEW_LABEL = re.compile(r'复核线(?:数量|股数|尺寸)\s*(?:是|为|[:：])?\s*$')
_REMAINDER = re.compile(r'(?:[减砍降压](?:仓)?[到至]|(?:只)?剩(?:下|余)?|余(?:下|量)?|留(?:下|存)?)'
                        r'\s*(?:为|是|[:：]|约)?\s*$')
_SELL = re.compile(r'(?:卖|减|砍|削)(?:出|掉|去|仓|持)?\s*$')
_REQUIRED = re.compile(r'需(?:要)?|须|不得不|得|至少')
_INCREMENTAL = re.compile(r'(?:还|再|另|额外)(?:须|得|需要?|要)?\s*(?:卖|减|砍|削)?'
                          r'(?:出|掉|去|仓|持)?\s*$')
_EQUIVALENT = re.compile(r'^\s*(?:也?就(?:是|意味着)|(?:也)?即(?:为|是)?|换言之)')
_RESULT = re.compile(r'^\s*(?:就|才|即|便|方|即可|这样|之后|以后|卖完|减完)')
# Historical sentences can omit the goal in the last clause ("40 股才够").
_ELLIPTICAL_SUFFICIENCY = re.compile(r'^\s*(?:才够|就够|足够)')

_SAME_POSITION = r'这一格(?:在(?:美国|美股|香港|港股)腿)?'
_WEIGHT_DESTINATION = r'[落降压回变剩占](?!报)[^，,。；;%％\d]{0,6}?'
_POST_WEIGHT = re.compile(
    rf'(?:(?:占比|支配度|集中度)\s*{_WEIGHT_DESTINATION}'
    rf'|(?:卖|减)[^。；;！？!?\n]{{0,18}}股后[^，,。；;%％]{{0,8}}{_WEIGHT_DESTINATION}'
    rf'|(?:卖|减)(?:完|掉|了)\s*(?:{_SAME_POSITION}\s*)?{_WEIGHT_DESTINATION}'
    rf'|(?:卖|减)\s*{_NUMBER}\s*股\s*(?:能把|把|之后)\s*{_SAME_POSITION}'
    rf'\s*{_WEIGHT_DESTINATION})'
    rf'(?:约)?\s*({_NUMBER})\s*[%％]')
_POST_TRIM_SCOPE = re.compile(
    rf'[卖减](?:完|掉|了)|(?:卖出|减仓|减持|[卖减]\s*{_NUMBER}\s*股)\s*(?:之)?后')
_CURRENT_SCOPE = re.compile(r'当前|目前|现在|减仓(?:之)?前|卖出(?:之)?前')
_ABOVE_LINE = re.compile(
    rf'仍(?:然)?\s*(?:略微|略|稍|明显)?\s*(?:高于|超过)\s*'
    rf'(?:(?P<level>{_NUMBER})\s*[%％]\s*(?:的\s*)?)?(?:单名)?复核线')
_BELOW_LINE = re.compile(
    r'[落降压回变剩][^。；;！？!?]{0,10}复核线(?:下方|以下)')
_LINE_SUFFIX = re.compile(r'\s*(?:的\s*)?(?:单名)?复核线(?:下方|以下)')
_CONCENTRATION = re.compile(r'支配度|集中度|占.{0,8}腿|仓位占比')
_CONCENTRATION_VALUE = re.compile(
    r'(?:支配度|集中度|仓位占比|占[^，,。；;%％]{0,8}腿)[^，,。；;%％]{0,12}$')
_PERCENT = re.compile(rf'({_NUMBER})\s*[%％]')
_PROSE_SENTENCE = re.compile(r'([。；;！？!?])')
_PROSE_TICKER_HEADING = re.compile(r'- \*\*([^*]+)\*\*')
_SHARE_CLASS_SUFFIX = re.compile(r'-(?:SW|W|S|B)$', re.I)


def position_subjects(context, tickers=()):
    """Index known names, including unreviewed names that bound attribution."""
    aliases = {ticker.casefold(): ticker for ticker in tickers if ticker}
    portfolio = context.get('portfolio') or {}
    book_holdings = (row for leg in (portfolio.get('portfolios') or {}).values()
                     for row in leg.get('holdings') or [])
    published = context.get('holdings')
    published_holdings = (row for rows in published.values() if isinstance(rows, list)
                          for row in rows) if isinstance(published, dict) else ()
    reviews = (context.get('risk_guardrail') or {}).get('concentration_reviews') or []
    for rows in (book_holdings, published_holdings, reviews):
        for row in rows:
            ticker = row.get('ticker')
            if not ticker:
                continue
            for name in (ticker, row.get('name')):
                if name:
                    aliases[name.casefold()] = ticker
                    aliases[_SHARE_CLASS_SUFFIX.sub('', name).casefold()] = ticker
    names = re.compile(r'(?<![0-9A-Za-z])(?:' + '|'.join(
        re.escape(a) for a in sorted(aliases, key=len, reverse=True)) + r')(?![0-9A-Za-z])',
        re.I) if aliases else None
    return names, aliases


def position_fragments(prose, subjects, default_ticker=None):
    """Yield prose fragments with the nearest named position or structured row."""
    names, aliases = subjects
    active = default_ticker
    for paragraph in prose.splitlines():
        if heading := _PROSE_TICKER_HEADING.match(paragraph):
            active = aliases.get(heading[1].casefold())
        elif paragraph.startswith('#') or not paragraph.strip():
            active = default_ticker
        ticker = active
        parts = _PROSE_SENTENCE.split(paragraph)
        for fragment, separator in zip(parts[::2], [*parts[1::2], '']):
            start = 0
            for mention in names.finditer(fragment) if names else ():
                named = aliases[mention[0].casefold()]
                if named == ticker:
                    continue
                # The price basis can introduce a named position. Keep it
                # with that position rather than dropping an unlabeled prefix.
                if not ticker and _PRICE_BASIS.fullmatch(
                        fragment[start:mention.start()].strip(' \t，,：:')):
                    ticker = named
                    continue
                if ticker and start < mention.start():
                    yield ticker, fragment[start:mention.start()]
                start = mention.start()
                ticker = named
            if ticker and fragment:
                yield ticker, fragment[start:]
            if separator not in ('；', ';'):
                ticker = active


def _price_scenario(mark, projection, book_projection):
    label = mark['label'] or ''
    price = mark['label_price'] or mark['price']
    price = float(price.replace(',', '')) if price else None
    book = book_projection or (projection if projection.get('price_basis') == 'book_mark' else {})
    if '触发价' in label:
        choices = (projection,) if projection.get('price_basis') != 'book_mark' else ()
    elif label:
        choices = (book,)
    else:
        choices = (book, projection)
    return next((row for row in choices if price is None or row.get('price') == price), {})


def trim_claim_projection(text, projection, book_projection=None):
    """Return the default scenario or the first explicitly stated price basis."""
    mark = _PRICE_BASIS.search(text)
    return _price_scenario(mark, projection, book_projection) if mark else projection


def _scenarios(text, projection, book_projection):
    for sentence in _SENTENCE.split(text):
        start = 0
        scenario = projection
        for mark in _PRICE_BASIS.finditer(sentence):
            if scenario is not None and sentence[start:mark.start()].strip(' ，,、'):
                yield sentence[start:mark.start()], scenario
            start = mark.end()
            scenario = _price_scenario(mark, projection, book_projection) or None
        if scenario is not None and start < len(sentence):
            yield sentence[start:], scenario


def _share_claims(sentence):
    if '股' not in sentence or not _REVIEW_CONTEXT.search(sentence):
        return
    clauses = _CLAUSE.split(sentence)
    prior_review_size = False
    for i, clause in enumerate(clauses):
        goal = bool(_GOAL.search(clause))
        next_clause = clauses[i + 1] if i + 1 < len(clauses) else ''
        leads_to_goal = (_RESULT.match(next_clause) and _GOAL.search(next_clause)
                         and not _NEGATED.search(next_clause)
                         and not _POST_WEIGHT.search(next_clause))
        follows_goal = (i > 0 and bool(_GOAL.search(clauses[i - 1]))
                        and not _SHARE.search(clauses[i - 1]) and not _NEGATED.search(clauses[i - 1]))
        review_size = False
        # A parenthesized remainder can follow the sale immediately. Start
        # each amount's role at the preceding quantity to avoid borrowing it.
        start = 0
        for match in _SHARE.finditer(clause):
            prefix, suffix = clause[start:match.start()], clause[match.end():]
            start = match.end()
            if (_NEGATED.search(prefix) or _AFTER_SIZE_NEGATION.match(suffix)
                    or _INCREMENTAL.search(prefix)):
                continue
            if _REVIEW_LABEL.search(prefix):
                review_size = True
                yield _Claim(_Field.REVIEW_SALE, match[1])
                continue
            equivalent = (prior_review_size or review_size) and _EQUIVALENT.match(prefix.lstrip(' （(：:'))
            remainder = _REMAINDER.search(prefix)
            named_requirement = _LINE_REQUIREMENT.search(prefix)
            required = named_requirement or _REQUIRED.search(prefix)
            explicit_sale = _SELL.search(prefix)
            bare_sale = _SIZE_AS_SUBJECT.fullmatch(prefix) and _RESULT.match(suffix)
            if remainder and (goal or review_size or prior_review_size or follows_goal):
                yield _Claim(_Field.REVIEW_REMAINDER, match[1])
            elif (named_requirement or
                  ((explicit_sale or required or bare_sale) and
                   (goal or leads_to_goal or equivalent or follows_goal))):
                field = _Field.REVIEW_SALE if required or equivalent else _Field.ENOUGH_TO_REACH_LINE
                review_size |= field == _Field.REVIEW_SALE
                yield _Claim(field, match[1])
            elif _ELLIPTICAL_SUFFICIENCY.match(suffix):
                yield _Claim(_Field.ENOUGH_TO_REACH_LINE, match[1])
        prior_review_size = review_size


def _weight_claims(sentence, review):
    destinations = set()
    for match in _POST_WEIGHT.finditer(sentence):
        destinations.add(match.start(1))
        prefix = _CLAUSE.split(sentence[:match.start()])[-1]
        if _NEGATED.search(prefix):
            continue
        field = (_Field.AT_OR_BELOW_LINE if _LINE_SUFFIX.match(sentence, match.end())
                 else _Field.POST_SALE_WEIGHT)
        yield _Claim(field, match[1])
    for match in _ABOVE_LINE.finditer(sentence):
        prefix = sentence[:match.start()]
        scopes = list(_POST_TRIM_SCOPE.finditer(prefix))
        if (scopes and not _CURRENT_SCOPE.search(prefix, scopes[-1].end())
                and not _NEGATED.search(_CLAUSE.split(prefix)[-1])):
            yield _Claim(_Field.ABOVE_LINE, match['level'] or '')
    if _CONCENTRATION.search(sentence):
        if review:
            for match in _PERCENT.finditer(sentence):
                prefix = _CLAUSE.split(sentence[:match.start()])[-1]
                if (match.start(1) not in destinations and not _NEGATED.search(prefix)
                        and _CONCENTRATION_VALUE.search(prefix)):
                    yield _Claim(_Field.CONCENTRATION, match[1])
        if _BELOW_LINE.search(sentence) and not _NEGATED.search(sentence):
            yield _Claim(_Field.AT_OR_BELOW_LINE)


def _rounded_match(claim, expected):
    # Half a unit of the precision actually stated in the prose.
    decimals = len(claim.raw.partition('.')[2])
    return abs(claim.value - expected) <= 0.5 * 10 ** -decimals + 1e-9


def _weight_warning(claim, scenario, review):
    expected = scenario.get('post_trim_weight_pct')
    target = scenario.get('target_pct', (review or {}).get('review_pct'))
    if claim.field == _Field.CONCENTRATION:
        allowed = (review.get('weight_pct'), target, expected)
        if any(value is not None and _rounded_match(claim, value) for value in allowed):
            return None
        return f'{claim.raw}%，请引用减仓联立计算'
    if expected is None:
        return None
    if claim.field == _Field.ABOVE_LINE:
        if target is not None and expected <= target and (not claim.raw or claim.value == target):
            return (f'作者称减仓后仍高于复核线，当前账本联立解 {expected}% '
                    f'不高于 {target:g}% 复核线；请复核')
        return None
    if claim.field == _Field.AT_OR_BELOW_LINE and target is not None:
        if not claim.raw or claim.value == target:
            return f'减仓后 {expected}% 仍高于复核线' if expected > target else None
    if claim.raw and not _rounded_match(claim, expected):
        return f'作者减仓后占比 {claim.raw}% 与当前账本联立解 {expected}% 不一致；请复核'
    return None


def _share_warning(claim, scenario):
    need = scenario.get('shares_to_review_line')
    if claim.field == _Field.REVIEW_REMAINDER:
        remaining = scenario.get('remaining_shares_at_review_line')
        if remaining is not None and claim.value != remaining:
            return (f'作者称到复核线应剩 {claim.raw} 股，当前账本联立解应剩 {remaining:g} 股；请复核')
    elif need is not None:
        if claim.field == _Field.ENOUGH_TO_REACH_LINE and claim.value < need:
            return f'作者称 {claim.raw} 股足够回到复核线，当前账本联立解需 {need:g} 股；请复核'
        if claim.field == _Field.REVIEW_SALE and claim.value != need:
            return f'作者称到复核线需卖 {claim.raw} 股，当前账本联立解需卖 {need:g} 股；请复核'
    return None


def trim_claim_warnings(text, projection, book_projection=None, *, review=None):
    """Reconcile claims for one ticker. Callers bind the ticker to its facts."""
    warnings = {}
    for sentence, scenario in _scenarios(text, projection, book_projection):
        if scenario or review:
            if '%' in sentence or '％' in sentence or '复核线' in sentence:
                for claim in _weight_claims(sentence, review):
                    if warning := _weight_warning(claim, scenario, review):
                        warnings[warning] = None
            if scenario.get('shares_to_review_line') is not None:
                for claim in _share_claims(sentence):
                    if warning := _share_warning(claim, scenario):
                        warnings[warning] = None
    return list(warnings)


def plan_trim_warnings(decision, projection, book_projection=None, *, subjects=None):
    """Advisory timeline check of authored prose against today's book."""
    fields = (decision.get('rationale'), (decision.get('condition') or {}).get('description'),
              decision.get('hypothesis'), decision.get('method'))
    text = '\n'.join(field for field in fields if isinstance(field, str))
    if subjects:
        ticker = decision.get('ticker')
        text = '\n'.join(fragment for name, fragment in position_fragments(text, subjects, ticker)
                         if ticker == name)
    return trim_claim_warnings(text, projection, book_projection)
