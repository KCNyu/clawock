"""Headings and body requirements for newly generated weekly reviews."""
import re

from clawock.prose_validation import section_prose_lines

WEEKLY_REQUIRED_SECTIONS = ('本周净值', '决策兑现', '风险演变', '下周关注')
WEEKLY_SECTION_HEADINGS = tuple(
    f'## {i}. {name}' for i, name in enumerate(WEEKLY_REQUIRED_SECTIONS, 1))


# Shared by generation and Pages. The body must speak to the section's fact
# category, including when the author has to explain an evidence gap.
_COVERAGE = tuple(map(re.compile, (
    r'净值|盈亏|损益|回撤|收益|拖累|拖了后腿|贡献|出入金|账面',
    r'成交|执行|下单|挂单|决策|计划|校准|(?:已|未|才|没)触发',
    r'风控|风险|回撤|敞口|集中|相关性|杠杆|红线|一起[跌涨]|仓位',
    r'看[^。！？\n]|跟踪|观察|留意|复查|等到|关注|触发|证伪|确认|如果|条件',
)))


_GENERIC_RISK = re.compile(r'^(?:本周|目前)?(?:没有|暂无|无|留意|关注)(?:明显)?风险(?:敞口)?[。！ ]*$')


def weekly_sections(text):
    """Return exact section headings found and the ones with prose."""
    found, filled = set(), set()
    heading = None
    for _, line in section_prose_lines(text):
        if re.match(r'^ {0,3}#{1,2} ', line):
            heading = line.strip()
            if heading in WEEKLY_SECTION_HEADINGS:
                found.add(heading)
        elif heading in found and not re.match(r'^ {0,3}#{3,6} ', line):
            position = WEEKLY_SECTION_HEADINGS.index(heading)
            pattern = _COVERAGE[position]
            prose = line.strip(' *。！')
            if (pattern.search(prose) and not pattern.fullmatch(prose)
                    and not (position == 2 and _GENERIC_RISK.fullmatch(prose))):
                filled.add(heading)
    return found, filled
