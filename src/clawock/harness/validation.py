"""Text and numeric validation primitives shared by every report path.

Moved out of `scripts/harness/_harness_common.py` so the report core can live in
the installed package: a wheel cannot reach `scripts/`, and `clawock report` must
work with no repository checkout at all.

These are pure functions over text and context dicts — no I/O, no git, no
workspace. `_harness_common` re-exports them, so all ten in-repo importers are
untouched.
"""
from __future__ import annotations

import re


def _extract_md_tables(text):
    """Yield lists of consecutive lines that look like markdown table rows."""
    cur = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith('|') and s.endswith('|'):
            cur.append(ln)
        elif cur:
            yield cur
            cur = []
    if cur:
        yield cur


def check_raw_tables_verbatim(text, raw_wechat_block):
    """Verify every markdown-table line in raw_wechat_block appears verbatim in text.

    preflight builds the holdings table via clawock.adapters.mobile (7-col, known correct).
    LLMs sometimes paraphrase rows or drop a separator segment when "copying" —
    e.g. 5/21+ regression where header had 7 cols but separator only 6, breaking
    markdown renderers. Strict substring match catches that.

    Returns list of issue strings (empty = pass).
    """
    if not raw_wechat_block:
        return []
    issues = []
    for tbl in _extract_md_tables(raw_wechat_block):
        for ln in tbl:
            if ln not in text:
                issues.append(f'表格行未 verbatim 复制: "{ln.strip()[:50]}..."')
                break  # one issue per table is enough
    return issues


def check_md_table_column_consistency(text):
    """Verify every markdown table inside text has uniform pipe-segment counts
    across its header/separator/data rows.

    Use this when there's no canonical `raw_wechat_block` to compare against —
    e.g. LLM-authored pre-open.md where tables are composed (not copied).
    A diverging segment count breaks markdown renderers.

    Returns list of issue strings.
    """
    issues = []
    for i, tbl in enumerate(_extract_md_tables(text), start=1):
        counts = {ln.count('|') for ln in tbl}
        if len(counts) > 1:
            issues.append(f'markdown 表格 #{i} 列数不一致: pipe-segments={sorted(counts)}')
    return issues


def validate_forbidden_phrases(text, phrases, label='报告'):
    """Return one issue per forbidden phrase found in text."""
    return [f'{label}含敷衍词 "{p}"' for p in phrases if p in text]
# SCOPE, stated plainly: this catches magnitudes that appear NOWHERE in the
# context. It cannot catch a real number attached to the wrong thing — the same
# report's "07226 + 03033 各 1000 股" quotes a share count that genuinely exists
# (03033 holds 1000), it is simply not 07226's. That class is addressed by not
# restating position sizes at all (SKILL rule) and by handing the prose the plan's
# own numbers (plan_context, issue #119), not by a regex.
_MAGNITUDE = {'万': 10_000, '亿': 100_000_000, 'w': 10_000}
_CURRENCY = r'(?:HK\$|US\$|RMB|\$|¥|港元|美元|港币)'
_NUM = r'-?\d[\d,]*(?:\.\d+)?'
_SHARE_CLAIM = re.compile(rf'({_NUM})\s*(万|亿)?\s*(?:股|shares?\b)')
_CURRENCY_CLAIM = re.compile(
    rf'{_CURRENCY}\s*({_NUM})\s*(万|亿)?|({_NUM})\s*(万|亿)?\s*{_CURRENCY}'
)
# A range whose endpoints run backwards describes nothing real. The ASCII hyphen is
# deliberately NOT a separator here: HK tickers are numeric, so "07226 -3.5%" —
# the most common phrase in these reports — parsed as a range from 07226 to 3.5.
# Checked against 23 real sent reports: that one character was every false
# positive. `~` is what the observed defect ("+0.3~-0.4%") actually used.
_RANGE = re.compile(rf'({_NUM})\s*(?:~|～|—|–|到|至)\s*({_NUM})\s*%')
_UNIT_NUM = r'[+-]?\d[\d,]*(?:\.\d+)?'
_UNIT_CLAIMS = {
    'percent': re.compile(rf'({_UNIT_NUM})\s*[%％]'),
    'pp': re.compile(rf'({_UNIT_NUM})\s*(?:pp\b|个百分点|百分点)', re.IGNORECASE),
    'multiple': re.compile(rf'({_UNIT_NUM})\s*(?:[xX×](?![A-Za-z])|倍)'),
    'sigma': re.compile(rf'({_UNIT_NUM})\s*(?:σ|sigma\b)', re.IGNORECASE),
}
_UNIT_LABELS = {'percent': '%', 'pp': 'pp', 'multiple': 'x', 'sigma': 'σ'}
_UNIT_KEY_HINTS = {
    # ``range_pos`` is the T+0 strategy's 0–100 intraday range percentile.
    # It is rendered and discussed with ``%`` even though its established JSON
    # key predates the otherwise-consistent ``*_pct`` naming convention.
    'percent': re.compile(r'(?:^|_)(?:pct|percent|percentage|range_pos)(?:_|$)'),
    'pp': re.compile(r'(?:^|_)(?:pp|percentage_points?)(?:_|$)'),
    'multiple': re.compile(r'(?:^|_)(?:multiple|multiplier|leverage|leverage_ratio)(?:_|$)'),
    'sigma': re.compile(r'(?:^|_)(?:sigma|z_?score\d*)(?:_|$)'),
}
# A hypothetical percentage is not a claim about current evidence. Keep the
# long-standing low-noise boundary: "若再跌 2%" may be scenario prose, while an
# asserted "今日 -2%" must quote the context.
_HYPOTHETICAL = re.compile(r'(?:若|如果|假如|一旦|假设|情景|scenario|\bif\b)', re.IGNORECASE)
MAX_NUMERIC_SAMPLES = 4
# Only book-scale currency figures are checked. US price talk is conventionally
# written with the symbol — "跌破 $65，下一支撑 $60" is a level, not a claim about
# the book, and flagging it would make the gate noise on ordinary technical
# analysis. Book amounts in this portfolio are five figures; the fabricated
# estimate this gate exists for (1.5-2 万 HK$ = 20,000) is far above the line.
MIN_CHECKED_AMOUNT = 1_000


def _as_number(raw, magnitude=None):
    try:
        value = float(str(raw).replace(',', ''))
    except (TypeError, ValueError):
        return None
    return value * _MAGNITUDE.get(magnitude, 1)


def _context_numbers(ctx):
    """Every number the context states, in every form it states it.

    Walks the whole context rather than a chosen subset: the data block, peer
    percentages, plan sizes and index levels are all legitimate things for prose
    to quote, and a hand-picked list would silently make new context fields
    unquotable the day they are added.
    """
    seen = set()

    def add(value):
        number = _as_number(value)
        if number is not None:
            seen.add(round(abs(number), 4))

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)
        elif isinstance(node, bool):
            return
        elif isinstance(node, (int, float)):
            add(node)
        elif isinstance(node, str):
            for token in re.findall(_NUM, node):
                add(token)

    walk(ctx)
    return seen


def _context_unit_numbers(ctx):
    """Numbers with the market unit the context actually attaches to them.

    A flat number set lets an unrelated ``2.3%`` authorize an invented
    ``2.3x``. Strings carry their units explicitly; numeric JSON fields carry a
    unit only when their key names it (``move_pct``, ``gap_pp``, ``zscore20``).
    """
    seen = {unit: set() for unit in _UNIT_CLAIMS}

    def add(unit, value):
        number = _as_number(value)
        if number is not None:
            seen[unit].add(round(abs(number), 4))

    def walk(node, key=''):
        if isinstance(node, dict):
            for child_key, value in node.items():
                walk(value, str(child_key).lower())
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value, key)
        elif isinstance(node, bool):
            return
        elif isinstance(node, (int, float)):
            for unit, hint in _UNIT_KEY_HINTS.items():
                if hint.search(key):
                    add(unit, node)
        elif isinstance(node, str):
            for unit, pattern in _UNIT_CLAIMS.items():
                for raw in pattern.findall(node):
                    add(unit, raw)

    walk(ctx)
    return seen


def _is_hypothetical_percent(text, start):
    clause_start = max(text.rfind(mark, 0, start) for mark in '\n。！？；;') + 1
    return bool(_HYPOTHETICAL.search(text[max(clause_start, start - 16):start]))


def check_numeric_claims(text, ctx):
    """Flag unit-bearing magnitudes the context never states, and impossible
    percentage ranges.

    Returns at most ONE issue on purpose. Every postflight turns a small number of
    non-critical issues into `warn` (still delivered) and a larger number into
    `fail` (not delivered): a chatty new heuristic that pushed a good report over
    that line would convert a cosmetic problem into a missed report, which is the
    strictly worse failure. One aggregated line keeps the gate advisory.
    """
    known = _context_numbers(ctx)
    known_by_unit = _context_unit_numbers(ctx)
    unverified = []

    def check(value, label):
        if value is None or round(abs(value), 4) in known:
            return
        if label not in unverified:
            unverified.append(label)

    for raw, magnitude in _SHARE_CLAIM.findall(text):
        check(_as_number(raw, magnitude), f'{raw}{magnitude or ""}股')
    for cur_num, cur_mag, num_cur, mag_cur in _CURRENCY_CLAIM.findall(text):
        raw, magnitude = (cur_num, cur_mag) if cur_num else (num_cur, mag_cur)
        amount = _as_number(raw, magnitude)
        if amount is not None and abs(amount) >= MIN_CHECKED_AMOUNT:
            check(amount, f'{raw}{magnitude or ""}')

    for unit, pattern in _UNIT_CLAIMS.items():
        for match in pattern.finditer(text):
            if unit == 'percent' and _is_hypothetical_percent(text, match.start()):
                continue
            raw = match.group(1)
            value = _as_number(raw)
            if value is None or round(abs(value), 4) in known_by_unit[unit]:
                continue
            label = f'{raw}{_UNIT_LABELS[unit]}'
            if label not in unverified:
                unverified.append(label)

    impossible = [
        f'{lo}~{hi}%' for lo, hi in _RANGE.findall(text)
        if (_as_number(lo) is not None and _as_number(hi) is not None
            and (_as_number(lo) > _as_number(hi)))
    ]

    parts = []
    if unverified:
        shown = ', '.join(unverified[:MAX_NUMERIC_SAMPLES])
        parts.append(f'context 里没有的数字: {shown}')
    if impossible:
        parts.append(f'区间自相矛盾: {", ".join(impossible[:MAX_NUMERIC_SAMPLES])}')
    if not parts:
        return []
    return [f'{"；".join(parts)} —— 数字只能引用 context，不许心算 {ADVISORY_MARK}']

ADVISORY_MARK = '(advisory)'


def is_advisory(issue):
    """An advisory issue is reported but never escalates.

    Without this, an advisory check still counts toward `warn_max` and can push a
    report from `warn` (delivered) to `fail` (not delivered) purely by coexisting
    with two unrelated soft issues — verified: intraday `[soft-length, thin
    section, numeric]` categorised as `fail` while the same list minus the numeric
    line categorised as `warn`. An advisory heuristic that can silently cost kcn a
    report is worse than the cosmetic problem it reports.
    """
    return ADVISORY_MARK in issue


def split_advisory(issues):
    """(escalating, advisory) — the banner must count and show them separately.

    Both banners print a truncated list (`issues[:2]` intraday, `issues[:3]`
    report). While advisory findings shared that list they were the ones most
    likely to be cut, because they only appear on reports that already have
    other findings — i.e. exactly the reports where an invented number matters
    most. They get their own line instead.
    """
    return ([i for i in issues if not is_advisory(i)],
            [i for i in issues if is_advisory(i)])


def advisory_prefix(advisories, shown=2):
    """A visible, non-blocking line for advisory findings ('' when there are none).

    Deliberately not styled as a warning: it must read as information, or the
    next person to see one will start treating it as a failure and the gate
    becomes the blocker it was designed not to be.
    """
    if not advisories:
        return ''
    body = '; '.join(a.replace(ADVISORY_MARK, '').strip() for a in advisories[:shown])
    more = f'；另 {len(advisories) - shown} 条' if len(advisories) > shown else ''
    return f'ℹ️ 数字校验（不影响投递）：{body}{more}\n\n'


def categorize_issues(issues, critical_substrings, warn_max=2, extra_critical=None):
    """Common pass/warn/fail decision used by all postflights.

    - empty issues → pass
    - any issue containing any critical_substring OR matching extra_critical(i) → fail
    - advisory issues (see is_advisory) are reported but never counted or escalated
    - otherwise warn if ≤ warn_max non-advisory issues else fail

    extra_critical: optional callable(issue_str) -> bool for compound checks
    (e.g. hard char limit detection that can't be a simple substring).
    """
    if not issues:
        return 'pass'
    escalating = [i for i in issues if not is_advisory(i)]
    has_critical = any(
        any(c in i for c in critical_substrings)
        or (extra_critical is not None and extra_critical(i))
        for i in escalating
    )
    if has_critical:
        return 'fail'
    if not escalating:
        return 'warn'
    return 'warn' if len(escalating) <= warn_max else 'fail'



# The only length numbers in the system. One pair, shared by Mode 6 (open /
# midday / close reports) and Mode 7 (intraday) — they used to be two copies of
# the same 3000/3500, one here per market and one hardcoded in
# intraday_postflight, which is how they could drift apart unnoticed.
#
# These are NOT a writing target. #214 handed the model an exact pre-write prose
# budget (2800 assembled minus title and data block ≈ 1,200 chars) and every
# report was then written under a compression instruction; kcn's call on
# 2026-08-06 was to take that away and let the model decide length. What is left
# is a ceiling a normal report never approaches and a repeat-loop always does —
# a model stuck restating itself blows past it, which is the only automatic
# signal we have for that failure (see intraday_watchdog's fail-closed path).
# Widen them if a real report ever legitimately reaches one; do not turn them
# back into a target.
REPORT_CHAR_LIMITS = {'soft': 5_000, 'hard': 6_000}
